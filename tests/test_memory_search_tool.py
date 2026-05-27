"""Tests for the search_memory built-in tool."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import DOMAIN, MEMORY_TOOL_NAME
from custom_components.smartchain.tools.memory.search_tool import (
    execute_memory_search,
    get_memory_tool_definition,
)
from custom_components.smartchain.tools.memory.store import MemorySnippet


def test_definition_shape() -> None:
    spec = get_memory_tool_definition()
    assert spec["name"] == MEMORY_TOOL_NAME
    params = spec["parameters"]["properties"]
    assert "query" in params
    assert "top_k" in params
    assert "kind" in params


async def test_execute_returns_formatted_snippets(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.search = AsyncMock(
        return_value=[
            MemorySnippet(
                text="User: hi\nAssistant: hello",
                score=0.9,
                metadata={"kind": "conversation", "timestamp": "2026-05-27T18:00:00+00:00"},
            )
        ]
    )
    hass.data.setdefault(DOMAIN, {})["memory"] = store

    result = await execute_memory_search(hass, query="greeting", top_k=5, kind="any")
    assert "User: hi" in result
    assert "conversation" in result
    assert "2026-05-27" in result
    store.search.assert_awaited_once()


async def test_execute_filters_by_kind(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.search = AsyncMock(return_value=[])
    hass.data.setdefault(DOMAIN, {})["memory"] = store

    await execute_memory_search(hass, query="x", top_k=3, kind="logbook")
    args, kwargs = store.search.call_args
    where = kwargs.get("where") if "where" in kwargs else args[2] if len(args) > 2 else None
    assert where is not None
    assert where.get("kind") == "logbook"


async def test_execute_returns_not_configured_when_missing(hass: HomeAssistant) -> None:
    hass.data.pop(DOMAIN, None)
    result = await execute_memory_search(hass, query="x")
    assert "not configured" in result.lower()


async def test_execute_returns_failure_string_on_exception(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.search = AsyncMock(side_effect=RuntimeError("boom"))
    hass.data.setdefault(DOMAIN, {})["memory"] = store

    result = await execute_memory_search(hass, query="x")
    assert "lookup failed" in result.lower()


async def test_execute_empty_results_returns_no_memories(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.search = AsyncMock(return_value=[])
    hass.data.setdefault(DOMAIN, {})["memory"] = store
    result = await execute_memory_search(hass, query="x")
    assert "no" in result.lower() and "memor" in result.lower()
