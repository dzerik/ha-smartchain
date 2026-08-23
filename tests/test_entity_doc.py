"""What gets embedded, and how a change in it is detected."""

from custom_components.smartchain.tools.memory.entity_doc import (
    build_metadata,
    doc_id_for,
    fingerprint,
    render_catalogue,
)
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.store import chunk_text


def _cand(**kw) -> EntityCandidate:
    base = dict(
        entity_id="light.ceiling",
        domain="light",
        name="Потолок",
        area="Кухня",
        device="Yeelight",
        device_class="",
        aliases=(),
    )
    base.update(kw)
    return EntityCandidate(**base)


def test_doc_id_is_namespaced() -> None:
    assert doc_id_for("light.ceiling") == "entity:light.ceiling"


def test_catalogue_has_the_two_fixed_lines() -> None:
    text = render_catalogue(_cand())
    lines = text.split("\n")
    assert len(lines) == 2
    assert lines[0] == "light.ceiling — Потолок"
    assert lines[1] == "Area: Кухня | Device: Yeelight | Domain: light | Class: —"


def test_aliases_add_a_third_line() -> None:
    text = render_catalogue(_cand(aliases=("люстра", "верхний свет")))
    assert text.split("\n")[2] == "Also known as: люстра, верхний свет"


def test_absent_fields_render_as_a_dash_not_dropped() -> None:
    """Clearing a field must change the fingerprint, so the slot has to stay."""
    text = render_catalogue(_cand(area="", device=""))
    assert "Area: — | Device: —" in text
    assert len(text.split("\n")) == 2


def test_clearing_a_field_changes_the_fingerprint() -> None:
    before = fingerprint(render_catalogue(_cand()))
    after = fingerprint(render_catalogue(_cand(area="")))
    assert before != after


def test_fingerprint_is_stable_and_short() -> None:
    text = render_catalogue(_cand())
    assert fingerprint(text) == fingerprint(text)
    assert len(fingerprint(text)) == 16


def test_a_pathological_alias_set_still_fits_one_chunk() -> None:
    """The invariant that actually matters: the real chunker sees one piece.

    `MemoryStore.add` only honours a given doc_id verbatim when the text
    chunks to exactly one piece; anything more and the next sweep's
    fingerprint lookup can never find it again, re-embedding it forever.
    Asserting against `chunk_text` itself — not a magic character count —
    means a future change to the chunk size surfaces here.
    """
    many_long_aliases = tuple(f"alias-{i}-{'x' * 40}" for i in range(200))
    cand = _cand(aliases=many_long_aliases)

    text = render_catalogue(cand)

    assert len(chunk_text(text)) == 1


def test_truncation_is_deterministic() -> None:
    """A truncated catalogue must fingerprint the same way every render.

    Otherwise the entity would re-embed on every sweep for a different
    reason than the one this whole design exists to eliminate.
    """
    many_long_aliases = tuple(f"alias-{i}-{'x' * 40}" for i in range(200))
    cand = _cand(aliases=many_long_aliases)

    first = render_catalogue(cand)
    second = render_catalogue(cand)

    assert first == second
    assert fingerprint(first) == fingerprint(second)


def test_metadata_shape_without_state() -> None:
    cand = _cand(device_class="illuminance")
    meta = build_metadata(cand, render_catalogue(cand))
    assert meta["kind"] == "entity"
    assert meta["entity_id"] == "light.ceiling"
    assert meta["domain"] == "light"
    assert meta["area"] == "Кухня"
    assert meta["device_class"] == "illuminance"
    assert len(meta["fingerprint"]) == 16
    assert "state" not in meta


def test_metadata_carries_state_when_given() -> None:
    cand = _cand()
    meta = build_metadata(cand, render_catalogue(cand), state="on")
    assert meta["state"] == "on"
    assert meta["state_updated"]


def test_every_metadata_value_is_a_string() -> None:
    """The Filter contract is equality over scalars; keep it to str."""
    cand = _cand()
    meta = build_metadata(cand, render_catalogue(cand), state="on")
    assert all(isinstance(v, str) for v in meta.values())
