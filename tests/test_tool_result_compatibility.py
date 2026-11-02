"""Tool results survive the HA 2026.10 API change (issue #16).

The strict modern doubles follow the 2026.10.4 contracts in
homeassistant/helpers/llm.py and components/conversation/chat_log.py. They omit
the deprecated tool_result property so reading it cannot silently pass.

https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/components/conversation/chat_log.py
"""

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.components.conversation import ConversationInput
from homeassistant.components.conversation.chat_log import AssistantContent, ChatLog, UserContent
from homeassistant.core import Context
from homeassistant.helpers import llm
from langchain_core.messages import AIMessageChunk, ToolMessage

from custom_components.smartchain import conversation
from custom_components.smartchain.const import (
    CONF_PROCESS_BUILTIN_SENTENCES,
    CRITIQUE_TOOL_NAME,
    DELEGATE_MANY_TOOL_NAME,
    DELEGATE_TOOL_NAME,
    DOMAIN,
    ENTITY_TOOL_NAME,
    HISTORY_TOOL_NAME,
    MEMORY_TOOL_NAME,
)
from custom_components.smartchain.tools.model import CustomTool, TemplateAction


@dataclass(slots=True)
class ModernToolResult:
    """HA 2026.10 wraps the payload and error flag in llm.ToolResult."""

    data: Any
    error: bool = False


@dataclass(frozen=True)
class ModernToolResultContent:
    """HA 2026.10 accepts result, rather than tool_result, in its constructor."""

    role: Literal["tool_result"] = field(init=False, default="tool_result")
    agent_id: str
    tool_call_id: str
    tool_name: str
    result: ModernToolResult

    def as_dict(self):
        """Allow the real ChatLog to publish the message."""
        return asdict(self)


@dataclass(frozen=True)
class LegacyToolResultContent:
    """The pre-2026.10 constructor accepts a bare payload."""

    role: Literal["tool_result"] = field(init=False, default="tool_result")
    agent_id: str
    tool_call_id: str
    tool_name: str
    tool_result: Any

    def as_dict(self):
        """Allow the real ChatLog to publish the message."""
        return asdict(self)


@pytest.fixture(params=["installed", "legacy", "2026.10"])
def tool_result_api(request, monkeypatch):
    """Exercise installed HA and both constructor contracts, independently of version."""
    if request.param == "2026.10":
        monkeypatch.setattr(conversation, "ToolResultContent", ModernToolResultContent)
        monkeypatch.setattr(llm, "ToolResult", ModernToolResult, raising=False)
    elif request.param == "legacy":
        monkeypatch.setattr(conversation, "ToolResultContent", LegacyToolResultContent)
        monkeypatch.delattr(llm, "ToolResult", raising=False)


async def test_history_result_reaches_the_model(hass, monkeypatch, tool_result_api):
    """Reproduce the issue's history handler, then feed its result back to the LLM."""
    chat_log = ChatLog(hass, "tool-result-compatibility")
    chat_log.content.append(
        AssistantContent(
            agent_id="test_agent",
            tool_calls=[
                llm.ToolInput(
                    tool_name=HISTORY_TOOL_NAME,
                    tool_args={"entity_id": "light.test"},
                    id="call_history",
                    external=True,
                )
            ],
        )
    )
    execute = AsyncMock(return_value="light.test was on")
    monkeypatch.setattr(conversation, "execute_history_tool", execute)

    await conversation._handle_history_tool_calls(hass, chat_log, "test_agent")

    result = conversation._chatlog_to_langchain(chat_log)[-1]
    assert result.tool_call_id == "call_history"
    assert result.name == HISTORY_TOOL_NAME
    assert result.content == '"light.test was on"'
    # A resolved call must not execute again on the next tool-loop iteration.
    await conversation._handle_history_tool_calls(hass, chat_log, "test_agent")
    execute.assert_awaited_once_with(hass, "light.test", 1.0)


@pytest.mark.parametrize(
    ("tool_name", "executor", "args"),
    [
        (HISTORY_TOOL_NAME, "execute_history_tool", {"entity_id": "light.test"}),
        (MEMORY_TOOL_NAME, "execute_memory_search", {"query": "lights"}),
        (ENTITY_TOOL_NAME, "execute_entity_search", {"query": "lights"}),
        (DELEGATE_TOOL_NAME, "execute_delegate_tool", {"agent_name": "other", "message": "hi"}),
        (
            DELEGATE_MANY_TOOL_NAME,
            "execute_delegate_many_tool",
            {"agents": ["other"], "query": "hi"},
        ),
        (
            CRITIQUE_TOOL_NAME,
            "execute_critique_tool",
            {"reviewer": "other", "original_question": "hi", "candidate_answer": "hello"},
        ),
        ("ping", "dispatch_custom_tool", {}),
    ],
)
async def test_external_tool_turn_completes(
    hass, monkeypatch, tool_result_api, tool_name, executor, args
):
    """Every external handler returns its payload to the model and finishes the turn."""
    payload = {"state": "on"} if tool_name == "ping" else "light.test was on"
    execute = AsyncMock(return_value=payload)
    monkeypatch.setattr(conversation, executor, execute)
    monkeypatch.setattr(conversation, "builtin_tool_names", lambda *args: frozenset({tool_name}))
    ping = CustomTool(
        name="ping",
        description="return a result",
        parameters={"type": "object", "properties": {}},
        action=TemplateAction(value_template="pong"),
    )
    monkeypatch.setattr(
        conversation, "custom_tools_for", lambda *args: [ping] if tool_name == "ping" else []
    )
    registry = MagicMock()
    registry.describe.return_value = []
    registry.entity_store_names.return_value = []
    hass.data[DOMAIN] = {"memory": registry}
    sent = []

    async def astream(messages):
        sent.append(list(messages))
        if any(isinstance(message, ToolMessage) for message in messages):
            yield AIMessageChunk(content="Done.")
        else:
            yield AIMessageChunk(
                content="",
                tool_calls=[{"id": "call_1", "name": tool_name, "args": args}],
            )

    client = MagicMock()
    client.astream = astream
    client.bind_tools.return_value = client
    entry = MagicMock()
    entry.options = {CONF_PROCESS_BUILTIN_SENTENCES: False}
    entry.runtime_data = client
    entity = conversation.SmartChainConversationEntity(entry)
    entity.hass = hass
    entity._skills_prompt = ""
    entity._sibling_agents_cache = [{"name": "other", "sub_id": "other"}]
    monkeypatch.setattr(entity, "_build_system_prompt", AsyncMock(return_value="Test assistant"))
    chat_log = ChatLog(hass, "tool-result-turn")
    chat_log.llm_api = MagicMock(tools=[])
    user_input = ConversationInput(
        text="Check the lights",
        context=Context(),
        conversation_id=chat_log.conversation_id,
        device_id=None,
        satellite_id=None,
        language="en",
        agent_id="test_agent",
    )
    chat_log.async_add_user_content(UserContent(content=user_input.text))

    result = await entity._async_handle_message(user_input, chat_log)

    assert result.response.error_code is None
    assert result.response.speech["plain"]["speech"] == "Done."
    execute.assert_awaited_once()
    assert len(sent) == 2
    tool_messages = [message for message in sent[1] if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "call_1"
    assert tool_messages[0].name == tool_name
    assert json.loads(tool_messages[0].content) == payload
