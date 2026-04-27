"""Config flow for SmartChain integration."""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any

import voluptuous as vol
from gigachat.exceptions import ResponseError
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import llm, selector
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    SelectSelectorMode,
    TemplateSelector,
)
from httpx import ConnectError

from .client_util import async_fetch_models, validate_client
from .const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_CHAT_HISTORY,
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENABLE_HISTORY_TOOL,
    CONF_ENGINE,
    CONF_ENGINE_OPTIONS,
    CONF_FOLDER_ID,
    CONF_LLM_HASS_API,
    CONF_MAX_TOKENS,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROFANITY,
    CONF_PROMPT,
    CONF_SKIP_VALIDATION,
    CONF_TEMPERATURE,
    CONF_VERIFY_SSL,
    DEFAULT_CHAT_HISTORY,
    DEFAULT_CHAT_MODEL,
    DEFAULT_ENABLE_HISTORY_TOOL,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_PROCESS_BUILTIN_SENTENCES,
    DEFAULT_PROFANITY,
    DEFAULT_PROMPT,
    DEFAULT_SKIP_VALIDATION,
    DEFAULT_TEMPERATURE,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    ENGINE_MODELS,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    ID_OLLAMA,
    ID_OPENAI,
    ID_YANDEX_GPT,
    SUBENTRY_TYPE_CONVERSATION,
    UNIQUE_ID,
    UNIQUE_ID_GIGACHAT,
)

LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENGINE): selector.SelectSelector(
            selector.SelectSelectorConfig(options=CONF_ENGINE_OPTIONS),
        ),
    }
)
STEP_API_KEY_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
        vol.Optional(CONF_SKIP_VALIDATION, default=DEFAULT_SKIP_VALIDATION): bool,
    }
)
STEP_YANDEXGPT_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
        vol.Required(CONF_FOLDER_ID): str,
        vol.Optional(CONF_SKIP_VALIDATION, default=DEFAULT_SKIP_VALIDATION): bool,
    }
)
STEP_OLLAMA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL, default=DEFAULT_OLLAMA_BASE_URL): str,
        vol.Optional(CONF_SKIP_VALIDATION, default=DEFAULT_SKIP_VALIDATION): bool,
    }
)

ENGINE_SCHEMA = {
    ID_GIGACHAT: STEP_API_KEY_SCHEMA,
    ID_YANDEX_GPT: STEP_YANDEXGPT_SCHEMA,
    ID_OPENAI: STEP_API_KEY_SCHEMA,
    ID_OLLAMA: STEP_OLLAMA_SCHEMA,
    ID_DEEPSEEK: STEP_API_KEY_SCHEMA,
    ID_ANTHROPIC: STEP_API_KEY_SCHEMA,
}

DEFAULT_OPTIONS = MappingProxyType(
    {
        CONF_PROMPT: DEFAULT_PROMPT,
        CONF_CHAT_MODEL: DEFAULT_CHAT_MODEL,
        CONF_CHAT_MODEL_USER: DEFAULT_CHAT_MODEL,
        CONF_PROCESS_BUILTIN_SENTENCES: DEFAULT_PROCESS_BUILTIN_SENTENCES,
    }
)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartChain."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

        engine = user_input[CONF_ENGINE]
        unique_id = UNIQUE_ID[engine]
        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_show_form(step_id=engine, data_schema=ENGINE_SCHEMA[engine])

    async def async_step_gigachat(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_GIGACHAT, user_input)

    async def async_step_yandexgpt(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_YANDEX_GPT, user_input)

    async def async_step_openai(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_OPENAI, user_input)

    async def async_step_ollama(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_OLLAMA, user_input)

    async def async_step_deepseek(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_DEEPSEEK, user_input)

    async def async_step_anthropic(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_ANTHROPIC, user_input)

    async def _common_model_async_step(
        self, engine: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id=engine, data_schema=ENGINE_SCHEMA[engine])

        errors: dict[str, str] = {}
        user_input[CONF_ENGINE] = engine
        unique_id = UNIQUE_ID[engine]
        try:
            await validate_client(self.hass, user_input)
        except ConnectError:
            errors["base"] = "cannot_connect"
        except ResponseError:
            errors["base"] = "invalid_response"
        except Exception as inst:
            LOGGER.exception("Unexpected exception %s", type(inst))
            errors["base"] = "unknown"
        else:
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=unique_id, data=user_input)

        return self.async_show_form(
            step_id=engine, data_schema=ENGINE_SCHEMA[engine], errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Create the options flow."""
        return OptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return supported subentry types."""
        return {SUBENTRY_TYPE_CONVERSATION: ConversationSubentryFlow}


class ConversationSubentryFlow(ConfigSubentryFlow):
    """Handle subentry flow for adding/modifying a conversation agent."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle adding a new conversation agent."""
        entry = self._get_entry()
        unique_id = entry.unique_id
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        models = await async_fetch_models(self.hass, engine, entry.data)
        schema = _subentry_schema(self.hass, unique_id, {}, models=models)

        if user_input is not None:
            return self._validate_and_create(user_input, unique_id, schema)

        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Handle reconfiguring an existing conversation agent."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        unique_id = entry.unique_id
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        models = await async_fetch_models(self.hass, engine, entry.data)
        schema = _subentry_schema(self.hass, unique_id, subentry.data, models=models)

        if user_input is not None:
            return self._validate_and_update(user_input, entry, subentry, unique_id, schema)

        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    def _validate_and_create(
        self, user_input: dict[str, Any], unique_id: str, schema: vol.Schema
    ) -> SubentryFlowResult:
        """Validate user input and create subentry."""
        model = user_input.get(CONF_CHAT_MODEL_USER)
        if not model or not model.strip():
            model = user_input.get(CONF_CHAT_MODEL)
        if not model or not model.strip():
            return self.async_show_form(
                step_id="user",
                data_schema=schema,
                errors={"base": "model_required"},
            )

        if not user_input.get(CONF_LLM_HASS_API):
            user_input.pop(CONF_LLM_HASS_API, None)

        title = user_input.get(CONF_CHAT_MODEL_USER) or user_input.get(CONF_CHAT_MODEL) or "Agent"
        return self.async_create_entry(title=title, data=user_input)

    def _validate_and_update(
        self,
        user_input: dict[str, Any],
        entry: ConfigEntry,
        subentry: Any,
        unique_id: str,
        schema: vol.Schema,
    ) -> SubentryFlowResult:
        """Validate user input and update subentry."""
        model = user_input.get(CONF_CHAT_MODEL_USER)
        if not model or not model.strip():
            model = user_input.get(CONF_CHAT_MODEL)
        if not model or not model.strip():
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=schema,
                errors={"base": "model_required"},
            )

        if not user_input.get(CONF_LLM_HASS_API):
            user_input.pop(CONF_LLM_HASS_API, None)

        title = user_input.get(CONF_CHAT_MODEL_USER) or user_input.get(CONF_CHAT_MODEL) or "Agent"
        return self.async_update_and_abort(
            entry,
            subentry,
            title=title,
            data=user_input,
        )


class OptionsFlow(config_entries.OptionsFlow):
    """SmartChain config flow options handler."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show settings form directly (no menu — only one option)."""
        return await self.async_step_settings(user_input)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage model settings."""
        unique_id = self.config_entry.unique_id
        engine = self.config_entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        models = await async_fetch_models(self.hass, engine, self.config_entry.data)
        schema = _subentry_schema(self.hass, unique_id, self.config_entry.options, models=models)
        if user_input is not None:
            model = user_input.get(CONF_CHAT_MODEL_USER)
            if not model or not model.strip():
                model = user_input.get(CONF_CHAT_MODEL)
            if not model or not model.strip():
                return self.async_show_form(
                    step_id="settings",
                    data_schema=schema,
                    errors={"base": "model_required"},
                )

            # Remove empty LLM API selection
            if not user_input.get(CONF_LLM_HASS_API):
                user_input.pop(CONF_LLM_HASS_API, None)

            return self.async_create_entry(title=unique_id, data=user_input)

        return self.async_show_form(
            step_id="settings",
            data_schema=schema,
        )


def _subentry_schema(
    hass,
    unique_id: str,
    options: MappingProxyType[str, Any] | dict[str, Any],
    models: list[str] | None = None,
) -> vol.Schema:
    """Return a schema for SmartChain agent options (used by both OptionsFlow and SubentryFlow)."""
    if not options:
        options = DEFAULT_OPTIONS

    if models is None:
        models = ENGINE_MODELS[unique_id]

    hass_apis: list[selector.SelectOptionDict] = [
        selector.SelectOptionDict(value=api.id, label=api.name) for api in llm.async_get_apis(hass)
    ]

    schema = vol.Schema(
        {
            vol.Optional(
                CONF_CHAT_MODEL,
                description={
                    "suggested_value": options.get(CONF_CHAT_MODEL),
                },
                default="",
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    mode=SelectSelectorMode("dropdown"),
                    options=models,
                ),
            ),
            vol.Optional(
                CONF_CHAT_MODEL_USER,
                description={"suggested_value": options.get(CONF_CHAT_MODEL_USER)},
            ): str,
            vol.Optional(
                CONF_LLM_HASS_API,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=hass_apis,
                    multiple=True,
                    mode=SelectSelectorMode("dropdown"),
                ),
            ),
            vol.Optional(
                CONF_PROMPT,
                description={"suggested_value": options.get(CONF_PROMPT, DEFAULT_PROMPT)},
                default=DEFAULT_PROMPT,
            ): TemplateSelector(),
            vol.Optional(
                CONF_TEMPERATURE,
                description={"suggested_value": options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)},
                default=DEFAULT_TEMPERATURE,
            ): NumberSelector(NumberSelectorConfig(min=0, max=1, step=0.05)),
            vol.Optional(
                CONF_MAX_TOKENS,
                description={"suggested_value": options.get(CONF_MAX_TOKENS)},
            ): int,
            vol.Optional(
                CONF_PROCESS_BUILTIN_SENTENCES,
                description={
                    "suggested_value": options.get(
                        CONF_PROCESS_BUILTIN_SENTENCES,
                        DEFAULT_PROCESS_BUILTIN_SENTENCES,
                    )
                },
                default=DEFAULT_PROCESS_BUILTIN_SENTENCES,
            ): bool,
            vol.Optional(
                CONF_CHAT_HISTORY,
                description={
                    "suggested_value": options.get(CONF_CHAT_HISTORY, DEFAULT_CHAT_HISTORY)
                },
                default=DEFAULT_CHAT_HISTORY,
            ): bool,
            vol.Optional(
                CONF_ENABLE_HISTORY_TOOL,
                description={
                    "suggested_value": options.get(
                        CONF_ENABLE_HISTORY_TOOL, DEFAULT_ENABLE_HISTORY_TOOL
                    )
                },
                default=DEFAULT_ENABLE_HISTORY_TOOL,
            ): bool,
        }
    )
    if unique_id == UNIQUE_ID_GIGACHAT:
        schema = schema.extend(
            {
                vol.Optional(
                    CONF_PROFANITY,
                    description={"suggested_value": options.get(CONF_PROFANITY, DEFAULT_PROFANITY)},
                    default=DEFAULT_PROFANITY,
                ): bool,
                vol.Optional(
                    CONF_VERIFY_SSL,
                    description={
                        "suggested_value": options.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
                    },
                    default=DEFAULT_VERIFY_SSL,
                ): bool,
            }
        )
    return schema


# Keep backward-compatible alias
common_config_option_schema = _subentry_schema
