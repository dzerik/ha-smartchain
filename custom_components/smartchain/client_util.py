import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from langchain_community.chat_models import ChatYandexGPT
from langchain_core.messages import SystemMessage
from langchain_gigachat import GigaChat
from langchain_openai import ChatOpenAI

from .const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    CONF_FOLDER_ID,
    CONF_PROFANITY,
    CONF_SKIP_VALIDATION,
    CONF_VERIFY_SSL,
    DEFAULT_DEEPSEEK_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_PROFANITY,
    DEFAULT_VERIFY_SSL,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
)

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
    elif engine == ID_OLLAMA:
        from langchain_ollama import ChatOllama

        base_url = user_input.get(CONF_BASE_URL, DEFAULT_OLLAMA_BASE_URL)
        client = ChatOllama(
            model=DEFAULT_MODEL[ID_OLLAMA],
            base_url=base_url,
            num_predict=10,
        )
    elif engine == ID_DEEPSEEK:
        client = ChatOpenAI(
            max_tokens=10,
            model=DEFAULT_MODEL[ID_DEEPSEEK],
            openai_api_key=user_input[CONF_API_KEY],
            openai_api_base=DEFAULT_DEEPSEEK_BASE_URL,
        )
    elif engine == ID_ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        client = ChatAnthropic(
            max_tokens=10,
            model_name=DEFAULT_MODEL[ID_ANTHROPIC],
            api_key=user_input[CONF_API_KEY],
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
        if not common_args.get("model"):
            common_args.pop("model", None)
        common_args["credentials"] = entry.data[CONF_API_KEY]
        common_args["verify_ssl_certs"] = entry.options.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        common_args["profanity_check"] = entry.options.get(CONF_PROFANITY, DEFAULT_PROFANITY)
        common_args["auto_upload_images"] = True
        client = GigaChat(**common_args)
    elif engine == ID_YANDEX_GPT:
        if not common_args.get("model"):
            common_args.pop("model", None)
        common_args["api_key"] = entry.data[CONF_API_KEY]
        common_args["folder_id"] = entry.data[CONF_FOLDER_ID]
        common_args["max_retries"] = 2
        client = ChatYandexGPT(**common_args)
    elif engine == ID_OLLAMA:
        from langchain_ollama import ChatOllama

        base_url = entry.data.get(CONF_BASE_URL, DEFAULT_OLLAMA_BASE_URL)
        if common_args["model"] is None:
            common_args["model"] = DEFAULT_MODEL[ID_OLLAMA]
        common_args["base_url"] = base_url
        common_args.pop("verbose", None)
        client = ChatOllama(**common_args)
    elif engine == ID_DEEPSEEK:
        if common_args["model"] is None:
            common_args["model"] = DEFAULT_MODEL[ID_DEEPSEEK]
        common_args["openai_api_key"] = entry.data[CONF_API_KEY]
        common_args["openai_api_base"] = DEFAULT_DEEPSEEK_BASE_URL
        client = ChatOpenAI(**common_args)
    elif engine == ID_ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        if common_args["model"] is None:
            common_args["model"] = DEFAULT_MODEL[ID_ANTHROPIC]
        common_args["api_key"] = entry.data[CONF_API_KEY]
        common_args.pop("verbose", None)
        common_args["model_name"] = common_args.pop("model")
        client = ChatAnthropic(**common_args)
    else:
        if common_args["model"] is None:
            common_args["model"] = DEFAULT_MODEL[ID_OPENAI]
        common_args["openai_api_key"] = entry.data[CONF_API_KEY]
        client = ChatOpenAI(**common_args)
    return client


async def async_fetch_models(
    hass: HomeAssistant,
    engine: str,
    data: dict,
) -> list[str]:
    """Fetch available models from provider API.

    Returns a list of model names with empty string first (for 'custom' option).
    Falls back to static ENGINE_MODELS on any error.
    """
    from .const import ENGINE_MODELS, UNIQUE_ID

    try:
        if engine == ID_OLLAMA:
            models = await _fetch_ollama_models(hass, data)
        elif engine == ID_OPENAI:
            models = await _fetch_openai_compatible_models(
                hass, data, "https://api.openai.com/v1/models"
            )
        elif engine == ID_DEEPSEEK:
            models = await _fetch_openai_compatible_models(
                hass, data, f"{DEFAULT_DEEPSEEK_BASE_URL}/models"
            )
        elif engine == ID_ANTHROPIC:
            models = await _fetch_anthropic_models(hass, data)
        elif engine == ID_GIGACHAT:
            models = await _fetch_gigachat_models(hass, data)
        else:
            # YandexGPT — no standard list API, use static
            return ENGINE_MODELS.get(UNIQUE_ID.get(engine, ""), [""])

        if models:
            return [""] + models
        raise ValueError("Empty model list")
    except Exception:
        LOGGER.debug("Failed to fetch models for %s, using static list", engine)
        return ENGINE_MODELS.get(UNIQUE_ID.get(engine, ""), [""])


async def _fetch_ollama_models(hass: HomeAssistant, data: dict) -> list[str]:
    """Fetch models from Ollama API."""
    import aiohttp
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    base_url = data.get(CONF_BASE_URL, DEFAULT_OLLAMA_BASE_URL)
    resp = await session.get(
        f"{base_url}/api/tags",
        timeout=aiohttp.ClientTimeout(total=10),
    )
    result = await resp.json()
    return sorted(m["name"] for m in result.get("models", []))


async def _fetch_openai_compatible_models(hass: HomeAssistant, data: dict, url: str) -> list[str]:
    """Fetch models from OpenAI-compatible API (OpenAI, DeepSeek)."""
    import aiohttp
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    headers = {"Authorization": f"Bearer {data[CONF_API_KEY]}"}
    resp = await session.get(
        url,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=10),
    )
    result = await resp.json()
    return sorted(m["id"] for m in result.get("data", []))


async def _fetch_anthropic_models(hass: HomeAssistant, data: dict) -> list[str]:
    """Fetch models from Anthropic API."""
    import aiohttp
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    headers = {
        "x-api-key": data[CONF_API_KEY],
        "anthropic-version": "2023-06-01",
    }
    resp = await session.get(
        "https://api.anthropic.com/v1/models",
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=10),
    )
    result = await resp.json()
    return sorted(m["id"] for m in result.get("data", []))


async def _fetch_gigachat_models(hass: HomeAssistant, data: dict) -> list[str]:
    """Fetch models from GigaChat API via SDK."""
    client = GigaChat(credentials=data[CONF_API_KEY], verify_ssl_certs=False)
    result = await hass.async_add_executor_job(client.get_models)
    return sorted(m.id_ for m in result.data)
