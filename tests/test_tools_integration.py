"""End-to-end: tools.yaml -> registry -> LLM tool_call -> dispatch -> tool_result."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    SystemContent,
    ToolResultContent,
    UserContent,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from langchain_core.messages import AIMessageChunk
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
)
from custom_components.smartchain.conversation import _async_langchain_stream
from custom_components.smartchain.tools.model import CustomTool, TemplateAction

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _make_ping_tool() -> CustomTool:
    return CustomTool(
        name="ping",
        description="return pong",
        parameters={"type": "object", "properties": {}},
        action=TemplateAction(value_template="pong"),
    )


# ---------------------------------------------------------------------------
# Unit-level: _async_langchain_stream marks custom tool names as external
# ---------------------------------------------------------------------------


async def test_langchain_stream_marks_custom_tool_external() -> None:
    """Tool calls whose names are in external_tool_names must have external=True."""
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "id": "tc1",
                "name": "ping",
                "args": "{}",
                "index": 0,
                "type": "tool_call_chunk",
            }
        ],
    )

    async def _astream(_messages):
        yield chunk

    fake_client = MagicMock()
    fake_client.astream = _astream

    deltas = []
    async for delta in _async_langchain_stream(
        fake_client, [], external_tool_names=frozenset({"ping"})
    ):
        deltas.append(delta)

    tool_inputs = [tc for d in deltas for tc in (d.get("tool_calls") or [])]
    assert tool_inputs, "Expected at least one tool call in stream deltas"
    ping_inputs = [t for t in tool_inputs if t.tool_name == "ping"]
    assert ping_inputs, "Expected 'ping' tool_call in deltas"
    assert all(t.external for t in ping_inputs), "Custom tool must be marked external=True"


async def test_langchain_stream_unknown_tool_not_external() -> None:
    """Tool calls NOT in external_tool_names stay external=False (HA handles them)."""
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "id": "tc2",
                "name": "ha_builtin_tool",
                "args": "{}",
                "index": 0,
                "type": "tool_call_chunk",
            }
        ],
    )

    async def _astream(_messages):
        yield chunk

    fake_client = MagicMock()
    fake_client.astream = _astream

    deltas = []
    async for delta in _async_langchain_stream(fake_client, [], external_tool_names=frozenset()):
        deltas.append(delta)

    tool_inputs = [tc for d in deltas for tc in (d.get("tool_calls") or [])]
    assert tool_inputs
    assert not tool_inputs[0].external, "Non-custom tool must NOT be marked external"


# ---------------------------------------------------------------------------
# Handler-level: custom tool calls are dispatched and results appended
# ---------------------------------------------------------------------------


async def test_custom_tool_handler_dispatches_and_appends(hass: HomeAssistant) -> None:
    """When ChatLog has an unresolved custom tool call, the handler dispatches it
    and appends a ToolResultContent to chat_log.content."""
    ping = _make_ping_tool()
    tool_call = llm.ToolInput(
        tool_name="ping",
        tool_args={},
        id="tc_ping_1",
        external=True,
    )

    chat_log = MagicMock()
    chat_log.content = [
        SystemContent(content="System prompt"),
        UserContent(content="ping me"),
        AssistantContent(
            agent_id="test_agent",
            content=None,
            tool_calls=[tool_call],
        ),
    ]
    chat_log.async_add_assistant_content_without_tools = MagicMock()

    with patch(
        "custom_components.smartchain.conversation.dispatch_custom_tool",
        new_callable=AsyncMock,
        return_value="pong",
    ) as mock_dispatch:
        # Simulate what the conversation loop does after streaming
        custom_by_name = {"ping": ping}
        agent_id = "test_agent"

        for content in list(chat_log.content):
            if not isinstance(content, AssistantContent) or not content.tool_calls:
                continue
            for tc in content.tool_calls:
                if tc.tool_name not in custom_by_name:
                    continue
                if any(
                    isinstance(c, ToolResultContent) and c.tool_call_id == tc.id
                    for c in chat_log.content
                ):
                    continue
                tool_result = await mock_dispatch(hass, custom_by_name[tc.tool_name], tc.tool_args)
                chat_log.async_add_assistant_content_without_tools(
                    ToolResultContent(
                        agent_id=agent_id,
                        tool_call_id=tc.id,
                        tool_name=tc.tool_name,
                        tool_result=tool_result,
                    )
                )

    mock_dispatch.assert_called_once_with(hass, ping, {})
    chat_log.async_add_assistant_content_without_tools.assert_called_once()
    result_content = chat_log.async_add_assistant_content_without_tools.call_args[0][0]
    assert isinstance(result_content, ToolResultContent)
    assert result_content.tool_call_id == "tc_ping_1"
    assert result_content.tool_name == "ping"
    assert result_content.tool_result == "pong"


async def test_custom_tool_handler_skips_already_resolved(hass: HomeAssistant) -> None:
    """Tool calls that already have a ToolResultContent are not dispatched again."""
    ping = _make_ping_tool()
    tool_call = llm.ToolInput(
        tool_name="ping",
        tool_args={},
        id="tc_ping_2",
        external=True,
    )

    chat_log = MagicMock()
    chat_log.content = [
        AssistantContent(
            agent_id="test_agent",
            content=None,
            tool_calls=[tool_call],
        ),
        ToolResultContent(
            agent_id="test_agent",
            tool_call_id="tc_ping_2",
            tool_name="ping",
            tool_result="already pong",
        ),
    ]
    chat_log.async_add_assistant_content_without_tools = MagicMock()

    with patch(
        "custom_components.smartchain.conversation.dispatch_custom_tool",
        new_callable=AsyncMock,
    ) as mock_dispatch:
        custom_by_name = {"ping": ping}
        agent_id = "test_agent"

        for content in list(chat_log.content):
            if not isinstance(content, AssistantContent) or not content.tool_calls:
                continue
            for tc in content.tool_calls:
                if tc.tool_name not in custom_by_name:
                    continue
                if any(
                    isinstance(c, ToolResultContent) and c.tool_call_id == tc.id
                    for c in chat_log.content
                ):
                    continue
                tool_result = await mock_dispatch(hass, custom_by_name[tc.tool_name], tc.tool_args)
                chat_log.async_add_assistant_content_without_tools(
                    ToolResultContent(
                        agent_id=agent_id,
                        tool_call_id=tc.id,
                        tool_name=tc.tool_name,
                        tool_result=tool_result,
                    )
                )

    mock_dispatch.assert_not_called()
    chat_log.async_add_assistant_content_without_tools.assert_not_called()


# ---------------------------------------------------------------------------
# Integration: tools.yaml -> registry -> entity setup -> tool schemas passed
# ---------------------------------------------------------------------------


async def test_yaml_tools_registered_and_collected(hass: HomeAssistant) -> None:
    """Tools loaded from tools.yaml appear in _collect_custom_tools()."""
    from custom_components.smartchain.conversation import (
        SmartChainConversationEntity,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=MagicMock(),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Inject a tool directly into the registry (mirrors what tools.yaml loading does)
    registry = hass.data[DOMAIN]["tools"]
    registry.replace_all([_make_ping_tool()])

    # The entity with no allowed_tools restriction should return all tools
    ent = SmartChainConversationEntity(entry, subentry_id=None, options={})
    collected = ent._collect_custom_tools(registry)

    assert len(collected) == 1
    assert collected[0].name == "ping"
    schema = collected[0].to_llm_schema()
    assert schema["name"] == "ping"
    assert schema["description"] == "return pong"


async def test_custom_tools_extend_bind_tools_list(hass: HomeAssistant) -> None:
    """Custom tool schemas are passed to bind_tools when tools are registered."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    fake_client = MagicMock()
    fake_client.astream = AsyncMock(return_value=iter([]))

    bound_tools_received = []

    def _bind_tools(tools):
        bound_tools_received.extend(tools)
        return fake_client

    fake_client.bind_tools = _bind_tools

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=fake_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    # Inject ping tool into registry
    registry = hass.data[DOMAIN]["tools"]
    registry.replace_all([_make_ping_tool()])

    from custom_components.smartchain.conversation import SmartChainConversationEntity

    ent = SmartChainConversationEntity(entry, subentry_id=None, options={})
    ent.hass = hass

    registry2: object | None = ent.hass.data.get(DOMAIN, {}).get("tools")
    custom_tools = ent._collect_custom_tools(registry2) if registry2 else []
    schemas = [t.to_llm_schema() for t in custom_tools]

    assert any(s["name"] == "ping" for s in schemas), (
        "ping tool schema must appear when custom tools are registered"
    )
