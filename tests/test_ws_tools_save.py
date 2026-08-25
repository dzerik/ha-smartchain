"""Saving and rolling back tools.yaml through the panel's websocket API.

A malformed tools.yaml disables every custom tool, every MCP server and the
memory subsystem at once, and `main` here is deployed to a live Home
Assistant instance. These tests establish the write path's safety argument:
a stale edit is refused rather than merged, an invalid file is never
written, a backup always precedes the atomic replace, a reload failure rolls
back automatically, no refusal ever carries a resolved `!secret`, and the
whole thing works from a fresh install where `/config/smartchain/` does not
exist yet.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.smartchain.const import DOMAIN
from custom_components.smartchain.tools.loader import LoaderError

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SECRET_VALUE = "sk-must-not-appear"

VALID_TOOL = (
    "tools:\n"
    "  - name: ping\n"
    "    description: x\n"
    "    parameters: { type: object, properties: {} }\n"
    "    action: { type: template, value_template: pong }\n"
)

VALID_TOOL_V2 = (
    "tools:\n"
    "  - name: pong\n"
    "    description: y\n"
    "    parameters: { type: object, properties: {} }\n"
    "    action: { type: template, value_template: ping }\n"
)


@pytest.fixture
def tools_dir(hass: HomeAssistant, tmp_path_factory) -> Path:
    """Point hass.config.config_dir at a writable temp dir with a smartchain/ subdir.

    Must be set before async_setup_component(hass, DOMAIN, {}) runs, since
    domain setup itself performs the first tools.yaml load. Mirrors the
    fixture of the same name in test_ws_tools.py — not shared via conftest
    because that file scopes it to itself.
    """
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    hass.config.config_dir = str(cdir)
    return cdir / "smartchain"


@pytest.fixture
def config_dir(hass: HomeAssistant, tmp_path_factory) -> Path:
    """Point hass.config.config_dir at a writable temp dir WITHOUT a
    smartchain/ subdir — the fresh-install state, and the user's actual
    current state on their live system."""
    cdir = tmp_path_factory.mktemp("ha")
    hass.config.config_dir = str(cdir)
    return cdir


async def _get_hash(client) -> str | None:
    await client.send_json_auto_id({"type": "smartchain/tools/get"})
    msg = await client.receive_json()
    assert msg["success"], msg
    return msg["result"]["hash"]


async def test_secret_reference_survives_a_save_round_trip_byte_for_byte(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """This is the property the whole design exists to protect: raw text in,
    raw text out. Nothing on this path parses the submitted text and
    re-serialises it, so `!secret openai_key` stays a reference rather than
    being written back as the resolved key."""
    (tools_dir.parent / "secrets.yaml").write_text(f"my_key: {SECRET_VALUE}\n")
    original = (
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
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(original)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    base_hash = await _get_hash(client)

    await client.send_json_auto_id(
        {"type": "smartchain/tools/save", "text": original, "base_hash": base_hash}
    )
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["ok"] is True
    assert tools_path.read_bytes() == original.encode()
    assert "!secret my_key" in tools_path.read_text()
    assert SECRET_VALUE not in tools_path.read_text()
    assert not (tools_dir / "tools.yaml.tmp").exists()


async def test_invalid_file_is_never_written(hass: HomeAssistant, hass_ws_client, tools_dir: Path):
    """Malformed YAML must not reach disk, and no temp file may survive it."""
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(VALID_TOOL)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    base_hash = await _get_hash(client)

    broken = "tools:\n  - name: ping\n    action: [unterminated\n"
    await client.send_json_auto_id(
        {"type": "smartchain/tools/save", "text": broken, "base_hash": base_hash}
    )
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["ok"] is False
    assert msg["result"]["reason"] == "invalid"
    assert tools_path.read_text() == VALID_TOOL
    assert not (tools_dir / "tools.yaml.tmp").exists()


async def test_stale_base_hash_is_refused(hass: HomeAssistant, hass_ws_client, tools_dir: Path):
    """The file may have changed underneath the editor — through a file
    editor, SSH or a second tab. Refusing is the whole behaviour: no merge,
    no last-write-wins."""
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(VALID_TOOL)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    base_hash = await _get_hash(client)

    # Someone else edits the file directly, after the panel loaded its copy.
    concurrent_edit = "tools: []\n"
    tools_path.write_text(concurrent_edit)

    await client.send_json_auto_id(
        {"type": "smartchain/tools/save", "text": VALID_TOOL_V2, "base_hash": base_hash}
    )
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["ok"] is False
    assert msg["result"]["reason"] == "stale"
    assert tools_path.read_text() == concurrent_edit
    assert not (tools_dir / "tools.yaml.tmp").exists()


async def test_backup_precedes_replace_and_rollback_restores_exactly(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The backup must hold the PRE-save bytes, not the new ones — this only
    holds if the backup is taken before `os.replace`, not after. Rollback
    then restores exactly what was there before the save."""
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(VALID_TOOL)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    base_hash = await _get_hash(client)

    await client.send_json_auto_id(
        {"type": "smartchain/tools/save", "text": VALID_TOOL_V2, "base_hash": base_hash}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["ok"] is True

    assert tools_path.read_text() == VALID_TOOL_V2
    backup = tools_dir / "tools.yaml.bak"
    assert backup.is_file()
    # Proves the backup was copied from the file as it stood BEFORE the
    # replace — if the copy happened after, this would read VALID_TOOL_V2.
    assert backup.read_text() == VALID_TOOL

    await client.send_json_auto_id({"type": "smartchain/tools/rollback"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["ok"] is True
    assert tools_path.read_text() == VALID_TOOL


async def test_failing_reload_restores_the_previous_file(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """A file can validate and still fail to load — an MCP server that will
    not start, an embeddings binding that no longer resolves. The user asked
    to save a file, not lose their tools."""
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(VALID_TOOL)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    base_hash = await _get_hash(client)

    with patch(
        "custom_components.smartchain._reload_registry",
        new=AsyncMock(side_effect=LoaderError("boom")),
    ):
        await client.send_json_auto_id(
            {"type": "smartchain/tools/save", "text": VALID_TOOL_V2, "base_hash": base_hash}
        )
        msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["ok"] is False
    assert msg["result"]["reason"] == "reload_failed"
    assert tools_path.read_text() == VALID_TOOL
    assert not (tools_dir / "tools.yaml.tmp").exists()


async def test_smartchain_directory_is_created_on_a_fresh_install(
    hass: HomeAssistant, hass_ws_client, config_dir: Path
):
    """`/config/smartchain/` is absent on a fresh install — and on the
    user's actual current system. Save must create it rather than fail."""
    smartchain_dir = config_dir / "smartchain"
    assert not smartchain_dir.exists()
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    base_hash = await _get_hash(client)
    assert base_hash is None

    await client.send_json_auto_id(
        {"type": "smartchain/tools/save", "text": VALID_TOOL, "base_hash": base_hash}
    )
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["ok"] is True
    assert smartchain_dir.is_dir()
    assert (smartchain_dir / "tools.yaml").read_text() == VALID_TOOL


async def test_save_of_a_secret_used_as_an_extra_key_leaks_nothing(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Same leak vector `_safe_loader_error` already guards on `validate` and
    `reload`: `!secret` resolves on mapping keys too, and every schema block
    uses PREVENT_EXTRA, so a `!secret` used as an unexpected key would put a
    resolved credential in `err.path` if that path were ever forwarded."""
    (tools_dir.parent / "secrets.yaml").write_text(f"my_key: {SECRET_VALUE}\n")
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(VALID_TOOL)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    base_hash = await _get_hash(client)

    bad = (
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action:\n"
        "      type: template\n"
        "      value_template: pong\n"
        "      !secret my_key: extra\n"
    )
    await client.send_json_auto_id(
        {"type": "smartchain/tools/save", "text": bad, "base_hash": base_hash}
    )
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["ok"] is False
    assert SECRET_VALUE not in json.dumps(msg)
    assert tools_path.read_text() == VALID_TOOL


async def test_reload_failed_refusal_leaks_no_secret(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The reload_failed path forwards the loader error through the same
    `_safe_loader_error` scrubbing as validate/reload — never the raw
    message, which for a schema failure can embed a resolved value."""
    (tools_dir.parent / "secrets.yaml").write_text(f"my_key: {SECRET_VALUE}\n")
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(VALID_TOOL)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    base_hash = await _get_hash(client)

    with patch(
        "custom_components.smartchain._reload_registry",
        new=AsyncMock(side_effect=LoaderError(f"tools.yaml validation error: {SECRET_VALUE}")),
    ):
        await client.send_json_auto_id(
            {"type": "smartchain/tools/save", "text": VALID_TOOL_V2, "base_hash": base_hash}
        )
        msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["ok"] is False
    assert SECRET_VALUE not in json.dumps(msg)


async def test_save_requires_admin(
    hass: HomeAssistant, hass_ws_client, hass_admin_user, tools_dir: Path
):
    hass_admin_user.groups = []
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/tools/save", "text": VALID_TOOL, "base_hash": None}
    )
    msg = await client.receive_json()

    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"


async def test_rollback_requires_admin(
    hass: HomeAssistant, hass_ws_client, hass_admin_user, tools_dir: Path
):
    hass_admin_user.groups = []
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/rollback"})
    msg = await client.receive_json()

    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"


async def test_rollback_without_a_backup_is_refused(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """No backup exists until a save has succeeded at least once."""
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/rollback"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["ok"] is False
    assert msg["result"]["reason"] == "no_backup"
