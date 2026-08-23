"""The document one entity becomes: what is embedded, and how change is spotted."""

import hashlib

from homeassistant.util import dt as dt_util

from .entity_filter import EntityCandidate

_ABSENT = "—"


def doc_id_for(entity_id: str) -> str:
    return f"entity:{entity_id}"


def render_catalogue(cand: EntityCandidate) -> str:
    """The text that gets embedded.

    Catalogue only — the state is deliberately absent. If the state were in
    here, every state change would force a re-embed, which is the cost the
    whole design exists to avoid.

    Structural labels stay in English; names, areas and aliases are whatever
    Home Assistant holds, in the user's own language.
    """
    lines = [
        f"{cand.entity_id} — {cand.name or cand.entity_id}",
        (
            f"Area: {cand.area or _ABSENT} | Device: {cand.device or _ABSENT} "
            f"| Domain: {cand.domain} | Class: {cand.device_class or _ABSENT}"
        ),
    ]
    if cand.aliases:
        lines.append("Also known as: " + ", ".join(cand.aliases))
    return "\n".join(lines)


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
