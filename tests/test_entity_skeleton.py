"""The always-present map of what exists."""

from custom_components.smartchain.const import ENTITY_SKELETON_MAX_CHARS
from custom_components.smartchain.tools.memory.entity_context import render_skeleton
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate


def _cand(entity_id: str, name: str, area: str = "") -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        area=area,
        device="",
        device_class="",
        aliases=(),
    )


def _skeleton(*cands: EntityCandidate) -> str:
    return render_skeleton({c.entity_id: c for c in cands})


def test_empty_home_renders_nothing() -> None:
    assert render_skeleton({}) == ""


def test_one_area_groups_by_domain() -> None:
    text = _skeleton(
        _cand("light.a", "Потолочный", "Кухня"),
        _cand("light.b", "Подсветка", "Кухня"),
        _cand("switch.c", "Кофеварка", "Кухня"),
    )
    assert "Кухня — light: Потолочный, Подсветка; switch: Кофеварка" in text


def test_areas_are_separate_lines() -> None:
    text = _skeleton(
        _cand("light.a", "Потолочный", "Кухня"),
        _cand("light.b", "Бра", "Спальня"),
    )
    lines = [ln for ln in text.split("\n") if ln.strip()]
    assert len(lines) == 2


def test_entities_without_an_area_get_their_own_line_last() -> None:
    """An unassigned entity is exactly the kind a user forgets exists."""
    text = _skeleton(
        _cand("light.a", "Потолочный", "Кухня"),
        _cand("vacuum.v", "Пылесос"),
    )
    lines = [ln for ln in text.split("\n") if ln.strip()]
    assert lines[-1].startswith("No area —")
    assert "Пылесос" in lines[-1]


def test_no_entity_ids_appear() -> None:
    """Ids are near-useless without HA control tools; states are retrieved."""
    text = _skeleton(_cand("light.kitchen_ceiling", "Потолочный", "Кухня"))
    assert "light.kitchen_ceiling" not in text


def test_a_nameless_entity_falls_back_to_its_entity_id() -> None:
    text = _skeleton(_cand("light.orphan", "", "Кухня"))
    assert "light.orphan" in text


def test_output_is_deterministic() -> None:
    cands = [
        _cand("switch.c", "Кофеварка", "Кухня"),
        _cand("light.a", "Потолочный", "Кухня"),
        _cand("light.b", "Бра", "Спальня"),
    ]
    assert _skeleton(*cands) == _skeleton(*reversed(cands))


def test_output_is_deterministic_within_a_single_domain_and_area() -> None:
    """Two entities sharing a domain and area must not depend on input order.

    Without a stable tiebreaker, the name list for a (area, domain) group
    would follow whatever order the candidates happened to be discovered
    in — the earlier version of this test never had two entities sharing a
    group, so it could not catch that.
    """
    cands = [
        _cand("light.a", "Потолочный", "Кухня"),
        _cand("light.b", "Подсветка", "Кухня"),
    ]
    assert _skeleton(*cands) == _skeleton(*reversed(cands))


def test_a_huge_home_is_truncated_within_the_budget() -> None:
    cands = [
        _cand(f"light.a{i}", f"Светильник номер {i}", f"Комната {i // 5}") for i in range(4000)
    ]
    text = _skeleton(*cands)
    assert len(text) <= ENTITY_SKELETON_MAX_CHARS


def test_truncation_says_what_it_omitted_and_points_at_the_tool() -> None:
    """Silent truncation would make the model confidently wrong about the home."""
    cands = [
        _cand(f"light.a{i}", f"Светильник номер {i}", f"Комната {i // 5}") for i in range(4000)
    ]
    last = _skeleton(*cands).rstrip().split("\n")[-1]
    assert "more area" in last
    assert "search_entities" in last


def test_a_home_that_fits_has_no_omission_line() -> None:
    text = _skeleton(_cand("light.a", "Потолочный", "Кухня"))
    assert "Кухня — light: Потолочный" in text
    assert "search_entities" not in text


def test_a_single_oversized_area_is_still_capped_and_announces_itself() -> None:
    """The reviewer's repro: one area alone that exceeds the whole budget.

    The bug was that the first area was admitted unconditionally (nothing yet
    to reserve room after), so a single huge area silently blew the budget
    with no omission line at all. This must now stay within the budget and
    say, right where the area is, that it was cut off.
    """
    cands = [_cand(f"sensor.s{i}", f"Датчик номер {i}", "Кухня") for i in range(500)]
    text = _skeleton(*cands)
    assert len(text) <= ENTITY_SKELETON_MAX_CHARS
    assert text.startswith("Кухня — sensor:")
    assert "search_entities" in text
