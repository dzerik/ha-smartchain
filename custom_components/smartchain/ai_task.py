"""AI Task entity for SmartChain integration."""

import logging
from typing import Any

from homeassistant.components import ai_task, conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import MAX_TOOL_ITERATIONS
from .conversation import (
    _async_langchain_stream,
    _chatlog_to_langchain,
    _ha_tool_to_dict,
)

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AI Task entity."""
    async_add_entities([SmartChainAITaskEntity(config_entry)])


class SmartChainAITaskEntity(ai_task.AITaskEntity):
    """SmartChain AI Task entity for data generation."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the entity."""
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_ai_task"
        self._attr_supported_features = ai_task.AITaskEntityFeature.GENERATE_DATA

    async def _async_generate_data(
        self,
        task: ai_task.GenDataTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenDataTaskResult:
        """Handle a generate data task."""
        client = self.entry.runtime_data
        tools: list[dict[str, Any]] = (
            [_ha_tool_to_dict(tool) for tool in chat_log.llm_api.tools]
            if chat_log.llm_api
            else []
        )
        bound_client = client.bind_tools(tools) if tools else client

        for _iteration in range(MAX_TOOL_ITERATIONS):
            messages = _chatlog_to_langchain(chat_log)

            try:
                async for _content in chat_log.async_add_delta_content_stream(
                    self.entity_id,
                    _async_langchain_stream(bound_client, messages),
                ):
                    pass
            except Exception as err:
                LOGGER.exception("AI Task error: %s", type(err))
                raise HomeAssistantError(f"AI Task error: {err}") from err

            if not chat_log.unresponded_tool_results:
                break

        if not isinstance(chat_log.content[-1], conversation.AssistantContent):
            raise HomeAssistantError(
                "Last content in chat log is not an AssistantContent"
            )

        text = chat_log.content[-1].content or ""

        if task.structure:
            from homeassistant.util.json import json_loads
            from json import JSONDecodeError

            try:
                data = json_loads(text)
            except JSONDecodeError as err:
                LOGGER.error("Failed to parse structured response: %s", err)
                raise HomeAssistantError(
                    "Failed to parse structured AI Task response"
                ) from err

            return ai_task.GenDataTaskResult(
                conversation_id=chat_log.conversation_id,
                data=data,
            )

        return ai_task.GenDataTaskResult(
            conversation_id=chat_log.conversation_id,
            data=text,
        )
