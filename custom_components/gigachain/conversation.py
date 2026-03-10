"""Conversation entity for GigaChain integration."""

import logging
from collections import OrderedDict
from typing import Literal

from home_assistant_intents import get_languages
from homeassistant.components.conversation import (
    AssistantContent,
    ChatLog,
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import intent
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
    DOMAIN,
    MAX_HISTORY_CONVERSATIONS,
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

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the entity."""
        self.entry = entry
        self.history: OrderedDict[str, list[BaseMessage]] = OrderedDict()
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
        raw_prompt = self.entry.options.get(CONF_PROMPT, DEFAULT_PROMPT)
        chat_history_enabled = self.entry.options.get(
            CONF_CHAT_HISTORY, DEFAULT_CHAT_HISTORY
        )
        conversation_id = chat_log.conversation_id

        # Build LangChain message list
        if conversation_id in self.history and chat_history_enabled:
            messages = self.history[conversation_id]
        else:
            from homeassistant.helpers import template

            prompt = template.Template(raw_prompt, self.hass).async_render(
                {"ha_name": self.hass.config.location_name},
                parse_result=False,
            )
            messages = [SystemMessage(content=prompt)]

        messages.append(HumanMessage(content=user_input.text))

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
                messages.append(AIMessage(content=speech))
                self._save_history(conversation_id, messages)

                chat_log.async_add_assistant_content_without_tools(
                    AssistantContent(
                        agent_id=user_input.agent_id,
                        content=speech,
                    )
                )
                return default_response

        # Call LLM
        client = self.entry.runtime_data

        try:
            res = await self.hass.async_add_executor_job(client.invoke, messages)
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

        messages.append(res)
        self._save_history(conversation_id, messages)
        LOGGER.debug("Conversation %s: %s", conversation_id, messages)

        content_text = res.content
        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(
                agent_id=user_input.agent_id,
                content=content_text,
            )
        )

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(content_text)
        return ConversationResult(
            conversation_id=conversation_id, response=response
        )

    def _save_history(
        self, conversation_id: str, messages: list[BaseMessage]
    ) -> None:
        """Save conversation history with size limit."""
        self.history[conversation_id] = messages
        while len(self.history) > MAX_HISTORY_CONVERSATIONS:
            self.history.popitem(last=False)
