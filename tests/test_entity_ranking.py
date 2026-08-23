"""The shared ranking both search_entities and the prompt context use."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import DOMAIN
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer
from custom_components.smartchain.tools.memory.entity_tool import (
    _MAX_STORE_FETCH_K,
    execute_entity_search,
    rank_entities,
)
from custom_components.smartchain.tools.memory.registry import MemoryRegistry
from custom_components.smartchain.tools.memory.store import MemorySnippet, MemoryStore

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str, name: str, area: str = "Кухня") -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        area=area,
        device="",
        device_class="",
        aliases=(),
    )


def _registry(names: list[str], hits: list[MemorySnippet] | None = None):
    store = MagicMock(spec=MemoryStore)
    store.is_available = True
    store.search = AsyncMock(return_value=hits or [])
    reg = MagicMock(spec=MemoryRegistry)
    reg.entity_store_names.return_value = names
    reg.get.return_value = store
    return reg, store


async def test_lexical_only_without_a_store(hass: HomeAssistant) -> None:
    reg, store = _registry([])
    cands = {"light.a": _cand("light.a", "Потолок")}

    ranked = await rank_entities(hass, reg, cands, "потолок", top_k=5)

    assert [c.entity_id for c in ranked] == ["light.a"]
    assert store.search.await_count == 0


async def test_a_whole_sentence_matches_nothing_without_tokenize(
    hass: HomeAssistant,
) -> None:
    """The gate. `search_entities` must keep matching the query whole.

    Its `query` is a short phrase a model composed on purpose, so folding it
    into one needle is right there. If this test ever starts finding
    something, the token pass has leaked out of the prompt-context caller.
    """
    reg, _ = _registry([])
    cands = {"light.a": _cand("light.a", "Свет")}

    assert await rank_entities(hass, reg, cands, "включи свет на кухне", top_k=5) == []


async def test_tokenize_finds_the_entity_a_russian_sentence_names(
    hass: HomeAssistant,
) -> None:
    reg, _ = _registry([])
    cands = {
        # "свет" is one whole word of this name, not the whole name — the
        # case whole-word matching has to keep working for.
        "light.a": _cand("light.a", "Потолочный свет"),
        "sensor.b": _cand("sensor.b", "Влажность"),
    }

    ranked = await rank_entities(hass, reg, cands, "включи свет на кухне", top_k=5, tokenize=True)

    assert [c.entity_id for c in ranked] == ["light.a"]


async def test_tokenize_finds_the_entity_an_english_sentence_names(
    hass: HomeAssistant,
) -> None:
    reg, _ = _registry([])
    cands = {
        "light.a": _cand("light.a", "Kitchen Light", area="Kitchen"),
        "sensor.b": _cand("sensor.b", "Humidity", area="Bedroom"),
    }

    ranked = await rank_entities(
        hass, reg, cands, "turn off the kitchen light", top_k=5, tokenize=True
    )

    assert [c.entity_id for c in ranked] == ["light.a"]


async def test_a_whole_phrase_match_outranks_a_token_match(hass: HomeAssistant) -> None:
    """Tokens share the prefix tier but sort below a whole-needle hit."""
    reg, _ = _registry([])
    cands = {
        "light.token": _cand("light.token", "Свет"),
        "light.phrase": _cand("light.phrase", "Свет на кухне слева"),
    }

    ranked = await rank_entities(hass, reg, cands, "свет на кухне", top_k=5, tokenize=True)

    assert [c.entity_id for c in ranked] == ["light.phrase", "light.token"]


async def test_tokens_under_three_characters_are_dropped(hass: HomeAssistant) -> None:
    """Short function words carry no selective power and are discarded.

    The candidate's name must contain the short token as a WHOLE WORD, or
    this test cannot tell the length filter from the word-boundary rule —
    under whole-word matching an earlier version of it (query "то на ты"
    against a name "Ванна") passed with the length filter entirely removed,
    because "на" is not a word of "ванна" either way. "Свет на кухне" does
    have "на" as a word, so only the length filter keeps this empty.
    """
    reg, _ = _registry([])
    cands = {"light.a": _cand("light.a", "Свет на кухне")}

    # The whole needle is not a substring of anything here, so the first two
    # arms cannot fire and the token arm is the only one under test.
    assert await rank_entities(hass, reg, cands, "ты на", top_k=5, tokenize=True) == []


async def test_off_does_not_match_inside_office(hass: HomeAssistant) -> None:
    """ "off" must not reach "Office". The substring bug this round fixed.

    A three-character minimum cannot help — "off" and "the" clear it — and a
    stopword list would need one per language. Matching word-to-word is what
    fixes the class.
    """
    reg, _ = _registry([])
    cands = {
        "switch.office": _cand("switch.office", "Office", area="Hall"),
        "light.ceiling": _cand("light.ceiling", "Ceiling light", area="Hall"),
    }

    ranked = await rank_entities(hass, reg, cands, "turn off the light", top_k=5, tokenize=True)

    # Positive control in the same call, so this cannot pass by matching
    # nothing at all.
    assert [c.entity_id for c in ranked] == ["light.ceiling"]


async def test_the_does_not_match_inside_thermostat(hass: HomeAssistant) -> None:
    """ "the" must not reach "Thermostat"."""
    reg, _ = _registry([])
    cands = {
        "climate.thermostat": _cand("climate.thermostat", "Thermostat", area="Hall"),
        "sensor.temp": _cand("sensor.temp", "Temperature", area="Hall"),
    }

    ranked = await rank_entities(
        hass, reg, cands, "what is the temperature", top_k=5, tokenize=True
    )

    assert [c.entity_id for c in ranked] == ["sensor.temp"]


async def test_exact_lexical_outranks_a_higher_scored_vector_hit(
    hass: HomeAssistant,
) -> None:
    """The ranking's whole reason for existing."""
    hit = MemorySnippet(text="…", score=0.99, metadata={"kind": "entity", "entity_id": "switch.b"})
    reg, _ = _registry(["entities"], [hit])
    cands = {
        "light.a": _cand("light.a", "Кофеварка"),
        "switch.b": _cand("switch.b", "Розетка"),
    }

    ranked = await rank_entities(hass, reg, cands, "Кофеварка", top_k=5, store_name="entities")

    assert [c.entity_id for c in ranked] == ["light.a", "switch.b"]


async def test_a_vector_hit_outside_the_candidate_set_is_dropped(
    hass: HomeAssistant,
) -> None:
    """A stale document must not resurrect an entity that no longer exists."""
    hit = MemorySnippet(
        text="…", score=0.99, metadata={"kind": "entity", "entity_id": "light.gone"}
    )
    reg, _ = _registry(["entities"], [hit])

    ranked = await rank_entities(
        hass,
        reg,
        {"light.a": _cand("light.a", "Потолок")},
        "что-нибудь",
        top_k=5,
        store_name="entities",
    )

    assert "light.gone" not in [c.entity_id for c in ranked]


async def test_top_k_is_respected(hass: HomeAssistant) -> None:
    reg, _ = _registry([])
    cands = {f"light.{i}": _cand(f"light.{i}", "Свет") for i in range(10)}

    assert len(await rank_entities(hass, reg, cands, "свет", top_k=3)) == 3


async def test_results_are_deduplicated(hass: HomeAssistant) -> None:
    hit = MemorySnippet(text="…", score=0.9, metadata={"kind": "entity", "entity_id": "light.a"})
    reg, _ = _registry(["entities"], [hit])

    ranked = await rank_entities(
        hass,
        reg,
        {"light.a": _cand("light.a", "Потолок")},
        "потолок",
        top_k=5,
        store_name="entities",
    )

    assert [c.entity_id for c in ranked] == ["light.a"]


async def test_a_failing_store_degrades_to_lexical(hass: HomeAssistant) -> None:
    reg, store = _registry(["entities"])
    store.search = AsyncMock(side_effect=RuntimeError("boom"))

    ranked = await rank_entities(
        hass,
        reg,
        {"light.a": _cand("light.a", "Потолок")},
        "потолок",
        top_k=5,
        store_name="entities",
    )

    assert [c.entity_id for c in ranked] == ["light.a"]


async def test_store_fetch_is_capped_regardless_of_top_k(hass: HomeAssistant) -> None:
    """A caller may inflate `top_k` well past its real page size — as
    `execute_entity_search` does, to avoid losing candidates to this
    function's own truncation ahead of filters applied afterwards. That must
    not turn into an unbounded store query: the store's `top_k=` stays
    bounded and small, not proportional to the candidate count or to the
    inflated `top_k`.
    """
    reg, store = _registry(["entities"])
    cands = {f"light.{i}": _cand(f"light.{i}", "Свет") for i in range(1000)}

    await rank_entities(hass, reg, cands, "свет", top_k=1000, store_name="entities")

    fetch = store.search.await_args.kwargs["top_k"]
    assert fetch <= _MAX_STORE_FETCH_K
    assert fetch < 1000


async def test_domain_filter_does_not_shrink_the_page_below_top_k(
    hass: HomeAssistant,
) -> None:
    """Regression guard for the bug fixed in `execute_entity_search`.

    Before the fix, rank_entities truncated the merged candidate pool to the
    render `top_k` before domain/area/state filters ran. With enough
    same-ranked non-matching candidates ahead of the matching ones, that
    truncation could throw away every entity the filter would have kept,
    returning an empty or partial page even though a full page of matches
    existed further down the ranking.
    """
    all_cands: dict[str, EntityCandidate] = {}
    for i in range(20):
        entity_id = f"sensor.noise{i}"
        hass.states.async_set(entity_id, "on", {})
        all_cands[entity_id] = _cand(entity_id, "Свет")
    for i in range(5):
        entity_id = f"light.{i}"
        hass.states.async_set(entity_id, "on", {})
        all_cands[entity_id] = _cand(entity_id, "Свет")

    indexer = MagicMock(spec=EntityIndexer)
    indexer.config = MagicMock()

    reg = MagicMock(spec=MemoryRegistry)
    reg.entity_store_names.return_value = ["entities"]
    reg.indexer_for.return_value = indexer
    reg.get.return_value = MagicMock(spec=MemoryStore, is_available=False)
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    with patch(
        "custom_components.smartchain.tools.memory.entity_tool.resolve_candidates",
        return_value=all_cands,
    ):
        result = await execute_entity_search(hass, query="свет", domain="light", top_k=5)

    assert result.count("light.") == 5
    assert "sensor.noise" not in result
