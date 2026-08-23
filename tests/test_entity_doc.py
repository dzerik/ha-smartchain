"""What gets embedded, and how a change in it is detected."""

from custom_components.smartchain.tools.memory.entity_doc import (
    build_metadata,
    doc_id_for,
    fingerprint,
    render_catalogue,
)
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate


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
