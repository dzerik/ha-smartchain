"""Tests for the ask_agents (parallel fan-out) tool."""

from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from langchain_core.messages import AIMessage

from custom_components.smartchain.const import (
    DELEGATE_MANY_TOOL_NAME,
    MULTI_AGENT_MAX_PARALLEL,
)
from custom_components.smartchain.tools.delegate_many_tool import (
    execute_delegate_many_tool,
    get_delegate_many_tool_definition,
)


def test_definition_shape() -> None:
    spec = get_delegate_many_tool_definition(
        [{"name": "weather", "sub_id": "s1"}, {"name": "shopping", "sub_id": "s2"}]
    )
    assert spec["name"] == DELEGATE_MANY_TOOL_NAME
    props = spec["parameters"]["properties"]
    assert "agents" in props
    assert "query" in props
    assert props["agents"]["items"]["enum"] == ["weather", "shopping"]
    assert props["agents"]["maxItems"] == MULTI_AGENT_MAX_PARALLEL
    assert spec["parameters"]["required"] == ["agents", "query"]


def _make_client(reply: str) -> AsyncMock:
    client = AsyncMock()
    client.ainvoke = AsyncMock(return_value=AIMessage(content=reply))
    return client


async def test_fanout_happy_path(hass: HomeAssistant) -> None:
    clients = {"s1": _make_client("sunny"), "s2": _make_client("milk")}
    agent_map = {"weather": "s1", "shopping": "s2"}
    result = await execute_delegate_many_tool(clients, agent_map, ["weather", "shopping"], "today?")
    assert "[weather] sunny" in result
    assert "[shopping] milk" in result
    assert "Responses from 2 agents" in result


async def test_unknown_agent_is_reported_per_line(hass: HomeAssistant) -> None:
    clients = {"s1": _make_client("ok")}
    agent_map = {"weather": "s1"}
    result = await execute_delegate_many_tool(clients, agent_map, ["weather", "ghost"], "x")
    assert "[weather] ok" in result
    assert "[ghost]" in result and "unavailable" in result.lower()


async def test_duplicate_agent_names_are_deduplicated(hass: HomeAssistant) -> None:
    client = _make_client("hi")
    clients = {"s1": client}
    agent_map = {"weather": "s1"}
    await execute_delegate_many_tool(clients, agent_map, ["weather", "weather", "weather"], "x")
    assert client.ainvoke.await_count == 1


async def test_truncates_at_max_parallel(hass: HomeAssistant) -> None:
    siblings = {f"a{i}": _make_client("ok") for i in range(MULTI_AGENT_MAX_PARALLEL + 3)}
    agent_map = {name: name for name in siblings}
    await execute_delegate_many_tool(siblings, agent_map, list(siblings.keys()), "x")
    called = sum(1 for c in siblings.values() if c.ainvoke.await_count > 0)
    assert called == MULTI_AGENT_MAX_PARALLEL


async def test_timeout_reported_per_agent(hass: HomeAssistant, monkeypatch) -> None:
    from custom_components.smartchain.tools import delegate_many_tool as mod

    monkeypatch.setattr(mod, "MULTI_AGENT_PER_CALL_TIMEOUT_SECONDS", 0.01)

    async def slow(_messages):
        import asyncio

        await asyncio.sleep(1)
        return AIMessage(content="late")

    slow_client = AsyncMock()
    slow_client.ainvoke = AsyncMock(side_effect=slow)
    fast_client = _make_client("fast")

    clients = {"s1": slow_client, "s2": fast_client}
    agent_map = {"slow": "s1", "fast": "s2"}

    result = await execute_delegate_many_tool(clients, agent_map, ["slow", "fast"], "x")
    assert "[slow]" in result and "timeout" in result.lower()
    assert "[fast] fast" in result


async def test_exception_is_caught_and_reported(hass: HomeAssistant) -> None:
    bad_client = AsyncMock()
    bad_client.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    clients = {"s1": bad_client}
    agent_map = {"weather": "s1"}
    result = await execute_delegate_many_tool(clients, agent_map, ["weather"], "x")
    assert "[weather]" in result
    assert "error" in result.lower()
    # "boom" must NOT leak into the LLM-facing string (security boundary)
    assert "boom" not in result


async def test_empty_filtered_list_returns_generic_message(hass: HomeAssistant) -> None:
    result = await execute_delegate_many_tool({}, {}, ["ghost"], "x")
    assert "No matching sibling agents" in result
