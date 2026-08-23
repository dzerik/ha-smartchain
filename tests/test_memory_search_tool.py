"""search_memory routes to a named store and describes what each one holds."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import DOMAIN, MEMORY_TOOL_NAME
from custom_components.smartchain.tools.memory.search_tool import (
    execute_memory_search,
    get_memory_tool_definition,
)
from custom_components.smartchain.tools.memory.store import MemorySnippet


def _registry(entries: dict[str, str], stores: dict[str, MagicMock] | None = None):
    """A stub registry: {name: description} plus optional store mocks."""
    made = stores or {name: MagicMock() for name in entries}
    reg = MagicMock()
    reg.names.return_value = list(entries)
    reg.describe.return_value = list(entries.items())
    reg.__len__.return_value = len(entries)
    reg.get.side_effect = lambda name: (
        made.get(name)
        if name is not None
        else (next(iter(made.values())) if len(made) == 1 else None)
    )
    return reg, made


def _store_returning(snippets: list[MemorySnippet]) -> MagicMock:
    store = MagicMock()
    store.is_available = True
    store.search = AsyncMock(return_value=snippets)
    return store


def test_definition_has_no_store_enum_for_a_single_store() -> None:
    reg, _ = _registry({"only": "The one store"})
    spec = get_memory_tool_definition(reg)
    assert spec["name"] == MEMORY_TOOL_NAME
    assert "store" not in spec["parameters"].get("required", [])


def test_definition_requires_store_when_several_exist() -> None:
    reg, _ = _registry({"a": "First", "b": "Second"})
    spec = get_memory_tool_definition(reg)
    assert spec["parameters"]["properties"]["store"]["enum"] == ["a", "b"]
    assert "store" in spec["parameters"]["required"]


def test_definition_embeds_store_descriptions() -> None:
    reg, _ = _registry({"a": "Dialogue history", "b": "Devices and sensors"})
    spec = get_memory_tool_definition(reg)
    text = spec["description"] + spec["parameters"]["properties"]["store"]["description"]
    assert "Dialogue history" in text
    assert "Devices and sensors" in text


async def test_execute_routes_to_the_named_store(hass: HomeAssistant) -> None:
    hit = MemorySnippet(text="from B", score=0.9, metadata={"kind": "logbook", "timestamp": "t"})
    store_a = _store_returning([])
    store_b = _store_returning([hit])
    reg, _ = _registry({"a": "", "b": ""}, {"a": store_a, "b": store_b})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    result = await execute_memory_search(hass, query="x", store="b")
    assert "from B" in result
    store_a.search.assert_not_awaited()
    store_b.search.assert_awaited_once()


async def test_execute_defaults_to_the_only_store(hass: HomeAssistant) -> None:
    hit = MemorySnippet(text="only", score=0.9, metadata={"kind": "conversation", "timestamp": "t"})
    store = _store_returning([hit])
    reg, _ = _registry({"only": ""}, {"only": store})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    result = await execute_memory_search(hass, query="x")
    assert "only" in result


async def test_execute_rejects_unknown_store_by_name(hass: HomeAssistant) -> None:
    reg, _ = _registry({"a": ""})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    result = await execute_memory_search(hass, query="x", store="ghost")
    assert "ghost" in result
    assert "a" in result  # the available names are listed back to the model


async def test_execute_asks_for_a_store_when_ambiguous(hass: HomeAssistant) -> None:
    reg, _ = _registry({"a": "", "b": ""})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    result = await execute_memory_search(hass, query="x")
    assert "store" in result.lower()


async def test_execute_returns_not_configured_for_empty_registry(
    hass: HomeAssistant,
) -> None:
    reg, _ = _registry({})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg
    assert "not configured" in (await execute_memory_search(hass, query="x")).lower()


async def test_execute_still_filters_by_kind_and_subentry(hass: HomeAssistant) -> None:
    store = _store_returning([])
    reg, _ = _registry({"only": ""}, {"only": store})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    await execute_memory_search(hass, query="x", kind="logbook", subentry_id="s1")
    where = store.search.call_args.kwargs["where"]
    assert where == {"kind": "logbook", "subentry_id": "s1"}


async def test_execute_returns_failure_string_on_exception(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.search = AsyncMock(side_effect=RuntimeError("boom"))
    reg, _ = _registry({"only": ""}, {"only": store})
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    result = await execute_memory_search(hass, query="x")
    assert "lookup failed" in result.lower()
    assert "boom" not in result
