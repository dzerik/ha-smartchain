"""Tests for the critique_response tool."""

from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant
from langchain_core.messages import AIMessage, HumanMessage

from custom_components.smartchain.const import CRITIQUE_TOOL_NAME
from custom_components.smartchain.tools.critique_tool import (
    CRITIQUE_PROMPT,
    execute_critique_tool,
    get_critique_tool_definition,
)


def test_definition_shape() -> None:
    spec = get_critique_tool_definition([{"name": "auditor", "sub_id": "s1"}])
    assert spec["name"] == CRITIQUE_TOOL_NAME
    props = spec["parameters"]["properties"]
    assert props["reviewer"]["enum"] == ["auditor"]
    assert "original_question" in props
    assert "candidate_answer" in props
    assert spec["parameters"]["required"] == [
        "reviewer",
        "original_question",
        "candidate_answer",
    ]


async def test_critique_invokes_reviewer_with_formatted_prompt(
    hass: HomeAssistant,
) -> None:
    reviewer = AsyncMock()
    reviewer.ainvoke = AsyncMock(return_value=AIMessage(content="looks good"))
    clients = {"s1": reviewer}
    agent_map = {"auditor": "s1"}

    result = await execute_critique_tool(
        clients, agent_map, "auditor", "Will it rain?", "Yes, expect rain."
    )
    assert result == "looks good"

    reviewer.ainvoke.assert_awaited_once()
    sent_messages = reviewer.ainvoke.await_args.args[0]
    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert isinstance(msg, HumanMessage)
    assert "Will it rain?" in msg.content
    assert "Yes, expect rain." in msg.content
    assert CRITIQUE_PROMPT.split("\n")[0] in msg.content


async def test_critique_unknown_reviewer(hass: HomeAssistant) -> None:
    result = await execute_critique_tool({}, {}, "ghost", "q", "a")
    assert "unavailable" in result.lower()


async def test_critique_timeout(hass: HomeAssistant, monkeypatch) -> None:
    from custom_components.smartchain.tools import critique_tool as mod

    monkeypatch.setattr(mod, "MULTI_AGENT_PER_CALL_TIMEOUT_SECONDS", 0.01)

    async def slow(_messages):
        import asyncio

        await asyncio.sleep(1)
        return AIMessage(content="late")

    reviewer = AsyncMock()
    reviewer.ainvoke = AsyncMock(side_effect=slow)
    clients = {"s1": reviewer}
    agent_map = {"auditor": "s1"}

    result = await execute_critique_tool(clients, agent_map, "auditor", "q", "a")
    assert "timeout" in result.lower()


async def test_critique_exception_is_caught(hass: HomeAssistant) -> None:
    reviewer = AsyncMock()
    reviewer.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    clients = {"s1": reviewer}
    agent_map = {"auditor": "s1"}

    result = await execute_critique_tool(clients, agent_map, "auditor", "q", "a")
    assert "critique failed" in result.lower()
    assert "boom" not in result  # no internal detail leaks
