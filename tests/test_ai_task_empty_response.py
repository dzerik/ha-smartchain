"""An AI Task that got nothing back must say so, not return an empty string.

Before the stream learned to always close with an assistant message, a model
that answered with nothing left the chat log ending in something else, and
`_async_generate_data` raised on it. Now the stream closes every turn with a
`native`-only delta, so that guard cannot fire any more and the task quietly
succeeds with `data == ""`.

The consumer is the difference. A conversation can answer "I didn't get that"
and the person asks again; an automation takes `data` and carries on — writing
an empty notification, storing an empty summary, comparing an empty string.
Silence has to reach it as a failure, and it has to be told apart from a model
that deliberately answered with an empty string, which is why the marker in
`native` is what these tests key on rather than the emptiness of the text.

These run a real `ChatLog`, because the thing under test is what HA builds out
of our deltas.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.components import ai_task
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    ChatLog,
    SystemContent,
    UserContent,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from langchain_core.messages import AIMessageChunk

from custom_components.smartchain.ai_task import SmartChainAITaskEntity
from custom_components.smartchain.const import CONF_ENGINE, ID_GIGACHAT
from custom_components.smartchain.conversation import EMPTY_RESPONSE_NATIVE


def _entity(hass: HomeAssistant, *chunks: AIMessageChunk) -> SmartChainAITaskEntity:
    """Build an AI Task entity whose model replays `chunks`."""

    async def _astream(_messages):
        for chunk in chunks:
            yield chunk

    client = MagicMock()
    client.astream = _astream

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {}
    entry.runtime_data = client
    ent = SmartChainAITaskEntity(entry)
    ent.hass = hass
    ent._attr_entity_id = "ai_task.smartchain_test"
    return ent


def _chat_log(hass: HomeAssistant) -> ChatLog:
    """A real chat log holding the instructions of one task."""
    chat_log = ChatLog(hass, "conv-ai-task")
    chat_log.content = [
        SystemContent(content=""),
        UserContent(content="Сводка погоды одной строкой"),
    ]
    chat_log.llm_api = None
    return chat_log


def _task(structure: Any = None) -> ai_task.GenDataTask:
    return ai_task.GenDataTask(
        name="test_task",
        instructions="Сводка погоды одной строкой",
        structure=structure,
    )


async def test_empty_stream_fails_the_task(hass: HomeAssistant) -> None:
    """A model that streamed nothing at all is a failed task, not empty data."""
    entity = _entity(hass, AIMessageChunk(content=""))
    chat_log = _chat_log(hass)

    with pytest.raises(HomeAssistantError, match="no usable response"):
        await entity._async_generate_data(_task(), chat_log)


async def test_thinking_only_stream_fails_the_task(hass: HomeAssistant) -> None:
    """Thinking is not an answer: the automation gets nothing it can use."""
    entity = _entity(
        hass,
        AIMessageChunk(content=[{"type": "thinking", "thinking": "hmm", "index": 0}]),
    )
    chat_log = _chat_log(hass)

    with pytest.raises(HomeAssistantError, match="no usable response"):
        await entity._async_generate_data(_task(), chat_log)


async def test_the_failed_task_is_the_marker_not_the_empty_text(hass: HomeAssistant) -> None:
    """The turn that fails is the one HA marked as carrying no response.

    An assistant message whose text is empty for any other reason is a model
    decision and stays a successful task; the marker is set by our own stream
    and by nothing else.
    """
    entity = _entity(hass, AIMessageChunk(content=""))
    chat_log = _chat_log(hass)

    with pytest.raises(HomeAssistantError):
        await entity._async_generate_data(_task(), chat_log)

    last = chat_log.content[-1]
    assert isinstance(last, AssistantContent)
    assert last.native == EMPTY_RESPONSE_NATIVE
    assert not last.content


async def test_structured_empty_response_fails_before_json_parsing(hass: HomeAssistant) -> None:
    """ "Nothing came back" is a truer report than "the JSON did not parse"."""
    entity = _entity(hass, AIMessageChunk(content=""))
    chat_log = _chat_log(hass)
    task = _task(structure=vol.Schema({vol.Required("summary"): str}))

    with pytest.raises(HomeAssistantError, match="no usable response"):
        await entity._async_generate_data(task, chat_log)


async def test_a_real_answer_still_comes_back(hass: HomeAssistant) -> None:
    """The guard must not cost a task that worked."""
    entity = _entity(hass, AIMessageChunk(content="Ясно, +18"))
    chat_log = _chat_log(hass)

    result = await entity._async_generate_data(_task(), chat_log)

    assert result.data == "Ясно, +18"
    assert result.conversation_id == "conv-ai-task"
