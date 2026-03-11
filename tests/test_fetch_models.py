"""Tests for dynamic model fetching."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.client_util import async_fetch_models
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    ENGINE_MODELS,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
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
