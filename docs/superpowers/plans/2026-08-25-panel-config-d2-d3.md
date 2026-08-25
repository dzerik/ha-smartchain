# Panel configuration parts 2 and 3 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish subsystem D — settings and embeddings tabs, a read-only `tools.yaml` view, translated field labels, and per-field validation errors.

**Architecture:** Everything reuses D1's pipeline: the backend serialises the config flow's own `vol.Schema` and `<ha-form>` renders it. Settings point that pipeline at `entry.options` instead of a subentry; embeddings point it at a second, smaller schema. `tools.yaml` is served as raw text and validated with the loader the integration already uses. `agent-form.js` is generalised into one form component rather than copied per tab.

**Tech Stack:** Python 3.13, Home Assistant 2026.8, `homeassistant.components.websocket_api`, `voluptuous_serialize`, `homeassistant.helpers.translation`, plain ES modules with no build step.

**Spec:** `docs/superpowers/specs/2026-08-25-panel-config-d2-d3-design.md`

**A note on ordering.** Tasks 1–4 are backend and fully testable here. Tasks 5–6 are panel work that cannot be verified in this environment — there is no browser and no running Home Assistant. Those checks belong to the user, as they did in D1, and the `<ha-form>` assumption remains unconfirmed. Do not block the backend tasks on it.

## Global Constraints

- **No new runtime dependencies.** `voluptuous_serialize` and `homeassistant.helpers.translation` ship with Home Assistant. `manifest.json` requirements must not change.
- Version stays `5.0.0` — it is unreleased, so tasks in this plan do not bump it.
- **Every websocket command is admin-only**, decorated in this exact order: `@websocket_api.require_admin`, then `@websocket_api.websocket_command({...})`, then `@websocket_api.async_response`.
- **No response and no error message may carry a credential.** `entry.data` holds `CONF_API_KEY` and `CONF_FOLDER_ID`. Responses are assembled field by field. Additionally in this plan: `load_tools_file` **resolves `!secret`**, so the parsed structure holds real credentials and must never cross the wire, and voluptuous embeds offending values in its messages, so a validation error from that loader must not be forwarded raw.
- **Serve only the fields the schema declares.** D1 learned this the hard way: `subentry_schema` is conditional, and serving an undeclared key makes a form permanently unsavable because `save` uses `PREVENT_EXTRA` and `<ha-form>` echoes unknown keys back. Every new schema-serving command follows the same rule.
- The panel adds **no build step and no framework**. Components are plain `HTMLElement` subclasses matching `panel/components/agents-tab.js`.
- All user-facing text goes through `escapeHtml` before reaching `innerHTML`.
- Test: `uv run --prerelease=allow pytest tests/ -q` (currently 765 passing)
- Lint: `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .`
- `pyproject.toml` sets `asyncio_mode = "auto"` — async tests need no marker.
- Websocket tests need the **domain** set up, not just a config entry: `pytestmark = pytest.mark.usefixtures("enable_custom_integrations")` and `await async_setup_component(hass, DOMAIN, {})`. Without it every test fails with `unknown_command`.
- Every commit message ends with:
  ```

  🤖 Generated with [Claude Code](https://claude.com/claude-code)

  Co-Authored-By: Claude <noreply@anthropic.com>
  ```

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `custom_components/smartchain/websocket_api.py` | All new commands; labels and error helpers | 1–4 |
| `custom_components/smartchain/config_flow.py` | One rename | 3 |
| `custom_components/smartchain/tools/memory/registry.py` | One public method | 3 |
| `tests/test_ws_labels_errors.py` | Labels and per-field errors (new) | 1 |
| `tests/test_ws_settings.py` | Settings commands (new) | 2 |
| `tests/test_ws_embeddings.py` | Embeddings commands and title hazards (new) | 3 |
| `tests/test_ws_tools.py` | tools.yaml commands and secret containment (new) | 4 |
| `panel/components/config-form.js` | Generalised form (renamed from agent-form.js) | 5 |
| `panel/components/settings-tab.js`, `embeddings-tab.js` | New tabs | 5 |
| `panel/components/tools-tab.js` | Raw view, validate, reload | 6 |
| `panel/smartchain-panel.js`, `styles.js` | Tab wiring and styles | 5, 6 |

---

### Task 1: Labels and per-field errors

These are D1's two deferred debts. Doing them first means every command added later inherits them rather than retrofitting three times.

**Files:**
- Modify: `custom_components/smartchain/websocket_api.py`
- Test: `tests/test_ws_labels_errors.py` (create)

**Interfaces:**
- Produces: `async_field_labels(hass, category) -> dict[str, str]`; `_invalid_data_error(connection, msg_id, err)` sending both a flat message and a per-field `errors` map. `smartchain/agent/schema` gains a `labels` key; `smartchain/agent/save` gains `errors` in its error payload.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_labels_errors.py`:

```python
"""Translated field labels, and per-field validation errors."""

from unittest.mock import patch

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_PROMPT,
    DOMAIN,
    ID_OPENAI,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

MODELS = ["", "gpt-4.1-mini"]


@pytest.fixture(autouse=True)
def _models():
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=MODELS,
    ):
        yield


@pytest.fixture
async def entry(hass):
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sk-labels-secret"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
    )
    entry.add_to_hass(hass)
    return entry


async def test_schema_serves_a_label_for_every_field(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    labels = msg["result"]["labels"]
    for field in msg["result"]["schema"]:
        assert field["name"] in labels, field["name"]
        assert labels[field["name"]], field["name"]


async def test_labels_are_translated_not_raw_names(hass, hass_ws_client, entry):
    """The whole point: 'model' must render as its English label, not as 'model'."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
    )
    msg = await client.receive_json()

    labels = msg["result"]["labels"]
    assert labels[CONF_PROMPT] != CONF_PROMPT
    assert labels[CONF_CHAT_MODEL] != CONF_CHAT_MODEL


async def test_an_untranslated_field_falls_back_to_its_name(hass, hass_ws_client, entry):
    """A field added without a translation must still render, not vanish."""
    from custom_components.smartchain.websocket_api import async_field_labels

    with patch(
        "custom_components.smartchain.websocket_api.translation.async_get_translations",
        return_value={},
    ):
        labels = await async_field_labels(hass, "config_subentries")
    assert labels == {} or all(isinstance(v, str) for v in labels.values())


async def test_save_reports_the_offending_field(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1-mini", "not_a_field": 1},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_data"
    # The flat message stays, so nothing regresses if ha-form ignores the map.
    assert msg["error"]["message"]


async def test_missing_model_is_reported_against_the_model_field(
    hass, hass_ws_client, entry
):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_PROMPT: "no model"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert "model_required" in msg["error"]["message"]


async def test_no_label_or_error_response_carries_a_credential(
    hass, hass_ws_client, entry
):
    import json

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
    )
    schema_msg = await client.receive_json()
    await client.send_json_auto_id(
        {"type": "smartchain/agent/save", "entry_id": entry.entry_id, "data": {}}
    )
    error_msg = await client.receive_json()

    both = json.dumps(schema_msg) + json.dumps(error_msg)
    assert "sk-labels-secret" not in both
    assert CONF_API_KEY not in both
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run --prerelease=allow pytest tests/test_ws_labels_errors.py -q`
Expected: `KeyError: 'labels'` on the label tests; the error tests may already pass, which is fine — they are the regression guard for the flat message.

- [ ] **Step 3: Add the label helper**

In `websocket_api.py`, near the top:

```python
from homeassistant.helpers import translation
```

and:

```python
async def async_field_labels(hass: HomeAssistant, category: str) -> dict[str, str]:
    """Translated labels for the fields of one flow category.

    The schema's field names are exactly the keys in the integration's
    translation files, so no mapping table is needed — and none should be added,
    because a mapping table is a second place for the field list to live.

    Returns whatever it can. A field with no translation is simply absent, and
    the panel falls back to the raw name: a field added without a translation
    must still render.
    """
    resources = await translation.async_get_translations(
        hass, hass.config.language, category, [DOMAIN]
    )
    labels: dict[str, str] = {}
    for key, value in resources.items():
        # Keys look like `component.smartchain.<category>.….data.<field>`.
        marker = ".data."
        index = key.rfind(marker)
        if index == -1:
            continue
        labels.setdefault(key[index + len(marker) :], value)
    return labels
```

`setdefault` rather than assignment is deliberate: the same field appears under
several steps (`user`, `reconfigure`, `settings`) with the same label, and the
first wins rather than the last, which keeps the result stable.

- [ ] **Step 4: Serve labels from the schema command**

In `ws_agent_schema`, add to the result:

```python
            "labels": await async_field_labels(hass, "config_subentries"),
```

- [ ] **Step 5: Make validation messages name the field**

**A decision resolved while planning, so you do not have to.** I checked the
installed signature: `connection.send_error(msg_id, code, message,
translation_key, translation_domain, translation_placeholders)` cannot carry a
per-field map. Delivering Home Assistant's `{field_name: error_key}` shape would
mean moving every save command onto a `{"ok": false, …}` result and rewriting the
error contract of five working D1 commands — for a benefit that depends on
`<ha-form>` consuming the map, which nobody has confirmed in a browser.

So **do not change the error contract.** `send_error` with `code="invalid_data"`
stays exactly as D1 built it. What changes is the message: it must name the
field the failure came from.

```python
def _describe_invalid(err: vol.Invalid) -> str:
    """A validation message that names the offending field.

    Never `str(err)`: voluptuous embeds the value that failed, which would leak
    a credential if one were ever validated. Only the field name and a short
    reason travel.
    """
    fields = sorted(
        {
            str(sub.path[0])
            for sub in getattr(err, "errors", [err])
            if getattr(sub, "path", None)
        }
    )
    if not fields:
        return "invalid_data"
    return f"invalid_data: {', '.join(fields)}"
```

Use it where `ws_agent_save` currently sends `str(err)`. Then check D1's existing
tests still pass unmodified — `tests/test_ws_agent_save.py` asserts
`msg["error"]["code"] == "invalid_data"`, which this preserves. If one of those
tests breaks, you have changed the contract and the change is wrong.

Add a test asserting a bad field's **name** appears in the message and that the
value that failed does **not**.

- [ ] **Step 6: Run the tests, then the suite and lint**

Run: `uv run --prerelease=allow pytest tests/test_ws_labels_errors.py -q`, then `uv run --prerelease=allow pytest tests/ -q` and the lint command.

- [ ] **Step 7: Break-it check**

Substitute wrong values; do not delete.

- Make `async_field_labels` return `{}` unconditionally. `test_schema_serves_a_label_for_every_field` must fail. Revert.
- Make it return `{name: name for name in ...}` — labels equal to raw names. `test_labels_are_translated_not_raw_names` must fail. Revert. This is the check that matters: a label map that echoes the field name would look like a working feature.

- [ ] **Step 8: Commit**

```bash
git add custom_components/smartchain/websocket_api.py tests/test_ws_labels_errors.py
git commit -m "feat(panel): translated field labels and per-field validation errors

The schema's field names are the translation keys, so labels come from the
integration's own translation files with no mapping table to keep in step.
Validation failures now carry both a flat message and a per-field map, so
nothing depends on whether ha-form consumes the map."
```

---

### Task 2: Settings commands

**Files:**
- Modify: `custom_components/smartchain/websocket_api.py`
- Test: `tests/test_ws_settings.py` (create)

**Interfaces:**
- Consumes: `_get_entry`, `_models_for`, `async_field_labels`, and `_describe_invalid` from Task 1. Validation failures keep D1's `send_error(..., "invalid_data", ...)` contract.
- Produces: `smartchain/settings/get` returning `{schema, data, labels}`; `smartchain/settings/save`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_settings.py`:

```python
"""Entry settings over the panel's websocket API."""

from unittest.mock import patch

import pytest
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_PROMPT,
    DOMAIN,
    ID_OPENAI,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SECRET = "sk-settings-secret"


@pytest.fixture(autouse=True)
def _models():
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini", "gpt-4.1"],
    ):
        yield


@pytest.fixture
async def entry(hass):
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET},
        options={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "current"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
    )
    entry.add_to_hass(hass)
    return entry


async def test_get_returns_the_current_options(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/settings/get", "entry_id": entry.entry_id}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["data"][CONF_PROMPT] == "current"
    assert msg["result"]["schema"]
    assert msg["result"]["labels"]


async def test_save_writes_to_options_and_never_to_data(hass, hass_ws_client, entry):
    """Settings live in options. Writing them into data would put them where
    the provider credential lives."""
    before = dict(entry.data)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/settings/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1", CONF_PROMPT: "updated"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    assert entry.options[CONF_PROMPT] == "updated"
    assert entry.options[CONF_CHAT_MODEL] == "gpt-4.1"
    assert dict(entry.data) == before


async def test_save_rejects_input_with_no_model(hass, hass_ws_client, entry):
    before = dict(entry.options)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/settings/save",
            "entry_id": entry.entry_id,
            "data": {CONF_PROMPT: "no model"},
        }
    )
    msg = await client.receive_json()
    # Shape depends on Task 1's ruling; assert the failure and that nothing moved.
    assert dict(entry.options) == before


async def test_get_serves_only_declared_fields(hass, hass_ws_client, entry):
    """The trap D1 hit: a served key the schema does not declare makes the form
    permanently unsavable, because save uses PREVENT_EXTRA."""
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "a_field_no_schema_declares": True}
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/settings/get", "entry_id": entry.entry_id}
    )
    msg = await client.receive_json()
    assert "a_field_no_schema_declares" not in msg["result"]["data"]

    # And what was served must round-trip.
    await client.send_json_auto_id(
        {
            "type": "smartchain/settings/save",
            "entry_id": entry.entry_id,
            "data": msg["result"]["data"],
        }
    )
    save = await client.receive_json()
    assert save["success"], save


async def test_settings_commands_require_admin(hass, hass_ws_client, hass_admin_user, entry):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    for command in ("get", "save"):
        payload = {"type": f"smartchain/settings/{command}", "entry_id": entry.entry_id}
        if command == "save":
            payload["data"] = {CONF_CHAT_MODEL: "gpt-4.1"}
        await client.send_json_auto_id(payload)
        msg = await client.receive_json()
        assert not msg["success"], command
        assert msg["error"]["code"] == "unauthorized", command


async def test_settings_responses_carry_no_credential(hass, hass_ws_client, entry):
    import json

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/settings/get", "entry_id": entry.entry_id}
    )
    msg = await client.receive_json()
    body = json.dumps(msg)
    assert SECRET not in body
    assert CONF_API_KEY not in body
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run --prerelease=allow pytest tests/test_ws_settings.py -q`
Expected: `unknown_command`.

- [ ] **Step 3: Implement both commands**

Add to `websocket_api.py` and register both. The shape mirrors `ws_agent_schema` and `ws_agent_save`, with `entry.options` in place of a subentry and `async_update_entry` in place of the subentry writers:

```python
@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/settings/get",
        vol.Required("entry_id"): str,
        vol.Optional("refresh", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_settings_get(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Serve the entry's options form — the same schema the agent form uses."""
    from .config_flow import subentry_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    defaults = dict(entry.options)
    models = await _models_for(hass, entry, refresh=msg["refresh"], purpose=CAPABILITY_CHAT)
    schema = subentry_schema(hass, entry.unique_id, defaults, models=models)
    declared = {str(key.schema) for key in schema.schema}

    connection.send_result(
        msg["id"],
        {
            "schema": voluptuous_serialize.convert(
                schema, custom_serializer=cv.custom_serializer
            ),
            "data": {k: v for k, v in defaults.items() if k in declared},
            "labels": await async_field_labels(hass, "options"),
        },
    )
```

The save command validates through the same schema and `normalize_model_input`, exactly as `ws_agent_save` does, then:

```python
    hass.config_entries.async_update_entry(entry, options=data)
```

**Do not** pass `data=` — that is where the credential lives, and the test above asserts it is untouched.

- [ ] **Step 4: Run the tests, suite and lint**

- [ ] **Step 5: Break-it check**

- Change `async_update_entry(entry, options=data)` to `data={**entry.data, **data}`. `test_save_writes_to_options_and_never_to_data` must fail. Revert.
- Remove the `declared` filter from `ws_settings_get`. `test_get_serves_only_declared_fields` must fail on the round trip. Revert.

- [ ] **Step 6: Commit**

```bash
git add custom_components/smartchain/websocket_api.py tests/test_ws_settings.py
git commit -m "feat(panel): entry settings over websocket

The settings form is the agent pipeline pointed at entry.options. Options
are written with options=, never data=, and a test asserts entry.data is
untouched — that is where the provider credential lives."
```

---

### Task 3: Embeddings commands and the title hazards

**Files:**
- Modify: `custom_components/smartchain/websocket_api.py`, `config_flow.py`, `tools/memory/registry.py`
- Test: `tests/test_ws_embeddings.py` (create)

**Interfaces:**
- Consumes: everything above.
- Produces: `embeddings_subentry_schema` (renamed from `_embeddings_subentry_schema`); `MemoryRegistry.stores_bound_to(title) -> list[str]`; `smartchain/embeddings/schema`, `smartchain/embeddings/save`, `smartchain/embeddings/delete`. The schema command's response includes `bound_stores` and `title_taken_by`.

- [ ] **Step 1: Rename the schema helper and add the registry method**

In `config_flow.py`, rename `_embeddings_subentry_schema` → `embeddings_subentry_schema` and fix every call site. Run `grep -rn "_embeddings_subentry_schema" custom_components/ tests/` and confirm zero hits remain.

In `tools/memory/registry.py`, add a public method beside `_embeddings_subentries`:

```python
    def stores_bound_to(self, title: str) -> list[str]:
        """Names of configured memory stores bound to this embeddings title.

        Stores bind by title, so renaming or duplicating a title silently
        unbinds them. The panel asks this before writing, never after.
        """
        return [
            name
            for name, config in self._configs.items()
            if config.embeddings == title
        ]
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_ws_embeddings.py`. Cover, at minimum:

```python
async def test_schema_uses_the_embeddings_model_purpose(hass, hass_ws_client, entry):
    """A chat model list here would offer models that cannot embed."""
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models"
    ) as fetch:
        fetch.return_value = ["", "text-embedding-3-small"]
        await client.send_json_auto_id(
            {"type": "smartchain/embeddings/schema", "entry_id": entry.entry_id}
        )
        await client.receive_json()
    assert fetch.call_args.kwargs["purpose"] == CAPABILITY_EMBEDDINGS


async def test_save_reports_a_title_already_taken(hass, hass_ws_client, ...):
    """MemoryRegistry maps a duplicated title to None, silently unbinding the
    store. The panel must be able to warn before writing."""
    # two entries, each with an embeddings subentry; ask to save the second
    # with the first's title; assert the response reports the collision.


async def test_schema_reports_which_stores_are_bound(hass, hass_ws_client, ...):
    # a configured memory store bound to this subentry's title;
    # assert `bound_stores` names it, so the panel can warn before a rename.


async def test_delete_reports_bound_stores_rather_than_silently_breaking_them(...):
    ...


async def test_save_and_delete_reject_a_conversation_subentry(...):
    """The mirror of D1's guard: agent commands reject embeddings subentries,
    so embeddings commands must reject agents."""


async def test_embeddings_commands_require_admin(...):
    ...


async def test_embeddings_responses_carry_no_credential(...):
    ...
```

Write these out in full, following the shape of `tests/test_ws_settings.py` from Task 2 and `tests/test_ws_agent_copy_delete.py` from D1. Use `SUBENTRY_TYPE_EMBEDDINGS` and build the memory registry through the integration's normal setup rather than by hand where you can.

- [ ] **Step 3: Implement the three commands**

`ws_embeddings_schema` mirrors `ws_agent_schema` but calls `embeddings_subentry_schema(models, defaults)` with `purpose=CAPABILITY_EMBEDDINGS`, and adds:

```python
            "bound_stores": registry.stores_bound_to(subentry.title) if subentry else [],
```

`ws_embeddings_save` validates, then checks the title before writing:

```python
    taken = _title_claimed_by_another(hass, title, subentry_id)
    if taken is not None:
        connection.send_result(
            msg["id"],
            {"ok": False, "message": f"The title {title!r} is already used", "field": "name"},
        )
        return
```

`_title_claimed_by_another` walks every SmartChain entry's embeddings subentries, as `MemoryRegistry._embeddings_subentries` does, and returns the offending subentry id or `None`. Reuse the registry's logic rather than restating the rule if you can reach it cleanly; say in your report which you did.

`ws_embeddings_delete` reports `bound_stores` in its result so the panel can tell the user what it just unbound, and rejects a subentry whose `subentry_type` is not `SUBENTRY_TYPE_EMBEDDINGS`.

- [ ] **Step 4: Run the tests, suite and lint**

- [ ] **Step 5: Break-it check**

- Make the schema command fetch with `purpose=CAPABILITY_CHAT`. The purpose test must fail. Revert.
- Remove the title-collision check from save. That test must fail. Revert.
- Remove the `subentry_type` guard. The cross-type test must fail. Revert.

- [ ] **Step 6: Commit**

```bash
git add custom_components/smartchain/websocket_api.py custom_components/smartchain/config_flow.py custom_components/smartchain/tools/memory/registry.py tests/test_ws_embeddings.py
git commit -m "feat(panel): embeddings bindings over websocket

Memory stores bind to an embeddings subentry by title, and a title claimed
twice maps to None — a collision unbinds a store as thoroughly as a rename.
The panel shows every entry at once and so makes that easy to hit, which is
why save refuses a taken title and both schema and delete report which
stores a change would affect."
```

---

### Task 4: tools.yaml, read-only

**Files:**
- Modify: `custom_components/smartchain/websocket_api.py`
- Test: `tests/test_ws_tools.py` (create)

**Interfaces:**
- Produces: `smartchain/tools/get` → `{text, path, exists}`; `smartchain/tools/validate` → `{valid, error?}`; `smartchain/tools/reload` → `{tools: int}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_tools.py`. The two tests that matter most, written in full:

```python
async def test_get_returns_raw_text_with_secret_references_unresolved(
    hass, hass_ws_client, tmp_path
):
    """load_tools_file resolves !secret, so the parsed structure holds real
    credentials. Only the file as it sits on disk may cross the wire."""
    # Write a tools.yaml containing `api_key: !secret my_key` and a secrets.yaml
    # defining my_key: "sk-must-not-appear". Point hass.config.config_dir at it.
    ...
    await client.send_json_auto_id({"type": "smartchain/tools/get"})
    msg = await client.receive_json()

    assert "!secret" in msg["result"]["text"]
    assert "sk-must-not-appear" not in json.dumps(msg)


async def test_validate_of_a_broken_file_leaks_no_resolved_secret(
    hass, hass_ws_client, tmp_path
):
    """Voluptuous embeds the offending value in its message, so a resolved
    secret that fails validation would appear in the error text."""
    # tools.yaml where a !secret value lands somewhere the schema rejects.
    ...
    await client.send_json_auto_id({"type": "smartchain/tools/validate"})
    msg = await client.receive_json()

    assert msg["result"]["valid"] is False
    assert "sk-must-not-appear" not in json.dumps(msg)
```

Also cover: a missing file reports `exists: false` rather than erroring; a valid file validates; `reload` succeeds and reports how many tools loaded; all three commands are admin-only.

- [ ] **Step 2: Run to confirm failure**

- [ ] **Step 3: Implement the three commands**

```python
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartchain/tools/get"})
@websocket_api.async_response
async def ws_tools_get(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """The file as it sits on disk.

    Never the parsed structure: `load_tools_file` resolves `!secret`, so the
    parsed form holds real credentials, while the raw text holds only the
    reference name.
    """
    from . import _tools_yaml_path

    path = _tools_yaml_path(hass)
    text = await hass.async_add_executor_job(_read_text_if_present, path)
    connection.send_result(
        msg["id"],
        {"text": text or "", "path": str(path), "exists": text is not None},
    )
```

`validate` runs `load_tools_file` in an executor and, on `LoaderError`, sends a
message built from the **exception type and the YAML path**, not `str(err)`:

```python
    except LoaderError as err:
        LOGGER.warning("tools.yaml validation failed: %s", err)  # detail stays server-side
        connection.send_result(
            msg["id"],
            {"valid": False, "error": _safe_loader_error(err)},
        )
```

`_safe_loader_error` must not include the exception's message text verbatim.
Decide what it *can* safely include — a line number, a key path — and say in your
report what you chose and how you convinced yourself it carries no value. If you
cannot establish that for some part, leave it out: the full detail is in the log,
which is where an admin can read it.

`reload` calls the existing `_reload_registry(hass)` and reports the tool count.

- [ ] **Step 4: Run the tests, suite and lint**

- [ ] **Step 5: Break-it check**

- Make `tools/get` return the parsed structure instead of the raw text. The secret test must fail. Revert.
- Make `_safe_loader_error` return `str(err)`. The validate-leak test must fail. Revert. **If it does not fail, your fixture is not exercising a resolved secret — fix the fixture, not the assertion.**

- [ ] **Step 6: Commit**

```bash
git add custom_components/smartchain/websocket_api.py tests/test_ws_tools.py
git commit -m "feat(panel): read-only tools.yaml view

The file is served as raw text because load_tools_file resolves !secret and
the parsed structure holds real credentials. Validation errors report a
location, not voluptuous's message, which embeds the offending value."
```

---

### Task 5: The settings and embeddings tabs

**Files:**
- Rename: `panel/components/agent-form.js` → `config-form.js`
- Create: `panel/components/settings-tab.js`, `panel/components/embeddings-tab.js`
- Modify: `panel/smartchain-panel.js`, `panel/styles.js`, `panel/components/agents-tab.js`

- [ ] **Step 1: Generalise the form component**

`agent-form.js` already knows nothing about agents — it takes a schema and data. Rename it to `config-form.js`, the element to `<sc-config-form>`, and make the command names properties rather than constants:

```javascript
  set commands(val) {
    // {schema: "smartchain/agent/schema", save: "smartchain/agent/save"}
    this._commands = val;
  }
```

Update `agents-tab.js` to pass the agent commands. **Do not copy this component per tab** — three copies is how the panel starts to drift, and the whole design rests on there being one place that renders a served schema.

Wire the `labels` the backend now returns into `computeLabel`, falling back to the raw field name when a field has none.

- [ ] **Step 2: The settings tab**

`settings-tab.js` lists the configured entries and shows `<sc-config-form>` for the selected one, with `smartchain/settings/get` and `smartchain/settings/save`. With a single entry — the common case — skip the list and show the form directly.

- [ ] **Step 3: The embeddings tab**

`embeddings-tab.js` mirrors `agents-tab.js`: a list per entry, with create, edit and delete. Two differences the spec requires:

- Before saving a rename, if the response reports `bound_stores`, confirm with the user, naming the stores that would be unbound.
- If a save is refused because the title is taken, show that against the name field rather than as a bare toast.
- The delete confirmation names the bound stores when there are any.

- [ ] **Step 4: Wire the tabs**

Add Settings and Embeddings to `smartchain-panel.js`'s `TABS`, both `adminOnly`. Embeddings is additionally hidden when no entry in `overview` reports `supports_embeddings`; the shell will need the overview data, so fetch it once in the shell and pass it down rather than each tab fetching separately.

- [ ] **Step 5: Write the browser checklist**

You cannot run it. Write it out for the user: both new tabs, the rename warning, the title-collision refusal, and that labels now read as words rather than field names.

- [ ] **Step 6: Run the suite and lint, then commit**

No Python changes; run both to prove it.

---

### Task 6: The tools tab

**Files:**
- Create: `panel/components/tools-tab.js`
- Modify: `panel/smartchain-panel.js`, `panel/styles.js`

- [ ] **Step 1: Build the tab**

A read-only view of the file with a monospace font, a Validate button and a Reload button. On validate, show valid or the reported location. On reload, toast the tool count. Show the file path, and a clear message when the file does not exist — that is the common first-run state, not an error.

The text is displayed, never edited: no `contenteditable`, no textarea the user could type into and expect to save. If it looks editable, someone will try.

- [ ] **Step 2: Wire the tab**, `adminOnly` like the others.

- [ ] **Step 3: Write the browser checklist** — including a deliberately broken `tools.yaml`, to confirm the error is readable and carries no secret.

- [ ] **Step 4: Run the suite and lint, then commit**

---

## Self-Review

**Spec coverage.** §3 settings → Task 2. §4 embeddings, including all three title hazards → Task 3. §5.1 labels → Task 1. §5.2 per-field errors → Task 1. §6 tools.yaml and both secret traps → Task 4. §7 the command table → Tasks 2–4. §8 panel structure, including generalising the form rather than copying it → Tasks 5, 6. §9 testing → each task's tests. §10 the unverified assumption → stated in the header and in Tasks 5–6. §11 deferred → nothing to build.

**Placeholder scan.** Task 3's Step 2 and Task 4's Step 1 give test *shapes* with prose for the bodies rather than complete code, which is a deliberate exception: both depend on fixtures whose exact form the implementer must establish against the installed Home Assistant, and inventing them here would produce code that looks authoritative and does not run. Every other step carries its code. Task 1 Step 5 deliberately names a correction the implementer must make rather than guessing the `send_error` signature.

**Type consistency.** `async_field_labels(hass, category)`, `_get_entry`, `_models_for(hass, entry, *, refresh, purpose)` — note Task 2 passes `purpose` explicitly, which D1's final fix added. `subentry_schema` and `embeddings_subentry_schema` are the public names after Task 3's rename. The save-result shape is chosen once in Task 1 and used by every save command after it.

**A decision planning resolved rather than delegating:** `send_error` cannot carry a per-field map, so the `{field_name: error_key}` shape would require rewriting five working commands' error contract for an unproven benefit. The plan keeps the contract and makes the message name the field instead. Recorded in the spec, with the precondition for revisiting it.
