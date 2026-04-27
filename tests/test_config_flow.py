"""Tests for SmartChain config flow."""

from unittest.mock import AsyncMock, patch

import pytest
from gigachat.exceptions import ResponseError
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from httpx import ConnectError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENGINE,
    CONF_FOLDER_ID,
    CONF_LLM_HASS_API,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROFANITY,
    CONF_PROMPT,
    CONF_SKIP_VALIDATION,
    CONF_TEMPERATURE,
    CONF_VERIFY_SSL,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_PROMPT,
    DEFAULT_TEMPERATURE,
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


# --- Options Flow Tests ---


@pytest.fixture
def mock_gigachat_options_entry(hass: HomeAssistant):
    """Create a mock GigaChat config entry for options flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test-credentials"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_openai_options_entry(hass: HomeAssistant):
    """Create a mock OpenAI config entry for options flow."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "test-openai-key"},
        options={},
        unique_id="OpenAI",
    )
    entry.add_to_hass(hass)
    return entry


async def _options_flow_select_settings(hass, entry_id):
    """Helper: init options flow — goes directly to the settings form."""
    result = await hass.config_entries.options.async_init(entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"
    return result


async def test_options_flow_shows_settings(
    hass: HomeAssistant, mock_gigachat_options_entry, mock_llm_client
) -> None:
    """Test that options flow init step shows the settings form directly."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_options_entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(mock_gigachat_options_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "settings"


async def test_options_flow_submit_with_model(
    hass: HomeAssistant, mock_gigachat_options_entry, mock_llm_client
) -> None:
    """Test options flow creates entry when model is selected."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_options_entry.entry_id)
        await hass.async_block_till_done()

    result = await _options_flow_select_settings(hass, mock_gigachat_options_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CHAT_MODEL: "GigaChat",
            CONF_PROMPT: DEFAULT_PROMPT,
            CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
            CONF_PROCESS_BUILTIN_SENTENCES: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CHAT_MODEL] == "GigaChat"


async def test_options_flow_model_required_error(
    hass: HomeAssistant, mock_gigachat_options_entry, mock_llm_client
) -> None:
    """Test options flow shows error when no model selected."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_options_entry.entry_id)
        await hass.async_block_till_done()

    result = await _options_flow_select_settings(hass, mock_gigachat_options_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CHAT_MODEL: "",
            CONF_CHAT_MODEL_USER: "",
            CONF_PROMPT: DEFAULT_PROMPT,
            CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
            CONF_PROCESS_BUILTIN_SENTENCES: True,
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "model_required"}


async def test_options_flow_custom_model_user(
    hass: HomeAssistant, mock_gigachat_options_entry, mock_llm_client
) -> None:
    """Test options flow accepts custom model_user even without dropdown model."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_options_entry.entry_id)
        await hass.async_block_till_done()

    result = await _options_flow_select_settings(hass, mock_gigachat_options_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CHAT_MODEL: "",
            CONF_CHAT_MODEL_USER: "GigaChat-Pro-2",
            CONF_PROMPT: DEFAULT_PROMPT,
            CONF_TEMPERATURE: 0.5,
            CONF_PROCESS_BUILTIN_SENTENCES: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CHAT_MODEL_USER] == "GigaChat-Pro-2"
    assert result["data"][CONF_TEMPERATURE] == 0.5


async def test_options_flow_gigachat_extra_fields(
    hass: HomeAssistant, mock_gigachat_options_entry, mock_llm_client
) -> None:
    """Test GigaChat options flow includes profanity and verify_ssl fields."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_options_entry.entry_id)
        await hass.async_block_till_done()

    result = await _options_flow_select_settings(hass, mock_gigachat_options_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CHAT_MODEL: "GigaChat",
            CONF_PROMPT: DEFAULT_PROMPT,
            CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
            CONF_PROCESS_BUILTIN_SENTENCES: True,
            CONF_PROFANITY: True,
            CONF_VERIFY_SSL: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PROFANITY] is True
    assert result["data"][CONF_VERIFY_SSL] is True


async def test_options_flow_openai_no_gigachat_fields(
    hass: HomeAssistant, mock_openai_options_entry, mock_llm_client
) -> None:
    """Test OpenAI options flow does not include GigaChat-specific fields."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_openai_options_entry.entry_id)
        await hass.async_block_till_done()

    result = await _options_flow_select_settings(hass, mock_openai_options_entry.entry_id)
    # Schema should not contain profanity/verify_ssl for non-GigaChat
    schema_keys = [str(k) for k in result["data_schema"].schema]
    assert CONF_PROFANITY not in schema_keys
    assert CONF_VERIFY_SSL not in schema_keys


async def test_options_flow_empty_llm_api_removed(
    hass: HomeAssistant, mock_gigachat_options_entry, mock_llm_client
) -> None:
    """Test that empty LLM API selection is removed from options."""
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(mock_gigachat_options_entry.entry_id)
        await hass.async_block_till_done()

    result = await _options_flow_select_settings(hass, mock_gigachat_options_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CHAT_MODEL: "GigaChat",
            CONF_PROMPT: DEFAULT_PROMPT,
            CONF_TEMPERATURE: DEFAULT_TEMPERATURE,
            CONF_PROCESS_BUILTIN_SENTENCES: True,
            CONF_LLM_HASS_API: [],
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert CONF_LLM_HASS_API not in result["data"]
