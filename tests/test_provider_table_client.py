"""Client build, validation and discovery for OpenAI-compatible providers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.client_util import (
    async_fetch_models,
    get_client,
    validate_client,
)
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    CONF_SKIP_VALIDATION,
    DOMAIN,
    ID_DEEPSEEK,
    ID_GROQ,
    ID_LMSTUDIO,
    ID_OPENAI,
    ID_OPENROUTER,
    OPENAI_COMPATIBLE,
)

PLACEHOLDER_KEY = "not-needed"


def _entry(hass, engine: str, data: dict) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_ENGINE: engine, **data})
    entry.add_to_hass(hass)
    return entry


async def test_hosted_provider_uses_its_default_base_url(hass):
    entry = _entry(hass, ID_GROQ, {CONF_API_KEY: "k"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_GROQ, entry, {"model": "llama-3.3-70b"})
    kwargs = chat.call_args.kwargs
    assert kwargs["openai_api_base"] == OPENAI_COMPATIBLE[ID_GROQ].default_base_url
    assert kwargs["openai_api_key"] == "k"
    assert kwargs["model"] == "llama-3.3-70b"


async def test_hosted_provider_never_gets_the_placeholder_key(hass):
    # A fake credential must never reach a paid API: an empty key makes the
    # provider return its own auth error, which is the honest outcome.
    entry = _entry(hass, ID_GROQ, {})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_GROQ, entry, {"model": "m"})
    assert chat.call_args.kwargs["openai_api_key"] == ""


async def test_hosted_provider_with_a_blank_key_gets_no_placeholder(hass):
    entry = _entry(hass, ID_GROQ, {CONF_API_KEY: "   "})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_GROQ, entry, {"model": "m"})
    assert chat.call_args.kwargs["openai_api_key"] == ""


async def test_entry_base_url_overrides_the_default(hass):
    entry = _entry(hass, ID_GROQ, {CONF_API_KEY: "k", CONF_BASE_URL: "http://mirror/v1"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_GROQ, entry, {"model": "m"})
    assert chat.call_args.kwargs["openai_api_base"] == "http://mirror/v1"


async def test_local_provider_gets_a_placeholder_key(hass):
    entry = _entry(hass, ID_LMSTUDIO, {CONF_BASE_URL: "http://localhost:1234/v1"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_LMSTUDIO, entry, {"model": "m"})
    assert chat.call_args.kwargs["openai_api_key"] == PLACEHOLDER_KEY


async def test_local_provider_honours_a_supplied_key(hass):
    entry = _entry(hass, ID_LMSTUDIO, {CONF_API_KEY: "real", CONF_BASE_URL: "http://x/v1"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_LMSTUDIO, entry, {"model": "m"})
    assert chat.call_args.kwargs["openai_api_key"] == "real"


async def test_row_without_a_default_model_omits_the_argument(hass):
    entry = _entry(hass, ID_OPENROUTER, {CONF_API_KEY: "k"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_OPENROUTER, entry, {"model": None})
    assert "model" not in chat.call_args.kwargs


async def test_validate_uses_the_row_base_url(hass):
    # A row with a default model (unlike ID_GROQ, which has none) takes the
    # ChatOpenAI probe branch this test exercises.
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        chat.return_value.invoke = MagicMock()
        await validate_client(hass, {CONF_ENGINE: ID_DEEPSEEK, CONF_API_KEY: "k"})
    assert (
        chat.call_args.kwargs["openai_api_base"] == OPENAI_COMPATIBLE[ID_DEEPSEEK].default_base_url
    )


async def test_validate_lists_models_when_the_row_has_no_default(hass):
    # A local server has no name we could put in a chat probe.
    fetch = AsyncMock(return_value=["local-model"])
    with (
        patch(
            "custom_components.smartchain.client_util._fetch_openai_compatible_models",
            fetch,
        ),
        patch("custom_components.smartchain.client_util.ChatOpenAI") as chat,
    ):
        await validate_client(hass, {CONF_ENGINE: ID_LMSTUDIO})
    chat.assert_not_called()
    assert fetch.call_args.args[2].endswith("/models")


async def test_validate_rejects_a_server_serving_nothing(hass):
    fetch = AsyncMock(return_value=[])
    with patch("custom_components.smartchain.client_util._fetch_openai_compatible_models", fetch):
        with pytest.raises(ValueError, match="no models"):
            await validate_client(hass, {CONF_ENGINE: ID_LMSTUDIO})


async def test_validate_is_skippable(hass):
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await validate_client(
            hass, {CONF_ENGINE: ID_GROQ, CONF_API_KEY: "k", CONF_SKIP_VALIDATION: True}
        )
    chat.assert_not_called()


async def test_discovery_hits_the_row_models_endpoint(hass):
    fetch = AsyncMock(return_value=["llama-3.3-70b", "mixtral"])
    with patch("custom_components.smartchain.client_util._fetch_openai_compatible_models", fetch):
        models = await async_fetch_models(hass, ID_GROQ, {CONF_API_KEY: "k"})
    assert fetch.call_args.args[2] == (f"{OPENAI_COMPATIBLE[ID_GROQ].default_base_url}/models")
    assert models == ["", "llama-3.3-70b", "mixtral"]


async def test_discovery_honours_an_overridden_base_url(hass):
    fetch = AsyncMock(return_value=["m"])
    with patch("custom_components.smartchain.client_util._fetch_openai_compatible_models", fetch):
        await async_fetch_models(
            hass, ID_GROQ, {CONF_API_KEY: "k", CONF_BASE_URL: "http://mirror/v1"}
        )
    assert fetch.call_args.args[2] == "http://mirror/v1/models"


async def test_discovery_falls_back_to_the_static_list(hass):
    fetch = AsyncMock(side_effect=RuntimeError("down"))
    with patch("custom_components.smartchain.client_util._fetch_openai_compatible_models", fetch):
        models = await async_fetch_models(hass, ID_OPENROUTER, {CONF_API_KEY: "k"})
    assert models == OPENAI_COMPATIBLE[ID_OPENROUTER].static_models


async def test_keyless_local_provider_validates_without_a_configured_key(hass, aioclient_mock):
    # Nothing between validate_client and the credential it builds is
    # mocked here — only the outbound HTTP call is faked. LM Studio is
    # keyless (requires_api_key=False), so its config entry carries no
    # CONF_API_KEY at all; validate_client must still succeed rather than
    # raising a bare KeyError while building the request headers.
    aioclient_mock.get(
        f"{OPENAI_COMPATIBLE[ID_LMSTUDIO].default_base_url}/models",
        json={"data": [{"id": "local-model"}]},
    )
    await validate_client(hass, {CONF_ENGINE: ID_LMSTUDIO})


async def test_openai_with_no_base_url_omits_the_argument(hass):
    # Before the provider table, OpenAI got no explicit base URL, letting
    # the OPENAI_BASE_URL environment variable apply. That must not change.
    entry = _entry(hass, ID_OPENAI, {CONF_API_KEY: "k"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_OPENAI, entry, {"model": "gpt-4.1-mini"})
    assert "openai_api_base" not in chat.call_args.kwargs


async def test_openai_with_a_configured_base_url_receives_it(hass):
    entry = _entry(hass, ID_OPENAI, {CONF_API_KEY: "k", CONF_BASE_URL: "http://mirror/v1"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_OPENAI, entry, {"model": "gpt-4.1-mini"})
    assert chat.call_args.kwargs["openai_api_base"] == "http://mirror/v1"
