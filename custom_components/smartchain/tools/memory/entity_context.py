"""Builds the entity context a conversation turn puts in its system prompt.

Two blocks. The skeleton says what exists and is always complete for the
configured scope; the retrieved block says what this message is about, in
detail. Splitting them this way is what keeps the model from concluding a
device does not exist merely because the query worded it badly.
"""

import logging
import time
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from ...const import ENTITY_SKELETON_CACHE_TTL, ENTITY_SKELETON_MAX_CHARS
from .config import EntitySourceConfig
from .entity_filter import EntityCandidate, resolve_candidates

LOGGER = logging.getLogger(__name__)

_NO_AREA = "No area"

# Headroom reserved for an omission note — either the trailing "N more areas"
# line, or the inline note a single oversized area gets appended to itself.
_NOTE_RESERVE = 120


def _partial_area_line(
    area: str, domains: dict[str, list[str]], budget: int
) -> tuple[str, int, int]:
    """Render as much of one oversized area's names as fits in `budget` chars.

    Names are taken in the same domain-then-name order the whole-area line
    would use, so a partial area reads as "the area's contents, cut off"
    rather than an arbitrary sample. Returns (line, kept_count, dropped_count);
    the caller appends the omission note itself, in the trailing note's voice.
    """
    total = sum(len(names) for names in domains.values())
    prefix = f"{area} — "
    used = len(prefix)
    groups: list[str] = []
    kept = 0

    for domain, names in sorted(domains.items()):
        picked: list[str] = []
        for name in names:
            trial = f"{domain}: {', '.join(picked + [name])}"
            sep_len = 2 if groups else 0  # "; " between this group and the previous one
            if used + sep_len + len(trial) > budget:
                break
            picked.append(name)
        if picked:
            group_text = f"{domain}: {', '.join(picked)}"
            used += (2 if groups else 0) + len(group_text)
            groups.append(group_text)
            kept += len(picked)
        if len(picked) < len(names):
            # Ran out of room at or before this domain; budget only shrinks from
            # here, so nothing after it can fit either.
            break

    line = prefix + "; ".join(groups)
    return line, kept, total - kept


def render_skeleton(candidates: dict[str, EntityCandidate]) -> str:
    """A compact map of the home: areas, then names grouped by domain.

    No entity ids, no device classes, no states, no device grouping. Without
    the Assist API the model has no Home Assistant control tools, so an
    entity id buys it nothing here; names, areas and — from the retrieved
    block — states are what it can actually use.
    """
    if not candidates:
        return ""

    # Iterate by entity_id so the grouped output is deterministic regardless
    # of the order candidates were discovered in — insertion order into a
    # dict comprehension is not something callers should have to control.
    by_area: dict[str, dict[str, list[str]]] = {}
    for entity_id in sorted(candidates):
        cand = candidates[entity_id]
        area = cand.area or _NO_AREA
        by_area.setdefault(area, {}).setdefault(cand.domain, []).append(cand.name or cand.entity_id)

    # Named areas alphabetically, the unassigned bucket last: it is the one a
    # user is most likely to have forgotten, so it should not be buried.
    ordered = sorted(a for a in by_area if a != _NO_AREA)
    if _NO_AREA in by_area:
        ordered.append(_NO_AREA)

    lines: list[str] = []
    remaining = ENTITY_SKELETON_MAX_CHARS
    omitted_areas = 0
    omitted_entities = 0

    for area in ordered:
        domains = by_area[area]
        area_entity_count = sum(len(names) for names in domains.values())
        groups = "; ".join(
            f"{domain}: {', '.join(names)}" for domain, names in sorted(domains.items())
        )
        line = f"{area} — {groups}"
        full_len = len(line) + 1  # + the newline that joins it to the next line

        if full_len <= remaining - _NOTE_RESERVE:
            # Fits whole, with room left over for a trailing note should a later
            # area need one.
            lines.append(line)
            remaining -= full_len
            continue

        # Would this area ever fit whole, on a completely fresh budget? If so it
        # is merely a victim of what came before it — skip it whole rather than
        # rendering half of it. Half an area reads as though the rest of it does
        # not exist, which is the exact failure this design avoids.
        fits_whole_ever = len(line) + 1 <= ENTITY_SKELETON_MAX_CHARS - _NOTE_RESERVE
        if fits_whole_ever or remaining <= _NOTE_RESERVE:
            omitted_areas += 1
            omitted_entities += area_entity_count
            continue

        # This area alone is bigger than the whole budget allows — it can never
        # be rendered whole, in any order, on any input. Rendering it partially
        # only reads as complete if it stays silent about the cut; it doesn't
        # here, because it carries its own inline note in the same voice as the
        # trailing one. Whatever budget is left goes entirely to this area, so
        # anything still to come after it is reported as omitted.
        partial_line, kept, dropped = _partial_area_line(area, domains, remaining - _NOTE_RESERVE)
        if kept:
            lines.append(partial_line)
        if dropped:
            lines.append(
                f"… {dropped} more entities in {area} — use search_entities to look them up."
            )
        remaining = 0

    if omitted_areas:
        lines.append(
            f"… and {omitted_areas} more area(s) holding {omitted_entities} "
            "entities — use search_entities to look any of them up."
        )

    result = "\n".join(lines)
    # Belt-and-braces: the reserve above is generous but not a proof for every
    # pathological input (an area name of its own can be arbitrarily long), so
    # the hard guarantee is enforced here rather than merely hoped for.
    if len(result) > ENTITY_SKELETON_MAX_CHARS:
        result = result[:ENTITY_SKELETON_MAX_CHARS]
    return result


class SkeletonCache:
    """One rendered map per preset, shared by every conversation agent.

    Registry events are the real invalidation; the TTL is a backstop for a
    change that somehow raises none.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._cache: dict[str, tuple[str, float]] = {}
        self._unsubs: list[Any] = []

    def start(self) -> None:
        if self._unsubs:
            return
        for event in (
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            ar.EVENT_AREA_REGISTRY_UPDATED,
        ):
            self._unsubs.append(self.hass.bus.async_listen(event, self._on_registry))

    async def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    @callback
    def _on_registry(self, _event: Event) -> None:
        self.invalidate()

    @callback
    def invalidate(self) -> None:
        self._cache.clear()

    def get(self, preset: str) -> str | None:
        """The map for `preset`, or None if it could not be built.

        The tri-state matters: "" is a genuinely empty home, None is a
        failure, and the caller falls back to the full devices dump only for
        the second. A failure is never cached — a transient registry error
        must not blind the agent for the whole TTL.
        """
        now = time.monotonic()
        cached = self._cache.get(preset)
        if cached is not None and (now - cached[1]) < ENTITY_SKELETON_CACHE_TTL:
            return cached[0]

        try:
            candidates = resolve_candidates(self.hass, EntitySourceConfig(preset=preset))
            rendered = render_skeleton(candidates)
        except Exception:  # noqa: BLE001 — a prompt must never fail to build
            LOGGER.exception("entity skeleton could not be built")
            return None

        self._cache[preset] = (rendered, now)
        return rendered
