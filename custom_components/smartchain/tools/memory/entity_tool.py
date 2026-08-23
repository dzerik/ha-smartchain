"""`search_entities` — find a device by describing it.

Lexical matching runs first and outranks vector hits, because on the most
common query ("свет на кухне") a name match is both faster and more accurate
than cosine similarity. The vector pass earns its keep on the semantic tail.
"""

import logging
import re
import unicodedata
from typing import Any

from homeassistant.core import HomeAssistant

from ...const import (
    DOMAIN,
    ENTITY_LEXICAL_CANDIDATES,
    ENTITY_SEARCH_DEFAULT_TOP_K,
    ENTITY_SEARCH_MAX_TOP_K,
    ENTITY_TOOL_NAME,
)
from .entity_filter import EntityCandidate, resolve_candidates

LOGGER = logging.getLogger(__name__)

_EXACT, _PREFIX, _VECTOR = 0, 1, 2

# Ceiling on `fetch_k` in `rank_entities`: the most hits any call will ever
# ask a vector store for in one query, no matter what `fetch_k` (or, when it
# is omitted, `top_k`) a caller passes. Keeps a caller that inflates `top_k`
# to preserve candidates before filtering (see `execute_entity_search`) from
# turning that into an unbounded store scan.
_MAX_STORE_FETCH_K = 200

# Runs of alphanumerics, Unicode-aware, with `_` deliberately excluded so
# `light.kitchen_ceiling` yields "light", "kitchen" and "ceiling" rather than
# one unusable "kitchen_ceiling".
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Tokens shorter than this are dropped before matching. Two-letter fragments
# ("на", "то", "in", "on") are substrings of half a home's entity names and
# would turn a token pass into "return everything".
_TOKEN_MIN_LEN = 3

# Score for a token hit. It shares the `_PREFIX` tier with a whole-needle
# partial match but sorts after it, so a candidate that matched the entire
# phrase still outranks one that only matched a word of it.
_TOKEN_SCORE = 0.25


def _fold(text: str) -> str:
    """Case- and accent-insensitive comparison key."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def get_entity_tool_definition(registry: Any) -> dict[str, Any]:
    names = registry.entity_store_names()
    properties: dict[str, Any] = {
        "query": {"type": "string", "description": "What the device is or does."},
        "top_k": {
            "type": "integer",
            "default": ENTITY_SEARCH_DEFAULT_TOP_K,
            "minimum": 1,
            "maximum": ENTITY_SEARCH_MAX_TOP_K,
        },
        "domain": {"type": "string", "description": "Restrict to one domain, e.g. light."},
        "area": {"type": "string", "description": "Restrict to one area by name."},
        "state": {"type": "string", "description": "Restrict to a current state, e.g. on."},
    }
    required = ["query"]
    if names:
        properties["store"] = {
            "type": "string",
            "enum": names,
            "description": "Which entity index to search.",
        }
        if len(names) > 1:
            required.append("store")

    return {
        "name": ENTITY_TOOL_NAME,
        "description": (
            "Find Home Assistant entities by describing them, when the exact "
            "entity_id is unknown. Returns entity_ids that can be used directly "
            "in service calls."
        ),
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


def _lexical(
    candidates: dict[str, EntityCandidate], query: str, tokenize: bool = False
) -> list[tuple[int, float, EntityCandidate]]:
    """Fold the query and match it against every candidate's text.

    `tokenize` decides what "the query" means. Off — the default, and what
    `search_entities` uses — the whole query is one needle, which is right
    when a model supplies a short descriptive phrase. On, the needle is
    additionally split into words and a candidate is admitted when any word
    of three characters or more occurs in one of its haystacks. That is what
    the prompt context needs, because it passes the raw user utterance:
    "включи свет на кухне" is nobody's entity name, and without the token
    pass it matches nothing at all on an install with no vector index.
    """
    needle = _fold(query)
    if not needle:
        return []
    tokens: list[str] = []
    if tokenize:
        tokens = [t for t in _TOKEN_RE.findall(needle) if len(t) >= _TOKEN_MIN_LEN]
    ranked: list[tuple[int, float, EntityCandidate]] = []
    for cand in candidates.values():
        haystacks = [cand.name, cand.entity_id, cand.area, *cand.aliases]
        folded = [_fold(h) for h in haystacks if h]
        if any(h == needle for h in folded):
            ranked.append((_EXACT, 1.0, cand))
        elif any(h.startswith(needle) or needle in h for h in folded):
            ranked.append((_PREFIX, 0.5, cand))
        elif tokens and any(t in h for h in folded for t in tokens):
            ranked.append((_PREFIX, _TOKEN_SCORE, cand))
        if len(ranked) >= ENTITY_LEXICAL_CANDIDATES:
            break
    return ranked


async def rank_entities(
    hass: HomeAssistant,
    registry: Any,
    candidates: dict[str, EntityCandidate],
    query: str,
    top_k: int,
    store_name: str | None = None,
    where_extra: dict[str, Any] | None = None,
    degrade_on_store_failure: bool = True,
    fetch_k: int | None = None,
    tokenize: bool = False,
) -> list[EntityCandidate]:
    """Candidates ranked lexical-first, then by vector score, deduplicated.

    Lexical matching always runs; the vector pass runs only when `store_name`
    names an available store. A vector hit for an entity outside `candidates`
    is dropped — a stale document must not resurrect an entity that no longer
    exists, or that the caller's preset excludes.

    `top_k` and `fetch_k` bound two different things and are deliberately not
    the same number. `top_k` bounds the *result*: the ranked, deduplicated
    list this function returns is sliced to it. `fetch_k` bounds the *store
    query* instead — how many hits are requested from the vector backend,
    before ranking, dedup or any caller-side filtering. A caller that inflates
    `top_k` past its real page size (to avoid losing candidates to this
    function's own truncation ahead of filters it applies afterwards — see
    `execute_entity_search`) must not have that inflation turn into an
    equally inflated store query. When `fetch_k` is omitted it derives from
    `top_k` as `top_k * 2`, matching this function's pre-extraction inline
    behaviour. Either way the request sent to the store is capped at
    `_MAX_STORE_FETCH_K`, so no caller — accidentally or otherwise — can turn
    a search into an unbounded store scan.

    By default a failing store degrades to lexical rather than failing the
    caller: this function is on the path that builds a system prompt, and a
    prompt without vector hits is far better than no prompt. Pass
    `degrade_on_store_failure=False` to let the exception propagate instead —
    `execute_entity_search` does this, because its own caller (the LLM tool
    boundary) must see a fixed failure string rather than a partial result,
    and it keeps the try/except that produces that string around its call
    here.

    `tokenize` is off by default so `search_entities`, whose `query` is a
    short phrase a model chose deliberately, keeps matching exactly as it
    always has. The prompt-context caller turns it on, because its query is
    the raw user utterance — see `_lexical`.
    """
    ranked = _lexical(candidates, query, tokenize=tokenize)
    seen = {cand.entity_id for _tier, _score, cand in ranked}

    target = registry.get(store_name) if store_name is not None else None
    if target is not None and target.is_available:
        where: dict[str, Any] = {"kind": "entity"}
        if where_extra:
            where.update(where_extra)
        fetch = fetch_k if fetch_k is not None else top_k * 2
        fetch = min(fetch, _MAX_STORE_FETCH_K)
        try:
            for snippet in await target.search(query, top_k=fetch, where=where):
                entity_id = (snippet.metadata or {}).get("entity_id", "")
                cand = candidates.get(entity_id)
                if cand is not None and entity_id not in seen:
                    ranked.append((_VECTOR, snippet.score, cand))
                    seen.add(entity_id)
        except Exception:
            if not degrade_on_store_failure:
                raise
            LOGGER.exception("entity search failed; degrading to lexical only")

    ranked.sort(key=lambda item: (item[0], -item[1]))
    return [cand for _tier, _score, cand in ranked[:top_k]]


async def execute_entity_search(
    hass: HomeAssistant,
    query: str,
    top_k: int = ENTITY_SEARCH_DEFAULT_TOP_K,
    domain: str | None = None,
    area: str | None = None,
    state: str | None = None,
    store: str | None = None,
) -> str:
    registry = (hass.data.get(DOMAIN) or {}).get("memory")
    names = registry.entity_store_names() if registry is not None else []
    if not names:
        return "Entity search is not configured for this installation."

    if store is not None and store not in names:
        return f"Unknown entity index {store!r}. Configured: {', '.join(names)}."
    target_name = store or (names[0] if len(names) == 1 else None)
    if target_name is None:
        return f"Several entity indexes exist — pass `store`. Available: {', '.join(names)}."

    indexer = registry.indexer_for(target_name)
    if indexer is None:
        # Unreachable in practice: target_name always comes from
        # entity_store_names(), which is backed by the same mapping
        # indexer_for() reads. Guarded anyway rather than trusting that.
        LOGGER.error("search_entities: no indexer registered for store %r", target_name)
        return "Entity lookup failed; see logs."
    candidates = resolve_candidates(hass, indexer.config)

    where_extra: dict[str, Any] = {}
    if domain:
        where_extra["domain"] = domain
    if area:
        where_extra["area"] = area
    # `state` is deliberately NOT a store-side filter, even when the store
    # has index_states: true. Stored state is up to a flush interval old —
    # and arbitrarily old for an entity that has not changed since its last
    # sweep — so pruning vector hits against it discards exactly the
    # semantic matches this tool exists to find. The live post-filter below
    # is authoritative and runs unconditionally.

    # rank_entities truncates its return to `top_k`, but this tool must not
    # lose candidates to that truncation before domain/area/state are
    # applied below — a match ranked just outside `top_k` may be the only
    # one of the top matches to survive those filters. `len(candidates)` is
    # a true upper bound on the merged, deduplicated ranking (it can never
    # contain more distinct entities than were resolved), so passing it
    # makes rank_entities' truncation a no-op here; this function's own loop
    # below still stops at the caller's real `top_k` once filters are
    # applied, exactly as before this was split out.
    #
    # That inflated `top_k` must not also inflate the vector *query* —
    # rank_entities derives its store fetch size from `top_k` by default,
    # which would ask the store for `len(candidates) * 2` hits on a large
    # install. `fetch_k` is passed explicitly instead, sized off this
    # function's real render `top_k` (over-fetched enough to survive the
    # filters below), and rank_entities caps it regardless.
    try:
        ranked = await rank_entities(
            hass,
            registry,
            candidates,
            query,
            top_k=max(len(candidates), 1),
            store_name=target_name,
            where_extra=where_extra,
            degrade_on_store_failure=False,
            fetch_k=top_k * 4,
        )
    except Exception:
        LOGGER.exception("entity search failed")
        return "Entity lookup failed; see logs."

    lines: list[str] = []
    for cand in ranked:
        if domain and cand.domain != domain:
            continue
        if area and cand.area != area:
            continue
        live = hass.states.get(cand.entity_id)
        current = live.state if live else "unavailable"
        if state and current != state:
            continue
        lines.append(
            f"{len(lines) + 1}. {cand.entity_id} — {cand.name} "
            f"[{cand.domain}, {cand.area or '—'}] = {current}"
        )
        if len(lines) >= top_k:
            break

    if not lines:
        applied = [
            f"{k}={v!r}" for k, v in (("domain", domain), ("area", area), ("state", state)) if v
        ]
        suffix = f" Filters applied: {', '.join(applied)}." if applied else ""
        return f"No entities matched the query.{suffix}"

    return f"Found {len(lines)} entities:\n" + "\n".join(lines)
