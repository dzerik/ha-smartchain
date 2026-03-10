"""Conversation entity for SmartChain integration."""

import json
import logging
from collections.abc import AsyncIterable
from typing import Any, Literal

import voluptuous_openapi
from home_assistant_intents import get_languages
from homeassistant.components import conversation
from homeassistant.components.conversation import (
    ChatLog,
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    SystemContent,
    ToolResultContent,
    UserContent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import intent, llm, template
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from .const import (
    CONF_CHAT_HISTORY,
    CONF_LLM_HASS_API,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    DEFAULT_CHAT_HISTORY,
    DEFAULT_DEVICES_PROMPT,
    DEFAULT_PROCESS_BUILTIN_SENTENCES,
    DEFAULT_PROMPT,
    DOMAIN,
    MAX_TOOL_ITERATIONS,
    SUBENTRY_TYPE_CONVERSATION,
)

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up conversation entities."""
    entities: list[SmartChainConversationEntity] = []

    subentries = config_entry.subentries
    if subentries:
        for sub_id, subentry in subentries.items():
            if subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
                continue
            entities.append(
                SmartChainConversationEntity(
                    config_entry,
                    subentry_id=sub_id,
                    options=dict(subentry.data),
                )
            )
    else:
        # Legacy mode: single entity from entry.options
        entities.append(SmartChainConversationEntity(config_entry))

    async_add_entities(entities)


def _ha_tool_to_dict(tool: llm.Tool) -> dict[str, Any]:
    """Convert HA llm.Tool to dict for LangChain bind_tools."""
    parameters = voluptuous_openapi.convert(tool.parameters)
    return {
        "name": tool.name,
        "description": tool.description or "",
        "parameters": parameters,
    }


class SmartChainConversationEntity(ConversationEntity):
    """SmartChain conversation entity using ConversationEntity API."""

    _attr_has_entity_name = True
    _attr_supports_streaming = True

    def __init__(
        self,
        entry: ConfigEntry,
        subentry_id: str | None = None,
        options: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the entity."""
        self.entry = entry
        self._subentry_id = subentry_id
        self._options = options or {}

        if subentry_id:
            self._attr_unique_id = f"{entry.entry_id}_{subentry_id}"
            self._attr_name = entry.subentries[subentry_id].title
        else:
            self._attr_unique_id = entry.entry_id
            self._attr_name = None

    @property
    def _agent_options(self) -> dict[str, Any]:
        """Return the effective options for this agent."""
        if self._subentry_id:
            return self._options
        return dict(self.entry.options)

    @property
    def _client(self) -> Any:
        """Return the LLM client for this agent."""
        if self._subentry_id and isinstance(self.entry.runtime_data, dict):
            return self.entry.runtime_data[self._subentry_id]
        return self.entry.runtime_data

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return get_languages()

    async def _async_handle_message(
        self,
        user_input: ConversationInput,
        chat_log: ChatLog,
    ) -> ConversationResult:
        """Handle a conversation message via ChatLog API."""
        options = self._agent_options
        llm_hass_api = options.get(CONF_LLM_HASS_API)
        user_prompt = options.get(CONF_PROMPT, DEFAULT_PROMPT)

        if llm_hass_api:
            try:
                await chat_log.async_provide_llm_data(
                    user_input.as_llm_context(DOMAIN),
                    llm_hass_api,
                    user_prompt,
                    user_input.extra_system_prompt,
                )
            except conversation.ConverseError as err:
                return err.as_conversation_result()
        else:
            raw_prompt = user_prompt + DEFAULT_DEVICES_PROMPT
            prompt = template.Template(raw_prompt, self.hass).async_render(
                {"ha_name": self.hass.config.location_name},
                parse_result=False,
            )
            chat_log.content[0] = SystemContent(content=prompt)

        use_builtin = options.get(CONF_PROCESS_BUILTIN_SENTENCES, DEFAULT_PROCESS_BUILTIN_SENTENCES)
        if use_builtin and not llm_hass_api:
            from homeassistant.components.conversation import agent_manager

            default_agent = agent_manager.async_get_agent(self.hass, None)
            default_response = await default_agent.async_process(user_input)

            if default_response.response.intent:
                speech = default_response.response.speech.get("plain", {}).get("speech", "")
                chat_log.async_add_assistant_content_without_tools(
                    AssistantContent(
                        agent_id=user_input.agent_id,
                        content=speech,
                    )
                )
                return default_response

        client = self._client
        tools = (
            [_ha_tool_to_dict(tool) for tool in chat_log.llm_api.tools] if chat_log.llm_api else []
        )
        bound_client = client.bind_tools(tools) if tools else client

        for _iteration in range(MAX_TOOL_ITERATIONS):
            chat_history_enabled = options.get(CONF_CHAT_HISTORY, DEFAULT_CHAT_HISTORY)
            if chat_history_enabled:
                messages = _chatlog_to_langchain(chat_log)
            else:
                messages = [
                    SystemMessage(content=chat_log.content[0].content),
                    HumanMessage(content=user_input.text),
                ]

            try:
                async for _content in chat_log.async_add_delta_content_stream(
                    user_input.agent_id,
                    _async_langchain_stream(bound_client, messages),
                ):
                    pass
            except Exception as err:
                LOGGER.exception("Unexpected exception %s", type(err))
                response = intent.IntentResponse(language=user_input.language)
                response.async_set_error(
                    intent.IntentResponseErrorCode.UNKNOWN,
                    f"Houston we have a problem: {err}",
                )
                return ConversationResult(
                    conversation_id=chat_log.conversation_id, response=response
                )

            if not chat_log.unresponded_tool_results:
                break

        return conversation.async_get_result_from_chat_log(user_input, chat_log)


def _chatlog_to_langchain(chat_log: ChatLog) -> list[BaseMessage]:
    """Convert ChatLog content to LangChain message list."""
    messages: list[BaseMessage] = []
    for content in chat_log.content:
        if isinstance(content, SystemContent):
            messages.append(SystemMessage(content=content.content))
        elif isinstance(content, UserContent):
            messages.append(HumanMessage(content=content.content))
        elif isinstance(content, AssistantContent):
            if content.tool_calls:
                tool_calls = [
                    {
                        "id": tc.id,
                        "name": tc.tool_name,
                        "args": tc.tool_args,
                    }
                    for tc in content.tool_calls
                ]
                messages.append(
                    AIMessage(
                        content=content.content or "",
                        tool_calls=tool_calls,
                    )
                )
            elif content.content:
                messages.append(AIMessage(content=content.content))
        elif isinstance(content, ToolResultContent):
            messages.append(
                ToolMessage(
                    content=json.dumps(content.tool_result),
                    tool_call_id=content.tool_call_id,
                    name=content.tool_name,
                )
            )
    return messages


async def _async_langchain_stream(
    client: Any, messages: list[BaseMessage]
) -> AsyncIterable[dict[str, Any]]:
    """Convert LangChain astream chunks to HA delta dicts."""
    first = True
    async for chunk in client.astream(messages):
        delta: dict[str, Any] = {}
        if first:
            delta["role"] = "assistant"
            first = False
        if chunk.content:
            delta["content"] = chunk.content

        if chunk.tool_calls:
            delta["tool_calls"] = [
                llm.ToolInput(
                    tool_name=tc["name"],
                    tool_args=tc["args"],
                    id=tc["id"],
                )
                for tc in chunk.tool_calls
            ]

        if delta:
            yield delta
