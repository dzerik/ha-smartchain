"""The SmartChain integration."""

import base64
import logging
from pathlib import Path

import voluptuous as vol
from homeassistant.components.camera import async_get_image
from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.util import dt as dt_util
from langchain_core.messages import HumanMessage

from .client_util import get_client
from .helpers import async_generate_structured  # re-exported for downstream integrations
from .tools import ToolRegistry
from .tools.loader import LoaderError, load_tools_file
from .tools.mcp import MCPManager
from .tools.memory import create_embeddings
from .tools.memory import store as _memory_store_mod
from .tools.memory.embeddings import EmbeddingsConfigError
from .tools.memory.ingest import MemoryLogbookPoller
from .tools.memory.retention import RetentionTask
from .tools.memory.store import MemoryStore

__all__ = ["async_generate_structured"]
from .const import (
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENGINE,
    CONF_MAX_TOKENS,
    CONF_PROFANITY,
    CONF_TEMPERATURE,
    CONF_VERIFY_SSL,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    EVENT_MEMORY_CLEARED,
    EVENT_TOOLS_RELOADED,
    ID_GIGACHAT,
    MEMORY_PERSIST_DIRNAME,
    SERVICE_CLEAR_MEMORY,
    SERVICE_RELOAD_TOOLS,
    SIGNAL_NEW_ANALYSIS,
    SUBENTRY_TYPE_CONVERSATION,
    TOOLS_YAML_PATH,
)

LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CONVERSATION, Platform.SENSOR]

try:
    from homeassistant.components import ai_task  # noqa: F401

    PLATFORMS.append(Platform.AI_TASK)
except (ImportError, AttributeError):
    pass


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    await hass.config_entries.async_reload(entry.entry_id)


def _resolve_client_args(options: dict) -> dict:
    """Build common LLM client args from options/subentry data dict."""
    model = options.get(CONF_CHAT_MODEL_USER)
    if not model or not model.strip():
        model = options.get(CONF_CHAT_MODEL)
    if not model or not model.strip() or model == "none":
        model = None
    temperature = options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)
    max_tokens = options.get(CONF_MAX_TOKENS)

    common_args: dict = {
        "verbose": False,
        "model": model,
    }
    if temperature is not None:
        common_args["temperature"] = temperature
    if max_tokens is not None:
        common_args["max_tokens"] = max_tokens
    # Pass through GigaChat-specific toggles so subentry values aren't silently lost.
    if CONF_VERIFY_SSL in options:
        common_args[CONF_VERIFY_SSL] = options[CONF_VERIFY_SSL]
    if CONF_PROFANITY in options:
        common_args[CONF_PROFANITY] = options[CONF_PROFANITY]
    return common_args


SERVICE_ASK = "ask"
SERVICE_ASK_SCHEMA = vol.Schema(
    {
        vol.Required("message"): str,
        vol.Optional("entity_id"): str,
    }
)

SERVICE_ANALYZE_IMAGE = "analyze_image"
SERVICE_ANALYZE_IMAGE_SCHEMA = vol.Schema(
    {
        vol.Required("message"): str,
        vol.Required("camera_entity_id"): str,
        vol.Optional("entity_id"): str,
        vol.Optional("notify_entity"): str,
    }
)

# Kept for backwards-compatibility with users who reference the entity_id from
# automations / templates. The actual entity is registered via the SENSOR platform
# in sensor.py.
SENSOR_LAST_ANALYSIS = f"sensor.{DOMAIN}_last_analysis"
EVENT_IMAGE_ANALYZED = f"{DOMAIN}_image_analyzed"

_GENERIC_LLM_ERROR = "LLM request failed; see Home Assistant logs for details."
_GENERIC_CAMERA_ERROR = "Failed to read camera image; see Home Assistant logs for details."


def _find_client(hass: HomeAssistant, entity_id: str | None = None):
    """Find a SmartChain LLM client, optionally routed by entity_id.

    Routing uses entity_registry to resolve `entity_id` -> `unique_id`, which is
    the only stable mapping back to a subentry / config entry (entity_id is
    derived from the title slug, not the unique_id).
    """
    if entity_id:
        ent_reg = er.async_get(hass)
        ent_entry = ent_reg.async_get(entity_id)
        if ent_entry and ent_entry.platform == DOMAIN and ent_entry.unique_id:
            unique_id = ent_entry.unique_id
            for entry in hass.config_entries.async_entries(DOMAIN):
                if entry.runtime_data is None:
                    continue
                if isinstance(entry.runtime_data, dict):
                    for sub_id, client in entry.runtime_data.items():
                        if unique_id == f"{entry.entry_id}_{sub_id}":
                            return client
                elif unique_id == entry.entry_id:
                    return entry.runtime_data

    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.runtime_data is None:
            continue
        if isinstance(entry.runtime_data, dict):
            for _sub_id, c in entry.runtime_data.items():
                return c
        else:
            return entry.runtime_data
    return None


def _tools_yaml_path(hass: HomeAssistant) -> Path:
    """Resolve the absolute path to tools.yaml under the HA config directory."""
    return Path(hass.config.config_dir) / TOOLS_YAML_PATH


def _memory_persist_dir(hass: HomeAssistant) -> Path:
    """Absolute path of the Chroma persist dir under .storage/."""
    return Path(hass.config.config_dir) / ".storage" / MEMORY_PERSIST_DIRNAME


async def _build_memory(
    hass: HomeAssistant, cfg
) -> tuple[MemoryStore | None, RetentionTask | None, MemoryLogbookPoller | None]:
    """Construct MemoryStore + auxiliary tasks for a MemoryConfig.

    Returns (None, None, None) when cfg is None/disabled or the embeddings
    provider could not be constructed.
    """
    if cfg is None or not cfg.enabled:
        return None, None, None
    try:
        embeddings = create_embeddings(hass, cfg)
    except EmbeddingsConfigError as err:
        LOGGER.error("SmartChain memory disabled: %s", err)
        return None, None, None

    store = await hass.async_add_executor_job(
        _memory_store_mod.MemoryStore, hass, embeddings, _memory_persist_dir(hass)
    )
    if not store.is_available:
        return None, None, None

    retention = RetentionTask(hass, store, cfg.retention_days)
    poller = MemoryLogbookPoller(hass, store, cfg.logbook)
    return store, retention, poller


async def _reload_registry(hass: HomeAssistant) -> int:
    """Re-read tools.yaml into the registry. Raises LoaderError on failure."""
    path = _tools_yaml_path(hass)
    result = await hass.async_add_executor_job(load_tools_file, path)
    registry: ToolRegistry = hass.data[DOMAIN]["tools"]
    registry.replace_all(result.yaml_tools)

    manager: MCPManager | None = hass.data[DOMAIN].get("mcp_manager")
    if manager is not None:
        await manager.stop()
        manager.configure(result.mcp_servers)
        await manager.start()

    # --- Memory subsystem (re)build ---
    try:
        new_store, new_retention, new_poller = await _build_memory(hass, result.memory_config)
    except Exception:  # noqa: BLE001
        LOGGER.exception("memory rebuild failed; keeping previous subsystem")
    else:
        old_retention: RetentionTask | None = hass.data[DOMAIN].get("memory_retention")
        old_poller: MemoryLogbookPoller | None = hass.data[DOMAIN].get("memory_logbook")
        if old_retention is not None:
            await old_retention.stop()
        if old_poller is not None:
            await old_poller.stop()
        hass.data[DOMAIN]["memory"] = new_store
        hass.data[DOMAIN]["memory_retention"] = new_retention
        hass.data[DOMAIN]["memory_logbook"] = new_poller
        hass.data[DOMAIN]["memory_config"] = result.memory_config
        if new_retention is not None:
            new_retention.start()
        if new_poller is not None:
            new_poller.start()

    # MCP tools arrive asynchronously after start(); the count fired in the
    # reload event therefore reflects only the synchronously-loaded YAML tools.
    return len(result.yaml_tools)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up SmartChain domain (register services)."""

    async def _handle_ask(call: ServiceCall) -> ServiceResponse:
        """Handle smartchain.ask service call."""
        message = call.data["message"]
        entity_id = call.data.get("entity_id")

        client = _find_client(hass, entity_id)
        if not client:
            return {"response": "No SmartChain agent available."}

        try:
            result = await client.ainvoke([HumanMessage(content=message)])
            return {"response": result.content}
        except Exception:
            # Provider exception messages may embed credentials (e.g. OpenAI's
            # AuthenticationError includes the offending key fragment). Don't
            # surface them to service callers — full detail is in the log.
            LOGGER.exception("SmartChain ask service error")
            return {"response": _GENERIC_LLM_ERROR}

    async def _handle_analyze_image(call: ServiceCall) -> ServiceResponse:
        """Handle smartchain.analyze_image service call."""
        message = call.data["message"]
        camera_entity_id = call.data["camera_entity_id"]
        entity_id = call.data.get("entity_id")

        try:
            image = await async_get_image(hass, camera_entity_id, timeout=10)
        except Exception:
            LOGGER.exception("Failed to get image from %s", camera_entity_id)
            return {"response": _GENERIC_CAMERA_ERROR}

        encoded = base64.b64encode(image.content).decode("utf-8")
        mime_type = image.content_type or "image/jpeg"
        data_url = f"data:{mime_type};base64,{encoded}"

        client = _find_client(hass, entity_id)
        if not client:
            return {"response": "No SmartChain agent available."}

        multimodal_content = [
            {"type": "text", "text": message},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

        try:
            result = await client.ainvoke([HumanMessage(content=multimodal_content)])
            response_text = result.content
        except Exception:
            LOGGER.exception("SmartChain analyze_image error")
            return {"response": _GENERIC_LLM_ERROR}

        now = dt_util.utcnow().isoformat()
        event_data = {
            "response": response_text,
            "camera_entity_id": camera_entity_id,
            "message": message,
            "timestamp": now,
        }

        hass.bus.async_fire(EVENT_IMAGE_ANALYZED, event_data)
        async_dispatcher_send(hass, SIGNAL_NEW_ANALYSIS, event_data)

        notify_entity = call.data.get("notify_entity")
        if notify_entity:
            try:
                await hass.services.async_call(
                    "notify",
                    "send_message",
                    {
                        "entity_id": notify_entity,
                        "message": response_text,
                        "title": f"SmartChain: {camera_entity_id}",
                    },
                )
            except Exception as err:
                LOGGER.warning("Failed to send notification to %s: %s", notify_entity, err)

        return {"response": response_text}

    # Initialise tools registry from /config/smartchain/tools.yaml (optional).
    hass.data.setdefault(DOMAIN, {})
    if "tools" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["tools"] = ToolRegistry()
    if "mcp_manager" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["mcp_manager"] = MCPManager(hass, hass.data[DOMAIN]["tools"])
    try:
        initial = await _reload_registry(hass)
        LOGGER.info("SmartChain loaded %d custom tools", initial)
    except LoaderError as err:
        LOGGER.error("SmartChain tools.yaml load failed at startup: %s", err)

    async def _handle_reload_tools(call: ServiceCall) -> None:
        try:
            count = await _reload_registry(hass)
        except LoaderError as err:
            raise HomeAssistantError(str(err)) from err
        hass.bus.async_fire(EVENT_TOOLS_RELOADED, {"count": count})

    async def _handle_clear_memory(call: ServiceCall) -> None:
        store: MemoryStore | None = hass.data.get(DOMAIN, {}).get("memory")
        if store is None or not store.is_available:
            raise HomeAssistantError("smartchain memory is not configured")
        kind = call.data.get("kind", "any")
        agent_id = call.data.get("agent_id")
        where: dict | None = {}
        if kind != "any":
            where["kind"] = kind
        if agent_id:
            where["agent_id"] = agent_id
        if not where:
            where = None
        deleted = await store.clear(where)
        hass.bus.async_fire(EVENT_MEMORY_CLEARED, {"deleted": deleted})

    # Register sidebar panel (graceful — skip if frontend not available).
    # Failures here aren't fatal but they do mean the user has no UI — bump from
    # DEBUG to WARNING so the cause is actually visible in logs.
    try:
        panel_dir = Path(__file__).parent / "panel"
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig("/smartchain", str(panel_dir), False)]
        )
        import json

        manifest_path = Path(__file__).parent / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        panel_version = manifest.get("version", "0")
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="SmartChain AI",
            sidebar_icon="mdi:robot",
            frontend_url_path="smartchain",
            config={
                "_panel_custom": {
                    "name": "smartchain-panel",
                    "module_url": f"/smartchain/smartchain-panel.js?v={panel_version}",
                },
                "version": panel_version,
            },
        )
    except Exception as err:
        LOGGER.warning("Could not register SmartChain panel: %s", err)

    hass.data[DOMAIN]["find_client"] = _find_client

    hass.services.async_register(
        DOMAIN,
        SERVICE_ASK,
        _handle_ask,
        schema=SERVICE_ASK_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ANALYZE_IMAGE,
        _handle_analyze_image,
        schema=SERVICE_ANALYZE_IMAGE_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    if not hass.services.has_service(DOMAIN, SERVICE_RELOAD_TOOLS):
        hass.services.async_register(
            DOMAIN,
            SERVICE_RELOAD_TOOLS,
            _handle_reload_tools,
            schema=vol.Schema({}),
        )
    if not hass.services.has_service(DOMAIN, SERVICE_CLEAR_MEMORY):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CLEAR_MEMORY,
            _handle_clear_memory,
            schema=vol.Schema(
                {
                    vol.Optional("kind", default="any"): vol.In(["any", "conversation", "logbook"]),
                    vol.Optional("agent_id"): str,
                }
            ),
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize SmartChain."""
    engine = entry.data.get(CONF_ENGINE) or ID_GIGACHAT

    entry.async_on_unload(entry.add_update_listener(update_listener))

    subentries = entry.subentries
    if subentries:
        clients: dict[str, object] = {}
        for sub_id, subentry in subentries.items():
            if subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
                continue
            common_args = _resolve_client_args(dict(subentry.data))
            clients[sub_id] = await get_client(hass, engine, entry, common_args)
        entry.runtime_data = clients
    else:
        common_args = _resolve_client_args(dict(entry.options))
        LOGGER.debug(
            "SmartChain setup: engine=%s, resolved_model=%s",
            engine,
            common_args.get("model"),
        )
        client = await get_client(hass, engine, entry, common_args)
        entry.runtime_data = client

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload SmartChain."""
    # Stop MCP connections and memory tasks when the last config entry is unloaded.
    remaining = [
        e for e in hass.config_entries.async_entries(DOMAIN) if e.entry_id != entry.entry_id
    ]
    if not remaining:
        manager: MCPManager | None = hass.data.get(DOMAIN, {}).get("mcp_manager")
        if manager is not None:
            await manager.stop()
        retention: RetentionTask | None = hass.data.get(DOMAIN, {}).get("memory_retention")
        if retention is not None:
            await retention.stop()
        poller: MemoryLogbookPoller | None = hass.data.get(DOMAIN, {}).get("memory_logbook")
        if poller is not None:
            await poller.stop()
        hass.data.get(DOMAIN, {}).pop("memory_config", None)
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
