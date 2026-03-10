"""Conversation entity for GigaChain integration."""

import logging
from collections.abc import AsyncIterable
from typing import Any, Literal

from home_assistant_intents import get_languages
from homeassistant.components.conversation import (
    ChatLog,
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    SystemContent,
    UserContent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import intent, template
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)

from .const import (
    CONF_CHAT_HISTORY,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    DEFAULT_CHAT_HISTORY,
    DEFAULT_PROCESS_BUILTIN_SENTENCES,
    DEFAULT_PROMPT,
)

LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up conversation entity."""
    async_add_entities([GigaChainConversationEntity(config_entry)])


class GigaChainConversationEntity(ConversationEntity):
    """GigaChain conversation entity using ConversationEntity API."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_supports_streaming = True

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the entity."""
        self.entry = entry
        self._attr_unique_id = entry.entry_id

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
        conversation_id = chat_log.conversation_id

        # Generate system prompt
        raw_prompt = self.entry.options.get(CONF_PROMPT, DEFAULT_PROMPT)
        prompt = template.Template(raw_prompt, self.hass).async_render(
            {"ha_name": self.hass.config.location_name},
            parse_result=False,
        )
        chat_log.content[0] = SystemContent(content=prompt)

        # Convert ChatLog content → LangChain messages for LLM
        chat_history_enabled = self.entry.options.get(
            CONF_CHAT_HISTORY, DEFAULT_CHAT_HISTORY
        )
        if chat_history_enabled:
            messages = _chatlog_to_langchain(chat_log)
        else:
            # Without history: only system prompt + current user message
            messages = [
                SystemMessage(content=prompt),
                HumanMessage(content=user_input.text),
            ]

        # Try builtin HA sentence processor first
        use_builtin = self.entry.options.get(
            CONF_PROCESS_BUILTIN_SENTENCES, DEFAULT_PROCESS_BUILTIN_SENTENCES
        )
        if use_builtin:
            from homeassistant.components.conversation import agent_manager

            default_agent = agent_manager.async_get_agent(self.hass, None)
            default_response = await default_agent.async_process(user_input)

            if default_response.response.intent:
                speech = (
                    default_response.response.speech.get("plain", {}).get("speech", "")
                )
                chat_log.async_add_assistant_content_without_tools(
                    AssistantContent(
                        agent_id=user_input.agent_id,
                        content=speech,
                    )
                )
                return default_response

        # Call LLM with streaming
        client = self.entry.runtime_data

        try:
            async for _content in chat_log.async_add_delta_content_stream(
                user_input.agent_id,
                _async_langchain_stream(client, messages),
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
                conversation_id=conversation_id, response=response
            )

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(chat_log.content[-1].content or "")
        return ConversationResult(
            conversation_id=conversation_id, response=response
        )


def _chatlog_to_langchain(chat_log: ChatLog) -> list[BaseMessage]:
    """Convert ChatLog content to LangChain message list."""
    messages: list[BaseMessage] = []
    for content in chat_log.content:
        if isinstance(content, SystemContent):
            messages.append(SystemMessage(content=content.content))
        elif isinstance(content, UserContent):
            messages.append(HumanMessage(content=content.content))
        elif isinstance(content, AssistantContent):
            if content.content:
                messages.append(AIMessage(content=content.content))
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
        if delta:
            yield delta
