"""The GigaChain integration."""

import logging
from collections import OrderedDict
from typing import Literal

from home_assistant_intents import get_languages
from homeassistant.components import conversation
from homeassistant.components.conversation import agent_manager
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent, template
from homeassistant.util import ulid
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage

from .client_util import get_client
from .const import (CONF_CHAT_MODEL, CONF_CHAT_MODEL_USER,
                    CONF_ENGINE, CONF_MAX_TOKENS,
                    CONF_PROFANITY, CONF_PROMPT, CONF_TEMPERATURE,
                    DEFAULT_PROFANITY, DEFAULT_PROMPT,
                    CONF_PROCESS_BUILTIN_SENTENCES, DEFAULT_PROCESS_BUILTIN_SENTENCES,
                    CONF_CHAT_HISTORY, DEFAULT_CHAT_HISTORY,
                    DEFAULT_TEMPERATURE, DOMAIN, ID_GIGACHAT,
                    MAX_HISTORY_CONVERSATIONS)

LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CONVERSATION]


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize GigaChain."""
    engine = entry.data.get(CONF_ENGINE) or ID_GIGACHAT
    model = entry.options.get(CONF_CHAT_MODEL_USER)
    if not model or not model.strip():
        model = entry.options.get(CONF_CHAT_MODEL)
    temperature = entry.options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
    max_tokens = entry.options.get(CONF_MAX_TOKENS)

    entry.async_on_unload(entry.add_update_listener(update_listener))

    common_args = {
        "verbose": False,
        "model": model
    }
    if temperature is not None:
        common_args["temperature"] = temperature
    if max_tokens is not None:
        common_args["max_tokens"] = max_tokens

    client = await get_client(hass, engine, entry, common_args)

    entry.runtime_data = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload GigaChain."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
