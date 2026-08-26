"""Two panels saving tools.yaml at the same moment.

`smartchain/tools/save` is the one command whose whole point is a refusal:
`base_hash` exists so that an edit made against a file that has since changed
is rejected instead of merged. That promise is only worth anything if the
check and the write cannot be pulled apart — and the write runs in Home
Assistant's *thread pool*, so two saves genuinely run at once.

These tests drive the interleaving rather than hoping for it: the first save
is parked mid-operation, at the validation step, while the second is sent and
allowed to run to completion. Calling save twice in a row proves nothing at
all here.
"""

import asyncio
import hashlib
import stat
import threading
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from custom_components.smartchain.const import DOMAIN
from custom_components.smartchain.tools.loader import LoaderError, load_tools_file

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

TOOL_A = (
    "tools:\n"
    "  - name: alpha\n"
    "    description: from panel A\n"
    "    parameters: { type: object, properties: {} }\n"
    "    action: { type: template, value_template: a }\n"
)

TOOL_B = (
    "tools:\n"
    "  - name: bravo\n"
    "    description: from panel B\n"
    "    parameters: { type: object, properties: {} }\n"
    "    action: { type: template, value_template: b }\n"
)

TOOL_C = (
    "tools:\n"
    "  - name: charlie\n"
    "    description: a third revision\n"
    "    parameters: { type: object, properties: {} }\n"
    "    action: { type: template, value_template: c }\n"
)

# How long the parked save waits for its partner. Only the *fixed* code ever
# spends it: with the operation serialised the second save is refused before
# it reaches the gate, so nobody releases it and it times out. Unserialised,
# the second save releases it within milliseconds.
GATE_TIMEOUT = 0.5


@pytest.fixture
def tools_dir(hass: HomeAssistant, tmp_path_factory) -> Path:
    """A writable config dir with a smartchain/ subdir, set before setup.

    Mirrors the fixture of the same name in test_ws_tools_save.py — domain
    setup performs the first tools.yaml load, so the path has to be in place
    before `async_setup_component`.
    """
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    hass.config.config_dir = str(cdir)
    return cdir / "smartchain"


async def _get_hash(client) -> str | None:
    await client.send_json_auto_id({"type": "smartchain/tools/get"})
    msg = await client.receive_json()
    assert msg["success"], msg
    return msg["result"]["hash"]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class _ValidationGate:
    """Parks the first save inside `load_tools_file`, releases it on the second.

    `load_tools_file` is the validation step of a save: by the time it is
    called the temp file has been written and the staleness check has already
    passed, which is precisely the window the race lives in.
    """

    def __init__(self) -> None:
        self.parked = threading.Event()
        self.released = threading.Event()
        self.paths: list[Path] = []
        self._lock = threading.Lock()

    def __call__(self, path, config_dir):
        with self._lock:
            first = not self.paths
            self.paths.append(Path(path))
        if first:
            self.parked.set()
            self.released.wait(GATE_TIMEOUT)
        else:
            self.released.set()
        return load_tools_file(path, config_dir)

    async def wait_until_parked(self) -> None:
        for _ in range(500):
            if self.parked.is_set():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("the first save never reached validation")


async def test_two_concurrent_saves_leave_one_whole_file_and_refuse_the_other(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The scenario `base_hash` exists for, driven for real.

    Panel A's save is parked after it has written its temp file and passed
    its staleness check; panel B's save is then sent against the same
    `base_hash` and runs to completion. Three things must hold afterwards:

    * exactly one save reports success and the other is refused as `stale` —
      not "both saved", which is the answer that poisons the panel;
    * the file on disk is one of the two texts *whole*, never a blend of the
      two, which is what a shared temp file name produces;
    * the hash handed back to the winner is the hash of the winner's own
      text, and of the bytes actually on disk. A winner told "saved" while
      holding the other panel's hash has had its staleness protection
      inverted: its next save would sail past the check and overwrite work
      it never saw.
    """
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(TOOL_C)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    base_hash = await _get_hash(client)

    gate = _ValidationGate()
    payload_a = {"type": "smartchain/tools/save", "text": TOOL_A, "base_hash": base_hash}
    payload_b = {"type": "smartchain/tools/save", "text": TOOL_B, "base_hash": base_hash}

    with patch("custom_components.smartchain.websocket_api.load_tools_file", new=gate):
        await client.send_json_auto_id(payload_a)
        # Only send B once A is demonstrably mid-save: this is what makes the
        # two overlap instead of merely following one another.
        await gate.wait_until_parked()
        await client.send_json_auto_id(payload_b)

        first = await client.receive_json()
        second = await client.receive_json()

    assert first["success"], first
    assert second["success"], second
    by_id = {first["id"]: first["result"], second["id"]: second["result"]}
    submitted = {payload_a["id"]: TOOL_A, payload_b["id"]: TOOL_B}

    winners = [msg_id for msg_id, result in by_id.items() if result["ok"]]
    losers = [msg_id for msg_id, result in by_id.items() if not result["ok"]]
    assert len(winners) == 1, by_id
    assert by_id[losers[0]]["reason"] == "stale", by_id[losers[0]]

    winning_text = submitted[winners[0]]
    on_disk = tools_path.read_text()
    assert on_disk == winning_text, "disk holds text the winning save never submitted"
    assert by_id[winners[0]]["hash"] == _sha(winning_text)
    assert by_id[winners[0]]["hash"] == _sha(on_disk)
    assert list(tools_dir.glob("*.tmp")) == []


async def test_a_rollback_arriving_mid_save_does_not_report_a_file_it_never_left(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Rollback writes tools.yaml too, so it belongs behind the same lock.

    A rollback sent while a save is mid-flight used to swap the backup in,
    reload, hash the result and answer `ok` — and only then would the save
    it overlapped publish its own text on top. The panel took that hash as
    the state of the file and repainted the editor with the restored text,
    while disk held something else entirely: a success message describing a
    file that no longer existed.

    Serialised, the two are simply two operations in order: the save
    publishes, the rollback then undoes it, and the hash the rollback
    returns is the hash of what is actually on disk when it returns.
    """
    tools_path = tools_dir / "tools.yaml"
    backup = tools_dir / "tools.yaml.bak"
    tools_path.write_text(TOOL_C)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    # A first, uncontended save, so there is a backup to roll back to.
    await client.send_json_auto_id(
        {
            "type": "smartchain/tools/save",
            "text": TOOL_B,
            "base_hash": await _get_hash(client),
        }
    )
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["ok"] is True, msg
    base_hash = await _get_hash(client)

    gate = _ValidationGate()
    with patch("custom_components.smartchain.websocket_api.load_tools_file", new=gate):
        await client.send_json_auto_id(
            {"type": "smartchain/tools/save", "text": TOOL_A, "base_hash": base_hash}
        )
        await gate.wait_until_parked()
        await client.send_json_auto_id({"type": "smartchain/tools/rollback"})

        save_msg = await client.receive_json()
        rollback_msg = await client.receive_json()

    assert save_msg["success"] and save_msg["result"]["ok"] is True, save_msg
    assert rollback_msg["success"] and rollback_msg["result"]["ok"] is True, rollback_msg

    on_disk = tools_path.read_text()
    assert rollback_msg["result"]["hash"] == _sha(on_disk)
    # The rollback ran after the save, so it undid it: the file is what the
    # save had backed up, and the save's own text is now the backup.
    assert on_disk == TOOL_B
    assert backup.read_text() == TOOL_A
    assert list(tools_dir.glob("*.tmp")) == []


async def test_the_temp_file_is_unique_per_save_and_sits_beside_the_target(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Two properties of the temp file, both load-bearing.

    Unique per save: a fixed `tools.yaml.tmp` is a shared mutable buffer
    between concurrent saves, so one save validates and publishes another's
    bytes.

    In the target's own directory: `os.replace` is only atomic within one
    filesystem, and the whole safety argument rests on that replace being
    atomic. A temp file in the system temp dir would silently turn it into a
    copy across a device boundary.
    """
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(TOOL_C)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    seen: list[Path] = []

    def recording(path, config_dir):
        seen.append(Path(path))
        return load_tools_file(path, config_dir)

    with patch("custom_components.smartchain.websocket_api.load_tools_file", new=recording):
        for text in (TOOL_A, TOOL_B):
            await client.send_json_auto_id(
                {
                    "type": "smartchain/tools/save",
                    "text": text,
                    "base_hash": await _get_hash(client),
                }
            )
            msg = await client.receive_json()
            assert msg["success"] and msg["result"]["ok"] is True, msg

    assert len(seen) == 2
    assert seen[0] != seen[1], "both saves staged through the same temp file name"
    for tmp in seen:
        assert tmp != tools_path
        assert tmp.parent == tools_dir, "temp file left the target's filesystem"
    assert list(tools_dir.glob("*.tmp")) == []


async def test_a_save_keeps_the_file_mode_it_found(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """Saving edits the contents of tools.yaml, not its permissions.

    The temp file a save stages through is created private to Home
    Assistant, as a temp file should be; replacing the target with it must
    not hand those permissions to the target as well. A user who made
    tools.yaml group-readable for a file-editor add-on would find it
    unreadable after the first save from the panel — a breakage with no
    error attached to it.
    """
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(TOOL_C)
    tools_path.chmod(0o640)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/tools/save",
            "text": TOOL_A,
            "base_hash": await _get_hash(client),
        }
    )
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["ok"] is True, msg

    assert tools_path.read_text() == TOOL_A
    assert stat.S_IMODE(tools_path.stat().st_mode) == 0o640


async def test_a_first_save_creates_the_file_private_to_home_assistant(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The other half of the mode rule, and the one with no prior mode to
    copy: a tools.yaml that did not exist before is created owner-only. It
    names `!secret` keys, and nothing else on the system has any business
    reading it until the user says otherwise."""
    assert not (tools_dir / "tools.yaml").exists()
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/tools/save", "text": TOOL_A, "base_hash": None}
    )
    msg = await client.receive_json()
    assert msg["success"] and msg["result"]["ok"] is True, msg

    assert stat.S_IMODE((tools_dir / "tools.yaml").stat().st_mode) == 0o600


async def test_reload_failed_tells_the_panel_a_backup_is_still_there(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """After a failed reload the restore *swaps*, so a backup still exists.

    `_restore_backup` puts `.bak` back onto the target and makes the file it
    displaced the new `.bak` — that is what makes every rollback undoable.
    The refusal has to say so: with no `backup_exists` on the wire the panel
    can only guess, and it guesses that the restore consumed the backup and
    hides Rollback — removing the escape hatch at the exact moment the user
    is looking for it.
    """
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(TOOL_C)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    base_hash = await _get_hash(client)

    with patch(
        "custom_components.smartchain._reload_registry",
        new=AsyncMock(side_effect=LoaderError("boom")),
    ):
        await client.send_json_auto_id(
            {"type": "smartchain/tools/save", "text": TOOL_A, "base_hash": base_hash}
        )
        msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["ok"] is False
    assert msg["result"]["reason"] == "reload_failed"
    # Ground truth: the swap left the displaced text as the new backup.
    backup = tools_dir / "tools.yaml.bak"
    assert backup.is_file()
    assert backup.read_text() == TOOL_A
    assert tools_path.read_text() == TOOL_C
    assert msg["result"]["backup_exists"] is True
    # ...and precisely because of that, Rollback must not be offered here: the
    # backup on disk is TOOL_A, the text that just refused to load, so restoring
    # it walks the user into the breakage instead of out of it. `backup_exists`
    # answers "is there a file"; `restored` answers "is there anything left to
    # undo", which is the question the button asks.
    assert msg["result"]["restored"] is True


async def test_reload_failed_on_a_first_save_reports_no_backup(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The other half of the same claim, so `backup_exists` cannot be a
    constant `True`: on a fresh install there was no previous file, the
    restore removes the one just written, and nothing is left to roll back
    to."""
    assert not (tools_dir / "tools.yaml").exists()
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)

    with patch(
        "custom_components.smartchain._reload_registry",
        new=AsyncMock(side_effect=LoaderError("boom")),
    ):
        await client.send_json_auto_id(
            {"type": "smartchain/tools/save", "text": TOOL_A, "base_hash": None}
        )
        msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["reason"] == "reload_failed"
    assert not (tools_dir / "tools.yaml.bak").exists()
    assert msg["result"]["backup_exists"] is False


async def test_a_failed_rollback_does_not_claim_anything_was_restored(
    hass: HomeAssistant, hass_ws_client, tools_dir: Path
):
    """The neighbouring case, and the reason `restored` is a field rather than
    a rule about `reload_failed`.

    A rollback whose own reload fails undid nothing on the user's behalf — the
    file it installed is the one now failing — so the escape hatch has to stay
    reachable. Sending `restored` here too would hide it.
    """
    tools_path = tools_dir / "tools.yaml"
    tools_path.write_text(TOOL_C)
    (tools_dir / "tools.yaml.bak").write_text(TOOL_A)
    await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)

    with patch(
        "custom_components.smartchain._reload_registry",
        new=AsyncMock(side_effect=LoaderError("boom")),
    ):
        await client.send_json_auto_id({"type": "smartchain/tools/rollback"})
        msg = await client.receive_json()

    assert msg["success"], msg
    assert msg["result"]["ok"] is False
    assert msg["result"]["reason"] == "reload_failed"
    assert msg["result"].get("restored") is not True
