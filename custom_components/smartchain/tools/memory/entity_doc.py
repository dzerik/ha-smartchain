"""The document one entity becomes: what is embedded, and how change is spotted."""

import hashlib

from homeassistant.util import dt as dt_util

from ...const import ENTITY_CATALOGUE_MAX_CHARS
from .entity_filter import EntityCandidate

_ABSENT = "—"
_ALIASES_PREFIX = "Also known as: "


def doc_id_for(entity_id: str) -> str:
    return f"entity:{entity_id}"


def render_catalogue(cand: EntityCandidate) -> str:
    """The text that gets embedded.

    Catalogue only — the state is deliberately absent. If the state were in
    here, every state change would force a re-embed, which is the cost the
    whole design exists to avoid.

    Structural labels stay in English; names, areas and aliases are whatever
    Home Assistant holds, in the user's own language.

    Kept to `ENTITY_CATALOGUE_MAX_CHARS`: a catalogue that spilled into a
    second embedding chunk would be stored under a doc_id the next sweep's
    fingerprint lookup can never find, and would re-embed forever. Aliases
    are appended one at a time only while the running total stays within
    budget; a catalogue long enough to need trimming is dominated by alias
    noise, so the rest are dropped rather than fought over.
    """
    lines = [
        f"{cand.entity_id} — {cand.name or cand.entity_id}",
        (
            f"Area: {cand.area or _ABSENT} | Device: {cand.device or _ABSENT} "
            f"| Domain: {cand.domain} | Class: {cand.device_class or _ABSENT}"
        ),
    ]
    text = "\n".join(lines)

    kept: list[str] = []
    for alias in cand.aliases:
        alias_line = _ALIASES_PREFIX + ", ".join([*kept, alias])
        if len(text) + 1 + len(alias_line) > ENTITY_CATALOGUE_MAX_CHARS:
            break
        kept.append(alias)
    if kept:
        text += "\n" + _ALIASES_PREFIX + ", ".join(kept)

    # Hard backstop: the fixed lines alone should never exceed the budget,
    # but never emit more than it regardless.
    return text[:ENTITY_CATALOGUE_MAX_CHARS]


def fingerprint(text: str) -> str:
    """Short digest of the catalogue text — the whole basis of incremental sweeps."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_metadata(cand: EntityCandidate, text: str, state: str | None = None) -> dict[str, str]:
    """Metadata for one entity document. Every value is a str by contract."""
    meta = {
        "kind": "entity",
        "entity_id": cand.entity_id,
        "domain": cand.domain,
        "area": cand.area,
        "device_class": cand.device_class,
        "fingerprint": fingerprint(text),
    }
    if state is not None:
        meta["state"] = state
        meta["state_updated"] = dt_util.utcnow().isoformat()
    return meta
