"""Loader errors: a parse failure may say where; a schema failure may not.

`_safe_loader_error` (custom_components/smartchain/websocket_api.py) must
widen what a *parse* error may say — a text editor without a line number is
much harder to use — without widening what a *schema* error may say, because
voluptuous embeds the offending value in its message and Home Assistant
resolves `!secret` on mapping keys as well as values. A prior review already
caught a secret reaching the wire through `err.path` this way.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.smartchain.const import DOMAIN
from custom_components.smartchain.tools.loader import LoaderError

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SECRET = "sk-must-not-appear"


def _write(cfg: Path, tools_text: str) -> None:
    (cfg / "secrets.yaml").write_text(f'my_key: "{SECRET}"\n')
    (cfg / "smartchain").mkdir(exist_ok=True)
    (cfg / "smartchain" / "tools.yaml").write_text(tools_text)


async def test_a_syntax_error_reports_where(hass: HomeAssistant, hass_ws_client, tmp_path: Path):
    """A text editor without a line number is much harder to use, and the
    parser fails before any !secret is resolved."""
    _write(tmp_path, "tools:\n  - name: x\n    broken: [unclosed\n")
    hass.config.config_dir = str(tmp_path)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/validate"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["valid"] is False
    assert "line" in msg["result"]["error"].lower()


async def test_a_syntax_error_carries_no_secret(
    hass: HomeAssistant, hass_ws_client, tmp_path: Path
):
    """A `!secret` reference sitting elsewhere in the same broken file must
    still not resolve — the parser fails before it ever gets there."""
    _write(
        tmp_path,
        "tools:\n  - name: x\n    k: !secret my_key\n    broken: [unclosed\n",
    )
    hass.config.config_dir = str(tmp_path)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/validate"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["valid"] is False
    assert SECRET not in json.dumps(msg)


async def test_a_schema_error_reports_only_a_type(
    hass: HomeAssistant, hass_ws_client, tmp_path: Path
):
    """Voluptuous embeds the offending value, and HA resolves !secret on
    mapping keys — so a schema failure must report the exception type only,
    never a message and never a line/column."""
    _write(
        tmp_path,
        "tools:\n"
        "  - name: x\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action:\n"
        "      type: rest\n"
        "      !secret my_key: y\n",
    )
    hass.config.config_dir = str(tmp_path)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/tools/validate"})
    msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["valid"] is False
    assert SECRET not in json.dumps(msg)
    assert "line" not in msg["result"]["error"].lower()


async def test_an_unfamiliar_cause_falls_back_to_the_type_name(
    hass: HomeAssistant, hass_ws_client, tmp_path: Path
):
    """The whitelist's point: an exception nobody enumerated must be
    withheld, not forwarded."""
    hass.config.config_dir = str(tmp_path)
    await async_setup_component(hass, DOMAIN, {})

    def _raise(*args, **kwargs):
        try:
            raise RuntimeError(f"boom {SECRET}")
        except RuntimeError as err:
            raise LoaderError("tools.yaml unexpected error") from err

    with patch(
        "custom_components.smartchain.websocket_api.load_tools_file",
        side_effect=_raise,
    ):
        client = await hass_ws_client(hass)
        await client.send_json_auto_id({"type": "smartchain/tools/validate"})
        msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["valid"] is False
    assert msg["result"]["error"] == "RuntimeError"
    assert SECRET not in json.dumps(msg)
