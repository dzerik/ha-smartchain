import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from langchain_core.messages import SystemMessage
from langchain_community.chat_models import ChatOpenAI, ChatYandexGPT, GigaChat

from .const import (CONF_API_KEY, CONF_ENGINE, CONF_FOLDER_ID, CONF_PROFANITY,
                    CONF_SKIP_VALIDATION, CONF_VERIFY_SSL, DEFAULT_PROFANITY,
                    DEFAULT_VERIFY_SSL, ID_GIGACHAT,
                    ID_YANDEX_GPT, ID_OPENAI, DEFAULT_MODEL)

LOGGER = logging.getLogger(__name__)


async def validate_client(
        hass: HomeAssistant,
        user_input: dict,
) -> None:
    """Validate LLM client connection."""
    if user_input.get(CONF_SKIP_VALIDATION):
        return
    engine = user_input.get(CONF_ENGINE) or ID_GIGACHAT
    if engine == ID_GIGACHAT:
        client = GigaChat(
            max_tokens=10,
            verbose=False,
            credentials=user_input[CONF_API_KEY],
            verify_ssl_certs=False,
        )
    elif engine == ID_YANDEX_GPT:
        client = ChatYandexGPT(
            max_tokens=10,
            max_retries=2,
            api_key=user_input[CONF_API_KEY],
            folder_id=user_input[CONF_FOLDER_ID],
        )
    else:
        client = ChatOpenAI(
            max_tokens=10,
            model=DEFAULT_MODEL[ID_OPENAI],
            openai_api_key=user_input[CONF_API_KEY],
        )
    await hass.async_add_executor_job(client.invoke, [SystemMessage(content="{}")])


async def get_client(
        hass: HomeAssistant,
        engine: str,
        entry: ConfigEntry,
        common_args: dict,
):
    """Create LLM client based on engine type."""
    if engine == ID_GIGACHAT:
        common_args["credentials"] = entry.data[CONF_API_KEY]
        common_args["verify_ssl_certs"] = entry.options.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        common_args["profanity_check"] = entry.options.get(CONF_PROFANITY, DEFAULT_PROFANITY)
        client = GigaChat(**common_args)
    elif engine == ID_YANDEX_GPT:
        common_args["api_key"] = entry.data[CONF_API_KEY]
        common_args["folder_id"] = entry.data[CONF_FOLDER_ID]
        common_args["max_retries"] = 2
        client = ChatYandexGPT(**common_args)
    else:
        if common_args["model"] is None:
            common_args["model"] = DEFAULT_MODEL[ID_OPENAI]
        common_args["openai_api_key"] = entry.data[CONF_API_KEY]
        client = ChatOpenAI(**common_args)
    return client
