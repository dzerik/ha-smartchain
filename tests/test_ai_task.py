"""Tests for SmartChain AI Task entity."""

from unittest.mock import MagicMock

import pytest
from homeassistant.components import ai_task
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    SystemContent,
    UserContent,
)
from homeassistant.exceptions import HomeAssistantError
from langchain_core.messages import AIMessageChunk

from custom_components.smartchain.ai_task import SmartChainAITaskEntity
from custom_components.smartchain.const import CONF_ENGINE, ID_GIGACHAT


def _make_chat_log(conversation_id="test-conv-id"):
    """Create a mock ChatLog for AI Task tests."""
    chat_log = MagicMock()
    chat_log.conversation_id = conversation_id
    chat_log.content = [
        SystemContent(content="You are a Home Assistant expert."),
        UserContent(content="Summarize the weather"),
    ]
    chat_log.llm_api = None
    chat_log.unresponded_tool_results = False

    async def _mock_add_delta_stream(agent_id, stream):
        collected = ""
        async for delta in stream:
            if "content" in delta:
                collected += delta["content"]
        content = AssistantContent(agent_id=agent_id, content=collected)
        chat_log.content.append(content)
        yield content

    chat_log.async_add_delta_content_stream = _mock_add_delta_stream
    return chat_log


def _make_gen_data_task(instructions="Summarize the weather", structure=None):
    """Create a GenDataTask."""
    return ai_task.GenDataTask(
        name="test_task",
        instructions=instructions,
        structure=structure,
    )


@pytest.fixture
def ai_task_entity(mock_llm_client):
    """Create a SmartChainAITaskEntity."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {}
    entry.runtime_data = mock_llm_client
    ent = SmartChainAITaskEntity(entry)
    ent.hass = MagicMock()
    ent._attr_entity_id = "ai_task.smartchain_test"
    return ent


async def test_ai_task_entity_init(ai_task_entity) -> None:
    """Test AI Task entity initialization."""
    assert ai_task_entity._attr_unique_id == "test_entry_ai_task"
    assert (
        ai_task_entity._attr_supported_features
        == ai_task.AITaskEntityFeature.GENERATE_DATA
    )
    assert ai_task_entity._attr_has_entity_name is True


async def test_generate_data_basic(ai_task_entity) -> None:
    """Test basic data generation returns text result."""
    chat_log = _make_chat_log()
    task = _make_gen_data_task()

    result = await ai_task_entity._async_generate_data(task, chat_log)

    assert isinstance(result, ai_task.GenDataTaskResult)
    assert result.conversation_id == "test-conv-id"
    assert result.data == "Test response from LLM"


async def test_generate_data_structured_json(ai_task_entity) -> None:
    """Test structured output parses JSON response."""
    import voluptuous as vol

    # Mock client to return JSON
    async def _json_astream(messages):
        yield AIMessageChunk(content='{"temperature": 22, "condition": "sunny"}')

    ai_task_entity.entry.runtime_data.astream = MagicMock(side_effect=_json_astream)

    chat_log = _make_chat_log()
    task = _make_gen_data_task(
        instructions="Get weather data",
        structure=vol.Schema(
            {
                vol.Required("temperature"): int,
                vol.Required("condition"): str,
            }
        ),
    )

    result = await ai_task_entity._async_generate_data(task, chat_log)

    assert isinstance(result, ai_task.GenDataTaskResult)
    assert result.data == {"temperature": 22, "condition": "sunny"}


async def test_generate_data_structured_invalid_json(ai_task_entity) -> None:
    """Test structured output raises error on invalid JSON."""
    import voluptuous as vol

    async def _bad_astream(messages):
        yield AIMessageChunk(content="not json at all")

    ai_task_entity.entry.runtime_data.astream = MagicMock(side_effect=_bad_astream)

    chat_log = _make_chat_log()
    task = _make_gen_data_task(
        instructions="Get data",
        structure=vol.Schema({vol.Required("key"): str}),
    )

    with pytest.raises(HomeAssistantError, match="Failed to parse"):
        await ai_task_entity._async_generate_data(task, chat_log)


async def test_generate_data_llm_error(ai_task_entity) -> None:
    """Test that LLM errors are raised as HomeAssistantError."""

    async def _error_astream(messages):
        raise RuntimeError("LLM API down")
        yield  # noqa: F841

    ai_task_entity.entry.runtime_data.astream = MagicMock(side_effect=_error_astream)

    chat_log = _make_chat_log()
    task = _make_gen_data_task()

    with pytest.raises(HomeAssistantError, match="AI Task error"):
        await ai_task_entity._async_generate_data(task, chat_log)


async def test_generate_data_with_tools(ai_task_entity) -> None:
    """Test that tools from llm_api are bound to client."""
    import voluptuous as vol

    class MockTool:
        name = "HassTurnOn"
        description = "Turn on"
        parameters = vol.Schema({vol.Required("entity_id"): str})

    mock_api = MagicMock()
    mock_api.tools = [MockTool()]

    chat_log = _make_chat_log()
    chat_log.llm_api = mock_api

    bound_client = MagicMock()

    async def _bound_astream(messages):
        yield AIMessageChunk(content="Done, light is on")

    bound_client.astream = MagicMock(side_effect=_bound_astream)
    ai_task_entity.entry.runtime_data.bind_tools = MagicMock(return_value=bound_client)

    task = _make_gen_data_task(instructions="Turn on kitchen light")

    result = await ai_task_entity._async_generate_data(task, chat_log)

    ai_task_entity.entry.runtime_data.bind_tools.assert_called_once()
    assert result.data == "Done, light is on"


async def test_generate_data_empty_response(ai_task_entity) -> None:
    """Test handling of empty LLM response."""

    async def _empty_astream(messages):
        yield AIMessageChunk(content="")

    ai_task_entity.entry.runtime_data.astream = MagicMock(side_effect=_empty_astream)

    chat_log = _make_chat_log()
    task = _make_gen_data_task()

    result = await ai_task_entity._async_generate_data(task, chat_log)

    assert result.data == ""
