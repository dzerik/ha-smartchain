# Editing tools.yaml from the panel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the panel's read-only `tools.yaml` view into an editor with a validity check, a backup and a rollback.

**Architecture:** Raw text in, raw text out — nothing passes through the YAML parser on the way to disk, so `!secret` references survive as references. A save writes a temp file, validates it with the integration's own loader, backs up the current file, replaces atomically, then reloads; a failing reload restores. A content hash refuses a save when the file changed underneath.

**Tech Stack:** Python 3.13, Home Assistant 2026.8, `homeassistant.components.websocket_api`, plain ES modules with no build step.

**Spec:** `docs/superpowers/specs/2026-08-25-tools-yaml-editing-design.md`

**This runs on the user's live system.** `main` is deployed to their Home Assistant. Every write path here touches a real configuration file that, if broken, disables their custom tools, MCP servers and memory subsystem at once.

## Global Constraints

- **No new runtime dependencies**; `manifest.json` must not change; version stays `5.0.0`.
- **Admin-only**, decorated `@websocket_api.require_admin`, then `@websocket_api.websocket_command({...})`, then `@websocket_api.async_response`.
- **No response and no error message may carry a resolved secret.** `load_tools_file` resolves `!secret`, HA's YAML loader resolves it on mapping **keys** as well as values, and voluptuous embeds offending values in its messages. A leak through `err.path` already shipped once and was caught in review.
- **All blocking file I/O runs in an executor.** The loader says so itself.
- Websocket tests need the domain set up: `pytestmark = pytest.mark.usefixtures("enable_custom_integrations")` and `await async_setup_component(hass, DOMAIN, {})`.
- Test: `uv run --prerelease=allow pytest tests/ -q` (currently 813 passing)
- Lint: `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .`
- Break-it checks **substitute a wrong value, never delete code** — deletion proves only that a test notices absence.
- Do not touch `panel/components/camera-tab.js`.
- Every commit message ends with:
  ```

  🤖 Generated with [Claude Code](https://claude.com/claude-code)

  Co-Authored-By: Claude <noreply@anthropic.com>
  ```

---

### Task 1: Distinguish a parse error from a schema error, and hash the file

**Files:** modify `custom_components/smartchain/websocket_api.py`; test `tests/test_ws_tools_errors.py` (create)

**Interfaces produced:** `_safe_loader_error(err)` returns a message carrying line and column for a parse failure and a bare type name otherwise; `smartchain/tools/get` gains `hash`.

- [ ] **Step 1: Write the failing test**

```python
"""Loader errors: a parse failure may say where; a schema failure may not."""

SECRET = "sk-must-not-appear"


def _write(cfg, tools_text):
    (cfg / "secrets.yaml").write_text(f'my_key: "{SECRET}"\n')
    (cfg / "smartchain").mkdir(exist_ok=True)
    (cfg / "smartchain" / "tools.yaml").write_text(tools_text)


async def test_a_syntax_error_reports_where(hass, hass_ws_client, tmp_path, entry):
    """A text editor without a line number is much harder to use, and the
    parser fails before any !secret is resolved."""
    _write(tmp_path, "tools:\n  - name: x\n    broken: [unclosed\n")
    # ... point hass.config.config_dir at tmp_path, call smartchain/tools/validate
    assert msg["result"]["valid"] is False
    assert "line" in msg["result"]["error"].lower()


async def test_a_syntax_error_carries_no_secret(hass, hass_ws_client, tmp_path, entry):
    _write(tmp_path, "tools:\n  - name: x\n    k: !secret my_key\n    broken: [unclosed\n")
    ...
    assert SECRET not in json.dumps(msg)


async def test_a_schema_error_reports_only_a_type(hass, hass_ws_client, tmp_path, entry):
    """Voluptuous embeds the offending value, and HA resolves !secret on keys."""
    _write(tmp_path, "tools:\n  - name: x\n    action:\n      type: rest\n      !secret my_key: y\n")
    ...
    assert SECRET not in json.dumps(msg)
    assert "line" not in msg["result"]["error"].lower()


async def test_an_unfamiliar_cause_falls_back_to_the_type_name(hass, ...):
    """The whitelist's point: an exception nobody enumerated must be withheld,
    not forwarded."""
    # patch load_tools_file to raise LoaderError from an unusual cause
    ...
```

Write these out fully against the installed loader. The `entry` fixture and the config-dir redirection follow `tests/test_ws_tools.py`, which already does both.

- [ ] **Step 2: Run to confirm failure**

- [ ] **Step 3: Implement the discriminator**

```python
# A parse failure comes from the YAML reader, which fails *before* any
# `!secret` is resolved, so its message carries a line and column and no
# credential. A schema failure comes from voluptuous, which embeds the
# offending value — and HA resolves `!secret` on mapping keys, so that value
# can be a credential.
#
# Whitelist the safe case. A blacklist would forward every cause nobody
# thought of, and this file has already shipped one leak from exactly that.
_PARSE_ERROR_CAUSES = (yaml.YAMLError, HomeAssistantError)


def _safe_loader_error(err: LoaderError) -> str:
    cause = err.__cause__
    if isinstance(cause, _PARSE_ERROR_CAUSES) and not isinstance(cause, vol.Invalid):
        return str(cause)
    return type(cause).__name__ if cause is not None else type(err).__name__
```

**Both facts were verified while planning, so do not re-check them:** Home
Assistant's YAML loader raises `HomeAssistantError` for a syntax error, whose MRO
is `HomeAssistantError → Exception` — it is **not** a `yaml.YAMLError` subclass.
And `vol.Invalid` is a subclass of **neither** whitelist entry, so a schema
failure cannot satisfy the test.

Keep the explicit `not isinstance(cause, vol.Invalid)` guard anyway. It is
redundant today and cheap; it stops a future Home Assistant that made `Invalid`
inherit from `HomeAssistantError` from silently turning the whitelist into a
leak.

- [ ] **Step 4: Add the hash to `tools/get`**

`hash` is `hashlib.sha256(text.encode()).hexdigest()` of exactly the text served, and `None` when the file does not exist. Task 2's save compares against it.

- [ ] **Step 5: Run tests, suite, lint**

- [ ] **Step 6: Break-it check**

Substitute, do not delete. Make `_safe_loader_error` forward `str(cause)` unconditionally: the schema test must fail naming the leaked secret. Then make it return the type name unconditionally: the line-number test must fail. Revert both.

- [ ] **Step 7: Commit**

---

### Task 2: Saving and rolling back

**Files:** modify `custom_components/smartchain/websocket_api.py`; test `tests/test_ws_tools_save.py` (create)

**Interfaces produced:** `smartchain/tools/save` taking `text` and `base_hash`; `smartchain/tools/rollback`.

- [ ] **Step 1: Write the failing tests**

The properties, each of which must have its own test:

1. **A `!secret` reference survives a round trip.** Load a file containing one, save the same text back, assert the bytes on disk are byte-identical and the reference is still `!secret my_key`. *This is the property the whole design exists to protect.*
2. **An invalid file is never written.** Save malformed YAML; the original file is byte-identical afterwards, and no `.tmp` remains.
3. **A stale `base_hash` is refused** with reason `stale`, and the file is untouched.
4. **The backup precedes the replace**, and `rollback` restores the previous bytes exactly.
5. **A failing reload restores the previous file.** Patch `_reload_registry` to raise; assert the file is back to its old bytes and the refusal reason is `reload_failed`.
6. **The directory is created** when `/config/smartchain/` does not exist — the fresh-install state, and the user's actual current state.
7. **No refusal carries a resolved secret**, on every path.
8. **Both commands are admin-only.**

- [ ] **Step 2: Run to confirm failure**

- [ ] **Step 3: Implement `save`**

The order is the safety argument and must not be rearranged:

```python
    # 1. refuse if the file moved under us
    current = await hass.async_add_executor_job(_read_tools_file, path)
    if _hash_of(current) != msg["base_hash"]:
        connection.send_result(msg["id"], {"ok": False, "reason": "stale"})
        return

    # 2. write a temp file beside the target — same directory, so os.replace
    #    stays on one filesystem and therefore stays atomic
    # 3. validate the temp file with the real loader, not a second one
    # 4. back up the current file
    # 5. os.replace(tmp, path)  — atomic; an in-place write could truncate
    # 6. reload; on failure restore from the backup, reload again, and report
```

Every step runs in an executor. Clean up the temp file on **every** exit path, including the exception ones — a stale `.tmp` beside a config file is confusing at best.

Reasons are `stale`, `invalid`, `write_failed`, `reload_failed`, each distinct because the panel responds differently to each.

- [ ] **Step 4: Implement `rollback`**

Restores `.bak` onto the target through the same atomic replace, then reloads. Refuses with `no_backup` when there is none. It must **not** validate the backup first: the backup is by construction a file that once validated, and refusing to restore it would strand the user exactly when they most need the escape.

- [ ] **Step 5: Run tests, suite, lint**

- [ ] **Step 6: Break-it check**

- Reorder so the backup is taken *after* the replace: the rollback test must fail.
- Make the reload-failure path skip the restore: that test must fail.
- Make `save` ignore `base_hash`: the stale test must fail.

Revert each.

- [ ] **Step 7: Commit**

---

### Task 3: The editor

**Files:** modify `custom_components/smartchain/panel/components/tools-tab.js`, `panel/styles.js`

- [ ] **Step 1: Replace the read-only view**

A monospace `<textarea>`, plus Validate, Save and Rollback. No syntax highlighting and no third-party editor: the panel has no build step and adding one for this costs more than it returns.

- **Save** is disabled until the text differs from what was loaded, and sends the `base_hash` that came with it.
- **Validate** checks without writing, at any time.
- **Rollback** appears only when a backup exists and confirms first — it discards what is currently on disk.
- A `stale` refusal offers to reload and **says plainly that reloading discards the unsaved edit**. Do not reload silently.
- An `invalid` refusal shows the reported location; a `reload_failed` refusal says the previous file was restored, because otherwise the user cannot tell what state they are in.
- On success, show the new hash's effect: the editor's baseline becomes the saved text so Save disables again.

Every call guarded so a failure toasts and leaves the editor usable **with the user's text intact** — losing an edit to a failed save would be worse than the failure.

- [ ] **Step 2: Do not let a `hass` tick repaint the editor**

The tab's `set hass` already guards with a `first` flag. Confirm that a repaint from any path cannot replace the textarea while it holds unsaved text — this is the same class as the bug the user reported on the live system, where a state change destroyed an open form.

- [ ] **Step 3: Verify by running it**

There is no browser here. Extend the jsdom harness used for the earlier panel fixes: mount the tab, type into the textarea, push `hass` twenty times, and assert the text survives and the node is the same. Assert Save sends the `base_hash` it was given, and that a `stale` response does not silently overwrite the editor.

Report the assertion counts, and write a browser checklist for the user covering a valid save, an invalid save, a rollback, and an edit made simultaneously through a file editor.

- [ ] **Step 4: Run the suite and lint** to prove no Python moved, then commit.

---

## Self-Review

**Spec coverage.** §3 write path → Task 2 Step 3, order preserved. §4 concurrency → Task 1 Step 4 and Task 2's stale test. §5 commands → Tasks 1, 2. §6 error content → Task 1, with the whitelist. §7 editor → Task 3. §8 testing → the eight properties in Task 2 Step 1 plus Task 1's four. §9 deferred → nothing to build.

**Placeholders.** Task 1's and Task 2's tests are given as properties with partial code rather than complete bodies. That is deliberate and the same call made twice before on this project: both need fixtures that redirect `hass.config.config_dir` and construct `secrets.yaml`, whose exact form must be established against the installed Home Assistant. `tests/test_ws_tools.py` already does this and is the model. Inventing the bodies here would produce code that reads as authoritative and does not run.

**Type consistency.** `_safe_loader_error`, `_read_tools_file`, `_tools_yaml_path`, `_reload_registry` are existing names used unchanged. `hash` is sha256 hex of the served text in both the producer (Task 1) and the consumer (Task 2).

**Settled while planning rather than delegated:** Home Assistant's YAML loader raises `HomeAssistantError` for a syntax error and it is not a `yaml.YAMLError`; `vol.Invalid` subclasses neither whitelist entry, so a schema failure cannot pass the test. Both recorded in Task 1 Step 3, with the redundant `vol.Invalid` guard kept as insurance against a future HA reparenting that class.
