"""Builds the entity context a conversation turn puts in its system prompt.

Two blocks. The skeleton says what exists and is always complete for the
configured scope; the retrieved block says what this message is about, in
detail. Splitting them this way is what keeps the model from concluding a
device does not exist merely because the query worded it badly.
"""

import logging

from ...const import ENTITY_SKELETON_MAX_CHARS
from .entity_filter import EntityCandidate

LOGGER = logging.getLogger(__name__)

_NO_AREA = "No area"


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
    budget = ENTITY_SKELETON_MAX_CHARS
    omitted_areas = 0
    omitted_entities = 0

    for area in ordered:
        domains = by_area[area]
        groups = "; ".join(
            f"{domain}: {', '.join(names)}" for domain, names in sorted(domains.items())
        )
        line = f"{area} — {groups}"
        # Leave room for the omission line itself.
        if len(line) + 1 > budget - 120 and lines:
            omitted_areas += 1
            omitted_entities += sum(len(n) for n in domains.values())
            continue
        lines.append(line)
        budget -= len(line) + 1

    if omitted_areas:
        lines.append(
            f"… and {omitted_areas} more area(s) holding {omitted_entities} "
            "entities — use search_entities to look any of them up."
        )
    return "\n".join(lines)
