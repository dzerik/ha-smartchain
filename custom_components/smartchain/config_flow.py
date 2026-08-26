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
    ALL_TOOLS_LABELS,
    ALL_TOOLS_SENTINEL,
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
    ENTITY_SOURCE_TYPE,
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
    MEMORY_BACKEND_TYPES,
    MEMORY_DEFAULT_BACKEND,
    MEMORY_DEFAULT_RETENTION_DAYS,
    MEMORY_IDENTIFIER_PATTERN,
    MEMORY_SECRET_FIELDS,
    MEMORY_SOURCE_TYPE_NONE,
    MEMORY_SOURCE_TYPES,
    MEMORY_STORE_NAME_PATTERN,
    OPENAI_COMPATIBLE,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
    SUBENTRY_TYPE_MEMORY_STORE,
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


# Everything that belongs to the connection rather than to an agent, per engine.
# Deliberately data-driven so the "does this provider have any connection
# settings at all" question has exactly one answer, and callers that must
# separate connection keys from agent keys (the migration in `__init__.py`) read
# the same list the form does.
CONNECTION_KEYS: dict[str, tuple[str, ...]] = {
    ID_GIGACHAT: (CONF_VERIFY_SSL, CONF_PROFANITY),
}


def connection_schema(engine: str, options: Mapping[str, Any] | None = None) -> vol.Schema:
    """Return the connection-level settings for ``engine``, and nothing else.

    A config entry is a connection to a provider: credentials, endpoint, and the
    few switches that belong to the connection itself. Model, prompt,
    temperature, tools and entity context are properties of an *agent* and live
    on a conversation subentry, so none of them appear here — this schema is
    deliberately not `subentry_schema`.

    For GigaChat that leaves `verify_ssl` and `profanity`, the two keys
    `client_util.get_client` reads off `entry.options`. Every other provider has
    none and gets an empty schema; a caller must show an honest sentence rather
    than render a form with no fields.
    """
    current = options or {}
    if not CONNECTION_KEYS.get(engine):
        return vol.Schema({})
    return vol.Schema(
        {
            vol.Optional(
                CONF_VERIFY_SSL,
                description={"suggested_value": current.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)},
                default=DEFAULT_VERIFY_SSL,
            ): bool,
            vol.Optional(
                CONF_PROFANITY,
                description={"suggested_value": current.get(CONF_PROFANITY, DEFAULT_PROFANITY)},
                default=DEFAULT_PROFANITY,
            ): bool,
        }
    )


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartChain."""

    VERSION = 1
    # 1 -> 2 turns a legacy entry's agent-shaped `options` into a real
    # conversation subentry; see `__init__.async_migrate_entry`.
    MINOR_VERSION = 2

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
            # Not gated on a provider capability, unlike embeddings: a store
            # binds to an embeddings *title*, which may well live on another
            # config entry, so a provider that cannot embed can still host the
            # store that uses one that can.
            SUBENTRY_TYPE_MEMORY_STORE: MemoryStoreSubentryFlow,
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
        """Manage the connection's settings — the connection's, and nothing else.

        An entry is a connection; the model, prompt and tools belong to an agent
        subentry. So this form is `connection_schema`, not `subentry_schema`, and
        there is deliberately no model list to fetch and no `normalize_model_input`
        to run — with no model field in the schema that check would return
        "model_required" forever and make the step unsubmittable.
        """
        engine = self.config_entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        schema = connection_schema(engine, self.config_entry.options)
        if not schema.schema:
            return self.async_abort(reason="no_connection_settings")

        if user_input is not None:
            # Merge rather than replace. A legacy entry that also has agents
            # keeps its old agent-shaped options in storage untouched (they are
            # simply no longer presented), and replacing wholesale here would
            # destroy them on the first save.
            options = {**dict(self.config_entry.options), **user_input}
            return self.async_create_entry(title=self.config_entry.unique_id or "", data=options)

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
        tool_options: list[selector.SelectOptionDict] = [
            selector.SelectOptionDict(
                value=ALL_TOOLS_SENTINEL,
                label=ALL_TOOLS_LABELS.get(hass.config.language, ALL_TOOLS_LABELS["en"]),
            ),
            *(selector.SelectOptionDict(value=name, label=name) for name in registry.names()),
        ]
        schema = schema.extend(
            {
                vol.Optional(
                    CONF_ALLOWED_TOOLS,
                    description={"suggested_value": options.get(CONF_ALLOWED_TOOLS)},
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=tool_options,
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


# ----- memory stores -----------------------------------------------------


# The reason each store-form rejection can give, keyed the way a config flow
# needs it (`errors={"base": key}`) and phrased the way the panel needs it.
# One table, so the flow dialog and the websocket command cannot disagree
# about why something was refused.
STORE_ERROR_TEXT: dict[str, str] = {
    "invalid_name": (
        "a store name must be lowercase letters, digits and underscores, "
        "starting with a letter or underscore"
    ),
    "name_taken": "another memory store already uses this name",
    "embeddings_required": "pick which embeddings binding this store uses",
    "embeddings_unknown": "no embeddings binding has that name",
    "embeddings_ambiguous": (
        "that embeddings title is claimed by more than one binding, so it "
        "resolves to nothing; rename one of them first"
    ),
    "dsn_required": "the pgvector backend needs a connection string",
    "url_required": "the qdrant backend needs a server URL",
    "invalid_identifier": (
        "must be lowercase letters, digits and underscores, starting with a letter or underscore"
    ),
}

# Fields whose value never travels back to the client. `dsn` is a PostgreSQL
# connection string, which embeds a password; `api_key` is a qdrant token.
# Both are served as `<field>_set: bool` and an empty submission on an existing
# store means "keep what is stored".
STORE_SECRET_FIELDS = MEMORY_SECRET_FIELDS

# Which extra fields each backend declares. Data-driven so the form, the
# validator and `store_config_from_subentry` cannot drift.
STORE_BACKEND_FIELDS: dict[str, tuple[str, ...]] = {
    "sqlite_numpy": ("path",),
    "sqlite_vec": ("path",),
    "pgvector": ("dsn", "table"),
    "qdrant": ("url", "api_key", "collection", "verify_ssl"),
}


def embeddings_binding_options(hass, *, keep: str | None = None) -> list[selector.SelectOptionDict]:
    """The embeddings titles a store may bind to, ambiguity spelled out.

    A title claimed by two subentries resolves to None in
    `embeddings_subentries_by_title` and silently unbinds every store that
    named it. Such a title is still offered — hiding it would leave a user
    editing an already-bound store unable to see why it stopped working — but
    it is labelled, and `validate_store_input` refuses it on the way in. Warn
    before writing, never after.

    `keep` is a title the caller must be able to submit even when no binding
    carries it any more: without it, editing a store whose binding was deleted
    would fail the selector's own membership check and become unsavable.
    """
    from .tools.memory.registry import embeddings_subentries_by_title

    available = embeddings_subentries_by_title(hass)
    options = [
        selector.SelectOptionDict(
            value=title,
            label=(title if available[title] is not None else f"{title} (duplicated title)"),
        )
        for title in sorted(available)
    ]
    if keep and keep not in available:
        options.append(selector.SelectOptionDict(value=keep, label=f"{keep} (missing binding)"))
    return options


def memory_store_subentry_schema(hass, defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """The store form, conditioned on the backend and source already chosen.

    Every backend carries different settings and an entity index has no use
    for retention or conversation ingest, so a flat form would show a dozen
    fields that do not apply and accept combinations the schema below rejects.
    Instead the schema is rebuilt from whatever `backend_type` / `source_type`
    the caller currently holds — for the panel that is the in-progress form
    value (see `reactive` in `ws_store_schema`), for the config-flow dialog it
    is the answer given on the previous step.

    Because irrelevant fields are simply not declared, voluptuous's default
    PREVENT_EXTRA does the mutual-exclusion work for free: an entity-source
    store that submits `retention_days` is rejected by the schema itself,
    exactly as `tools/schema.py::_validate_memory` rejects it in YAML.

    `dsn` and `api_key` are declared but never pre-filled — see
    STORE_SECRET_FIELDS.
    """
    current = dict(defaults or {})
    backend_type = current.get("backend_type") or MEMORY_DEFAULT_BACKEND
    if backend_type not in MEMORY_BACKEND_TYPES:
        backend_type = MEMORY_DEFAULT_BACKEND
    source_type = current.get("source_type") or MEMORY_SOURCE_TYPE_NONE
    if source_type not in MEMORY_SOURCE_TYPES:
        source_type = MEMORY_SOURCE_TYPE_NONE

    def suggest(key: str, fallback: Any = None) -> dict[str, Any]:
        return {"suggested_value": current.get(key, fallback)}

    fields: dict[Any, Any] = {
        vol.Required("name", description=suggest("name", "")): selector.TextSelector(),
        vol.Required("embeddings", description=suggest("embeddings")): selector.SelectSelector(
            selector.SelectSelectorConfig(
                mode=SelectSelectorMode("dropdown"),
                options=embeddings_binding_options(hass, keep=current.get("embeddings")),
            ),
        ),
        vol.Optional(
            "description", description=suggest("description", ""), default=""
        ): selector.TextSelector(),
        vol.Optional(
            "backend_type", description=suggest("backend_type", backend_type), default=backend_type
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                mode=SelectSelectorMode("dropdown"), options=MEMORY_BACKEND_TYPES
            ),
        ),
        vol.Optional(
            "source_type", description=suggest("source_type", source_type), default=source_type
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                mode=SelectSelectorMode("dropdown"), options=MEMORY_SOURCE_TYPES
            ),
        ),
    }

    if "path" in STORE_BACKEND_FIELDS[backend_type]:
        fields[vol.Optional("path", description=suggest("path", ""))] = selector.TextSelector()
    if backend_type == "pgvector":
        # No suggested value: a DSN carries the database password.
        fields[vol.Optional("dsn")] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
        fields[vol.Optional("table", description=suggest("table", ""))] = selector.TextSelector()
    if backend_type == "qdrant":
        fields[vol.Optional("url", description=suggest("url", ""))] = selector.TextSelector()
        # No suggested value: this is the qdrant token.
        fields[vol.Optional("api_key")] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
        fields[vol.Optional("collection", description=suggest("collection", ""))] = (
            selector.TextSelector()
        )
        fields[
            vol.Optional("verify_ssl", description=suggest("verify_ssl", True), default=True)
        ] = bool

    if source_type == ENTITY_SOURCE_TYPE:
        fields[
            vol.Optional(
                "preset",
                description=suggest("preset", ENTITY_DEFAULT_PRESET),
                default=ENTITY_DEFAULT_PRESET,
            )
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                mode=SelectSelectorMode("dropdown"), options=ENTITY_PRESETS
            ),
        )
        fields[
            vol.Optional("index_states", description=suggest("index_states", False), default=False)
        ] = bool
        for key in ("include", "exclude"):
            fields[vol.Optional(key, description=suggest(key, []), default=list)] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(options=[], multiple=True, custom_value=True),
                )
            )
    else:
        fields[
            vol.Optional(
                "retention_days",
                description=suggest("retention_days", MEMORY_DEFAULT_RETENTION_DAYS),
                default=MEMORY_DEFAULT_RETENTION_DAYS,
            )
        ] = NumberSelector(NumberSelectorConfig(min=0, max=3650, step=1, mode="box"))
        fields[
            vol.Optional(
                "ingest_conversation",
                description=suggest("ingest_conversation", True),
                default=True,
            )
        ] = bool
        # Deliberately no logbook-ingest switch. `tools/memory/ingest.py`
        # reaches for `logbook._get_events` / `logbook.humanify`, which the
        # installed Home Assistant no longer exposes, so the poller is a
        # runtime no-op. A toggle here would promise something the code cannot
        # do; the YAML `ingest_logbook:` block still parses for anyone who set
        # it before, and starts working again the day the fetcher does.

    return vol.Schema(fields)


def validate_store_input(
    hass,
    data: Mapping[str, Any],
    *,
    subentry_id: str | None = None,
) -> tuple[str, str] | None:
    """`(field, error_key)` for the first problem found, or None.

    Shared by `MemoryStoreSubentryFlow` and `ws_store_save` so a store created
    through Home Assistant's own dialog and one created through the panel are
    held to the same rules — including the rules the voluptuous schema cannot
    express: the name pattern (`vol.Match` does not serialise, so the pattern
    cannot live in the schema the panel renders), cross-store name uniqueness,
    and "this backend needs this field".

    Never raises and never echoes a submitted value back; the caller pairs the
    returned key with `STORE_ERROR_TEXT`.
    """
    import re

    from .tools.memory.registry import embeddings_subentries_by_title
    from .tools.memory.subentry_source import store_subentries

    name = str(data.get("name") or "").strip()
    if not re.match(MEMORY_STORE_NAME_PATTERN, name):
        return "name", "invalid_name"

    for _entry, subentry in store_subentries(hass):
        if subentry.subentry_id != subentry_id and subentry.title == name:
            return "name", "name_taken"

    title = str(data.get("embeddings") or "").strip()
    if not title:
        return "embeddings", "embeddings_required"
    available = embeddings_subentries_by_title(hass)
    if title not in available:
        return "embeddings", "embeddings_unknown"
    if available[title] is None:
        return "embeddings", "embeddings_ambiguous"

    backend_type = data.get("backend_type") or MEMORY_DEFAULT_BACKEND
    if backend_type == "pgvector" and not str(data.get("dsn") or "").strip():
        return "dsn", "dsn_required"
    if backend_type == "qdrant" and not str(data.get("url") or "").strip():
        return "url", "url_required"

    for key in ("table", "collection"):
        value = str(data.get(key) or "").strip()
        if value and not re.match(MEMORY_IDENTIFIER_PATTERN, value):
            # These land in pgvector DDL and a qdrant URL path and cannot be
            # parameterised, which is why the YAML schema constrains them too.
            return key, "invalid_identifier"

    return None


def merge_store_secrets(
    submitted: Mapping[str, Any],
    stored: Mapping[str, Any] | None,
    declared: set[str] | None = None,
) -> dict[str, Any]:
    """Carry a stored credential forward when the form submitted an empty one.

    The form never receives `dsn` or `api_key` back, so an untouched edit
    submits them empty. Treating that as "clear it" would silently break the
    store on the first unrelated edit — so empty means "keep", and clearing a
    credential is done by switching the backend or deleting the store.

    `declared` is the field set the *current* schema declares. Without it,
    switching a store from pgvector to qdrant would carry the old `dsn`
    forward into a backend that has no use for it, leaving a database password
    in storage for a store that no longer connects to a database.
    """
    out = dict(submitted)
    for key in STORE_SECRET_FIELDS:
        if declared is not None and key not in declared:
            out.pop(key, None)
            continue
        if not str(out.get(key) or "").strip():
            out.pop(key, None)
            kept = (stored or {}).get(key)
            if kept:
                out[key] = kept
    return out


class MemoryStoreSubentryFlow(ConfigSubentryFlow):
    """Add or reconfigure a memory store from Home Assistant's own dialog.

    Two steps rather than one: which fields a store needs depends on the
    backend and on whether it indexes entities, and a config-flow form cannot
    change shape while it is open. Step one asks the questions that decide the
    shape; step two asks the rest. The panel gets the same schema in a single
    reactive form (see `ws_store_schema`), from the same builder.
    """

    def __init__(self) -> None:
        self._basics: dict[str, Any] = {}
        self._reconfigure = False

    # -- step 1 ------------------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return await self._async_step_basics("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        self._reconfigure = True
        return await self._async_step_basics("reconfigure", user_input)

    async def _async_step_basics(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> SubentryFlowResult:
        defaults = self._stored_defaults()
        schema = _memory_store_basics_schema(self.hass, defaults)

        if user_input is None:
            return self.async_show_form(step_id=step_id, data_schema=schema)

        self._basics = dict(user_input)
        return await self._async_show_details()

    # -- step 2 ------------------------------------------------------------

    async def async_step_details(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        if user_input is None:
            return await self._async_show_details()

        stored = self._stored_defaults()
        submitted = {**self._basics, **user_input}
        declared = {
            str(key.schema) for key in memory_store_subentry_schema(self.hass, submitted).schema
        }
        data = merge_store_secrets(submitted, stored, declared)
        subentry_id = self._current_subentry_id()
        error = validate_store_input(self.hass, data, subentry_id=subentry_id)
        if error is not None:
            return await self._async_show_details(error=error[1])

        title = str(data.pop("name")).strip()
        if self._reconfigure:
            return self.async_update_and_abort(
                self._get_entry(), self._get_reconfigure_subentry(), title=title, data=data
            )
        return self.async_create_entry(title=title, data=data)

    async def _async_show_details(self, *, error: str | None = None) -> SubentryFlowResult:
        defaults = {**self._stored_defaults(), **self._basics}
        full = memory_store_subentry_schema(self.hass, defaults)
        basics = _memory_store_basics_schema(self.hass, defaults)
        declared = {str(key.schema) for key in basics.schema}
        rest = vol.Schema(
            {key: value for key, value in full.schema.items() if str(key.schema) not in declared}
        )
        return self.async_show_form(
            step_id="details",
            data_schema=rest,
            errors={"base": error} if error else None,
        )

    # -- helpers -----------------------------------------------------------

    def _current_subentry_id(self) -> str | None:
        """The subentry being reconfigured, or None while creating.

        Deliberately *not* named `_reconfigure_subentry_id`: `ConfigSubentryFlow`
        already owns that name, and shadowing it with a method turned every
        reconfigure into `UnknownSubEntry` — HA's own `_get_reconfigure_subentry`
        reads the attribute and got a bound method instead of an id.
        """
        if not self._reconfigure:
            return None
        return self._get_reconfigure_subentry().subentry_id

    def _stored_defaults(self) -> dict[str, Any]:
        if not self._reconfigure:
            return {}
        subentry = self._get_reconfigure_subentry()
        return {**subentry.data, "name": subentry.title}


def _memory_store_basics_schema(hass, defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """The five fields that decide what the rest of the store form looks like."""
    full = memory_store_subentry_schema(hass, defaults)
    wanted = ("name", "embeddings", "description", "backend_type", "source_type")
    return vol.Schema(
        {key: value for key, value in full.schema.items() if str(key.schema) in wanted}
    )
