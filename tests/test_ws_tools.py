"""Read-only tools.yaml view over the panel's websocket API.

`load_tools_file` resolves `!secret` references against Home Assistant's
secret store, so the *parsed* result holds real credentials. The raw file on
disk holds only the reference name (`!secret my_key`), which is safe to show.
These tests establish that `smartchain/tools/get` never crosses that line,
that a validation failure never forwards a resolved secret either, and the
ordinary operational shapes (missing file, valid file, reload count,
admin-only).
"""

import json
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.smartchain.const import DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SECRET_VALUE = "sk-must-not-appear"


@pytest.fixture
def tools_dir(hass: HomeAssistant, tmp_path_factory) -> Path:
    """Point hass.config.config_dir at a writable temp dir with a smartchain/ subdir.

    Must be set before async_setup_component(hass, DOMAIN, {}) runs, since
    domain setup itself performs the first tools.yaml load.
    """
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    hass.config.config_dir = str(cdir)
    return cdir / "smartchain"


async def test_get_returns_raw_text_with_secret_references_unresolved(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """load_tools_file resolves !secret, so the parsed structure holds real
    credentials. Only the file as it sits on disk may cross the wire."""
    (tools_dir.parent / "secrets.yaml").write_text(f"my_key: {SECRET_VALUE}\n")
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action:\n"
        "      type: rest\n"
        "      method: GET\n"
        "      url: https://example.invalid\n"
        "      headers:\n"
        "        Authorization: !secret my_key\n"
    )
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/get"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert "!secret" in msg["result"]["text"]
    assert msg["result"]["exists"] is True
    assert msg["result"]["path"].endswith("tools.yaml")
    assert SECRET_VALUE not in json.dumps(msg)


async def test_get_reports_missing_file_without_erroring(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """No tools.yaml at all is the normal first-run state, not a fault."""
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/get"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["exists"] is False
    assert msg["result"]["text"] == ""


async def test_validate_of_a_broken_file_leaks_no_resolved_secret(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Voluptuous embeds the offending value in its message for some
    validators (the action-type discriminator does exactly this), so a
    resolved secret landing in such a field and failing validation would
    appear in the error text if that text were forwarded verbatim."""
    (tools_dir.parent / "secrets.yaml").write_text(f"my_key: {SECRET_VALUE}\n")
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action:\n"
        "      type: !secret my_key\n"
    )
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/validate"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["valid"] is False
    assert SECRET_VALUE not in json.dumps(msg)
    # A location is still reported — just not the value that failed there.
    assert "action" in msg["result"]["error"]


async def test_validate_of_a_missing_file_reports_valid(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """load_tools_file treats a missing file as an empty, valid result."""
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/validate"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["valid"] is True
    assert "error" not in msg["result"]


async def test_validate_of_a_good_file_reports_valid(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: pong }\n"
    )
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/validate"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["valid"] is True


async def test_reload_reports_the_tool_count(hass: HomeAssistant, hass_ws_client, tools_dir: Path):
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: pong }\n"
        "  - name: pong\n"
        "    description: y\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: ping }\n"
    )
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/reload"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["tools"] == 2


@pytest.mark.parametrize(
    "command",
    ["smartchain/tools/get", "smartchain/tools/validate", "smartchain/tools/reload"],
)
async def test_all_three_commands_require_admin(
    hass: HomeAssistant, hass_ws_client, hass_admin_user, tools_dir: Path, command: str
):
    hass_admin_user.groups = []
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": command})
    msg = await client.receive_json()

    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"
