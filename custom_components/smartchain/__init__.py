"""The SmartChain integration."""

import base64
import logging

import voluptuous as vol
from homeassistant.components.camera import async_get_image
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from langchain_core.messages import HumanMessage

from .client_util import get_client
from .const import (
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENGINE,
    CONF_MAX_TOKENS,
    CONF_TEMPERATURE,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    ID_GIGACHAT,
    SUBENTRY_TYPE_CONVERSATION,
)

LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.CONVERSATION]

try:
    from homeassistant.components import ai_task  # noqa: F401

    PLATFORMS.append(Platform.AI_TASK)
except (ImportError, AttributeError):
    pass


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    await hass.config_entries.async_reload(entry.entry_id)


def _resolve_client_args(options: dict) -> dict:
    """Build common LLM client args from options dict."""
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
    }
)


def _find_client(hass: HomeAssistant, entity_id: str | None = None):
    """Find the first available SmartChain LLM client."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.runtime_data is None:
            continue
        if isinstance(entry.runtime_data, dict):
            for sub_id, c in entry.runtime_data.items():
                if entity_id:
                    uid = f"{entry.entry_id}_{sub_id}"
                    if entity_id.endswith(uid):
                        return c
                else:
                    return c
        else:
            return entry.runtime_data
    return None


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
        except Exception as err:
            LOGGER.exception("SmartChain ask service error: %s", err)
            return {"response": f"Error: {err}"}

    async def _handle_analyze_image(call: ServiceCall) -> ServiceResponse:
        """Handle smartchain.analyze_image service call."""
        message = call.data["message"]
        camera_entity_id = call.data["camera_entity_id"]
        entity_id = call.data.get("entity_id")

        # Get snapshot from camera
        try:
            image = await async_get_image(hass, camera_entity_id, timeout=10)
        except Exception as err:
            LOGGER.error("Failed to get image from %s: %s", camera_entity_id, err)
            return {"response": f"Error getting camera image: {err}"}

        # Encode image to base64
        encoded = base64.b64encode(image.content).decode("utf-8")
        mime_type = image.content_type or "image/jpeg"
        data_url = f"data:{mime_type};base64,{encoded}"

        # Find the SmartChain client
        client = _find_client(hass, entity_id)
        if not client:
            return {"response": "No SmartChain agent available."}

        # Build multimodal message
        multimodal_content = [
            {"type": "text", "text": message},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]

        try:
            result = await client.ainvoke([HumanMessage(content=multimodal_content)])
            return {"response": result.content}
        except Exception as err:
            LOGGER.exception("SmartChain analyze_image error: %s", err)
            return {"response": f"Error: {err}"}

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
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Initialize SmartChain."""
    engine = entry.data.get(CONF_ENGINE) or ID_GIGACHAT

    entry.async_on_unload(entry.add_update_listener(update_listener))

    # Build clients: one per subentry, or one from legacy options
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
        # Legacy mode: single client from entry.options
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
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
