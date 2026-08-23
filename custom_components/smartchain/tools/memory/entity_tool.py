"""`search_entities` — find a device by describing it.

Lexical matching runs first and outranks vector hits, because on the most
common query ("свет на кухне") a name match is both faster and more accurate
than cosine similarity. The vector pass earns its keep on the semantic tail.
"""

import logging
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
    candidates: dict[str, EntityCandidate], query: str
) -> list[tuple[int, float, EntityCandidate]]:
    needle = _fold(query)
    if not needle:
        return []
    ranked: list[tuple[int, float, EntityCandidate]] = []
    for cand in candidates.values():
        haystacks = [cand.name, cand.entity_id, cand.area, *cand.aliases]
        folded = [_fold(h) for h in haystacks if h]
        if any(h == needle for h in folded):
            ranked.append((_EXACT, 1.0, cand))
        elif any(h.startswith(needle) or needle in h for h in folded):
            ranked.append((_PREFIX, 0.5, cand))
        if len(ranked) >= ENTITY_LEXICAL_CANDIDATES:
            break
    return ranked


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

    ranked = _lexical(candidates, query)
    seen = {cand.entity_id for _tier, _score, cand in ranked}

    target = registry.get(target_name)
    if target is not None and target.is_available:
        where: dict[str, Any] = {"kind": "entity"}
        if domain:
            where["domain"] = domain
        if area:
            where["area"] = area
        if state and indexer.config.index_states:
            where["state"] = state
        try:
            for snippet in await target.search(query, top_k=top_k * 2, where=where):
                entity_id = (snippet.metadata or {}).get("entity_id", "")
                cand = candidates.get(entity_id)
                if cand is not None and entity_id not in seen:
                    ranked.append((_VECTOR, snippet.score, cand))
                    seen.add(entity_id)
        except Exception:
            LOGGER.exception("entity search failed")
            return "Entity lookup failed; see logs."

    ranked.sort(key=lambda item: (item[0], -item[1]))

    lines: list[str] = []
    for _tier, _score, cand in ranked:
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
