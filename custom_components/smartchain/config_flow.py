"""Config flow for SmartChain integration."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any

import voluptuous as vol
from gigachat.exceptions import ResponseError
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    ConfigSubentry,
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

from .client_util import async_fetch_models, connection_data, supports, validate_client
from .const import (
    ALL_TOOLS_LABELS,
    ALL_TOOLS_SENTINEL,
    BUILTIN_TOOL_LABELS,
    BUILTIN_TOOL_NAMES,
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
    MISSING_TOOL_LABELS,
    OPENAI_COMPATIBLE,
    RESERVED_TOOL_NAMES,
    REST_DEFAULT_TIMEOUT,
    REST_MAX_TIMEOUT,
    REST_METHODS,
    REST_MIN_TIMEOUT,
    REST_RESPONSE_FORMATS,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
    SUBENTRY_TYPE_MEMORY_STORE,
    SUBENTRY_TYPE_TOOL,
    TOOL_ACTION_TYPES,
    TOOL_DEFAULT_ACTION_TYPE,
    TOOL_EMPTY_PARAMETERS,
    TOOL_NAME_PATTERN,
    TOOL_PARAM_NAME_PATTERN,
    TOOL_PARAM_TYPES,
    TOOL_PARAMS_MODE_ADVANCED,
    TOOL_PARAMS_MODE_SIMPLE,
    TOOL_PARAMS_MODES,
    TOOL_SCRIPT_PATTERN,
    UNIQUE_ID,
)
from .storable import UNSTORABLE_TEXT, UnstorableValue, ensure_storable
from .tools.inventory import materialise_allowed_tools

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
    # conversation subentry. 2 -> 3 folds `enable_history_tool` and
    # `enable_multi_agent_tools` into an explicit `allowed_tools` list, so that
    # one control describes an agent's whole tool inventory. 3 -> 4 moves
    # `verify_ssl` and `profanity` off every agent and onto the entry, which is
    # the only place they are read from now. All in
    # `__init__.async_migrate_entry`.
    MINOR_VERSION = 4

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
            # Also not gated: a custom tool belongs to the installation, not to
            # one provider — the registry is global and every agent draws from
            # it, so which entry happens to host the subentry is arbitrary.
            SUBENTRY_TYPE_TOOL: ToolSubentryFlow,
        }
        engine = config_entry.data.get(CONF_ENGINE) or ID_GIGACHAT
        if supports(engine, CAPABILITY_EMBEDDINGS):
            types[SUBENTRY_TYPE_EMBEDDINGS] = EmbeddingsSubentryFlow
        return types


class StorableSubentryFlow(ConfigSubentryFlow):
    """The base class every subentry flow here extends, for one reason.

    Home Assistant's own dialogs write through `async_create_entry` and
    `async_update_and_abort`, and what they hand over is whatever the step's
    `data_schema` produced — including a `Template` object, which
    `selector.TargetSelector` makes out of `entity_id: "{{ entity }}"`. That
    object is not JSON, and a config entry that holds one takes down every
    later write of `core.config_entries` for every integration on the system
    (see `storable`).

    Overriding the two write methods rather than adding a call to each of the
    seven step handlers is the point: a subentry flow added next year inherits
    the guard by existing, and cannot forget it. The panel's websocket
    equivalent is `websocket_api._write_subentry`, for the same reason.

    Normalisation is silent because it is not a change: a `Template` is
    rewritten to the source text it was built from, which is what the user
    typed. The refusal — a value with no textual form — is a raise here rather
    than a form error because no schema in this integration can produce one;
    the paths that *can* be reached by a person refuse them by name instead
    (`build_tool_subentry_data`, `ensure_storable` in every save command).
    """

    @callback
    def async_create_entry(self, *, data: Mapping[str, Any], **kwargs: Any) -> SubentryFlowResult:
        """Create the subentry, with its data guaranteed to survive JSON."""
        return super().async_create_entry(data=ensure_storable(data), **kwargs)

    @callback
    def async_update_and_abort(
        self, entry: ConfigEntry, subentry: ConfigSubentry, **kwargs: Any
    ) -> SubentryFlowResult:
        """Update the subentry, with its data guaranteed to survive JSON.

        Both `data` (replace) and `data_updates` (merge) are guarded; either
        may be absent, and `UNDEFINED` must be passed through untouched rather
        than turned into an empty dict, which would erase the subentry.
        """
        for key in ("data", "data_updates"):
            value = kwargs.get(key)
            if isinstance(value, Mapping):
                kwargs[key] = ensure_storable(value)
        return super().async_update_and_abort(entry, subentry, **kwargs)


class ConversationSubentryFlow(StorableSubentryFlow):
    """Handle subentry flow for adding/modifying a conversation agent."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Handle adding a new conversation agent."""
        entry = self._get_entry()
        unique_id = entry.unique_id
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        models = await async_fetch_models(self.hass, engine, connection_data(entry))
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
        models = await async_fetch_models(self.hass, engine, connection_data(entry))
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

        # Same merge, and the same reason, as `websocket_api.ws_agent_save`:
        # a key this schema does not declare is absent from `user_input`, and
        # writing `user_input` as the whole of `data` would delete it.
        declared = {str(key.schema) for key in schema.schema}
        preserved = {name: value for name, value in subentry.data.items() if name not in declared}

        title = agent_title(user_input)
        return self.async_update_and_abort(
            entry,
            subentry,
            title=title,
            data={**preserved, **user_input},
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

    # An agent's own model always belongs in its own dropdown. The list is
    # either what the provider answered a moment ago or what we shipped, and
    # neither is guaranteed to contain a model that is already stored — a new
    # release, a private deployment, or simply a fetch that failed is enough.
    # Without this the select rejects the stored value, so opening an agent to
    # change its *prompt* dead-ends on a field the user never touched. Built as
    # a new list because `models` is frequently a module constant.
    stored_model = options.get(CONF_CHAT_MODEL)
    if stored_model and stored_model not in models:
        models = [*models, stored_model]

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
                # Every other field here carries one; this one did not, so the
                # form opened with the picker blank, the key never came back in
                # `user_input`, and `_validate_and_update` — which preserves
                # only keys the schema does *not* declare — wrote the agent
                # without it. Editing the temperature was enough to strip the
                # agent's Assist API, after which `_async_handle_message` takes
                # the `use_builtin and not llm_hass_api` branch and the sentence
                # goes to Home Assistant's own agent. No default is set on
                # purpose: an empty selection must stay clearable, and
                # `normalize_model_input` drops it.
                description={"suggested_value": options.get(CONF_LLM_HASS_API)},
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
    # `verify_ssl` and `profanity` are deliberately absent, though this schema
    # declared both for GigaChat until v5.4.1. They are properties of the
    # connection, not of an agent, and `connection_schema` renders them on the
    # entry — but declaring them here too made that hub form a placebo. Both
    # were `vol.Optional(..., default=...)`, so voluptuous injected them into
    # *every* agent save whether or not the user had ever seen the field, and
    # `client_util.get_client` preferred the agent's copy over `entry.options`.
    # A hub set to `verify_ssl: False` therefore built its client with the
    # agent's injected `True`. One setting, one place that owns it.
    #
    # An agent that already stored a value is handled by the 3 -> 4 migration
    # in `__init__._migrate_connection_keys`, which lifts it onto the entry
    # when the entry has none and then deletes the agent's copy.
    #
    # An agent that predates v5.4.0 may carry no list at all while still having
    # a built-in switched on. Prefilling with the materialised equivalent rather
    # than the raw value means the form opens showing what the agent can
    # actually do, and saving it writes that down — which is how the last
    # agents leave the legacy branch in `tools.inventory.builtin_admitted`.
    #
    # The same value is handed to the selector as `keep`: it is what the form
    # will echo back, so every name in it must be submittable.
    prefill = materialise_allowed_tools(options)
    return schema.extend(
        {
            vol.Optional(
                CONF_ALLOWED_TOOLS,
                description={"suggested_value": prefill},
            ): allowed_tools_selector(hass, keep=prefill),
        }
    )


def allowed_tools_selector(hass, *, keep: Iterable[str] = ()) -> selector.SelectSelector:
    """The one place an agent's whole tool inventory is offered.

    Rendered unconditionally. Until v5.4.0 it appeared only when the tools
    registry was non-empty, so a user who had never written a `tools.yaml` had
    never seen it — and the six built-ins were governed elsewhere or nowhere,
    which left no screen anywhere that answered "what can this agent do".

    Built-ins are labelled as such, listed first and in a fixed order, so that
    a name in this list is never ambiguous about where it comes from.

    `keep` is the agent's stored list, and every name in it is offered even
    when the registry has no such tool right now — the same gap
    `embeddings_binding_options(keep=…)` and `service_options(keep=…)` cover,
    reached here by three routine events: deleting a tool, switching one off,
    and reloading while an MCP server is unreachable. Without it the form
    echoes back a value its own schema rejects, so *every* later save of that
    agent fails, including edits that have nothing to do with tools — and the
    offending name is not rendered either, so the user cannot even remove it.
    Labelled `(missing tool)`, because a name the registry cannot resolve is
    doing nothing and the user should be able to see which one it is.
    """
    builtin_label = BUILTIN_TOOL_LABELS.get(hass.config.language, BUILTIN_TOOL_LABELS["en"])
    missing_label = MISSING_TOOL_LABELS.get(hass.config.language, MISSING_TOOL_LABELS["en"])
    registry = hass.data.get(DOMAIN, {}).get("tools")
    custom_names = registry.names() if registry is not None else []
    offered = {ALL_TOOLS_SENTINEL, *BUILTIN_TOOL_NAMES, *custom_names}
    missing = [name for name in dict.fromkeys(keep) if name not in offered]
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=[
                selector.SelectOptionDict(
                    value=ALL_TOOLS_SENTINEL,
                    label=ALL_TOOLS_LABELS.get(hass.config.language, ALL_TOOLS_LABELS["en"]),
                ),
                *(
                    selector.SelectOptionDict(value=name, label=f"{name} ({builtin_label})")
                    for name in BUILTIN_TOOL_NAMES
                ),
                *(selector.SelectOptionDict(value=name, label=name) for name in custom_names),
                *(
                    selector.SelectOptionDict(value=name, label=f"{name} ({missing_label})")
                    for name in missing
                ),
            ],
            multiple=True,
            mode=SelectSelectorMode("list"),
        ),
    )


def embeddings_subentry_schema(
    models: list[str], defaults: dict[str, Any] | None = None
) -> vol.Schema:
    """Schema for an embeddings binding: a name and a model, nothing more.

    An embeddings subentry has no prompt, no tools and no temperature — it
    exists purely to bind provider credentials to one embedding model.
    """
    current = defaults or {}

    # The same union `subentry_schema` does, and for the same reason — it was
    # applied there and not carried across, which left this form strictly
    # worse off than the agent one it mirrors.
    #
    # It bites harder here. `_resolve_embeddings_model` collapses a Custom
    # Model name into `model`, so the moment someone types a name the shipped
    # list has not caught up with — which the docs actively tell them to do —
    # the stored value is one this dropdown will not accept. No unreachable
    # provider and no failed fetch is needed: the very next save is refused,
    # including a save that only renames the binding and never touches the
    # model at all. `EMBEDDING_MODELS_GIGACHAT` having gone stale is what made
    # that the ordinary case rather than the exotic one.
    models = list(models)
    stored_model = current.get("model")
    if stored_model and stored_model not in models:
        models.append(stored_model)

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


class EmbeddingsSubentryFlow(StorableSubentryFlow):
    """Handle adding or reconfiguring an embeddings binding."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        """Add a new embeddings binding."""
        entry = self._get_entry()
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        models = await async_fetch_models(
            self.hass, engine, connection_data(entry), purpose=CAPABILITY_EMBEDDINGS
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
            self.hass, engine, connection_data(entry), purpose=CAPABILITY_EMBEDDINGS
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
    # Distinct from `embeddings_required` because the two are different
    # situations for the person reading them: one is "you skipped a question",
    # the other is "the question has no answers yet". The dropdown is Required
    # and its option list is empty, so there is no value that could be typed —
    # telling someone to pick one is telling them to do the impossible. This
    # sentence names the tab that makes the missing thing instead.
    "embeddings_none": (
        "no embeddings binding exists yet; create one on the Embeddings tab "
        "first, then bind this store to it"
    ),
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
    available = embeddings_subentries_by_title(hass)
    if not title:
        # An empty dropdown and an unanswered one look identical here and are
        # not the same problem — see `embeddings_none` in STORE_ERROR_TEXT.
        return "embeddings", ("embeddings_required" if available else "embeddings_none")
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


class MemoryStoreSubentryFlow(StorableSubentryFlow):
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


# ----- custom tools ------------------------------------------------------


# The reason each tool-form rejection can give, keyed the way a config flow
# needs it (`errors={"base": key}`) and phrased the way the panel needs it.
# One table, so the flow dialog and the websocket command cannot disagree about
# why something was refused — and, just as importantly, so no rejection is ever
# phrased by interpolating a submitted value. A `rest` action's headers can
# hold a bearer token and a `service` action's data can hold anything at all;
# an error message built from the submission would put it on the wire.
TOOL_ERROR_TEXT: dict[str, str] = {
    "invalid_name": (
        "a tool name must be lowercase letters, digits and underscores, "
        "starting with a letter or underscore"
    ),
    "reserved_name": (
        "that name belongs to a built-in tool. Pick another one — a custom tool "
        "cannot replace a built-in"
    ),
    "name_taken": "another tool already uses this name",
    "mcp_name_taken": (
        "a connected MCP server already provides a tool with this name. Pick another "
        "one, or give that server a prefix in tools.yaml"
    ),
    "description_required": (
        "describe what the tool does. This is the only thing the model reads when "
        "deciding whether to call it"
    ),
    "invalid_parameters_json": "the parameters box does not contain valid JSON",
    "invalid_parameters": (
        "parameters must be a JSON Schema object: an object with 'type': 'object' "
        "and a 'properties' map"
    ),
    "invalid_parameter_name": (
        "a parameter name must be letters, digits and underscores, starting with a "
        "letter or underscore"
    ),
    "duplicate_parameter": "two parameters have the same name",
    "parameter_type_required": "every parameter needs a type",
    "service_required": "pick the Home Assistant service this tool calls",
    "invalid_service": "a service is written as domain.service, e.g. light.turn_on",
    "value_template_required": "write the template this tool renders",
    "url_required": "the rest action needs a URL",
    "script_required": "pick the script this tool runs",
    "invalid_script": "a script action targets a script.* entity",
    "invalid_action": (
        "the action is not valid for its type. Check the Home Assistant log for the "
        "detail — it is withheld here because an action can carry a credential"
    ),
    "unstorable": UNSTORABLE_TEXT,
}

# Which extra fields each action type declares, in the order the form shows
# them. Data-driven so the form, the validator and the composer cannot drift.
TOOL_ACTION_FIELDS: dict[str, tuple[str, ...]] = {
    "service": ("service", "target", "service_data", "response"),
    "template": ("value_template",),
    "rest": ("method", "url", "headers", "payload", "timeout", "response_format"),
    "script": ("script", "variables"),
}

# The five answers that decide what the rest of the tool form looks like.
TOOL_BASIC_FIELDS = ("name", "description", "enabled", "action_type", "params_mode")


def service_options(hass, *, keep: str | None = None) -> list[selector.SelectOptionDict]:
    """Every registered Home Assistant service as `domain.service`.

    Home Assistant has no `service` selector any more — it was removed before
    2026.8, and `ActionSelector` (its replacement) yields a whole action block
    rather than the domain/service pair a `ServiceAction` stores. So the picker
    is a plain `SelectSelector` fed from the live service registry: the user
    still picks rather than types, and the options are exactly what
    `hass.services.async_call` will accept.

    `custom_value=True` on the selector, and `keep` here, cover the same gap
    from two directions: a service belonging to an integration that is not
    loaded right now is absent from the registry, and without both an existing
    tool that calls it could not be reopened and saved.
    """
    names = sorted(
        f"{domain}.{service}"
        for domain, services in (hass.services.async_services() if hass else {}).items()
        for service in services
    )
    if keep and keep not in names:
        names.append(keep)
    return [selector.SelectOptionDict(value=name, label=name) for name in names]


def _parameter_rows_selector() -> selector.ObjectSelector:
    """One row per tool argument — the reason this is a constructor at all.

    `ObjectSelector` with `multiple=True` and a `fields` map renders a
    repeating row editor in <ha-form> and serialises cleanly through
    `voluptuous_serialize`, so the whole thing is a backend-served schema like
    every other form in this panel. No new panel component, and no field name
    declared in JavaScript.
    """
    return selector.ObjectSelector(
        selector.ObjectSelectorConfig(
            multiple=True,
            label_field="name",
            description_field="description",
            fields={
                "name": {"selector": {"text": {}}, "required": True},
                "type": {
                    "selector": {"select": {"options": TOOL_PARAM_TYPES}},
                    "required": True,
                },
                "description": {"selector": {"text": {}}},
                "required": {"selector": {"boolean": {}}},
            },
        )
    )


def tool_subentry_schema(hass, defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """The tool form, conditioned on the action type and parameter mode chosen.

    A flat form would show every field of every action type at once — twelve
    of the fifteen irrelevant, and combinations the action validator then
    rejects. Instead the schema is rebuilt from whatever `action_type` /
    `params_mode` the caller currently holds: for the panel that is the
    in-progress form value (see `reactive` in `ws_tool_schema`), for the
    config-flow dialog it is the answer given on the previous step.

    Because irrelevant fields are simply not declared, voluptuous's default
    PREVENT_EXTRA does the mutual-exclusion work for free: a `template` tool
    that submits a `url` is rejected by the schema itself.
    """
    current = dict(defaults or {})
    action_type = current.get("action_type") or TOOL_DEFAULT_ACTION_TYPE
    if action_type not in TOOL_ACTION_TYPES:
        action_type = TOOL_DEFAULT_ACTION_TYPE
    params_mode = current.get("params_mode") or TOOL_PARAMS_MODE_SIMPLE
    if params_mode not in TOOL_PARAMS_MODES:
        params_mode = TOOL_PARAMS_MODE_SIMPLE

    def suggest(key: str, fallback: Any = None) -> dict[str, Any]:
        return {"suggested_value": current.get(key, fallback)}

    fields: dict[Any, Any] = {
        vol.Required("name", description=suggest("name", "")): selector.TextSelector(),
        vol.Required("description", description=suggest("description", "")): selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        ),
        vol.Optional("enabled", description=suggest("enabled", True), default=True): bool,
        vol.Optional(
            "action_type", description=suggest("action_type", action_type), default=action_type
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                mode=SelectSelectorMode("dropdown"), options=TOOL_ACTION_TYPES
            ),
        ),
        vol.Optional(
            "params_mode", description=suggest("params_mode", params_mode), default=params_mode
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                mode=SelectSelectorMode("dropdown"), options=TOOL_PARAMS_MODES
            ),
        ),
    }

    if params_mode == TOOL_PARAMS_MODE_SIMPLE:
        fields[
            vol.Optional("params_rows", description=suggest("params_rows", []), default=list)
        ] = _parameter_rows_selector()
    else:
        fields[vol.Optional("params_json", description=suggest("params_json", ""), default="")] = (
            selector.TextSelector(selector.TextSelectorConfig(multiline=True))
        )

    if action_type == "service":
        fields[vol.Optional("service", description=suggest("service", ""))] = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    mode=SelectSelectorMode("dropdown"),
                    options=service_options(hass, keep=current.get("service")),
                    custom_value=True,
                    sort=False,
                ),
            )
        )
        fields[vol.Optional("target", description=suggest("target", {}), default=dict)] = (
            selector.TargetSelector()
        )
        fields[
            vol.Optional("service_data", description=suggest("service_data", {}), default=dict)
        ] = selector.ObjectSelector()
        fields[vol.Optional("response", description=suggest("response", False), default=False)] = (
            bool
        )
    elif action_type == "template":
        fields[vol.Optional("value_template", description=suggest("value_template", ""))] = (
            TemplateSelector()
        )
    elif action_type == "rest":
        method = current.get("method") or REST_METHODS[0]
        fields[vol.Optional("method", description=suggest("method", method), default=method)] = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    mode=SelectSelectorMode("dropdown"), options=REST_METHODS
                ),
            )
        )
        fields[vol.Optional("url", description=suggest("url", ""))] = selector.TextSelector()
        fields[vol.Optional("headers", description=suggest("headers", {}), default=dict)] = (
            selector.ObjectSelector()
        )
        fields[vol.Optional("payload", description=suggest("payload", {}), default=dict)] = (
            selector.ObjectSelector()
        )
        fields[
            vol.Optional(
                "timeout",
                description=suggest("timeout", REST_DEFAULT_TIMEOUT),
                default=REST_DEFAULT_TIMEOUT,
            )
        ] = NumberSelector(
            NumberSelectorConfig(min=REST_MIN_TIMEOUT, max=REST_MAX_TIMEOUT, step=1, mode="box")
        )
        fields[
            vol.Optional(
                "response_format",
                description=suggest("response_format", REST_RESPONSE_FORMATS[0]),
                default=REST_RESPONSE_FORMATS[0],
            )
        ] = selector.SelectSelector(
            selector.SelectSelectorConfig(
                mode=SelectSelectorMode("dropdown"), options=REST_RESPONSE_FORMATS
            ),
        )
    elif action_type == "script":
        fields[vol.Optional("script", description=suggest("script", ""))] = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="script"),
        )
        fields[vol.Optional("variables", description=suggest("variables", {}), default=dict)] = (
            selector.ObjectSelector()
        )

    return vol.Schema(fields)


def _rows_to_parameters(rows: Any) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    """Turn the repeating parameter rows into a JSON Schema object."""
    import re

    if rows in (None, ""):
        rows = []
    if not isinstance(rows, list):
        return None, ("params_rows", "invalid_parameters")

    properties: dict[str, Any] = {}
    required: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            return None, ("params_rows", "invalid_parameters")
        name = str(row.get("name") or "").strip()
        if not re.match(TOOL_PARAM_NAME_PATTERN, name):
            return None, ("params_rows", "invalid_parameter_name")
        if name in properties:
            return None, ("params_rows", "duplicate_parameter")
        param_type = str(row.get("type") or "").strip()
        if param_type not in TOOL_PARAM_TYPES:
            return None, ("params_rows", "parameter_type_required")
        prop: dict[str, Any] = {"type": param_type}
        description = str(row.get("description") or "").strip()
        if description:
            prop["description"] = description
        properties[name] = prop
        if row.get("required"):
            required.append(name)

    parameters: dict[str, Any] = {"type": "object", "properties": properties}
    # Omitted rather than written as an empty list, so a form-built tool with
    # no required arguments composes to byte-identical `parameters` with the
    # YAML anyone would hand-write for the same tool.
    if required:
        parameters["required"] = required
    return parameters, None


def compose_tool_parameters(
    form: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    """`parameters` as a validated JSON Schema, or `(None, (field, key))`.

    Two authoring modes, one output. `simple` builds the schema from rows and
    can only produce shapes it knows are valid; `advanced` parses a textarea,
    which is the escape hatch for `anyOf`, nested objects and arrays that rows
    cannot express. Both end at `PARAMETERS_SCHEMA` — the same validator
    tools.yaml passes through — because `dispatcher.dispatch` hands
    `tool.parameters` straight to `jsonschema.validate`, and a shape that got
    past this would fail there instead, at call time, in front of the model.
    """
    import json

    from .tools.schema import PARAMETERS_SCHEMA

    mode = form.get("params_mode") or TOOL_PARAMS_MODE_SIMPLE
    if mode == TOOL_PARAMS_MODE_SIMPLE:
        parameters, error = _rows_to_parameters(form.get("params_rows"))
        if error is not None:
            return None, error
    else:
        text = str(form.get("params_json") or "").strip()
        if not text:
            parameters = dict(TOOL_EMPTY_PARAMETERS)
        else:
            try:
                parameters = json.loads(text)
            except ValueError:
                # Deliberately not `str(err)`: a JSON decode error quotes the
                # offending line, and the offending line is user-submitted.
                return None, ("params_json", "invalid_parameters_json")
        if not isinstance(parameters, dict):
            return None, ("params_json", "invalid_parameters")

    try:
        validated = PARAMETERS_SCHEMA(parameters)
    except vol.Invalid:
        field = "params_rows" if mode == TOOL_PARAMS_MODE_SIMPLE else "params_json"
        return None, (field, "invalid_parameters")
    return dict(validated), None


def compose_tool_action(
    form: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    """The `action` block as a validated dict, or `(None, (field, key))`.

    Ends at `tools.schema.validate_action`, the same discriminated validator
    tools.yaml goes through, so a form-built action and a hand-written one are
    held to identical rules. A failure there is reported as a bare
    `invalid_action`: that validator interpolates the offending value into its
    message (`unknown action type 'sk-...'`), and a `rest` action's headers can
    hold a bearer token.
    """
    import re

    from .tools.schema import validate_action

    action_type = form.get("action_type") or TOOL_DEFAULT_ACTION_TYPE
    action: dict[str, Any] = {"type": action_type}

    if action_type == "service":
        service = str(form.get("service") or "").strip()
        if not service:
            return None, ("service", "service_required")
        domain, _, name = service.partition(".")
        if not domain or not name or "." in name:
            return None, ("service", "invalid_service")
        action["domain"] = domain
        action["service"] = name
        action["target"] = dict(form.get("target") or {})
        action["data"] = dict(form.get("service_data") or {})
        action["response"] = bool(form.get("response", False))
    elif action_type == "template":
        value_template = str(form.get("value_template") or "").strip()
        if not value_template:
            return None, ("value_template", "value_template_required")
        action["value_template"] = value_template
    elif action_type == "rest":
        url = str(form.get("url") or "").strip()
        if not url:
            return None, ("url", "url_required")
        action["method"] = form.get("method") or REST_METHODS[0]
        action["url"] = url
        action["headers"] = {
            str(key): str(value) for key, value in dict(form.get("headers") or {}).items()
        }
        payload = dict(form.get("payload") or {})
        # An empty object and "no body" are different requests, and the
        # dataclass default is None. An untouched ObjectSelector submits {}.
        action["payload"] = payload or None
        action["timeout"] = int(form.get("timeout", REST_DEFAULT_TIMEOUT))
        action["response_format"] = form.get("response_format") or REST_RESPONSE_FORMATS[0]
    elif action_type == "script":
        script = str(form.get("script") or "").strip()
        if not script:
            return None, ("script", "script_required")
        if not re.match(TOOL_SCRIPT_PATTERN, script):
            return None, ("script", "invalid_script")
        action["script"] = script
        action["variables"] = dict(form.get("variables") or {})
    else:
        return None, ("action_type", "invalid_action")

    try:
        validated = validate_action(action)
    except vol.Invalid as err:
        LOGGER.warning(  # detail stays server-side — the message embeds the value
            "SmartChain tool action rejected by the action validator: %s", err
        )
        return None, ("action_type", "invalid_action")
    return dict(validated), None


def validate_tool_name(
    hass, name: str, *, subentry_id: str | None = None
) -> tuple[str, str] | None:
    """`(field, error_key)` for the first problem with a tool name, or None.

    Enforced here rather than only in `loader.py` because a name refused at
    load time is refused *silently* — `load_tools_file` logs and skips. A
    reserved or duplicate name typed into a form must be refused at the point
    it is typed, where the user is still looking at it.

    A live MCP tool's name is refused too. MCP tools are discovered, not
    declared, so this cannot be a guarantee — a server can announce the name
    tomorrow — but it catches the case that is visible today, and the case that
    is invisible is handled where it has to be, in `_reload_registry`'s
    ordering and in `_register_tools`'s own collision check.
    """
    import re

    from .tools.model import MCPAction
    from .tools.subentry_source import tool_subentries

    if not re.match(TOOL_NAME_PATTERN, name):
        return "name", "invalid_name"
    if name in RESERVED_TOOL_NAMES:
        return "name", "reserved_name"
    for _entry, subentry in tool_subentries(hass):
        if subentry.subentry_id != subentry_id and subentry.title == name:
            return "name", "name_taken"
    registry = (hass.data.get(DOMAIN) or {}).get("tools")
    if registry is not None:
        existing = registry.get(name)
        if existing is not None and isinstance(existing.action, MCPAction):
            return "name", "mcp_name_taken"
    return None


def build_tool_subentry_data(
    hass, form: Mapping[str, Any], *, subentry_id: str | None = None
) -> tuple[dict[str, Any] | None, tuple[str, str] | None]:
    """Turn the flat form into what a `tool` subentry stores.

    Returns `({description, parameters, action, enabled, params_mode}, None)`
    — deliberately without `name`, because the subentry *title* is the tool
    name, the convention every other subentry type here already follows — or
    `(None, (field, error_key))` for the first problem found.

    `parameters` and `action` are stored already composed and already
    validated. That is what lets `tool_from_subentry` be a straight read: the
    composition happens once, on the way in, where a failure can still be shown
    to the person who caused it, rather than on every registry rebuild where it
    could only be logged.

    The JSON guard runs here rather than at the two call sites because this is
    what both of them share: the panel's `smartchain/tool/save` and Home
    Assistant's own tool dialog compose through this one function, and only one
    of them can be reached from `websocket_api`. `target` is the field that
    needs it — see `storable` — and it needs it before `compose_tool_action`,
    which would otherwise bury a `Template` inside the `action` block where a
    refusal could no longer name a field the user can see.
    """
    try:
        form = ensure_storable(form)
    except UnstorableValue as err:
        return None, (str(err.path[0]), "unstorable")

    name = str(form.get("name") or "").strip()
    error = validate_tool_name(hass, name, subentry_id=subentry_id)
    if error is not None:
        return None, error

    description = str(form.get("description") or "").strip()
    if not description:
        return None, ("description", "description_required")

    parameters, error = compose_tool_parameters(form)
    if error is not None:
        return None, error

    action, error = compose_tool_action(form)
    if error is not None:
        return None, error

    return {
        "description": description,
        "parameters": parameters,
        "action": action,
        "enabled": bool(form.get("enabled", True)),
        # Form state, not tool state: which editor to reopen. `parameters` is
        # the authoritative schema either way.
        "params_mode": form.get("params_mode") or TOOL_PARAMS_MODE_SIMPLE,
    }, None


def _parameters_are_row_expressible(parameters: Mapping[str, Any]) -> bool:
    """Can the rows editor represent this JSON Schema without losing anything?"""
    if set(parameters) - {"type", "properties", "required"}:
        return False
    if parameters.get("type") != "object":
        return False
    properties = parameters.get("properties")
    if not isinstance(properties, dict):
        return False
    for prop in properties.values():
        if not isinstance(prop, dict) or set(prop) - {"type", "description"}:
            return False
        if prop.get("type") not in TOOL_PARAM_TYPES:
            return False
    required = parameters.get("required") or []
    return isinstance(required, list) and all(name in properties for name in required)


def _parameters_to_rows(parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
    required = set(parameters.get("required") or [])
    return [
        {
            "name": name,
            "type": prop.get("type", TOOL_PARAM_TYPES[0]),
            "description": prop.get("description", ""),
            "required": name in required,
        }
        for name, prop in (parameters.get("properties") or {}).items()
    ]


def redact_tool_secrets(form: Mapping[str, Any]) -> dict[str, Any]:
    """Blank the values of a `rest` action's headers, keeping their names.

    A header value is where an `Authorization: Bearer …` goes, so it is a
    credential by the same argument that made a store's `dsn` one — and it is
    now stored in `.storage` by a form rather than typed into a file the user
    already knows the browser can read. The names survive because a user
    editing a tool needs to see which headers exist; the values do not travel,
    and `merge_tool_secrets` puts them back when the form comes home unchanged.
    """
    out = dict(form)
    if isinstance(out.get("headers"), dict):
        out["headers"] = {key: "" for key in out["headers"]}
    return out


def merge_tool_secrets(
    submitted: Mapping[str, Any], stored: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Carry a stored header value forward when the form submitted an empty one.

    Per key rather than for the whole map, which is what makes the field still
    editable: a header submitted empty keeps whatever is stored under that
    name, a header submitted with a value takes the new one, and a header
    deleted from the form is deleted for real. The all-or-nothing rule
    `merge_store_secrets` uses would have made removing one header impossible.
    """
    out = dict(submitted)
    stored_headers = dict((stored or {}).get("headers") or {})
    if isinstance(out.get("headers"), dict):
        out["headers"] = {
            key: (stored_headers[key] if not str(value or "") and key in stored_headers else value)
            for key, value in out["headers"].items()
        }
    return out


def tool_form_defaults(subentry: Any, *, redact: bool = True) -> dict[str, Any]:
    """Stored tool data, decomposed back into the flat form's fields.

    The inverse of `build_tool_subentry_data`. `params_mode` is honoured when
    stored and derived when not — a subentry written by hand, or one whose
    schema stopped being row-expressible, opens in the editor that can actually
    represent it rather than in one that would silently rewrite it.

    Redacted by default, so the unsafe answer has to be asked for by name: only
    the save paths, which need the stored values to merge against, pass
    `redact=False`.
    """
    import json

    data = dict(subentry.data)
    parameters = dict(data.get("parameters") or TOOL_EMPTY_PARAMETERS)
    action = dict(data.get("action") or {})
    action_type = action.get("type") or TOOL_DEFAULT_ACTION_TYPE

    mode = data.get("params_mode")
    if mode not in TOOL_PARAMS_MODES or (
        mode == TOOL_PARAMS_MODE_SIMPLE and not _parameters_are_row_expressible(parameters)
    ):
        mode = (
            TOOL_PARAMS_MODE_SIMPLE
            if _parameters_are_row_expressible(parameters)
            else TOOL_PARAMS_MODE_ADVANCED
        )

    defaults: dict[str, Any] = {
        "name": subentry.title,
        "description": data.get("description", ""),
        "enabled": bool(data.get("enabled", True)),
        "action_type": action_type,
        "params_mode": mode,
    }
    if mode == TOOL_PARAMS_MODE_SIMPLE:
        defaults["params_rows"] = _parameters_to_rows(parameters)
    else:
        defaults["params_json"] = json.dumps(parameters, indent=2, ensure_ascii=False)

    if action_type == "service":
        domain = action.get("domain", "")
        service = action.get("service", "")
        defaults["service"] = f"{domain}.{service}" if domain and service else ""
        defaults["target"] = dict(action.get("target") or {})
        defaults["service_data"] = dict(action.get("data") or {})
        defaults["response"] = bool(action.get("response", False))
    elif action_type == "template":
        defaults["value_template"] = action.get("value_template", "")
    elif action_type == "rest":
        defaults["method"] = action.get("method", REST_METHODS[0])
        defaults["url"] = action.get("url", "")
        defaults["headers"] = dict(action.get("headers") or {})
        defaults["payload"] = dict(action.get("payload") or {})
        defaults["timeout"] = action.get("timeout", REST_DEFAULT_TIMEOUT)
        defaults["response_format"] = action.get("response_format", REST_RESPONSE_FORMATS[0])
    elif action_type == "script":
        defaults["script"] = action.get("script", "")
        defaults["variables"] = dict(action.get("variables") or {})

    return redact_tool_secrets(defaults) if redact else defaults


class ToolSubentryFlow(StorableSubentryFlow):
    """Build or edit a custom tool from Home Assistant's own dialog.

    Two steps rather than one, for the same reason the memory-store flow has
    two: which fields a tool needs depends on its action type and on how its
    arguments are being authored, and a config-flow form cannot change shape
    while it is open. Step one asks the questions that decide the shape; step
    two asks the rest. The panel gets the same schema in a single reactive form
    (see `ws_tool_schema`), from the same builder.
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
        schema = _tool_basics_schema(self.hass, self._stored_defaults())

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

        submitted = merge_tool_secrets({**self._basics, **user_input}, self._stored_raw())
        subentry_id = self._current_subentry_id()
        data, error = build_tool_subentry_data(self.hass, submitted, subentry_id=subentry_id)
        if error is not None:
            return await self._async_show_details(error=error[1])

        title = str(submitted["name"]).strip()
        if self._reconfigure:
            return self.async_update_and_abort(
                self._get_entry(), self._get_reconfigure_subentry(), title=title, data=data
            )
        return self.async_create_entry(title=title, data=data)

    async def _async_show_details(self, *, error: str | None = None) -> SubentryFlowResult:
        defaults = {**self._stored_defaults(), **self._basics}
        full = tool_subentry_schema(self.hass, defaults)
        declared = {str(key.schema) for key in _tool_basics_schema(self.hass, defaults).schema}
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
        already owns that name, and shadowing it with a method turns every
        reconfigure into `UnknownSubEntry` — see the same note on
        `MemoryStoreSubentryFlow`.
        """
        if not self._reconfigure:
            return None
        return self._get_reconfigure_subentry().subentry_id

    def _stored_defaults(self) -> dict[str, Any]:
        """What the form shows — header values blanked."""
        if not self._reconfigure:
            return {}
        return tool_form_defaults(self._get_reconfigure_subentry())

    def _stored_raw(self) -> dict[str, Any]:
        """What the save merges against — header values intact, never rendered."""
        if not self._reconfigure:
            return {}
        return tool_form_defaults(self._get_reconfigure_subentry(), redact=False)


def _tool_basics_schema(hass, defaults: Mapping[str, Any] | None = None) -> vol.Schema:
    """The five fields that decide what the rest of the tool form looks like."""
    full = tool_subentry_schema(hass, defaults)
    return vol.Schema(
        {key: value for key, value in full.schema.items() if str(key.schema) in TOOL_BASIC_FIELDS}
    )
