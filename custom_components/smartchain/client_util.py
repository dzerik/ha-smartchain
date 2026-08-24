import logging
import re
from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from langchain_community.chat_models import ChatYandexGPT
from langchain_core.messages import SystemMessage
from langchain_gigachat import GigaChat
from langchain_openai import ChatOpenAI

from .const import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDINGS,
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    CONF_FOLDER_ID,
    CONF_PROFANITY,
    CONF_SKIP_VALIDATION,
    CONF_VERIFY_SSL,
    DEFAULT_MODEL,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_PROFANITY,
    DEFAULT_VERIFY_SSL,
    EMBEDDING_RULE_HEURISTIC,
    EMBEDDING_RULE_OPENAI_PREFIX,
    ID_ANTHROPIC,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
    OPENAI_COMPATIBLE,
    OpenAICompatible,
)

LOGGER = logging.getLogger(__name__)

# The four hand-written providers are literal; every OpenAI-compatible one
# contributes its row's capabilities.
PROVIDER_CAPABILITIES: dict[str, frozenset[str]] = {
    ID_GIGACHAT: frozenset({CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS}),
    ID_YANDEX_GPT: frozenset({CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS}),
    ID_OLLAMA: frozenset({CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS}),
    ID_ANTHROPIC: frozenset({CAPABILITY_CHAT}),
    **{
        engine: frozenset(
            {CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS} if row.serves_embeddings else {CAPABILITY_CHAT}
        )
        for engine, row in OPENAI_COMPATIBLE.items()
    },
}


def supports(engine: str, capability: str) -> bool:
    """Whether `engine` can serve `capability`. Unknown engines support nothing."""
    return capability in PROVIDER_CAPABILITIES.get(engine, frozenset())


# A local server needs no credential, but ChatOpenAI rejects a None key.
_PLACEHOLDER_API_KEY = "not-needed"


def compatible_base_url(row: OpenAICompatible, data: Mapping[str, Any]) -> str:
    """The provider's endpoint: the user's if set, else the row's default."""
    return (data.get(CONF_BASE_URL) or "").strip() or row.default_base_url


def compatible_api_key(row: OpenAICompatible, data: Mapping[str, Any]) -> str:
    """The credential to send, with a placeholder for keyless local servers."""
    key = (data.get(CONF_API_KEY) or "").strip()
    if key:
        return key
    if row.requires_api_key:
        # The flow makes this field required, so an empty one means a
        # hand-edited entry; let the provider return its own auth error.
        return ""
    return _PLACEHOLDER_API_KEY


def compatible_endpoint(engine: str, row: OpenAICompatible, data: Mapping[str, Any]) -> str | None:
    """The endpoint to pass, or None to let the client's own default stand.

    OpenAI had no explicit base URL before the provider table existed, so an
    OPENAI_BASE_URL environment variable applied. Passing one now — even the
    correct one — would override it. Every other row always needs an endpoint.
    """
    raw = (data.get(CONF_BASE_URL) or "").strip()
    if engine == ID_OPENAI and not raw:
        return None
    return raw or row.default_base_url


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
    elif engine == ID_ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        client = ChatAnthropic(
            max_tokens=10,
            model_name=DEFAULT_MODEL[ID_ANTHROPIC],
            api_key=user_input[CONF_API_KEY],
        )
    elif engine in OPENAI_COMPATIBLE:
        row = OPENAI_COMPATIBLE[engine]
        base_url = compatible_base_url(row, user_input)
        api_key = compatible_api_key(row, user_input)
        if row.default_model is None:
            # No default model means no name we could put in a chat probe —
            # a local server almost certainly does not serve whatever we
            # guessed. Listing models proves reachability and credentials
            # without guessing, and it is exactly what these servers expose.
            models = await _fetch_openai_compatible_models(
                hass, user_input, f"{base_url}/models", api_key
            )
            if not models:
                raise ValueError(f"{row.label} returned no models")
            return
        chat_kwargs: dict[str, Any] = {
            "max_tokens": 10,
            "model": row.default_model,
            "openai_api_key": api_key,
        }
        endpoint = compatible_endpoint(engine, row, user_input)
        if endpoint is not None:
            chat_kwargs["openai_api_base"] = endpoint
        client = ChatOpenAI(**chat_kwargs)
    else:
        LOGGER.warning("Unrecognised engine %r during validation; treating it as OpenAI", engine)
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
        # Prefer per-subentry value (passed via common_args); fall back to legacy entry.options.
        verify_ssl = common_args.pop(
            CONF_VERIFY_SSL, entry.options.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
        )
        profanity = common_args.pop(
            CONF_PROFANITY, entry.options.get(CONF_PROFANITY, DEFAULT_PROFANITY)
        )
        common_args["verify_ssl_certs"] = verify_ssl
        common_args["profanity_check"] = profanity
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
    elif engine == ID_ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        if common_args["model"] is None:
            common_args["model"] = DEFAULT_MODEL[ID_ANTHROPIC]
        common_args["api_key"] = entry.data[CONF_API_KEY]
        common_args.pop("verbose", None)
        common_args["model_name"] = common_args.pop("model")
        client = ChatAnthropic(**common_args)
    elif engine in OPENAI_COMPATIBLE:
        row = OPENAI_COMPATIBLE[engine]
        if not common_args.get("model"):
            if row.default_model is None:
                # Let the provider pick, the way GigaChat and YandexGPT do.
                common_args.pop("model", None)
            else:
                common_args["model"] = row.default_model
        common_args["openai_api_key"] = compatible_api_key(row, entry.data)
        endpoint = compatible_endpoint(engine, row, entry.data)
        if endpoint is not None:
            common_args["openai_api_base"] = endpoint
        client = ChatOpenAI(**common_args)
    else:
        LOGGER.warning("Unrecognised engine %r; treating it as OpenAI", engine)
        if common_args["model"] is None:
            common_args["model"] = DEFAULT_MODEL[ID_OPENAI]
        common_args["openai_api_key"] = entry.data[CONF_API_KEY]
        client = ChatOpenAI(**common_args)
    return client


# Ollama's /api/tags does not report purpose, so names are classified by a
# heuristic covering the embedding families in common use.
_OLLAMA_EMBEDDING_HINT = re.compile(r"embed|bge-|gte-|e5-|minilm", re.IGNORECASE)


def is_embedding_model(engine: str, name: str) -> bool:
    """Whether `name` is an embedding model for `engine`."""
    row = OPENAI_COMPATIBLE.get(engine)
    if row is not None:
        if row.embedding_rule == EMBEDDING_RULE_OPENAI_PREFIX:
            return name.startswith("text-embedding-")
        if row.embedding_rule == EMBEDDING_RULE_HEURISTIC:
            return bool(_OLLAMA_EMBEDDING_HINT.search(name))
        return False
    if engine == ID_GIGACHAT:
        return name.startswith("Embeddings")
    if engine == ID_OLLAMA:
        return bool(_OLLAMA_EMBEDDING_HINT.search(name))
    if engine == ID_YANDEX_GPT:
        return name.startswith("text-search-")
    return False


async def async_fetch_models(
    hass: HomeAssistant,
    engine: str,
    data: dict,
    purpose: str = CAPABILITY_CHAT,
) -> list[str]:
    """Fetch available models from provider API, filtered by purpose.

    Returns a list of model names with an empty string first (the 'custom'
    option). Falls back to the static list for `purpose` on any error.
    """
    from .const import (
        ENGINE_EMBEDDING_MODELS,
        ENGINE_MODELS,
        UNIQUE_ID,
    )

    want_embeddings = purpose == CAPABILITY_EMBEDDINGS
    static = (
        ENGINE_EMBEDDING_MODELS.get(UNIQUE_ID.get(engine, ""), [""])
        if want_embeddings
        else ENGINE_MODELS.get(UNIQUE_ID.get(engine, ""), [""])
    )

    try:
        if engine in OPENAI_COMPATIBLE:
            row = OPENAI_COMPATIBLE[engine]
            models = await _fetch_openai_compatible_models(
                hass,
                data,
                f"{compatible_base_url(row, data)}/models",
                compatible_api_key(row, data),
            )
        elif engine == ID_OLLAMA:
            models = await _fetch_ollama_models(hass, data)
        elif engine == ID_ANTHROPIC:
            models = await _fetch_anthropic_models(hass, data)
        elif engine == ID_GIGACHAT:
            models = await _fetch_gigachat_models(hass, data)
        else:
            # YandexGPT has no list endpoint.
            return static

        models = [m for m in models if is_embedding_model(engine, m) == want_embeddings]
        if models:
            return [""] + models
        raise ValueError("Empty model list")
    except Exception:
        LOGGER.debug("Failed to fetch %s models for %s, using static list", purpose, engine)
        return static


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
    resp.raise_for_status()
    result = await resp.json()
    return sorted(m["name"] for m in result.get("models", []))


async def _fetch_openai_compatible_models(
    hass: HomeAssistant, data: dict, url: str, api_key: str | None = None
) -> list[str]:
    """Fetch models from any OpenAI-compatible /models endpoint."""
    import aiohttp
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    session = async_get_clientsession(hass)
    key = api_key if api_key is not None else data.get(CONF_API_KEY, "")
    headers = {"Authorization": f"Bearer {key}"}
    resp = await session.get(
        url,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=10),
    )
    resp.raise_for_status()
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
    resp.raise_for_status()
    result = await resp.json()
    return sorted(m["id"] for m in result.get("data", []))


async def _fetch_gigachat_models(hass: HomeAssistant, data: dict) -> list[str]:
    """Fetch models from GigaChat API via SDK."""
    client = GigaChat(credentials=data[CONF_API_KEY], verify_ssl_certs=False)
    result = await hass.async_add_executor_job(client.get_models)
    return sorted(m.id_ for m in result.data)
