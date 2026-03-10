"""Tests for SmartChain config flow."""

from unittest.mock import AsyncMock, patch

import pytest
from gigachat.exceptions import ResponseError
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from httpx import ConnectError

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    CONF_FOLDER_ID,
    CONF_SKIP_VALIDATION,
    DEFAULT_OLLAMA_BASE_URL,
    DOMAIN,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_step_user_shows_engine_form(hass: HomeAssistant) -> None:
    """Test that the user step shows engine selection form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_step_user_selects_gigachat(hass: HomeAssistant) -> None:
    """Test selecting GigaChat engine shows API key form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_GIGACHAT}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == ID_GIGACHAT


async def test_step_user_selects_yandexgpt(hass: HomeAssistant) -> None:
    """Test selecting YandexGPT engine shows API key + folder form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_YANDEX_GPT}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == ID_YANDEX_GPT


async def test_step_user_selects_openai(hass: HomeAssistant) -> None:
    """Test selecting OpenAI engine shows API key form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_OPENAI}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == ID_OPENAI


async def test_gigachat_full_flow(hass: HomeAssistant, mock_validate_client: AsyncMock) -> None:
    """Test full GigaChat config flow creates entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_GIGACHAT}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_KEY: "test-credentials", CONF_SKIP_VALIDATION: False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "GigaChat"
    assert result["data"][CONF_ENGINE] == ID_GIGACHAT
    assert result["data"][CONF_API_KEY] == "test-credentials"


async def test_yandexgpt_full_flow(hass: HomeAssistant, mock_validate_client: AsyncMock) -> None:
    """Test full YandexGPT config flow creates entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_YANDEX_GPT}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_API_KEY: "test-api-key",
            CONF_FOLDER_ID: "test-folder",
            CONF_SKIP_VALIDATION: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "YandexGPT"
    assert result["data"][CONF_ENGINE] == ID_YANDEX_GPT


async def test_openai_full_flow(hass: HomeAssistant, mock_validate_client: AsyncMock) -> None:
    """Test full OpenAI config flow creates entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_OPENAI}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_KEY: "test-openai-key", CONF_SKIP_VALIDATION: False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "OpenAI"
    assert result["data"][CONF_ENGINE] == ID_OPENAI


async def test_gigachat_connect_error(hass: HomeAssistant) -> None:
    """Test GigaChat config flow handles connection error."""
    with patch(
        "custom_components.smartchain.config_flow.validate_client",
        side_effect=ConnectError("Connection failed"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ENGINE: ID_GIGACHAT}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "bad-credentials", CONF_SKIP_VALIDATION: False},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_gigachat_invalid_response(hass: HomeAssistant) -> None:
    """Test GigaChat config flow handles invalid response."""
    with patch(
        "custom_components.smartchain.config_flow.validate_client",
        side_effect=ResponseError("https://example.com", 401, b"Unauthorized", None),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ENGINE: ID_GIGACHAT}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "bad-credentials", CONF_SKIP_VALIDATION: False},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_response"}


async def test_gigachat_unknown_error(hass: HomeAssistant) -> None:
    """Test GigaChat config flow handles unknown error."""
    with patch(
        "custom_components.smartchain.config_flow.validate_client",
        side_effect=RuntimeError("Something unexpected"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ENGINE: ID_GIGACHAT}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "bad-credentials", CONF_SKIP_VALIDATION: False},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_skip_validation(
    hass: HomeAssistant,
) -> None:
    """Test config flow with skip_validation=True skips API call."""
    with patch(
        "custom_components.smartchain.config_flow.validate_client",
        new_callable=AsyncMock,
    ) as mock_validate:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ENGINE: ID_GIGACHAT}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "test-credentials", CONF_SKIP_VALIDATION: True},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    mock_validate.assert_called_once()


async def test_step_user_selects_ollama(hass: HomeAssistant) -> None:
    """Test selecting Ollama engine shows base_url form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_OLLAMA}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == ID_OLLAMA


async def test_step_user_selects_deepseek(hass: HomeAssistant) -> None:
    """Test selecting DeepSeek engine shows API key form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_DEEPSEEK}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == ID_DEEPSEEK


async def test_step_user_selects_anthropic(hass: HomeAssistant) -> None:
    """Test selecting Anthropic engine shows API key form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_ANTHROPIC}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == ID_ANTHROPIC


async def test_ollama_full_flow(hass: HomeAssistant, mock_validate_client: AsyncMock) -> None:
    """Test full Ollama config flow creates entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_OLLAMA}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_BASE_URL: DEFAULT_OLLAMA_BASE_URL, CONF_SKIP_VALIDATION: False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ollama"
    assert result["data"][CONF_ENGINE] == ID_OLLAMA
    assert result["data"][CONF_BASE_URL] == DEFAULT_OLLAMA_BASE_URL


async def test_deepseek_full_flow(hass: HomeAssistant, mock_validate_client: AsyncMock) -> None:
    """Test full DeepSeek config flow creates entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_DEEPSEEK}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_KEY: "test-deepseek-key", CONF_SKIP_VALIDATION: False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "DeepSeek"
    assert result["data"][CONF_ENGINE] == ID_DEEPSEEK
    assert result["data"][CONF_API_KEY] == "test-deepseek-key"


async def test_anthropic_full_flow(hass: HomeAssistant, mock_validate_client: AsyncMock) -> None:
    """Test full Anthropic config flow creates entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_ANTHROPIC}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_API_KEY: "test-anthropic-key", CONF_SKIP_VALIDATION: False},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Anthropic"
    assert result["data"][CONF_ENGINE] == ID_ANTHROPIC
    assert result["data"][CONF_API_KEY] == "test-anthropic-key"


async def test_ollama_connect_error(hass: HomeAssistant) -> None:
    """Test Ollama config flow handles connection error."""
    with patch(
        "custom_components.smartchain.config_flow.validate_client",
        side_effect=ConnectError("Connection refused"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_ENGINE: ID_OLLAMA}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_BASE_URL: "http://bad-host:11434", CONF_SKIP_VALIDATION: False},
        )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
