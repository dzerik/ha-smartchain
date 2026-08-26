"""The preset tool catalogue — a set the user switches on rather than builds.

A preset is not a new kind of object. It is a `tool` subentry the integration
already knows how to create, described here as data so that enabling one is a
single write through the very path `smartchain/tool/save` and the tools.yaml
importer already use. Once written it is an ordinary tool: editable,
disableable, deletable, and indistinguishable from one built in the form.

**Composed, not YAML text.** `action` and `parameters` are the exact dicts a
`tool` subentry stores, so installing a preset needs no parser and no second
validator — `tests/test_tool_presets.py` holds every entry to `TOOL_SCHEMA`,
the same schema tools.yaml passes through, so a catalogue that would produce an
unusable tool fails in the test suite rather than in front of the model.

**What the catalogue deliberately does not contain.** Home Assistant's own
Assist API already turns things on and off, sets lights and climate and adds to
lists; our own built-ins already cover history, entity search, memory search and
agent delegation. A preset that competed with either would give the model two
ways to do one thing and make both worse. So every entry below is something
neither of them can do.

**Two languages, one split.** `description` is what the model reads to decide
whether to call the tool, so it is English here and stays English — that is what
the providers are trained on, and it is not a UI string. The panel-facing name
and blurb are translations, under `config_panel.presets.<name>` in strings.json;
see `websocket_api.async_preset_texts`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PresetTool:
    """One catalogue entry: everything a `tool` subentry needs, minus its id.

    `name` becomes the subentry title (the tool name — the convention every
    subentry type here follows), `description` / `parameters` / `action` become
    the subentry data verbatim.
    """

    name: str
    description: str
    parameters: dict[str, Any]
    action: dict[str, Any]

    @property
    def action_type(self) -> str:
        """The action's type, for the catalogue listing."""
        return str(self.action.get("type", ""))


# Ordered as the panel shows them: the ones that answer a question first, the
# one that acts on the house last.
PRESET_TOOLS: tuple[PresetTool, ...] = (
    PresetTool(
        name="weather_forecast",
        # Assist reports current conditions; it cannot answer "will it rain
        # tomorrow afternoon".
        description=(
            "Get the weather forecast for the coming days or hours. Use for questions "
            "about future weather, not current conditions."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Weather entity, e.g. weather.home"},
                "type": {
                    "type": "string",
                    "enum": ["daily", "hourly"],
                    "description": "Forecast granularity",
                },
            },
            "required": ["entity", "type"],
        },
        action={
            "type": "service",
            "domain": "weather",
            "service": "get_forecasts",
            "target": {"entity_id": "{{ entity }}"},
            "data": {"type": "{{ type }}"},
            # weather.get_forecasts is SupportsResponse.ONLY — the forecast is
            # the response, so this is not optional.
            "response": True,
        },
    ),
    PresetTool(
        name="sun_times",
        description=(
            "Today's sunrise, sunset, dawn and dusk times, and whether the sun is currently up."
        ),
        parameters={"type": "object", "properties": {}},
        action={
            "type": "template",
            "value_template": (
                "{% set s = states.sun.sun %}\n"
                "Sun is {{ s.state }}.\n"
                "Next dawn: {{ s.attributes.next_dawn }}.\n"
                "Next sunrise: {{ s.attributes.next_rising }}.\n"
                "Next sunset: {{ s.attributes.next_setting }}.\n"
                "Next dusk: {{ s.attributes.next_dusk }}."
            ),
        },
    ),
    PresetTool(
        name="calendar_events",
        # The agent otherwise has no idea what is planned.
        description=(
            "List calendar events in a date range. Use for questions about what is "
            "planned, scheduled or booked."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "Calendar entity, e.g. calendar.family",
                },
                "days": {
                    "type": "integer",
                    "description": "How many days ahead to look, from now",
                },
            },
            "required": ["entity", "days"],
        },
        action={
            "type": "service",
            "domain": "calendar",
            "service": "get_events",
            "target": {"entity_id": "{{ entity }}"},
            "data": {
                "start_date_time": "{{ now().isoformat() }}",
                "end_date_time": "{{ (now() + timedelta(days=days)).isoformat() }}",
            },
            "response": True,
        },
    ),
    PresetTool(
        name="todo_list_items",
        # Assist can add to a list but cannot read one back.
        description=(
            "Read the items on a to-do or shopping list. Use when asked what is on a "
            "list, not to add to it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Todo entity, e.g. todo.shopping_list"},
                "status": {
                    "type": "string",
                    "enum": ["needs_action", "completed"],
                    "description": "Which items",
                },
            },
            "required": ["entity"],
        },
        action={
            "type": "service",
            "domain": "todo",
            "service": "get_items",
            "target": {"entity_id": "{{ entity }}"},
            # `status` is optional, so the template must survive it being
            # undefined — which is exactly what `default()` is for.
            "data": {"status": "{{ status | default('needs_action') }}"},
            "response": True,
        },
    ),
    PresetTool(
        name="area_summary",
        # "What is on in the kitchen" in one call, instead of the model
        # guessing entity names one at a time.
        description=(
            "Summarise what is currently on or active in one area of the home. Use for "
            "questions about a room as a whole."
        ),
        parameters={
            "type": "object",
            "properties": {
                "area": {"type": "string", "description": "Area name or id, e.g. kitchen"},
            },
            "required": ["area"],
        },
        action={
            "type": "template",
            "value_template": (
                "{% set ids = area_entities(area) %}\n"
                "{% if ids | count == 0 %}\n"
                "No area named {{ area }}.\n"
                "{% else %}\n"
                "{% for e in ids %}\n"
                "{%- if states(e) not in ['unavailable', 'unknown'] %}\n"
                "{{ state_attr(e, 'friendly_name') or e }}: {{ states(e) }}\n"
                "{%- endif %}\n"
                "{%- endfor %}\n"
                "{% endif %}"
            ),
        },
    ),
    PresetTool(
        name="who_is_home",
        description="Who is currently home and who is away.",
        parameters={"type": "object", "properties": {}},
        action={
            "type": "template",
            "value_template": (
                "{% for p in states.person %}\n"
                "{{ p.attributes.friendly_name or p.name }}: {{ p.state }}\n"
                "{%- endfor %}"
            ),
        },
    ),
    PresetTool(
        name="look_at_camera",
        # The integration can already analyse a camera on a schedule; this lets
        # the agent do it mid-conversation, when asked.
        description=(
            "Look at a camera right now and describe what is visible. Use when asked "
            "what is happening somewhere the camera can see."
        ),
        parameters={
            "type": "object",
            "properties": {
                "camera_entity_id": {
                    "type": "string",
                    "description": "Camera entity, e.g. camera.front_door",
                },
                "message": {"type": "string", "description": "What to look for"},
            },
            "required": ["camera_entity_id", "message"],
        },
        action={
            "type": "service",
            "domain": "smartchain",
            "service": "analyze_image",
            # Empty, and written down rather than omitted: `compose_tool_action`
            # always composes all six keys, so a preset that left one out came
            # back with it added the first time the tool was opened and saved.
            # Spelling them makes an installed preset byte-identical to the same
            # tool built in the form.
            "target": {},
            "data": {
                "camera_entity_id": "{{ camera_entity_id }}",
                "message": "{{ message }}",
            },
            # smartchain.analyze_image is SupportsResponse.ONLY.
            "response": True,
        },
    ),
    PresetTool(
        name="notify_device",
        # Lets the agent reach the user rather than only answer them.
        description=(
            "Send a notification to a specific device or person. Use when asked to "
            "remind, alert or tell someone something."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "Notify entity, e.g. notify.mobile_app_phone",
                },
                "message": {"type": "string", "description": "The message text"},
                "title": {"type": "string", "description": "Optional title"},
            },
            "required": ["entity", "message"],
        },
        action={
            "type": "service",
            "domain": "notify",
            "service": "send_message",
            "target": {"entity_id": "{{ entity }}"},
            "data": {
                "message": "{{ message }}",
                "title": "{{ title | default('') }}",
            },
            # notify.send_message returns nothing; spelled for the same
            # round-trip reason as `look_at_camera`'s empty target.
            "response": False,
        },
    ),
)

PRESETS_BY_NAME: dict[str, PresetTool] = {preset.name: preset for preset in PRESET_TOOLS}


def preset_subentry_data(preset: PresetTool) -> dict[str, Any]:
    """The `tool` subentry data for one preset, minus its `params_mode`.

    Deep-copied on the way out: the catalogue is module-level state shared by
    every install, and handing a caller the live dict would let one edited tool
    rewrite the preset for the next installation.

    `params_mode` is form state — which editor to reopen — so it is *derived*
    at the call site by the same `_params_mode_for` the tools.yaml importer
    uses, rather than being written down twice. Two entries here
    (`weather_forecast`, `todo_list_items`) declare an `enum`, which the rows
    editor cannot express, so they land in the JSON editor and keep it.
    """
    import copy

    return {
        "description": preset.description,
        "parameters": copy.deepcopy(preset.parameters),
        "action": copy.deepcopy(preset.action),
        "enabled": True,
    }
