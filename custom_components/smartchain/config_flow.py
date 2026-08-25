"""Config flow for SmartChain integration."""

from __future__ import annotations

import logging
from collections.abc import Mapping
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

from .client_util import async_fetch_models, supports, validate_client
from .const import (
    CAPABILITY_EMBEDDINGS,
    CONF_ALLOWED_TOOLS,
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_CHAT_HISTORY,
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_DYNAMIC_CONTEXT_ON_ASSIST,
    CONF_DYNAMIC_CONTEXT_PRESET,
    CONF_DYNAMIC_ENTITY_CONTEXT,
    CONF_ENABLE_HISTORY_TOOL,
    CONF_ENABLE_MULTI_AGENT_TOOLS,
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
    DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST,
    DEFAULT_DYNAMIC_ENTITY_CONTEXT,
    DEFAULT_ENABLE_HISTORY_TOOL,
    DEFAULT_ENABLE_MULTI_AGENT_TOOLS,
    DEFAULT_OLLAMA_BASE_URL,
    DEFAULT_PROCESS_BUILTIN_SENTENCES,
    DEFAULT_PROFANITY,
    DEFAULT_PROMPT,
    DEFAULT_SKIP_VALIDATION,
    DEFAULT_TEMPERATURE,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
    ENGINE_MODELS,
    ENTITY_DEFAULT_PRESET,
    ENTITY_PRESETS,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    ID_GROQ,
    ID_LLAMACPP,
    ID_LMSTUDIO,
    ID_OLLAMA,
    ID_OPENAI,
    ID_OPENROUTER,
    ID_TOGETHER,
    ID_YANDEX_GPT,
    OPENAI_COMPATIBLE,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
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


def _compatible_schema(engine: str) -> vol.Schema:
    """Step schema for an OpenAI-compatible provider.

    The base URL is always editable and pre-filled from the table, so a stale
    default or a mirror costs the user one field rather than the integration.
    A local server's key is optional; a hosted one's is required.
    """
    row = OPENAI_COMPATIBLE[engine]
    fields: dict[Any, Any] = {}
    if row.requires_api_key:
        fields[vol.Required(CONF_API_KEY)] = str
    fields[vol.Required(CONF_BASE_URL, default=row.default_base_url)] = str
    if not row.requires_api_key:
        # Some local deployments sit behind a proxy that still wants one.
        fields[vol.Optional(CONF_API_KEY)] = str
    fields[vol.Optional(CONF_SKIP_VALIDATION, default=DEFAULT_SKIP_VALIDATION)] = bool
    return vol.Schema(fields)


ENGINE_SCHEMA = {
    ID_GIGACHAT: STEP_API_KEY_SCHEMA,
    ID_YANDEX_GPT: STEP_YANDEXGPT_SCHEMA,
    ID_OLLAMA: STEP_OLLAMA_SCHEMA,
    ID_ANTHROPIC: STEP_API_KEY_SCHEMA,
    **{engine: _compatible_schema(engine) for engine in OPENAI_COMPATIBLE},
}

DEFAULT_OPTIONS = MappingProxyType(
    {
        CONF_PROMPT: DEFAULT_PROMPT,
        CONF_CHAT_MODEL: DEFAULT_CHAT_MODEL,
        CONF_CHAT_MODEL_USER: DEFAULT_CHAT_MODEL,
        CONF_PROCESS_BUILTIN_SENTENCES: DEFAULT_PROCESS_BUILTIN_SENTENCES,
    }
)


def normalize_model_input(user_input: dict[str, Any]) -> str | None:
    """Validate that a model is set and strip an empty LLM-API selection.

    Mutates ``user_input`` (drops empty CONF_LLM_HASS_API). Returns a translation
    key for the error to show, or ``None`` when the input is valid.
    """
    model = user_input.get(CONF_CHAT_MODEL_USER)
    if not model or not model.strip():
        model = user_input.get(CONF_CHAT_MODEL)
    if not model or not model.strip():
        return "model_required"

    if not user_input.get(CONF_LLM_HASS_API):
        user_input.pop(CONF_LLM_HASS_API, None)
    return None


def agent_title(data: Mapping[str, Any]) -> str:
    """Title for an agent subentry: the user's model name, else the picked one."""
    return data.get(CONF_CHAT_MODEL_USER) or data.get(CONF_CHAT_MODEL) or "Agent"


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

    # Home Assistant dispatches a flow step by method name, so each provider
    # needs its own even though the bodies are identical. A setattr loop would
    # work until HA introspects the class.

    async def async_step_openrouter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_OPENROUTER, user_input)

    async def async_step_groq(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_GROQ, user_input)

    async def async_step_together(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_TOGETHER, user_input)

    async def async_step_lmstudio(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_LMSTUDIO, user_input)

    async def async_step_llamacpp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_LLAMACPP, user_input)

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
        """Return supported subentry types, filtered by provider capability."""
        types: dict[str, type[ConfigSubentryFlow]] = {
            SUBENTRY_TYPE_CONVERSATION: ConversationSubentryFlow,
        }
        engine = config_entry.data.get(CONF_ENGINE) or ID_GIGACHAT
        if supports(engine, CAPABILITY_EMBEDDINGS):
            types[SUBENTRY_TYPE_EMBEDDINGS] = EmbeddingsSubentryFlow
        return types


class ConversationSubentryFlow(ConfigSubentryFlow):
    """Handle subentry flow for adding/modifying a conversation agent."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle adding a new conversation agent."""
        entry = self._get_entry()
        unique_id = entry.unique_id
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        models = await async_fetch_models(self.hass, engine, entry.data)
        schema = subentry_schema(self.hass, unique_id, {}, models=models)

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
        schema = subentry_schema(self.hass, unique_id, subentry.data, models=models)

        if user_input is not None:
            return self._validate_and_update(user_input, entry, subentry, unique_id, schema)

        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    def _validate_and_create(
        self, user_input: dict[str, Any], unique_id: str, schema: vol.Schema
    ) -> SubentryFlowResult:
        """Validate user input and create subentry."""
        error = normalize_model_input(user_input)
        if error:
            return self.async_show_form(step_id="user", data_schema=schema, errors={"base": error})

        title = agent_title(user_input)
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
        error = normalize_model_input(user_input)
        if error:
            return self.async_show_form(
                step_id="reconfigure", data_schema=schema, errors={"base": error}
            )

        title = agent_title(user_input)
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
        schema = subentry_schema(self.hass, unique_id, self.config_entry.options, models=models)
        if user_input is not None:
            error = normalize_model_input(user_input)
            if error:
                return self.async_show_form(
                    step_id="settings", data_schema=schema, errors={"base": error}
                )
            return self.async_create_entry(title=unique_id, data=user_input)

        return self.async_show_form(
            step_id="settings",
            data_schema=schema,
        )


def subentry_schema(
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
            vol.Optional(
                CONF_DYNAMIC_ENTITY_CONTEXT,
                description={
                    "suggested_value": options.get(
                        CONF_DYNAMIC_ENTITY_CONTEXT, DEFAULT_DYNAMIC_ENTITY_CONTEXT
                    )
                },
                default=DEFAULT_DYNAMIC_ENTITY_CONTEXT,
            ): bool,
            vol.Optional(
                CONF_DYNAMIC_CONTEXT_PRESET,
                description={
                    "suggested_value": options.get(
                        CONF_DYNAMIC_CONTEXT_PRESET, ENTITY_DEFAULT_PRESET
                    )
                },
                default=ENTITY_DEFAULT_PRESET,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    mode=SelectSelectorMode("dropdown"), options=ENTITY_PRESETS
                )
            ),
            vol.Optional(
                CONF_DYNAMIC_CONTEXT_ON_ASSIST,
                description={
                    "suggested_value": options.get(
                        CONF_DYNAMIC_CONTEXT_ON_ASSIST, DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST
                    )
                },
                default=DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST,
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
    registry = hass.data.get(DOMAIN, {}).get("tools")
    if registry is not None and len(registry) > 0:
        schema = schema.extend(
            {
                vol.Optional(
                    CONF_ALLOWED_TOOLS,
                    description={"suggested_value": options.get(CONF_ALLOWED_TOOLS)},
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=registry.names(),
                        multiple=True,
                        mode=SelectSelectorMode("list"),
                    ),
                ),
            }
        )
    # Multi-agent tools are only meaningful when the user has 2+ subentries.
    entries = hass.config_entries.async_entries(DOMAIN) if hass else []
    has_multiple_subentries = any(len(e.subentries or {}) > 1 for e in entries)
    if has_multiple_subentries:
        schema = schema.extend(
            {
                vol.Optional(
                    CONF_ENABLE_MULTI_AGENT_TOOLS,
                    description={
                        "suggested_value": options.get(
                            CONF_ENABLE_MULTI_AGENT_TOOLS,
                            DEFAULT_ENABLE_MULTI_AGENT_TOOLS,
                        )
                    },
                    default=DEFAULT_ENABLE_MULTI_AGENT_TOOLS,
                ): bool,
            }
        )
    return schema


def embeddings_subentry_schema(
    models: list[str], defaults: dict[str, Any] | None = None
) -> vol.Schema:
    """Schema for an embeddings binding: a name and a model, nothing more.

    An embeddings subentry has no prompt, no tools and no temperature — it
    exists purely to bind provider credentials to one embedding model.
    """
    current = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                "name",
                description={"suggested_value": current.get("name", "")},
            ): str,
            vol.Optional(
                "model",
                description={"suggested_value": current.get("model")},
                default="",
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    mode=SelectSelectorMode("dropdown"),
                    options=models,
                ),
            ),
            vol.Optional(
                "model_user",
                description={"suggested_value": current.get("model_user")},
            ): str,
        }
    )


class EmbeddingsSubentryFlow(ConfigSubentryFlow):
    """Handle adding or reconfiguring an embeddings binding."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Add a new embeddings binding."""
        entry = self._get_entry()
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        models = await async_fetch_models(
            self.hass, engine, entry.data, purpose=CAPABILITY_EMBEDDINGS
        )
        schema = embeddings_subentry_schema(models)

        if user_input is not None:
            return self._create(user_input, schema)
        return self.async_show_form(step_id="user", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reconfigure an existing embeddings binding."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        models = await async_fetch_models(
            self.hass, engine, entry.data, purpose=CAPABILITY_EMBEDDINGS
        )
        defaults = {**subentry.data, "name": subentry.title}
        schema = embeddings_subentry_schema(models, defaults)

        if user_input is not None:
            model = _resolve_embeddings_model(user_input)
            if not model:
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=schema,
                    errors={"base": "model_required"},
                )
            return self.async_update_and_abort(
                entry,
                subentry,
                title=user_input["name"],
                data={"model": model, "model_user": user_input.get("model_user", "")},
            )
        return self.async_show_form(step_id="reconfigure", data_schema=schema)

    def _create(self, user_input: dict[str, Any], schema: vol.Schema) -> SubentryFlowResult:
        model = _resolve_embeddings_model(user_input)
        if not model:
            return self.async_show_form(
                step_id="user", data_schema=schema, errors={"base": "model_required"}
            )
        return self.async_create_entry(
            title=user_input["name"],
            data={"model": model, "model_user": user_input.get("model_user", "")},
        )


def _resolve_embeddings_model(user_input: dict[str, Any]) -> str:
    """A non-empty custom name wins over the dropdown selection."""
    custom = (user_input.get("model_user") or "").strip()
    if custom:
        return custom
    return (user_input.get("model") or "").strip()
