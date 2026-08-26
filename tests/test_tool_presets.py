"""The preset tool catalogue: a set the user switches on rather than builds.

Three things are being established.

**That the catalogue is real.** Every entry is held to `TOOL_SCHEMA` — the
schema tools.yaml passes through — and every service it calls is checked
against the service the installed Home Assistant actually declares, not against
memory. A preset that would fail at call time in front of the model must fail
here instead.

**That installing one produces an ordinary tool.** The subentry a preset writes
is the subentry the form writes: it reaches the registry as a `CustomTool`, it
is listed as `source: subentry`, it can be edited, and re-saving it unchanged
gives back byte-identical storage — which for four of the eight means a
templated `target` surviving `TargetSelector`, and for two of them means an
`enum` surviving the parameters editor.

**That the name rules are the same rules.** Install goes through
`validate_tool_name`, so a duplicate, a reserved name and a live MCP name are
refused for a preset exactly as they are for a hand-built tool, and shadowing a
tools.yaml twin is reported rather than silent.
"""

import json
from pathlib import Path

import pytest
import voluptuous as vol
import yaml
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
    TOOL_NAME_PATTERN,
    UNIQUE_ID_OPENAI,
)
from custom_components.smartchain.tools.presets import (
    PRESET_TOOLS,
    PRESETS_BY_NAME,
    preset_subentry_data,
)
from custom_components.smartchain.tools.schema import TOOL_SCHEMA

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


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


async def _install(client, entry, name):
    await client.send_json_auto_id(
        {"type": "smartchain/tool/preset/install", "entry_id": entry.entry_id, "preset": name}
    )
    return await client.receive_json()


# --- the catalogue itself -------------------------------------------------


@pytest.mark.parametrize("preset", PRESET_TOOLS, ids=lambda preset: preset.name)
def test_every_preset_is_a_valid_tool(preset):
    """The catalogue is data, so this is where a typo in it is caught.

    `TOOL_SCHEMA` is the same validator tools.yaml goes through, which is the
    point: a preset is not a privileged shape, it is a tool that happens to
    ship with the integration.
    """
    validated = TOOL_SCHEMA(
        {
            "name": preset.name,
            "description": preset.description,
            "parameters": preset.parameters,
            "action": preset.action,
        }
    )
    assert validated["name"] == preset.name
    assert validated["action"]["type"] == preset.action_type


def test_no_preset_takes_a_built_in_name():
    """A reserved name would make the preset uninstallable — `validate_tool_name`
    refuses it — so the catalogue must not contain one in the first place."""
    assert {preset.name for preset in PRESET_TOOLS} & RESERVED_TOOL_NAMES == set()


def test_the_catalogue_has_no_duplicates():
    names = [preset.name for preset in PRESET_TOOLS]
    assert len(names) == len(set(names)) == len(PRESETS_BY_NAME)


def test_every_preset_name_is_a_legal_tool_name():
    import re

    for preset in PRESET_TOOLS:
        assert re.match(TOOL_NAME_PATTERN, preset.name), preset.name


@pytest.mark.parametrize("locale", ["strings.json", "translations/en.json", "translations/ru.json"])
def test_every_locale_names_and_describes_every_preset(locale):
    """The translation-key convention, pinned in one place.

    `config_panel.presets.<tool name>.{name,description}` — `config_panel`
    because it is the only category Home Assistant defines for text a custom
    panel shows, `presets` so a second kind of panel text cannot collide with a
    preset name. A preset added without its pair still renders (the backend
    falls back to the tool name), which is exactly why it needs a test: the
    failure would otherwise be an English name in a Russian panel and nothing
    else.
    """
    path = Path(__file__).parent.parent / "custom_components" / DOMAIN / locale
    presets = json.loads(path.read_text(encoding="utf-8"))["config_panel"]["presets"]

    assert set(presets) == {preset.name for preset in PRESET_TOOLS}
    for name, texts in presets.items():
        assert set(texts) == {"name", "description"}, name
        assert all(text.strip() for text in texts.values()), name
    # And the model-facing description is *not* what is being translated — the
    # two are different strings for different audiences.
    assert not {texts["description"] for texts in presets.values()} & {
        preset.description for preset in PRESET_TOOLS
    }


@pytest.mark.parametrize(
    "preset",
    [preset for preset in PRESET_TOOLS if preset.action_type == "service"],
    ids=lambda preset: preset.name,
)
def test_every_service_a_preset_calls_is_declared(preset):
    """Checked against the installed Home Assistant, not against memory.

    A preset naming a service that does not exist would fail at call time, in
    front of the model, with an error the user cannot act on. Home Assistant
    declares its services in each integration's own `services.yaml`, so that
    file is the oracle — reading it needs no component set up, which is what
    makes this cheap enough to run for every preset.
    """
    domain = preset.action["domain"]
    service = preset.action["service"]

    if domain == DOMAIN:
        path = Path(__file__).parent.parent / "custom_components" / DOMAIN / "services.yaml"
    else:
        import homeassistant.components as components

        path = Path(components.__file__).parent / domain / "services.yaml"

    declared = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert service in declared, f"{domain}.{service} is not declared by {domain}"


def test_the_catalogue_is_copied_out_not_handed_out():
    """Module-level state shared by every install: one edited tool must not be
    able to rewrite the preset for the next installation."""
    first = preset_subentry_data(PRESETS_BY_NAME["weather_forecast"])
    first["action"]["domain"] = "wrong"
    first["parameters"]["properties"].clear()

    second = preset_subentry_data(PRESETS_BY_NAME["weather_forecast"])
    assert second["action"]["domain"] == "weather"
    assert set(second["parameters"]["properties"]) == {"entity", "type"}


# --- listing --------------------------------------------------------------


async def test_the_catalogue_lists_every_preset_with_its_translation(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tool/presets"})
    msg = await client.receive_json()
    assert msg["success"], msg

    presets = msg["result"]["presets"]
    assert [preset["name"] for preset in presets] == [preset.name for preset in PRESET_TOOLS]
    assert all(preset["installed"] is False for preset in presets)

    weather = next(preset for preset in presets if preset["name"] == "weather_forecast")
    # The panel-facing pair, from `config_panel.presets.<name>` — not the tool's
    # own description, which is the model's and stays English.
    assert weather["title"] == "Weather forecast"
    assert weather["blurb"]
    assert weather["action_type"] == "service"


async def test_the_catalogue_is_translated_into_the_users_language(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """`ru.json` carries the same keys, so switching the language switches the
    catalogue — and only the catalogue: the tool's `description` is what the
    model reads and never comes from here."""
    hass.config.language = "ru"
    await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tool/presets"})
    msg = await client.receive_json()
    titles = {preset["name"]: preset["title"] for preset in msg["result"]["presets"]}
    assert titles["who_is_home"] == "Кто дома"


async def test_installed_is_derived_from_the_tools_that_exist(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Nothing marks a subentry as having come from a preset, so `installed`
    can only be a name match — and must be one, or a renamed tool would hide
    its own preset forever."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    assert (await _install(client, entry, "who_is_home"))["result"]["ok"] is True

    await client.send_json_auto_id({"type": "smartchain/tool/presets"})
    msg = await client.receive_json()
    installed = {preset["name"]: preset["installed"] for preset in msg["result"]["presets"]}
    assert installed["who_is_home"] is True
    assert installed["sun_times"] is False


async def test_a_yaml_tool_of_the_same_name_is_not_installed(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """A tools.yaml twin is not a subentry, cannot be edited in the panel, and
    installing over it is allowed — so the switch must still read as off."""
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: who_is_home\n"
        "    description: from the file\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: x }\n"
    )
    await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tool/presets"})
    msg = await client.receive_json()
    installed = {preset["name"]: preset["installed"] for preset in msg["result"]["presets"]}
    assert installed["who_is_home"] is False


# --- installing -----------------------------------------------------------


@pytest.mark.parametrize("preset", PRESET_TOOLS, ids=lambda preset: preset.name)
async def test_every_preset_installs_and_reaches_the_registry(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path, preset
):
    """The whole catalogue, one at a time: stored, rebuilt, registered."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    msg = await _install(client, entry, preset.name)
    assert msg["success"], msg
    assert msg["result"]["ok"] is True
    assert msg["result"]["reload_error"] is None
    assert msg["result"]["shadows_yaml"] is False

    subentry = entry.subentries[msg["result"]["subentry_id"]]
    assert subentry.subentry_type == SUBENTRY_TYPE_TOOL
    assert subentry.title == preset.name
    assert subentry.data["description"] == preset.description
    assert subentry.data["parameters"] == preset.parameters
    assert subentry.data["action"] == preset.action
    assert subentry.data["enabled"] is True

    tool = hass.data[DOMAIN]["tools"].get(preset.name)
    assert tool is not None
    assert tool.description == preset.description
    assert tool.action.type == preset.action_type


async def test_an_installed_preset_is_an_ordinary_tool(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Listed like any other, editable like any other, deletable like any
    other. Nothing about it stays special."""
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    result = (await _install(client, entry, "sun_times"))["result"]

    await client.send_json_auto_id({"type": "smartchain/tool/list"})
    msg = await client.receive_json()
    listed = next(tool for tool in msg["result"]["tools"] if tool["name"] == "sun_times")
    assert listed["source"] == "subentry"
    assert listed["action_type"] == "template"
    assert listed["subentry_id"] == result["subentry_id"]

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/delete",
            "entry_id": entry.entry_id,
            "subentry_id": result["subentry_id"],
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert result["subentry_id"] not in entry.subentries
    assert hass.data[DOMAIN]["tools"].get("sun_times") is None


async def test_installing_twice_is_refused_by_the_shared_name_rule(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    assert (await _install(client, entry, "sun_times"))["result"]["ok"] is True
    second = (await _install(client, entry, "sun_times"))["result"]
    assert second == {"ok": False, "reason": "name_taken"}


async def test_a_hand_built_tool_of_the_same_name_blocks_the_preset(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """`validate_tool_name` is the one rule, so it does not matter which side
    of the collision was created first."""
    entry = await _entry(
        hass,
        [
            ConfigSubentryData(
                data={
                    "description": "mine",
                    "parameters": {"type": "object", "properties": {}},
                    "action": {"type": "template", "value_template": "x"},
                    "enabled": True,
                    "params_mode": "simple",
                },
                subentry_type=SUBENTRY_TYPE_TOOL,
                title="area_summary",
                unique_id=None,
            )
        ],
    )
    client = await hass_ws_client(hass)

    assert (await _install(client, entry, "area_summary"))["result"] == {
        "ok": False,
        "reason": "name_taken",
    }
    # And the user's own tool is untouched.
    assert hass.data[DOMAIN]["tools"].get("area_summary").description == "mine"


async def test_a_live_mcp_tool_of_the_same_name_blocks_the_preset(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The third rule `validate_tool_name` owns. An MCP server's tool is
    discovered rather than declared, so this is the case that is visible at the
    moment the user reaches for the switch."""
    from custom_components.smartchain.tools.model import CustomTool, MCPAction

    entry = await _entry(hass)
    hass.data[DOMAIN]["tools"].add(
        CustomTool(
            name="who_is_home",
            description="from a server",
            parameters={"type": "object", "properties": {}},
            action=MCPAction(server="files", tool_name="who_is_home"),
        )
    )
    client = await hass_ws_client(hass)

    assert (await _install(client, entry, "who_is_home"))["result"] == {
        "ok": False,
        "reason": "mcp_name_taken",
    }


async def test_installing_over_a_yaml_twin_reports_the_shadow(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The same report `tool/save` makes, for the same reason: the file's tool
    is now ignored and a log line nobody reads is not good enough."""
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: who_is_home\n"
        "    description: from the file\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: x }\n"
    )
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    result = (await _install(client, entry, "who_is_home"))["result"]
    assert result["ok"] is True
    assert result["shadows_yaml"] is True
    assert hass.data[DOMAIN]["tools"].get("who_is_home").description != "from the file"


async def test_an_unknown_preset_and_an_unknown_entry_are_refused(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    msg = await _install(client, entry, "no_such_preset")
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/preset/install",
            "entry_id": "nope",
            "preset": "sun_times",
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_nothing_in_a_preset_result_carries_the_provider_key(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tool/presets"})
    assert "sk-provider-secret" not in json.dumps(await client.receive_json())
    assert "sk-provider-secret" not in json.dumps(await _install(client, entry, "notify_device"))


# --- the two things a reviewer flagged ------------------------------------


TEMPLATED_TARGET = ("weather_forecast", "calendar_events", "todo_list_items", "notify_device")
ENUM_PRESETS = ("weather_forecast", "todo_list_items")


def test_the_reviewers_four_are_the_four():
    """The flagged set, pinned: a fifth templated target added later must join
    the round-trip test rather than slip past it."""
    templated = {
        preset.name
        for preset in PRESET_TOOLS
        if "{{" in json.dumps(preset.action.get("target") or {})
    }
    assert templated == set(TEMPLATED_TARGET)
    templated_data = {
        preset.name
        for preset in PRESET_TOOLS
        if "{{" in json.dumps(preset.action.get("data") or {})
    }
    assert templated_data == set(TEMPLATED_TARGET) | {"look_at_camera"}


@pytest.mark.parametrize("preset", PRESET_TOOLS, ids=lambda preset: preset.name)
async def test_a_preset_survives_open_and_save_unchanged(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path, preset
):
    """The round trip the Storage phase made possible.

    `target: {entity_id: "{{ entity }}"}` is what makes one preset serve every
    weather entity, calendar or phone. Opening the tool and pressing Save hands
    that string to `selector.TargetSelector`, which turns it into a `Template`
    object; before `storable.py` that object went into `.storage` and killed
    every later write of `core.config_entries`. Here the stored subentry must
    come back byte-identical — proof the fix covers the presets rather than the
    presets working around it.

    Run over the whole catalogue rather than only the four flagged entries,
    because the composition is where the other half of the risk was: a preset
    that omits an optional action key comes back with it filled in, and "the
    first Save rewrites the tool" is a corruption of a smaller kind.
    """
    name = preset.name
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    subentry_id = (await _install(client, entry, name))["result"]["subentry_id"]
    before = dict(entry.subentries[subentry_id].data)

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/schema",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
        }
    )
    served = (await client.receive_json())["result"]["data"]

    # Exactly what the panel would send back with nothing touched.
    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
            "data": served,
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    after = dict(entry.subentries[subentry_id].data)
    assert after == before
    # And it is still storable — the guard that would have caught a `Template`.
    json.dumps(after)
    if name in TEMPLATED_TARGET:
        assert "{{" in json.dumps(after["action"]["target"])


@pytest.mark.parametrize("name", ENUM_PRESETS)
async def test_an_enum_argument_opens_in_the_editor_that_can_hold_it(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path, name
):
    """`enum` is not row-expressible, so the tool stores `params_mode:
    advanced` and opens in the JSON editor, where the enum is text the user can
    see and keep. The rows editor is not offered at all — which is what stops
    the "degrades rather than breaks" case from ever arising by default.
    """
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    subentry_id = (await _install(client, entry, name))["result"]["subentry_id"]
    assert entry.subentries[subentry_id].data["params_mode"] == "advanced"

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/schema",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
        }
    )
    result = (await client.receive_json())["result"]
    fields = {field["name"] for field in result["schema"]}
    assert "params_json" in fields
    assert "params_rows" not in fields
    assert (
        "enum"
        in json.loads(result["data"]["params_json"])["properties"][
            "type" if name == "weather_forecast" else "status"
        ]
    )


@pytest.mark.parametrize("name", ENUM_PRESETS)
async def test_switching_an_enum_tool_to_the_rows_editor_carries_nothing_across(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path, name
):
    """The honest answer to "what happens if the user insists".

    Nothing reaches the rows editor by itself — `tool_form_defaults` forces
    `advanced` for a schema the rows cannot express, so opening a preset for
    editing keeps its enum. A user who *changes* the dropdown to `simple` gets
    a reshaped form with **no `params_rows` value at all**: `ws_tool_schema`
    serves only the keys the stored defaults actually hold, and an advanced
    tool holds `params_json`, so there is nothing to translate into rows.

    So it does not degrade to "the enum is quietly dropped" — it degrades to an
    empty arguments editor, and a Save from there writes a tool with no
    arguments. That is visible rather than silent, which is the better of the
    two failures, but it is not nothing: it is recorded here, exactly as it
    behaves, rather than asserted into the shape one might prefer. It is also
    not preset-specific — every `advanced` tool behaves this way.
    """
    entry = await _entry(hass)
    client = await hass_ws_client(hass)
    subentry_id = (await _install(client, entry, name))["result"]["subentry_id"]
    enum_field = "type" if name == "weather_forecast" else "status"

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/schema",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
            "data": {"params_mode": "simple"},
        }
    )
    reshaped = (await client.receive_json())["result"]
    assert "params_rows" in {field["name"] for field in reshaped["schema"]}
    assert "params_rows" not in reshaped["data"]
    assert "params_json" not in reshaped["data"]

    await client.send_json_auto_id(
        {
            "type": "smartchain/tool/save",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
            "data": {**reshaped["data"], "params_mode": "simple", "params_rows": []},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    parameters = entry.subentries[subentry_id].data["parameters"]
    assert parameters == {"type": "object", "properties": {}}
    assert enum_field not in parameters["properties"]
    # Still a registered, working tool — it simply takes no arguments now.
    assert hass.data[DOMAIN]["tools"].get(name) is not None


async def test_a_preset_that_cannot_be_stored_is_refused_not_written(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path, monkeypatch
):
    """`_write_subentry`'s guard is structural; this is the branch that keeps
    the install path from being the one place that swallows it."""
    from custom_components.smartchain.tools import presets as presets_module

    entry = await _entry(hass)
    client = await hass_ws_client(hass)

    def _unstorable(preset):
        return {
            "description": preset.description,
            "parameters": dict(preset.parameters),
            "action": {"type": "template", "value_template": "x", "oops": object()},
            "enabled": True,
        }

    monkeypatch.setattr(presets_module, "preset_subentry_data", _unstorable)

    msg = await _install(client, entry, "sun_times")
    assert msg["success"], msg
    assert msg["result"] == {"ok": False, "reason": "unstorable"}
    assert not any(sub.subentry_type == SUBENTRY_TYPE_TOOL for sub in entry.subentries.values())


def test_the_action_dicts_are_plain_json():
    """What the previous test's guard exists for, asserted about the real
    catalogue: nothing in it is a `Template`, a tuple or a set."""
    for preset in PRESET_TOOLS:
        json.dumps({"parameters": preset.parameters, "action": preset.action})


def test_the_parameters_of_every_preset_validate_as_json_schema():
    """`dispatcher.dispatch` hands `tool.parameters` straight to
    `jsonschema.validate`, so a shape that only looks like JSON Schema would
    fail at call time."""
    import jsonschema

    for preset in PRESET_TOOLS:
        jsonschema.Draft7Validator.check_schema(preset.parameters)


def test_the_catalogue_composes_the_action_field_names_the_executors_read():
    """Field names, not shapes: `validate_action` accepts an action whose
    optional keys are missing, so a preset that spelled `entity` instead of
    `target` would validate and then do nothing."""
    for preset in PRESET_TOOLS:
        if preset.action_type == "service":
            assert set(preset.action) <= {
                "type",
                "domain",
                "service",
                "target",
                "data",
                "response",
            }, preset.name
        elif preset.action_type == "template":
            assert set(preset.action) == {"type", "value_template"}, preset.name
        else:  # pragma: no cover - the catalogue has only these two today
            raise AssertionError(preset.action_type)


def test_a_broken_preset_would_be_caught():
    """The catalogue test above is only worth having if it can fail."""
    with pytest.raises(vol.Invalid):
        TOOL_SCHEMA(
            {
                "name": "Not A Tool Name",
                "description": "x",
                "parameters": {"type": "object", "properties": {}},
                "action": {"type": "template", "value_template": "x"},
            }
        )
