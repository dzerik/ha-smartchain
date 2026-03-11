"""The SmartChain integration."""

import asyncio
import base64
import logging
import re
import uuid
from pathlib import Path

import voluptuous as vol
import yaml
from homeassistant.components.camera import async_get_image
from homeassistant.components.frontend import async_register_built_in_panel
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from langchain_core.messages import HumanMessage

from .client_util import get_client
from .const import (
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENGINE,
    CONF_MAX_TOKENS,
    CONF_TEMPERATURE,
    DEFAULT_DEVICES_PROMPT,
    DEFAULT_TEMPERATURE,
    DOMAIN,
    GENERATE_PROMPTS,
    ID_GIGACHAT,
    IMPROVE_YAML_PROMPT,
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

VALID_GEN_TYPES = ["automation", "script", "scene", "blueprint"]

SERVICE_GENERATE_AUTOMATION = "generate_automation"
SERVICE_GENERATE_AUTOMATION_SCHEMA = vol.Schema(
    {
        vol.Required("description"): str,
        vol.Optional("entity_id"): str,
        vol.Optional("deploy", default=False): bool,
        vol.Optional("entity_ids"): [str],
        vol.Optional("type", default="automation"): vol.In(VALID_GEN_TYPES),
        vol.Optional("source_yaml"): str,
    }
)

SERVICE_DEPLOY_AUTOMATION = "deploy_automation"
SERVICE_DEPLOY_AUTOMATION_SCHEMA = vol.Schema(
    {
        vol.Required("automation_yaml"): str,
        vol.Optional("type", default="automation"): vol.In(VALID_GEN_TYPES),
    }
)

SERVICE_VALIDATE_AUTOMATION = "validate_automation"
SERVICE_VALIDATE_AUTOMATION_SCHEMA = vol.Schema(
    {
        vol.Required("automation_yaml"): str,
        vol.Optional("type", default="automation"): vol.In(VALID_GEN_TYPES),
    }
)

SERVICE_LIST_YAML = "list_yaml"
SERVICE_LIST_YAML_SCHEMA = vol.Schema(
    {
        vol.Optional("type"): vol.In(VALID_GEN_TYPES),
    }
)

SERVICE_GET_YAML = "get_yaml"
SERVICE_GET_YAML_SCHEMA = vol.Schema(
    {
        vol.Required("type"): vol.In(VALID_GEN_TYPES),
        vol.Required("id"): vol.All(str, vol.Match(r"^[a-zA-Z0-9_./\- ]+$")),
    }
)

YAML_FILE_MAP = {
    "automation": "automations.yaml",
    "script": "scripts.yaml",
    "scene": "scenes.yaml",
}

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


def _collect_ha_context(
    hass: HomeAssistant,
    selected_entity_ids: list[str] | None = None,
) -> str:
    """Collect HA context for the generation prompt.

    Without selected_entity_ids: renders DEFAULT_DEVICES_PROMPT via HA Jinja2
    template engine (same mechanism as conversation agent system prompt).
    With selected_entity_ids: compact list of only the selected entities.
    """
    if not selected_entity_ids:
        # Use standard HA Jinja2 template — same as conversation agent
        try:
            tpl = Template(DEFAULT_DEVICES_PROMPT, hass)
            return tpl.async_render()
        except Exception:
            LOGGER.debug("Failed to render devices template, falling back")
            return "No entity context available."

    # Selected entities — compact format
    lines = ["Selected Home Assistant entities:"]
    for eid in selected_entity_ids:
        state = hass.states.get(eid)
        if not state or state.state in ("unavailable", "unknown"):
            continue
        friendly = state.attributes.get("friendly_name", "")
        unit = state.attributes.get("unit_of_measurement", "")
        line = f"  - {eid}"
        if friendly:
            line += f" ({friendly})"
        line += f" = {state.state}"
        if unit:
            line += f" {unit}"
        lines.append(line)
    return "\n".join(lines) if len(lines) > 1 else "No entities available."


def _validate_automation_config(
    hass: HomeAssistant, yaml_text: str, gen_type: str = "automation"
) -> dict:
    """Validate YAML structure and entity references for any generation type."""
    errors: list[str] = []
    warnings: list[str] = []

    # Parse YAML
    try:
        config = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        return {"valid": False, "errors": [f"Invalid YAML syntax: {exc}"], "warnings": []}

    if not isinstance(config, dict):
        return {
            "valid": False,
            "errors": ["YAML must be a mapping (dict), not a list or scalar."],
            "warnings": [],
        }

    # Type-specific structure checks
    if gen_type == "automation":
        has_trigger = "trigger" in config or "triggers" in config
        has_action = "action" in config or "actions" in config
        if not has_trigger:
            errors.append("Missing required key: 'trigger' or 'triggers'")
        if not has_action:
            errors.append("Missing required key: 'action' or 'actions'")
        if "alias" not in config:
            warnings.append("Missing 'alias' — automation will be unnamed")

    elif gen_type == "script":
        has_sequence = "sequence" in config
        if not has_sequence:
            errors.append("Missing required key: 'sequence'")
        if "alias" not in config:
            warnings.append("Missing 'alias' — script will be unnamed")

    elif gen_type == "scene":
        has_entities = "entities" in config
        if not has_entities:
            errors.append("Missing required key: 'entities'")
        if "name" not in config:
            warnings.append("Missing 'name' — scene will be unnamed")

    elif gen_type == "blueprint":
        if "blueprint" not in config:
            errors.append("Missing required key: 'blueprint'")
        else:
            bp = config["blueprint"]
            if not isinstance(bp, dict):
                errors.append("'blueprint' must be a mapping")
            else:
                if "name" not in bp:
                    warnings.append("Missing 'blueprint.name'")
                if "domain" not in bp:
                    errors.append("Missing required key: 'blueprint.domain'")
                if "input" not in bp:
                    warnings.append("Missing 'blueprint.input' — no configurable inputs")

    # Collect all entity_id references from the config
    referenced_entities = set()
    _extract_entity_ids(config, referenced_entities)

    # Check if referenced entities exist
    existing_entities = {s.entity_id for s in hass.states.async_all()}
    for eid in sorted(referenced_entities):
        if eid not in existing_entities:
            # Check if it's a valid-looking entity_id (domain.object_id)
            if re.match(r"^[a-z_]+\.[a-z0-9_]+$", eid):
                errors.append(f"Entity '{eid}' does not exist in Home Assistant")

    # Check service calls
    _validate_services(config, hass, errors)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def _extract_entity_ids(obj: object, result: set[str]) -> None:
    """Recursively extract entity_id values from a config dict."""
    if isinstance(obj, dict):
        for key, val in obj.items():
            if key == "entity_id":
                if isinstance(val, str):
                    result.add(val)
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, str):
                            result.add(item)
            elif key == "target" and isinstance(val, dict):
                _extract_entity_ids(val, result)
            else:
                _extract_entity_ids(val, result)
    elif isinstance(obj, list):
        for item in obj:
            _extract_entity_ids(item, result)


def _validate_services(obj: object, hass: HomeAssistant, errors: list[str]) -> None:
    """Check that service calls reference valid domains."""
    if isinstance(obj, dict):
        svc = obj.get("service") or obj.get("action")
        if isinstance(svc, str) and "." in svc:
            domain = svc.split(".")[0]
            if not hass.services.has_service(domain, svc.split(".", 1)[1]):
                errors.append(f"Service '{svc}' is not registered in Home Assistant")
        for val in obj.values():
            _validate_services(val, hass, errors)
    elif isinstance(obj, list):
        for item in obj:
            _validate_services(item, hass, errors)


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

    async def _generate_automation_yaml(
        client,
        description: str,
        entity_ids: list[str] | None = None,
        gen_type: str = "automation",
        source_yaml: str | None = None,
    ) -> str:
        """Generate or improve YAML from natural language description."""
        ha_context = _collect_ha_context(hass, entity_ids or None)

        if source_yaml:
            # Improve existing YAML mode
            prompt = IMPROVE_YAML_PROMPT.format(
                description=description,
                ha_context=ha_context,
                source_yaml=source_yaml,
            )
        else:
            # Generate new YAML mode
            prompt_template = GENERATE_PROMPTS.get(gen_type, GENERATE_PROMPTS["automation"])
            prompt = prompt_template.format(
                description=description,
                ha_context=ha_context,
            )

        result = await client.ainvoke([HumanMessage(content=prompt)])
        yaml_text = result.content.strip()
        # Strip markdown code fences if LLM wraps output
        if yaml_text.startswith("```"):
            lines = yaml_text.split("\n")
            lines = [line for line in lines if not line.startswith("```")]
            yaml_text = "\n".join(lines).strip()
        return yaml_text

    _deploy_lock = asyncio.Lock()

    async def _deploy_automation_to_ha(yaml_text: str, gen_type: str = "automation") -> dict:
        """Deploy YAML to HA (automations.yaml, scripts.yaml, scenes.yaml, or blueprints/)."""
        config = yaml.safe_load(yaml_text)
        if not isinstance(config, dict):
            return {"error": "Generated YAML is not a valid object."}

        if gen_type == "blueprint":
            return await _deploy_blueprint(config, yaml_text)

        config["id"] = uuid.uuid4().hex

        file_map = {
            "automation": "automations.yaml",
            "script": "scripts.yaml",
            "scene": "scenes.yaml",
        }
        reload_domain = {
            "automation": "automation",
            "script": "script",
            "scene": "scene",
        }

        target_file = hass.config.path(file_map.get(gen_type, "automations.yaml"))
        domain = reload_domain.get(gen_type, "automation")

        def _write():
            existing = []
            try:
                with open(target_file, encoding="utf-8") as f:
                    content = yaml.safe_load(f)
                    if isinstance(content, list):
                        existing = content
            except FileNotFoundError:
                pass
            existing.append(config)
            with open(target_file, "w", encoding="utf-8") as f:
                yaml.dump(
                    existing,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

        async with _deploy_lock:
            await hass.async_add_executor_job(_write)

        # Reload — register service if not available (test env)
        if hass.services.has_service(domain, "reload"):
            await hass.services.async_call(domain, "reload", blocking=True)

        alias = config.get("alias") or config.get("name") or "Unnamed"
        return {"deployed": True, "automation_id": config["id"], "alias": alias}

    async def _deploy_blueprint(config: dict, yaml_text: str) -> dict:
        """Deploy a blueprint YAML file to blueprints/automation/smartchain/."""
        bp_meta = config.get("blueprint", {})
        alias = bp_meta.get("name", "unnamed_blueprint")
        # Slug-ify the name
        slug = re.sub(r"[^a-z0-9_]", "_", alias.lower().strip()).strip("_")
        if not slug:
            slug = uuid.uuid4().hex[:8]

        bp_dir = Path(hass.config.path("blueprints", "automation", "smartchain"))

        def _write():
            bp_dir.mkdir(parents=True, exist_ok=True)
            bp_path = bp_dir / f"{slug}.yaml"
            with open(bp_path, "w", encoding="utf-8") as f:
                f.write(yaml_text)
            return str(bp_path)

        async with _deploy_lock:
            bp_path = await hass.async_add_executor_job(_write)
        return {"deployed": True, "alias": alias, "blueprint_path": bp_path}

    def _list_yaml_items(gen_type: str | None = None) -> list[dict]:
        """List all YAML items (automations, scripts, scenes, blueprints)."""
        items: list[dict] = []
        types = [gen_type] if gen_type else list(YAML_FILE_MAP.keys()) + ["blueprint"]

        for t in types:
            if t == "blueprint":
                bp_dir = Path(hass.config.path("blueprints", "automation"))
                if bp_dir.is_dir():
                    for bp_file in sorted(bp_dir.rglob("*.yaml")):
                        try:
                            with open(bp_file, encoding="utf-8") as f:
                                data = yaml.safe_load(f)
                            bp_meta = data.get("blueprint", {}) if isinstance(data, dict) else {}
                            rel = str(bp_file.relative_to(bp_dir))
                            items.append(
                                {
                                    "id": rel,
                                    "alias": bp_meta.get("name", bp_file.stem),
                                    "type": "blueprint",
                                }
                            )
                        except Exception:
                            pass
            elif t in YAML_FILE_MAP:
                path = hass.config.path(YAML_FILE_MAP[t])
                try:
                    with open(path, encoding="utf-8") as f:
                        data = yaml.safe_load(f)
                    if isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and item.get("id"):
                                entry = {
                                    "id": item["id"],
                                    "alias": item.get("alias") or item.get("name", "Unnamed"),
                                    "type": t,
                                }
                                # Mark blueprint-based automations
                                if "use_blueprint" in item:
                                    bp = item["use_blueprint"]
                                    entry["blueprint_based"] = True
                                    if isinstance(bp, dict):
                                        entry["blueprint_path"] = bp.get("path", "")
                                items.append(entry)
                except FileNotFoundError:
                    pass
        return items

    def _get_yaml_item(gen_type: str, item_id: str) -> str | None:
        """Get YAML content for a specific item by type and id."""
        if gen_type == "blueprint":
            bp_base = Path(hass.config.path("blueprints", "automation"))
            bp_path = (bp_base / item_id).resolve()
            # Prevent path traversal — resolved path must be under bp_base
            if not str(bp_path).startswith(str(bp_base.resolve())):
                LOGGER.warning("Path traversal attempt blocked: %s", item_id)
                return None
            if not bp_path.is_file():
                return None
            with open(bp_path, encoding="utf-8") as f:
                return f.read()

        if gen_type not in YAML_FILE_MAP:
            return None
        path = hass.config.path(YAML_FILE_MAP[gen_type])
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            return None
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("id") == item_id:
                    return yaml.dump(
                        item,
                        default_flow_style=False,
                        allow_unicode=True,
                        sort_keys=False,
                    )
        return None

    async def _handle_list_yaml(call: ServiceCall) -> ServiceResponse:
        """Handle smartchain.list_yaml service call."""
        gen_type = call.data.get("type")
        items = await hass.async_add_executor_job(_list_yaml_items, gen_type)
        return {"items": items}

    async def _handle_get_yaml(call: ServiceCall) -> ServiceResponse:
        """Handle smartchain.get_yaml service call."""
        gen_type = call.data["type"]
        item_id = call.data["id"]
        yaml_text = await hass.async_add_executor_job(_get_yaml_item, gen_type, item_id)
        if yaml_text is None:
            return {"error": f"Item '{item_id}' not found", "yaml": ""}
        return {"yaml": yaml_text, "type": gen_type, "id": item_id}

    async def _handle_validate_automation(call: ServiceCall) -> ServiceResponse:
        """Handle smartchain.validate_automation service call."""
        yaml_text = call.data["automation_yaml"]
        gen_type = call.data.get("type", "automation")
        return _validate_automation_config(hass, yaml_text, gen_type)

    async def _handle_generate_automation(call: ServiceCall) -> ServiceResponse:
        """Handle smartchain.generate_automation service call."""
        description = call.data["description"]
        entity_id = call.data.get("entity_id")
        deploy = call.data.get("deploy", False)
        selected_entity_ids = call.data.get("entity_ids")
        gen_type = call.data.get("type", "automation")
        source_yaml = call.data.get("source_yaml")

        client = _find_client(hass, entity_id)
        if not client:
            return {"automation_yaml": "", "error": "No SmartChain agent available."}

        try:
            yaml_text = await _generate_automation_yaml(
                client, description, selected_entity_ids, gen_type, source_yaml
            )
        except Exception as err:
            LOGGER.exception("SmartChain generate_automation error: %s", err)
            return {"automation_yaml": "", "error": str(err)}

        response: dict = {"automation_yaml": yaml_text}

        if deploy:
            try:
                validation = _validate_automation_config(hass, yaml_text, gen_type)
                if not validation["valid"]:
                    response["error"] = "Validation failed: " + "; ".join(validation["errors"])
                    response["validation"] = validation
                    return response
                deploy_result = await _deploy_automation_to_ha(yaml_text, gen_type)
                response.update(deploy_result)
            except Exception as err:
                LOGGER.exception("SmartChain deploy_automation error: %s", err)
                response["error"] = f"Generated OK but deploy failed: {err}"

        return response

    # Register sidebar panel (graceful — skip if frontend not available)
    try:
        panel_dir = Path(__file__).parent / "panel"
        from homeassistant.components.http import StaticPathConfig

        await hass.http.async_register_static_paths(
            [StaticPathConfig("/smartchain", str(panel_dir), False)]
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
                    "module_url": "/smartchain/smartchain-panel.js",
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
        gen_type = call.data.get("type", "automation")

        # Validate before deploying
        validation = _validate_automation_config(hass, yaml_text, gen_type)
        if not validation["valid"]:
            return {
                "error": "Validation failed: " + "; ".join(validation["errors"]),
                "validation": validation,
            }

        try:
            result = await _deploy_automation_to_ha(yaml_text, gen_type)
            result["validation"] = validation
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
    hass.services.async_register(
        DOMAIN,
        SERVICE_VALIDATE_AUTOMATION,
        _handle_validate_automation,
        schema=SERVICE_VALIDATE_AUTOMATION_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LIST_YAML,
        _handle_list_yaml,
        schema=SERVICE_LIST_YAML_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_YAML,
        _handle_get_yaml,
        schema=SERVICE_GET_YAML_SCHEMA,
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
