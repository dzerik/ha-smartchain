"""End-to-end: SmartChainConversationEntity with 3 sibling stub clients."""

from unittest.mock import AsyncMock

from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    ToolResultContent,
)
from homeassistant.core import HomeAssistant
from langchain_core.messages import AIMessage

from custom_components.smartchain.const import DELEGATE_MANY_TOOL_NAME
from custom_components.smartchain.conversation import (
    _handle_delegate_many_tool_calls,
)


class _ToolCall:
    def __init__(self, id_: str, name: str, args: dict) -> None:
        self.id = id_
        self.tool_name = name
        self.tool_args = args
        self.external = True


class _FakeChatLog:
    def __init__(self) -> None:
        self.content: list = []

    def async_add_assistant_content_without_tools(self, item) -> None:
        self.content.append(item)


async def test_fanout_handler_appends_tool_result(hass: HomeAssistant) -> None:
    weather = AsyncMock()
    weather.ainvoke = AsyncMock(return_value=AIMessage(content="sunny"))
    shopping = AsyncMock()
    shopping.ainvoke = AsyncMock(return_value=AIMessage(content="milk"))
    clients = {"s_weather": weather, "s_shopping": shopping}
    agent_map = {"weather": "s_weather", "shopping": "s_shopping"}

    chat_log = _FakeChatLog()
    chat_log.content.append(
        AssistantContent(
            agent_id="conversation.smartchain",
            content="",
            tool_calls=[
                _ToolCall(
                    "call-1",
                    DELEGATE_MANY_TOOL_NAME,
                    {"agents": ["weather", "shopping"], "query": "what now?"},
                )
            ],
        )
    )

    await _handle_delegate_many_tool_calls(clients, agent_map, chat_log, "conversation.smartchain")

    tool_results = [c for c in chat_log.content if isinstance(c, ToolResultContent)]
    assert len(tool_results) == 1
    assert tool_results[0].tool_call_id == "call-1"
    assert "[weather] sunny" in tool_results[0].tool_result
    assert "[shopping] milk" in tool_results[0].tool_result
