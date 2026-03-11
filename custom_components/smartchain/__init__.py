"""The SmartChain integration."""

import base64
import logging
import uuid
from pathlib import Path

import voluptuous as vol
import yaml
from homeassistant.components.camera import async_get_image
from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.util import dt as dt_util
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
    GENERATE_AUTOMATION_PROMPT,
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
        vol.Optional("notify_entity"): str,
    }
)

SERVICE_GENERATE_AUTOMATION = "generate_automation"
SERVICE_GENERATE_AUTOMATION_SCHEMA = vol.Schema(
    {
        vol.Required("description"): str,
        vol.Optional("entity_id"): str,
        vol.Optional("deploy", default=False): bool,
    }
)

SERVICE_DEPLOY_AUTOMATION = "deploy_automation"
SERVICE_DEPLOY_AUTOMATION_SCHEMA = vol.Schema(
    {
        vol.Required("automation_yaml"): str,
    }
)

SENSOR_LAST_ANALYSIS = f"sensor.{DOMAIN}_last_analysis"
EVENT_IMAGE_ANALYZED = f"{DOMAIN}_image_analyzed"


def _find_client(hass: HomeAssistant, entity_id: str | None = None):
    """Find a SmartChain LLM client, optionally matching entity_id."""
    # First pass: try to match entity_id if provided
    if entity_id:
        for entry in hass.config_entries.async_entries(DOMAIN):
            if entry.runtime_data is None:
                continue
            if isinstance(entry.runtime_data, dict):
                for sub_id, c in entry.runtime_data.items():
                    uid = f"{entry.entry_id}_{sub_id}"
                    if entity_id.endswith(uid):
                        return c

    # Fallback: return first available client
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.runtime_data is None:
            continue
        if isinstance(entry.runtime_data, dict):
            for _sub_id, c in entry.runtime_data.items():
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
            response_text = result.content
        except Exception as err:
            LOGGER.exception("SmartChain analyze_image error: %s", err)
            return {"response": f"Error: {err}"}

        now = dt_util.utcnow().isoformat()
        event_data = {
            "response": response_text,
            "camera_entity_id": camera_entity_id,
            "message": message,
            "timestamp": now,
        }

        # 1. Fire event
        hass.bus.async_fire(EVENT_IMAGE_ANALYZED, event_data)

        # 2. Update sensor
        hass.states.async_set(
            SENSOR_LAST_ANALYSIS,
            response_text[:255],
            {
                "camera_entity_id": camera_entity_id,
                "message": message,
                "full_response": response_text,
                "timestamp": now,
                "friendly_name": "SmartChain Last Analysis",
                "icon": "mdi:camera-iris",
            },
        )

        # 3. Send notification (optional)
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

    async def _generate_automation_yaml(client, description: str) -> str:
        """Generate automation YAML from natural language description."""
        prompt = GENERATE_AUTOMATION_PROMPT.format(description=description)
        result = await client.ainvoke([HumanMessage(content=prompt)])
        yaml_text = result.content.strip()
        # Strip markdown code fences if LLM wraps output
        if yaml_text.startswith("```"):
            lines = yaml_text.split("\n")
            lines = [line for line in lines if not line.startswith("```")]
            yaml_text = "\n".join(lines).strip()
        return yaml_text

    async def _deploy_automation_to_ha(yaml_text: str) -> dict:
        """Deploy automation YAML to HA via automations.yaml."""
        config = yaml.safe_load(yaml_text)
        if not isinstance(config, dict):
            return {"error": "Generated YAML is not a valid automation object."}

        config["id"] = uuid.uuid4().hex

        automations_path = hass.config.path("automations.yaml")

        def _write_automation():
            # Read existing automations
            existing = []
            try:
                with open(automations_path, encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, list):
                        existing = content
            except FileNotFoundError:
                pass

            # Append new automation
            existing.append(config)

            # Write back
            with open(automations_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    existing,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

        await hass.async_add_executor_job(_write_automation)
        await hass.services.async_call("automation", "reload", blocking=True)

        alias = config.get("alias", "Unnamed")
        return {"deployed": True, "automation_id": config["id"], "alias": alias}

    async def _handle_generate_automation(call: ServiceCall) -> ServiceResponse:
        """Handle smartchain.generate_automation service call."""
        description = call.data["description"]
        entity_id = call.data.get("entity_id")
        deploy = call.data.get("deploy", False)

        client = _find_client(hass, entity_id)
        if not client:
            return {"automation_yaml": "", "error": "No SmartChain agent available."}

        try:
            yaml_text = await _generate_automation_yaml(client, description)
        except Exception as err:
            LOGGER.exception("SmartChain generate_automation error: %s", err)
            return {"automation_yaml": "", "error": str(err)}

        response: dict = {"automation_yaml": yaml_text}

        if deploy:
            try:
                deploy_result = await _deploy_automation_to_ha(yaml_text)
                response.update(deploy_result)
            except Exception as err:
                LOGGER.exception("SmartChain deploy_automation error: %s", err)
                response["error"] = f"Generated OK but deploy failed: {err}"

        return response

    # Register sidebar panel (graceful — skip if frontend not available)
    try:
        panel_dir = Path(__file__).parent / "panel"
        from homeassistant.components.http import StaticPathConfig

        panel_path = str(panel_dir / "smartchain-panel.js")
        await hass.http.async_register_static_paths(
            [StaticPathConfig("/smartchain/panel.js", panel_path, False)]
        )
        async_register_built_in_panel(
            hass,
            component_name="custom",
            sidebar_title="SmartChain AI",
            sidebar_icon="mdi:robot",
            frontend_url_path="smartchain",
            config={
                "_panel_custom": {
                    "name": "smartchain-panel",
                    "module_url": "/smartchain/panel.js",
                }
            },
        )
    except Exception:
        LOGGER.debug("Could not register SmartChain panel (frontend not available)")

    # Store helpers for use by Options Flow wizard
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["generate_yaml"] = _generate_automation_yaml
    hass.data[DOMAIN]["deploy_automation"] = _deploy_automation_to_ha
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
    hass.services.async_register(
        DOMAIN,
        SERVICE_GENERATE_AUTOMATION,
        _handle_generate_automation,
        schema=SERVICE_GENERATE_AUTOMATION_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    async def _handle_deploy_automation(call: ServiceCall) -> ServiceResponse:
        """Handle smartchain.deploy_automation — deploy raw YAML to HA."""
        yaml_text = call.data["automation_yaml"]
        try:
            result = await _deploy_automation_to_ha(yaml_text)
            return result
        except Exception as err:
            LOGGER.exception("SmartChain deploy_automation error: %s", err)
            return {"error": str(err)}

    hass.services.async_register(
        DOMAIN,
        SERVICE_DEPLOY_AUTOMATION,
        _handle_deploy_automation,
        schema=SERVICE_DEPLOY_AUTOMATION_SCHEMA,
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
