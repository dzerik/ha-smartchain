"""Tests for dynamic model fetching."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.client_util import (
    ModelFetchError,
    async_fetch_models,
    connection_data,
    static_models,
)
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    CONF_VERIFY_SSL,
    DOMAIN,
    ENGINE_MODELS,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
    UNIQUE_ID_GIGACHAT,
    UNIQUE_ID_YANDEX_GPT,
)

PATCH_SESSION = "homeassistant.helpers.aiohttp_client.async_get_clientsession"


@pytest.fixture
def mock_session():
    """Create a mock aiohttp session."""
    session = MagicMock()
    response = AsyncMock()
    response.raise_for_status = MagicMock()
    session.get = AsyncMock(return_value=response)
    return session, response


async def test_fetch_ollama_models(hass: HomeAssistant, mock_session):
    """Test fetching models from Ollama."""
    session, response = mock_session
    response.json = AsyncMock(
        return_value={
            "models": [
                {"name": "llama3.3"},
                {"name": "gemma3"},
                {"name": "qwen3"},
            ]
        }
    )

    with patch(PATCH_SESSION, return_value=session):
        models = await async_fetch_models(
            hass, ID_OLLAMA, {CONF_BASE_URL: "http://localhost:11434"}
        )

    assert models[0] == ""
    assert "gemma3" in models
    assert "llama3.3" in models
    assert "qwen3" in models


async def test_fetch_openai_models(hass: HomeAssistant, mock_session):
    """Test fetching models from OpenAI."""
    session, response = mock_session
    response.json = AsyncMock(
        return_value={
            "data": [
                {"id": "gpt-4o"},
                {"id": "gpt-4.1-mini"},
                {"id": "o3"},
            ]
        }
    )

    with patch(PATCH_SESSION, return_value=session):
        models = await async_fetch_models(hass, ID_OPENAI, {CONF_API_KEY: "test-key"})

    assert models[0] == ""
    assert "gpt-4o" in models
    assert "gpt-4.1-mini" in models


async def test_fetch_deepseek_models(hass: HomeAssistant, mock_session):
    """Test fetching models from DeepSeek."""
    session, response = mock_session
    response.json = AsyncMock(
        return_value={
            "data": [
                {"id": "deepseek-chat"},
                {"id": "deepseek-reasoner"},
            ]
        }
    )

    with patch(PATCH_SESSION, return_value=session):
        models = await async_fetch_models(hass, ID_DEEPSEEK, {CONF_API_KEY: "test-key"})

    assert models[0] == ""
    assert "deepseek-chat" in models
    assert "deepseek-reasoner" in models


async def test_fetch_anthropic_models(hass: HomeAssistant, mock_session):
    """Test fetching models from Anthropic."""
    session, response = mock_session
    response.json = AsyncMock(
        return_value={
            "data": [
                {"id": "claude-sonnet-4-6"},
                {"id": "claude-haiku-4-5"},
            ]
        }
    )

    with patch(PATCH_SESSION, return_value=session):
        models = await async_fetch_models(hass, ID_ANTHROPIC, {CONF_API_KEY: "test-key"})

    assert models[0] == ""
    assert "claude-haiku-4-5" in models
    assert "claude-sonnet-4-6" in models


async def test_fetch_gigachat_models(hass: HomeAssistant):
    """Test fetching models from GigaChat."""
    mock_model_1 = MagicMock()
    mock_model_1.id_ = "GigaChat"
    mock_model_2 = MagicMock()
    mock_model_2.id_ = "GigaChat-Pro"
    mock_result = MagicMock()
    mock_result.data = [mock_model_1, mock_model_2]

    with patch("custom_components.smartchain.client_util.GigaChat") as mock_giga_cls:
        mock_client = MagicMock()
        mock_client.get_models.return_value = mock_result
        mock_giga_cls.return_value = mock_client
        hass.async_add_executor_job = AsyncMock(return_value=mock_result)

        models = await async_fetch_models(hass, ID_GIGACHAT, {CONF_API_KEY: "test-creds"})

    assert models[0] == ""
    assert "GigaChat" in models
    assert "GigaChat-Pro" in models


async def test_fetch_yandex_returns_static(hass: HomeAssistant):
    """Test YandexGPT returns static list (no dynamic API)."""
    models = await async_fetch_models(hass, ID_YANDEX_GPT, {CONF_API_KEY: "test-key"})
    assert models == ENGINE_MODELS[UNIQUE_ID_YANDEX_GPT]


async def test_fetch_models_fallback_on_error(hass: HomeAssistant):
    """Test fallback to static list on network error."""
    with patch(PATCH_SESSION, side_effect=Exception("Network error")):
        models = await async_fetch_models(
            hass, ID_OLLAMA, {CONF_BASE_URL: "http://localhost:11434"}
        )

    # Should return static fallback
    assert "" in models
    assert len(models) > 1


async def test_strict_fetch_raises_instead_of_substituting(hass: HomeAssistant):
    """`strict=True` refuses to pass a fallback off as the provider's answer.

    The default is unchanged — a config-flow dialog still degrades to the
    static list. But a caller that is going to *cache* the result has to be
    able to tell "these are the models" from "we could not ask".
    """
    with patch(PATCH_SESSION, side_effect=Exception("Network error")):
        with pytest.raises(ModelFetchError):
            await async_fetch_models(
                hass,
                ID_OLLAMA,
                {CONF_BASE_URL: "http://localhost:11434"},
                strict=True,
            )


async def test_static_models_is_a_copy(hass: HomeAssistant):
    """Callers extend the list they are given; the constant must not move."""
    first = static_models(ID_GIGACHAT)
    first.append("GigaChat-99-Nonsense")
    assert "GigaChat-99-Nonsense" not in static_models(ID_GIGACHAT)
    assert "GigaChat-99-Nonsense" not in ENGINE_MODELS[UNIQUE_ID_GIGACHAT]


@pytest.mark.parametrize("verify_ssl", [True, False])
async def test_gigachat_fetch_honours_verify_ssl(hass: HomeAssistant, verify_ssl):
    """The hub's Verify SSL switch reaches the model listing too.

    It reached the chat client in v5.4.7 and stopped there: this one fetch
    stayed pinned to `verify_ssl_certs=False`, so the switch was a placebo for
    anyone on a network that requires certificates to be checked.
    """
    result = MagicMock()
    result.data = [MagicMock(id_="GigaChat-2-Max")]

    with patch("custom_components.smartchain.client_util.GigaChat") as giga_cls:
        giga_cls.return_value.get_models.return_value = result
        await async_fetch_models(
            hass,
            ID_GIGACHAT,
            {CONF_API_KEY: "creds", CONF_VERIFY_SSL: verify_ssl},
        )

    assert giga_cls.call_args.kwargs["verify_ssl_certs"] is verify_ssl


async def test_gigachat_fetch_is_bounded_by_a_timeout(hass: HomeAssistant):
    """A provider that accepts the connection and never answers must not hang.

    `get_models` is a blocking SDK call on an executor thread and the only
    provider fetch with no timeout of its own, so without this the Agents tab
    waited on it for as long as the provider felt like. The executor hop is
    stood in for here — what is under test is the bound around it, and a real
    blocked worker thread would outlive the test that started it.
    """
    hung = asyncio.Event()

    async def never_answers(*args):
        hung.set()
        await asyncio.sleep(30)
        raise AssertionError("should have been abandoned long before this")

    started = time.monotonic()
    with (
        patch("custom_components.smartchain.client_util.GigaChat"),
        patch("custom_components.smartchain.client_util.MODEL_FETCH_TIMEOUT", 0.05),
        patch.object(hass, "async_add_executor_job", never_answers),
        pytest.raises(ModelFetchError),
    ):
        await async_fetch_models(hass, ID_GIGACHAT, {CONF_API_KEY: "creds"}, strict=True)
    waited = time.monotonic() - started

    assert hung.is_set()
    # The elapsed time is the assertion that matters. Every way this call can
    # end raises something `async_fetch_models` turns into a ModelFetchError,
    # so `pytest.raises` alone would pass just as happily on a bound of an
    # hour as on one of 50ms.
    assert waited < 5, f"waited {waited:.1f}s — the fetch is not bounded"


async def test_connection_data_carries_the_hub_switches(hass: HomeAssistant):
    """Verify SSL lives in `entry.options`; a fetch reading only `entry.data`
    could never see it. Agent-shaped leftovers stay out."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "creds"},
        options={CONF_VERIFY_SSL: True, "prompt": "a legacy leftover"},
        unique_id=UNIQUE_ID_GIGACHAT,
    )
    entry.add_to_hass(hass)

    merged = connection_data(entry)
    assert merged[CONF_API_KEY] == "creds"
    assert merged[CONF_VERIFY_SSL] is True
    assert "prompt" not in merged
