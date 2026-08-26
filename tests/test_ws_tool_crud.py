"""The tool constructor over the panel's websocket API.

Three things are being established here.

**That it is a constructor, not an editor.** The whole form — every field, its
selector, and which two fields reshape it — is serialised by
`smartchain/tool/schema`, so the panel declares no field name of its own. A
test that reads a field name out of the served schema is therefore also a test
that the panel does not have to know it.

**That both sources produce one tool.** A tool saved here reaches the registry
as the same `CustomTool` the equivalent tools.yaml produces, and a name defined
in both resolves in favour of the editable one.

**That nothing leaks.** A REST header can hold a bearer token and a service
action's data can hold anything; `.storage` now holds both. No `tool/*` result
may carry one back, and no error message may be built from a submitted value.
"""

import json
from pathlib import Path

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_OPENAI,
    RESERVED_TOOL_NAMES,
    SUBENTRY_TYPE_TOOL,
    UNIQUE_ID_OPENAI,
)
from tests.conftest import BUILT_IN_TOOL_NAMES

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

PROVIDER_SECRET = "sk-provider-secret"
HEADER_SECRET = "Bearer must-not-come-back"


@pytest.fixture
def tools_dir(hass: HomeAssistant, tmp_path_factory) -> Path:
    """A writable config dir, set before setup runs its first tools.yaml load."""
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    hass.config.config_dir = str(cdir)
    return cdir / "smartchain"


async def _entry(hass: HomeAssistant, subentries=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: PROVIDER_SECRET},
        subentries_data=subentries or [],
        minor_version=2,
    )
    entry.add_to_hass(hass)
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return entry


def _tool_subentry(title: str, data: dict) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=data, subentry_type=SUBENTRY_TYPE_TOOL, title=title, unique_id=None
    )


SIMPLE_TOOL = {
    "name": "porch_light",
    "description": "Turn the porch light on.",
    "enabled": True,
    "action_type": "service",
    "params_mode": "simple",
    "params_rows": [],
    "service": "light.turn_on",
    # TargetSelector normalises a bare entity id into a list — the shape
    # `hass.services.async_call(target=...)` wants, and the shape every
    # assertion below therefore expects.
    "target": {"entity_id": ["light.porch"]},
    "service_data": {},
    "response": False,
}


# --- the served schema ---------------------------------------------------


async def test_the_backend_serialises_the_whole_form(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Every field the panel renders comes from here, `reactive` included."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tool/schema", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert msg["success"]

    names = [field["name"] for field in msg["result"]["schema"]]
    assert names[:5] == ["name", "description", "enabled", "action_type", "params_mode"]
    assert msg["result"]["reactive"] == ["action_type", "params_mode"]
    # The arguments editor is a repeating-row object selector, not a textarea:
    # that is what makes "minimal manual typing" true for the common case.
    rows = next(field for field in msg["result"]["schema"] if field["name"] == "params_rows")
    assert rows["selector"]["object"]["multiple"] is True
    assert set(rows["selector"]["object"]["fields"]) == {
        "name",
        "type",
        "description",
        "required",
    }


@pytest.mark.parametrize(
    "action_type,expected",
    [
        ("service", {"service", "target", "service_data", "response"}),
        ("template", {"value_template"}),
        ("rest", {"method", "url", "headers", "payload", "timeout", "response_format"}),
        ("script", {"script", "variables"}),
    ],
)
async def test_the_form_reshapes_around_the_action_type(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path, action_type, expected
):
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/schema",
            "entry_id": entry.entry_id,
            "data": {"action_type": action_type},
        }
    )
    msg = await client.receive_json()
    names = {field["name"] for field in msg["result"]["schema"]}
    assert expected <= names
    # And only this action type's fields: a template tool that could still
    # submit a `url` would be rejected by the action validator instead, after
    # the user had already typed it.
    others = set().union(
        {"service", "target", "service_data", "response"},
        {"value_template"},
        {"method", "url", "headers", "payload", "timeout", "response_format"},
        {"script", "variables"},
    )
    assert names & others == expected


async def test_the_service_field_is_a_picker_over_registered_actions(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """ "Pick a service, don't type one." Home Assistant removed its `service`
    selector before 2026.8, so the picker is a select fed from the live service
    registry — with custom_value so an action from an unloaded integration is
    still reachable."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tool/schema", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    field = next(f for f in msg["result"]["schema"] if f["name"] == "service")
    options = [option["value"] for option in field["selector"]["select"]["options"]]
    assert f"{DOMAIN}.reload_tools" in options
    assert field["selector"]["select"]["custom_value"] is True


# --- saving --------------------------------------------------------------


async def test_a_saved_tool_reaches_the_registry(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "smartchain/tool/save", "entry_id": entry.entry_id, "data": SIMPLE_TOOL}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["reload_error"] is None

    registry = hass.data[DOMAIN]["tools"]
    tool = registry.get("porch_light")
    assert tool is not None
    assert tool.action.domain == "light"
    assert tool.action.service == "turn_on"
    assert tool.action.target == {"entity_id": ["light.porch"]}


@pytest.mark.parametrize(
    "overrides,check",
    [
        (
            {"action_type": "template", "value_template": "{{ 1 + 1 }}"},
            lambda tool: tool.action.value_template == "{{ 1 + 1 }}",
        ),
        (
            {
                "action_type": "rest",
                "method": "POST",
                "url": "https://example.invalid/x",
                "payload": {"a": 1},
                "timeout": 42,
                "response_format": "json",
            },
            lambda tool: (
                tool.action.method == "POST"
                and tool.action.timeout == 42
                and tool.action.response_format == "json"
                and tool.action.payload == {"a": 1}
            ),
        ),
        (
            {"action_type": "script", "script": "script.goodnight", "variables": {"a": 1}},
            lambda tool: (
                tool.action.script == "script.goodnight" and tool.action.variables == {"a": 1}
            ),
        ),
        (
            {"response": True},
            lambda tool: tool.action.response is True,
        ),
    ],
    ids=["template", "rest", "script", "service-with-response"],
)
async def test_every_action_type_round_trips(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path, overrides, check
):
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    data = {**SIMPLE_TOOL, **overrides}
    for key in ("service", "target", "service_data", "response"):
        if overrides.get("action_type", "service") != "service":
            data.pop(key, None)

    await client.send_json_auto_id(
        {"type": "smartchain/tool/save", "entry_id": entry.entry_id, "data": data}
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    assert check(hass.data[DOMAIN]["tools"].get("porch_light"))


async def test_the_rows_editor_produces_a_json_schema(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The rows are the constructor; `parameters` is what the dispatcher hands
    to `jsonschema.validate`, so the conversion has to produce the real thing."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "data": {
                **SIMPLE_TOOL,
                "params_rows": [
                    {
                        "name": "city",
                        "type": "string",
                        "description": "Which city",
                        "required": True,
                    },
                    {"name": "days", "type": "integer"},
                ],
            },
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    assert hass.data[DOMAIN]["tools"].get("porch_light").parameters == {
        "type": "object",
        "properties": {
            "city": {"type": "string", "description": "Which city"},
            "days": {"type": "integer"},
        },
        "required": ["city"],
    }


async def test_the_advanced_box_accepts_a_shape_rows_cannot_express(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    nested = {
        "type": "object",
        "properties": {"where": {"type": "object", "properties": {"lat": {"type": "number"}}}},
    }
    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "data": {
                **{k: v for k, v in SIMPLE_TOOL.items() if k != "params_rows"},
                "params_mode": "advanced",
                "params_json": json.dumps(nested),
            },
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert hass.data[DOMAIN]["tools"].get("porch_light").parameters == nested


@pytest.mark.parametrize(
    "data,expected",
    [
        (
            {"params_mode": "advanced", "params_json": "{not json", "params_rows": None},
            "does not contain valid JSON",
        ),
        (
            {"params_mode": "advanced", "params_json": '{"type": "array"}', "params_rows": None},
            "must be a JSON Schema object",
        ),
        ({"params_rows": [{"name": "has space", "type": "string"}]}, "parameter name must be"),
        (
            {"params_rows": [{"name": "a", "type": "string"}, {"name": "a", "type": "string"}]},
            "same name",
        ),
        ({"service": "not-a-service"}, "written as domain.service"),
        ({"service": ""}, "pick the Home Assistant service"),
        ({"description": ""}, "describe what the tool does"),
    ],
    ids=[
        "bad-json",
        "not-an-object",
        "bad-arg-name",
        "duplicate-arg",
        "bad-service",
        "no-service",
        "no-description",
    ],
)
async def test_a_bad_submission_is_refused_with_fixed_text(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path, data, expected
):
    """Every refusal is fixed text plus a field name — never a submitted value."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    # A `None` override drops the key: an advanced-mode submission does not
    # carry `params_rows`, and PREVENT_EXTRA would reject it before the
    # rejection under test could happen.
    submitted = {**SIMPLE_TOOL, **data}
    submitted = {key: value for key, value in submitted.items() if value is not None}

    await client.send_json_auto_id(
        {"type": "smartchain/tool/save", "entry_id": entry.entry_id, "data": submitted}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert expected in msg["error"]["message"]
    for value in data.values():
        if isinstance(value, str) and value:
            assert value not in msg["error"]["message"]
    assert hass.data[DOMAIN]["tools"].get("porch_light") is None


def test_the_reserved_set_is_exactly_the_built_ins() -> None:
    """`BUILT_IN_TOOL_NAMES` in conftest is the specification; the constant has
    to match it. Without this, shrinking the frozenset would silently shrink
    every reserved-name parametrisation instead of failing one."""
    assert RESERVED_TOOL_NAMES == frozenset(BUILT_IN_TOOL_NAMES)


@pytest.mark.parametrize("reserved", BUILT_IN_TOOL_NAMES)
async def test_every_reserved_name_is_refused(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path, reserved
):
    """Parametrised over the whole frozenset, so adding a built-in later
    cannot quietly reopen the gap — three of these six were shadowable until
    the set was completed."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "data": {**SIMPLE_TOOL, "name": reserved},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert "built-in" in msg["error"]["message"]


async def test_a_name_taken_on_the_same_entry_is_refused(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The single-entry case specifically: every embeddings collision test in
    this suite builds *two* entries, leaving this one untested until now."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    for _ in range(2):
        await client.send_json_auto_id(
            {"type": "smartchain/tool/save", "entry_id": entry.entry_id, "data": SIMPLE_TOOL}
        )
        msg = await client.receive_json()

    assert not msg["success"]
    assert "already uses this name" in msg["error"]["message"]
    assert len([s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_TOOL]) == 1


async def test_a_disabled_tool_is_stored_but_not_registered(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "data": {**SIMPLE_TOOL, "enabled": False},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert hass.data[DOMAIN]["tools"].get("porch_light") is None
    assert any(s.title == "porch_light" for s in entry.subentries.values())


# --- editing -------------------------------------------------------------


async def test_editing_serves_the_stored_values_back(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "smartchain/tool/save", "entry_id": entry.entry_id, "data": SIMPLE_TOOL}
    )
    saved = await client.receive_json()
    subentry_id = saved["result"]["subentry_id"]

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/schema",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
        }
    )
    msg = await client.receive_json()
    served = msg["result"]["data"]
    assert served["name"] == "porch_light"
    assert served["service"] == "light.turn_on"
    assert served["action_type"] == "service"
    assert served["target"] == {"entity_id": ["light.porch"]}


async def test_editing_an_advanced_tool_reopens_in_the_advanced_box(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """A schema the rows cannot represent must not open in the rows editor,
    which would silently rewrite it into something smaller."""
    nested = {
        "type": "object",
        "properties": {"where": {"type": "object", "properties": {}}},
    }
    entry = await _entry(
        hass,
        [
            _tool_subentry(
                "nested",
                {
                    "description": "x",
                    "parameters": nested,
                    "action": {"type": "template", "value_template": "x"},
                    "enabled": True,
                    # Deliberately claims `simple`: a hand-edited subentry, or
                    # one whose schema stopped being row-expressible.
                    "params_mode": "simple",
                },
            )
        ],
    )
    subentry_id = next(iter(entry.subentries))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/schema",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
        }
    )
    msg = await client.receive_json()
    assert msg["result"]["data"]["params_mode"] == "advanced"
    assert json.loads(msg["result"]["data"]["params_json"]) == nested


# --- credentials ---------------------------------------------------------


async def test_a_header_value_never_comes_back(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """A REST header is where an Authorization token goes, and it now lives in
    .storage rather than in a file the user knows is readable."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "data": {
                **{
                    k: v
                    for k, v in SIMPLE_TOOL.items()
                    if k not in ("service", "target", "service_data", "response")
                },
                "action_type": "rest",
                "method": "GET",
                "url": "https://example.invalid/x",
                "headers": {"Authorization": HEADER_SECRET},
                "payload": {},
                "timeout": 10,
                "response_format": "text",
            },
        }
    )
    saved = await client.receive_json()
    assert saved["success"], saved
    assert HEADER_SECRET not in json.dumps(saved)
    subentry_id = saved["result"]["subentry_id"]

    for message in (
        {"type": "smartchain/tool/schema", "entry_id": entry.entry_id, "subentry_id": subentry_id},
        {"type": "smartchain/tool/list"},
        {"type": "smartchain/overview"},
    ):
        await client.send_json_auto_id(message)
        msg = await client.receive_json()
        assert msg["success"], msg
        assert HEADER_SECRET not in json.dumps(msg), message["type"]

    # It is still there — withheld, not dropped.
    assert hass.data[DOMAIN]["tools"].get("porch_light").action.headers == {
        "Authorization": HEADER_SECRET
    }


async def test_an_untouched_edit_keeps_the_stored_header(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The form never receives the value back, so an unrelated edit submits it
    empty. Treating that as "clear it" would break the tool on the first edit."""
    entry = await _entry(
        hass,
        [
            _tool_subentry(
                "fetch",
                {
                    "description": "x",
                    "parameters": {"type": "object", "properties": {}},
                    "action": {
                        "type": "rest",
                        "method": "GET",
                        "url": "https://example.invalid/x",
                        "headers": {"Authorization": HEADER_SECRET, "X-Other": "plain"},
                        "payload": None,
                        "timeout": 10,
                        "response_format": "text",
                    },
                    "enabled": True,
                    "params_mode": "simple",
                },
            )
        ],
    )
    subentry_id = next(iter(entry.subentries))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
            "data": {
                "name": "fetch",
                "description": "a new description",
                "enabled": True,
                "action_type": "rest",
                "params_mode": "simple",
                "params_rows": [],
                "method": "GET",
                "url": "https://example.invalid/x",
                # As the form serves them back: names, no values.
                "headers": {"Authorization": "", "X-Other": ""},
                "payload": {},
                "timeout": 10,
                "response_format": "text",
            },
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    tool = hass.data[DOMAIN]["tools"].get("fetch")
    assert tool.description == "a new description"
    assert tool.action.headers == {"Authorization": HEADER_SECRET, "X-Other": "plain"}


async def test_a_header_removed_from_the_form_is_really_removed(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The merge is per key, not all-or-nothing: keeping an empty value must
    not also make deleting a header impossible."""
    entry = await _entry(
        hass,
        [
            _tool_subentry(
                "fetch",
                {
                    "description": "x",
                    "parameters": {"type": "object", "properties": {}},
                    "action": {
                        "type": "rest",
                        "method": "GET",
                        "url": "https://example.invalid/x",
                        "headers": {"Authorization": HEADER_SECRET},
                        "payload": None,
                        "timeout": 10,
                        "response_format": "text",
                    },
                    "enabled": True,
                    "params_mode": "simple",
                },
            )
        ],
    )
    subentry_id = next(iter(entry.subentries))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
            "data": {
                "name": "fetch",
                "description": "x",
                "enabled": True,
                "action_type": "rest",
                "params_mode": "simple",
                "params_rows": [],
                "method": "GET",
                "url": "https://example.invalid/x",
                "headers": {},
                "payload": {},
                "timeout": 10,
                "response_format": "text",
            },
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert hass.data[DOMAIN]["tools"].get("fetch").action.headers == {}


async def test_no_tool_response_carries_the_provider_key(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    for message in (
        {"type": "smartchain/tool/schema", "entry_id": entry.entry_id},
        {"type": "smartchain/tool/list"},
        {"type": "smartchain/tools/export"},
    ):
        await client.send_json_auto_id(message)
        msg = await client.receive_json()
        assert msg["success"], msg
        assert PROVIDER_SECRET not in json.dumps(msg)


# --- listing, deleting, shadowing ---------------------------------------


async def test_the_list_says_where_each_tool_comes_from(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: from_the_file\n"
        "    description: yaml\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: x }\n"
    )
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "smartchain/tool/save", "entry_id": entry.entry_id, "data": SIMPLE_TOOL}
    )
    await client.receive_json()

    await client.send_json_auto_id({"type": "smartchain/tool/list"})
    msg = await client.receive_json()
    sources = {tool["name"]: tool["source"] for tool in msg["result"]["tools"]}
    assert sources == {"from_the_file": "yaml", "porch_light": "subentry"}


async def test_a_disabled_tool_is_still_listed(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """It is not in the registry, but it exists and the user turned it off —
    a list that hid it would leave no way to turn it back on."""
    entry = await _entry(
        hass,
        [
            _tool_subentry(
                "off_one",
                {
                    "description": "x",
                    "parameters": {"type": "object", "properties": {}},
                    "action": {"type": "template", "value_template": "x"},
                    "enabled": False,
                },
            )
        ],
    )
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tool/list"})
    msg = await client.receive_json()
    (tool,) = msg["result"]["tools"]
    assert tool["name"] == "off_one" and tool["enabled"] is False
    assert hass.data[DOMAIN]["tools"].get("off_one") is None
    assert entry.entry_id == tool["entry_id"]


async def test_a_subentry_tool_shadows_the_same_name_in_the_file(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: porch_light\n"
        "    description: from the file\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: x }\n"
    )
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "smartchain/tool/save", "entry_id": entry.entry_id, "data": SIMPLE_TOOL}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["shadows_yaml"] is True

    assert hass.data[DOMAIN]["tools"].get("porch_light").description == "Turn the porch light on."

    await client.send_json_auto_id({"type": "smartchain/tool/list"})
    listed = await client.receive_json()
    assert listed["result"]["shadowed_yaml"] == ["porch_light"]


async def test_deleting_removes_it_from_the_registry(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "smartchain/tool/save", "entry_id": entry.entry_id, "data": SIMPLE_TOOL}
    )
    saved = await client.receive_json()

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/delete",
            "entry_id": entry.entry_id,
            "subentry_id": saved["result"]["subentry_id"],
        }
    )
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["name"] == "porch_light"
    assert hass.data[DOMAIN]["tools"].get("porch_light") is None


# --- import / export -----------------------------------------------------


async def test_import_refuses_a_file_using_secret_and_names_no_value(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Importing would have to resolve the secret to store it, which would move
    a credential out of secrets.yaml into .storage as plain text."""
    (tools_dir.parent / "secrets.yaml").write_text("token: sk-must-not-appear\n")
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: fetch\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action:\n"
        "      type: rest\n"
        "      method: GET\n"
        "      url: https://example.invalid/x\n"
        "      headers:\n"
        "        Authorization: !secret token\n"
    )
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tools/import", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert msg["result"]["ok"] is False
    assert msg["result"]["reason"] == "secrets_present"
    assert "sk-must-not-appear" not in json.dumps(msg)
    assert not [s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_TOOL]


async def test_import_turns_yaml_tools_into_editable_subentries(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: kitchen_temperature\n"
        "    description: Read the kitchen temperature.\n"
        "    parameters:\n"
        "      type: object\n"
        "      properties:\n"
        "        unit:\n"
        "          type: string\n"
        '    action: { type: template, value_template: "{{ 1 }}" }\n'
    )
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tools/import", "entry_id": entry.entry_id})
    msg = await client.receive_json()
    assert msg["result"]["ok"] is True
    assert msg["result"]["imported"] == ["kitchen_temperature"]

    subentry = next(s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_TOOL)
    assert subentry.title == "kitchen_temperature"
    assert subentry.data["params_mode"] == "simple"
    # tools.yaml is left alone, and the import now shadows it.
    assert (tools_dir / "tools.yaml").exists()
    await client.send_json_auto_id({"type": "smartchain/tool/list"})
    listed = await client.receive_json()
    assert listed["result"]["shadowed_yaml"] == ["kitchen_temperature"]


async def test_export_round_trips_through_the_yaml_loader(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path, tmp_path: Path
):
    """What export writes must be what the loader reads — otherwise the escape
    hatch produces a file that does not come back."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "smartchain/tool/save", "entry_id": entry.entry_id, "data": SIMPLE_TOOL}
    )
    await client.receive_json()

    await client.send_json_auto_id({"type": "smartchain/tools/export"})
    msg = await client.receive_json()
    assert msg["result"]["count"] == 1
    assert msg["result"]["redacted"] == []

    from custom_components.smartchain.tools.loader import load_tools_file

    exported = tmp_path / "exported.yaml"
    exported.write_text(msg["result"]["text"])
    (from_export,) = load_tools_file(exported).yaml_tools
    assert from_export == hass.data[DOMAIN]["tools"].get("porch_light")


async def test_export_blanks_header_values_and_says_so(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Export is a response like any other, and the rule that no response
    carries a credential does not acquire an exception because the user asked
    for it."""
    await _entry(
        hass,
        [
            _tool_subentry(
                "fetch",
                {
                    "description": "x",
                    "parameters": {"type": "object", "properties": {}},
                    "action": {
                        "type": "rest",
                        "method": "GET",
                        "url": "https://example.invalid/x",
                        "headers": {"Authorization": HEADER_SECRET},
                        "payload": None,
                        "timeout": 10,
                        "response_format": "text",
                    },
                    "enabled": True,
                },
            )
        ],
    )
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tools/export"})
    msg = await client.receive_json()
    assert HEADER_SECRET not in json.dumps(msg)
    assert msg["result"]["redacted"] == ["fetch"]
    assert "Authorization: ''" in msg["result"]["text"]


# --- admin ---------------------------------------------------------------


@pytest.mark.parametrize(
    "message",
    [
        {"type": "smartchain/tool/schema", "entry_id": "x"},
        {"type": "smartchain/tool/save", "entry_id": "x", "data": {}},
        {"type": "smartchain/tool/delete", "entry_id": "x", "subentry_id": "y"},
        {"type": "smartchain/tool/list"},
        {"type": "smartchain/tools/import", "entry_id": "x"},
        {"type": "smartchain/tools/export"},
    ],
    ids=["schema", "save", "delete", "list", "import", "export"],
)
async def test_every_command_refuses_a_non_admin(
    hass: HomeAssistant, hass_ws_client, hass_admin_user, tools_dir: Path, message
):
    await _entry(hass)
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(message)
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"
