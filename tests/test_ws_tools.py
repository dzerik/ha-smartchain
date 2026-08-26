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
    # Only the exception type crosses the wire — see _safe_loader_error for
    # why even the structural-looking err.path isn't safe to include.
    assert msg["result"]["error"] == "MultipleInvalid"


async def test_get_reports_a_non_utf8_file_as_a_distinguishable_error(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """A file that exists but can't be decoded as text must not raise out of
    the executor job — that would degrade to HA's generic "Unknown error"
    and leave the panel unable to say what's wrong."""
    (tools_dir / "tools.yaml").write_bytes(b"tools:\n  - name: \xff\xfe not valid utf-8 \x80\x81\n")
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/get"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["exists"] is True
    assert msg["result"]["text"] == ""
    assert "UnicodeDecodeError" in msg["result"]["error"]


async def test_validate_leaks_no_secret_used_as_an_extra_mapping_key(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """`!secret` resolves on mapping *keys*, not only values. Every block in
    tools/schema.py uses voluptuous's default extra=PREVENT_EXTRA, so a
    `!secret` used as an unexpected key raises "extra keys not allowed" with
    the resolved key — not just a message fragment, an actual document value
    — sitting in `err.path`. A path-joining `_safe_loader_error` would leak
    it even though it never touches `str(err)`."""
    (tools_dir.parent / "secrets.yaml").write_text(f"my_key: {SECRET_VALUE}\n")
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action:\n"
        "      type: template\n"
        "      value_template: pong\n"
        "      !secret my_key: extra\n"
    )
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/validate"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["valid"] is False
    assert SECRET_VALUE not in json.dumps(msg)


async def test_reload_leaks_no_secret_used_as_an_extra_mapping_key(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Same leak vector as above, reached through smartchain/tools/reload
    instead of smartchain/tools/validate — both paths call
    _safe_loader_error on the same LoaderError."""
    (tools_dir.parent / "secrets.yaml").write_text(f"my_key: {SECRET_VALUE}\n")
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action:\n"
        "      type: template\n"
        "      value_template: pong\n"
        "      !secret my_key: extra\n"
    )
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/reload"})
    msg = await client.receive_json()

    assert not msg["success"]
    assert SECRET_VALUE not in json.dumps(msg)


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


async def test_get_reports_whether_a_backup_exists(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The Rollback button's visibility is a fact read from disk, not a guess
    the browser session has to make.

    The panel used to keep a local `_backupAvailable` flag starting at False,
    on the stated belief that "the backend exposes no 'does a backup exist'
    query" — which was never true: `_read_tools_file` has computed
    `backup_exists` all along. The consequence was that a backup left by an
    earlier session or surviving a restart never surfaced the button, exactly
    when the escape hatch was most wanted.
    """
    (tools_dir / "tools.yaml").write_text("tools: []\n")
    await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/tools/get"})
    msg = await client.receive_json()
    assert msg["result"]["backup_exists"] is False

    # A backup from "an earlier session" — nothing in this connection made it.
    (tools_dir / "tools.yaml.bak").write_text("tools: []\n")

    await client.send_json_auto_id({"type": "smartchain/tools/get"})
    msg = await client.receive_json()
    assert msg["result"]["backup_exists"] is True


async def test_the_reload_tools_action_leaks_no_resolved_secret(
    hass: HomeAssistant, tools_dir: Path
):
    """`smartchain.reload_tools` had the leak the websocket path was hardened
    against — and it is the louder of the two.

    `__init__.py` raised `HomeAssistantError(str(err))` on a `LoaderError`
    wrapping a `vol.Invalid`, whose message interpolates the offending value,
    and Home Assistant resolves `!secret` on mapping keys before validation
    runs. Calling the action from Developer Tools on a file the schema rejects
    therefore printed the resolved secret in the UI toast and wrote it into the
    automation trace, where it persists. Both callers now go through
    `_safe_loader_error`.
    """
    from homeassistant.exceptions import HomeAssistantError

    (tools_dir.parent / "secrets.yaml").write_text(f"my_key: {SECRET_VALUE}\n")
    (tools_dir / "tools.yaml").write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action:\n"
        "      type: template\n"
        "      value_template: pong\n"
        "      !secret my_key: extra\n"
    )
    await async_setup_component(hass, DOMAIN, {})

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(DOMAIN, "reload_tools", {}, blocking=True)

    assert SECRET_VALUE not in str(excinfo.value)
