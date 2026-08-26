"""Nothing this integration writes may be something JSON cannot hold.

The stakes are not local. `ConfigEntry.as_storage_fragment` serialises the
whole entry with orjson; one value it cannot encode raises `TypeError` inside
`ConfigEntries._data_to_save`, and `Store._async_handle_write_data` catches
only `SerializationError` and `WriteError` — having already dropped its
buffer. So a single bad subentry stops `core.config_entries` from ever being
written again, for *every* integration on the system, silently, until a
restart reads back whatever last made it to disk.

The route in was the tool form's `target` field: `selector.TargetSelector`
turns `entity_id: "{{ entity }}"` — the shape docs/USAGE.md §7.1 teaches and
the tools.yaml importer stores as a plain string — into a `Template` object.
Import, Edit, Save-unchanged was enough.

So these tests are about a class of value, not that one field: what the guard
normalises, what it refuses and how it says so, that every websocket write and
every config-flow subentry write goes through it, and that the runtime half
renders a `Template` it is nonetheless handed instead of passing an object to
a service call.
"""

import json
from pathlib import Path

import pytest
import voluptuous as vol
from homeassistant.config_entries import ConfigSubentryFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_bytes
from homeassistant.helpers.template import Template
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain import config_flow as config_flow_module
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_TOOL,
    UNIQUE_ID_OPENAI,
)
from custom_components.smartchain.storable import (
    UNSTORABLE_TEXT,
    UnstorableValue,
    ensure_storable,
    normalize_storable,
)
from custom_components.smartchain.websocket_api import _write_subentry, invalid_data

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

# Exactly the tool docs/USAGE.md §7.1 teaches: one argument, interpolated into
# the target. Written as a file so the reproduction starts where the reviewer's
# did — at Import — rather than at a hand-built form payload.
TEMPLATED_YAML = (
    "tools:\n"
    "  - name: turn_on_light\n"
    "    description: Turn on a light the user names.\n"
    "    parameters:\n"
    "      type: object\n"
    "      properties:\n"
    "        entity:\n"
    "          type: string\n"
    "      required: [entity]\n"
    "    action:\n"
    "      type: service\n"
    "      domain: light\n"
    "      service: turn_on\n"
    "      target:\n"
    '        entity_id: "{{ entity }}"\n'
)


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
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sk-provider-secret"},
        subentries_data=subentries or [],
        minor_version=2,
    )
    entry.add_to_hass(hass)
    await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return entry


def _config_entries_still_writable(hass: HomeAssistant) -> None:
    """The exact call the delayed write makes, and the exact way it used to die.

    `_data_to_save` builds each entry's `as_storage_fragment`, which is where
    the `TypeError` came from — so asserting on `subentry.data` alone would
    have passed against the bug for any value orjson merely reshapes.
    """
    json_bytes(hass.config_entries._data_to_save())


# --- the reviewer's click path -------------------------------------------


async def test_import_edit_save_leaves_config_entries_writable(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Import → Edit → Save with nothing changed. The whole defect, end to end."""
    (tools_dir / "tools.yaml").write_text(TEMPLATED_YAML)
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tools/import", "entry_id": entry.entry_id})
    imported = await client.receive_json()
    assert imported["result"]["imported"] == ["turn_on_light"]
    subentry = next(s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_TYPE_TOOL)

    # Edit: the form the panel would render, served back with stored values.
    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/schema",
            "entry_id": entry.entry_id,
            "subentry_id": subentry.subentry_id,
        }
    )
    schema_msg = await client.receive_json()
    form = dict(schema_msg["result"]["data"])
    assert form["target"] == {"entity_id": "{{ entity }}"}

    # Save, changing nothing at all.
    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "subentry_id": subentry.subentry_id,
            "data": form,
        }
    )
    saved = await client.receive_json()
    assert saved["success"], saved

    _config_entries_still_writable(hass)
    # And a round trip changed nothing: the tool is still the tool that was
    # imported, not a differently-shaped one that merely happens to serialise.
    stored = entry.subentries[subentry.subentry_id]
    assert stored.data["action"]["target"] == {"entity_id": "{{ entity }}"}


async def test_a_templated_target_is_stored_as_the_text_that_was_typed(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The normalise half of the guard, on the field that needs it."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "data": {
                "name": "turn_on_light",
                "description": "Turn on a light the user names.",
                "enabled": True,
                "action_type": "service",
                "params_mode": "simple",
                "params_rows": [
                    {"name": "entity", "type": "string", "description": "", "required": True}
                ],
                "service": "light.turn_on",
                "target": {"entity_id": "{{ entity }}"},
                "service_data": {"brightness": "{{ level }}"},
                "response": False,
            },
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    subentry = entry.subentries[msg["result"]["subentry_id"]]
    action = subentry.data["action"]
    assert action["target"] == {"entity_id": "{{ entity }}"}
    assert action["data"] == {"brightness": "{{ level }}"}
    _config_entries_still_writable(hass)


# --- the guard as a class -------------------------------------------------


def test_normalize_rewrites_a_template_to_its_source_text(hass: HomeAssistant):
    value = {"entity_id": Template("{{ entity }}", hass), "keep": ["a", 1, True, None]}
    assert normalize_storable(value) == {
        "entity_id": "{{ entity }}",
        "keep": ["a", 1, True, None],
    }


def test_normalize_collapses_the_sequence_types_json_does_not_have(hass: HomeAssistant):
    """A tuple survives orjson but comes back a list — so memory and disk would
    disagree until a restart quietly made them agree."""
    assert normalize_storable(("a", "b")) == ["a", "b"]
    assert normalize_storable(frozenset({"a"})) == ["a"]


def test_ensure_storable_refuses_what_it_cannot_rewrite_and_names_the_field():
    with pytest.raises(UnstorableValue) as caught:
        ensure_storable({"name": "ok", "payload": object()})
    assert caught.value.path == ["payload"]
    # The value itself never travels: `payload` is a free-form box that can
    # hold a bearer token.
    assert "object at 0x" not in str(caught.value)


def test_a_refusal_is_a_vol_invalid_so_callers_need_no_new_branch():
    """Every save path already has `except vol.Invalid`. That is the whole
    reason the guard raises this type rather than one of its own."""
    with pytest.raises(vol.Invalid):
        ensure_storable({"payload": object()})


@pytest.mark.parametrize(
    "subentry_type",
    [SUBENTRY_TYPE_CONVERSATION, SUBENTRY_TYPE_TOOL],
)
async def test_every_subentry_write_goes_through_the_guard(
    hass: HomeAssistant, tools_dir: Path, subentry_type
):
    """`_write_subentry` is the one door, so a value that cannot be stored is
    refused before `async_add_subentry` rather than after."""
    entry = await _entry(hass)
    before = len(entry.subentries)

    with pytest.raises(vol.Invalid) as caught:
        _write_subentry(
            hass,
            entry,
            None,
            subentry_type=subentry_type,
            data={"description": "x", "action": object()},
            title="broken",
        )
    assert caught.value.path == ["action"]
    assert len(entry.subentries) == before, "a refused write must create nothing"
    _config_entries_still_writable(hass)


async def test_the_guard_normalises_on_the_way_through(hass: HomeAssistant, tools_dir: Path):
    entry = await _entry(hass)
    subentry_id = _write_subentry(
        hass,
        entry,
        None,
        subentry_type=SUBENTRY_TYPE_CONVERSATION,
        data={CONF_CHAT_MODEL: "gpt-4.1", "prompt": Template("{{ ha_name }}", hass)},
        title="agent",
    )
    assert entry.subentries[subentry_id].data["prompt"] == "{{ ha_name }}"
    _config_entries_still_writable(hass)


def test_every_subentry_flow_inherits_the_guard():
    """The config-flow half. Home Assistant's own dialogs write through
    `async_create_entry` / `async_update_and_abort`, so the guard is a base
    class rather than a line in seven step handlers — a flow added later
    inherits it by existing."""
    flows = [
        value
        for name, value in vars(config_flow_module).items()
        if isinstance(value, type)
        and issubclass(value, ConfigSubentryFlow)
        and value is not ConfigSubentryFlow
        and value is not config_flow_module.StorableSubentryFlow
        and name.endswith("SubentryFlow")
    ]
    assert flows, "no subentry flows found — this test has stopped testing anything"
    for flow in flows:
        assert issubclass(flow, config_flow_module.StorableSubentryFlow), flow.__name__


async def test_the_tool_dialog_refuses_by_name_rather_than_raising(hass: HomeAssistant):
    """`build_tool_subentry_data` is what the panel and Home Assistant's own
    tool dialog share, so the refusal a person can actually be shown lives
    there — and names a form field, not the composed `action` block."""
    data, error = config_flow_module.build_tool_subentry_data(
        hass,
        {
            "name": "broken",
            "description": "x",
            "action_type": "service",
            "params_mode": "simple",
            "params_rows": [],
            "service": "light.turn_on",
            "target": {"entity_id": object()},
        },
    )
    assert data is None
    assert error == ("target", "unstorable")
    assert config_flow_module.TOOL_ERROR_TEXT["unstorable"] == UNSTORABLE_TEXT


# --- how a refusal reaches the user ---------------------------------------


def test_invalid_data_carries_both_the_fields_and_a_reason():
    """The protocol `<sc-config-form>` parses: a comma-separated field list the
    panel matches against its own schema, then an em dash, then the sentence to
    show. The em dash is the separator precisely because a field name can never
    contain one, so a reason may."""
    assert invalid_data(["model", "model_user"], "pick one, or type one") == (
        "invalid_data: model, model_user — pick one, or type one"
    )
    assert invalid_data(["target"]) == "invalid_data: target"
    assert invalid_data([]) == "invalid_data"


async def test_a_missing_model_names_the_fields_and_says_what_to_do(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """A new user's first click: `DEFAULT_CHAT_MODEL` is "", so "+ Agent" opens
    with an empty dropdown and Save used to toast the key `model_required`."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "smartchain/agent/save", "entry_id": entry.entry_id, "data": {}}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    message = msg["error"]["message"]
    assert message == "invalid_data: model, model_user — Either Model or Custom Model required"
    assert "model_required" not in message


async def test_the_agent_and_embeddings_forms_do_not_borrow_each_others_sentence(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Both subentry types define `model_required` and they are not the same
    sentence — which is why the lookup is scoped by subentry type."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(
        {"type": "smartchain/agent/save", "entry_id": entry.entry_id, "data": {}}
    )
    agent = (await client.receive_json())["error"]["message"]
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry.entry_id,
            "data": {"name": "Some Binding"},
        }
    )
    embeddings = (await client.receive_json())["error"]["message"]

    assert agent.endswith("Either Model or Custom Model required")
    assert embeddings.endswith("Select a model or enter a custom name")


async def test_no_refusal_carries_a_credential(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """A refused value is named by its field and never echoed — a REST header
    is where an `Authorization: Bearer …` goes."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    secret = "Bearer must-not-come-back"

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "data": {
                "name": "fetch",
                "description": "x",
                "enabled": True,
                "action_type": "rest",
                "params_mode": "simple",
                "params_rows": [],
                "method": "GET",
                "url": "",  # refused: url_required
                "headers": {"Authorization": secret},
                "payload": {},
                "timeout": 10,
                "response_format": "text",
            },
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert secret not in json.dumps(msg)
    assert msg["error"]["message"].startswith("invalid_data: url — ")


# --- the runtime half -----------------------------------------------------


async def test_a_template_object_handed_to_a_service_call_is_rendered(hass: HomeAssistant):
    """`_render_value` used to fall through to `return value` for anything that
    was not a str, dict or list — so an unrendered `Template` went into
    `hass.services.async_call(target=…)` and the model's argument never
    reached the service. The call did nothing, and said nothing."""
    from custom_components.smartchain.tools.actions.service_action import _render_value

    rendered = _render_value(
        {"entity_id": Template("{{ entity }}", hass)}, hass, {"entity": "light.porch"}
    )
    assert rendered == {"entity_id": "light.porch"}


async def test_a_nested_template_object_is_reached_too(hass: HomeAssistant):
    """The recursion has to carry the new branch: `target` and `data` are
    arbitrarily nested maps and lists."""
    from custom_components.smartchain.tools.actions.service_action import _render_value

    rendered = _render_value(
        {"area_id": ["static", Template("{{ where }}", hass)]}, hass, {"where": "kitchen"}
    )
    assert rendered == {"area_id": ["static", "kitchen"]}


async def test_the_devices_and_services_dialog_takes_a_templated_target_too(
    hass: HomeAssistant, tools_dir: Path
):
    """The same tool, built through Home Assistant's own two-step dialog.

    The panel is not the only way in, and the dialog hands over exactly what
    its step schema produced — `Template` object included.
    """
    entry = await _entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_TOOL), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "turn_on_light",
            "description": "Turn on a light the user names.",
            "enabled": True,
            "action_type": "service",
            "params_mode": "simple",
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "params_rows": [
                {"name": "entity", "type": "string", "description": "", "required": True}
            ],
            "service": "light.turn_on",
            "target": {"entity_id": "{{ entity }}"},
            "service_data": {},
            "response": False,
        },
    )
    assert result["type"] == "create_entry"
    assert result["data"]["action"]["target"] == {"entity_id": "{{ entity }}"}
    await hass.async_block_till_done()
    _config_entries_still_writable(hass)
