# Panel configuration part 1 — agents — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the SmartChain panel a websocket API and a tabbed shell, and make conversation agents fully manageable from it — listed, created, edited, duplicated and deleted.

**Architecture:** A new `websocket_api.py` exposes admin-only commands. The panel never defines a form: the backend serialises the config flow's own `vol.Schema` with `voluptuous_serialize.convert(..., custom_serializer=cv.custom_serializer)` and the panel renders it with Home Assistant's `<ha-form>`, so the field list has exactly one definition. The save handler validates through that same schema. Home Assistant's own config pages stay as the canonical path.

**Tech Stack:** Python 3.13, Home Assistant 2026.8, `homeassistant.components.websocket_api`, `voluptuous_serialize`, plain ES modules with no build step, `<ha-form>`.

**Spec:** `docs/superpowers/specs/2026-08-24-panel-config-d1-design.md`

**A note on ordering.** Tasks 1–4 are backend and testable here. Tasks 5–6 are
panel work whose correctness can only be confirmed on a running Home Assistant,
which the development environment does not have. The `<ha-form>` assumption named
in spec §8 is therefore verified by the **user**, once, after Task 1 — and only
Tasks 5–6 depend on the answer. Do not block Tasks 2–4 on it.

## Global Constraints

- **No new runtime dependencies.** `voluptuous_serialize` ships with Home Assistant; `manifest.json` requirements must not change.
- `requires-python>=3.13`; `langchain-core<1`; `langchain-community<0.4`.
- Version stays `5.0.0` — it is unreleased, so tasks in this plan do not bump it.
- **Every websocket command is admin-only**, decorated in this exact order, which is Home Assistant's own convention and was verified against `homeassistant.components.config.config_entries`:
  ```python
  @websocket_api.require_admin
  @websocket_api.websocket_command({...})
  @websocket_api.async_response
  async def ws_handler(hass, connection, msg): ...
  ```
- **No response and no error message may carry a credential.** `entry.data` holds `CONF_API_KEY` and `CONF_FOLDER_ID`; responses are assembled field by field from an explicit list, never by forwarding entry data.
- The panel adds **no build step and no framework**. Components are plain `HTMLElement` subclasses with a `set hass` setter and an `innerHTML` render, matching `panel/components/camera-tab.js`.
- Existing behaviour is preserved: the camera tab must keep working, reachable in at most one more click.
- Test: `uv run --prerelease=allow pytest tests/ -q` (currently 727 passing)
- Lint: `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .` — ruff selects `E`, `F`, `W`, `I`, `UP`.
- `pyproject.toml` sets `asyncio_mode = "auto"` — async tests need no marker.
- Every commit message ends with:
  ```

  🤖 Generated with [Claude Code](https://claude.com/claude-code)

  Co-Authored-By: Claude <noreply@anthropic.com>
  ```

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `custom_components/smartchain/websocket_api.py` | All panel commands (new) | 1–4 |
| `custom_components/smartchain/config_flow.py` | Two renames, one extraction | 1, 3 |
| `custom_components/smartchain/__init__.py` | Register the commands | 1 |
| `tests/test_ws_agent_schema.py` | Schema command + model cache (new) | 1 |
| `tests/test_ws_overview.py` | Overview + credential containment (new) | 2 |
| `tests/test_ws_agent_save.py` | Create, update, validation parity (new) | 3 |
| `tests/test_ws_agent_copy_delete.py` | Duplicate and delete (new) | 4 |
| `panel/smartchain-panel.js` | Tab shell | 1, 5 |
| `panel/services.js` | Websocket helpers | 1 |
| `panel/components/agents-tab.js` | List and actions (new) | 6 |
| `panel/components/agent-form.js` | `<ha-form>` wrapper (new) | 1, 6 |

---

### Task 1: Vertical slice — prove `<ha-form>` renders our schema

**This task exists to retire the plan's one unproven assumption.** Everything downstream depends on `<ha-form>` rendering a serialized SmartChain schema inside a custom panel. Build the thinnest possible path end to end and look at it in a browser before writing anything else.

**Files:**
- Create: `custom_components/smartchain/websocket_api.py`
- Create: `tests/test_ws_agent_schema.py`
- Create: `custom_components/smartchain/panel/components/agent-form.js`
- Modify: `custom_components/smartchain/config_flow.py` (two renames)
- Modify: `custom_components/smartchain/__init__.py` (registration)
- Modify: `custom_components/smartchain/panel/services.js`, `panel/smartchain-panel.js`

**Interfaces:**
- Produces: `async_register(hass)` in `websocket_api.py`; the command `smartchain/agent/schema` returning `{"schema": [...], "data": {...}}`; `subentry_schema(...)` and `normalize_model_input(...)` in `config_flow.py` (renamed from the underscore-prefixed forms); `callWS(hass, type, payload)` in `services.js`; `<sc-agent-form>`.

- [ ] **Step 1: Rename the two config-flow helpers**

`websocket_api.py` will import both, so they cross a module boundary and lose the underscore — the same call made for `compatible_api_key` in the provider work.

In `config_flow.py` rename `_subentry_schema` → `subentry_schema` and `_normalize_model_input` → `normalize_model_input`, updating all call sites in that file. Do not change either body.

Then run `grep -rn "_subentry_schema\|_normalize_model_input" custom_components/ tests/` and fix every remaining reference, including in tests. `tests/test_subentries.py` walks `_subentry_schema`'s AST by name and will need the new name.

- [ ] **Step 2: Write the failing test**

Create `tests/test_ws_agent_schema.py`:

```python
"""The websocket command that serialises the agent form schema."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_OPENAI,
    UNIQUE_ID_OPENAI,
)


@pytest.fixture
async def entry(hass):
    """A configured OpenAI entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sekrit-key"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
    )
    entry.add_to_hass(hass)
    return entry


async def test_schema_command_returns_renderable_fields(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ):
        await client.send_json_auto_id(
            {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
        )
        msg = await client.receive_json()

    assert msg["success"], msg
    fields = msg["result"]["schema"]
    assert fields, "an empty schema would render an empty form"
    # Every entry ha-form can render carries a name and either a plain type or
    # a selector; anything else would silently render as nothing.
    for field in fields:
        assert field.get("name"), field
        assert "type" in field or "selector" in field, field


async def test_schema_matches_the_config_flow_schema(hass, hass_ws_client, entry):
    """The single-source guarantee: the panel sees exactly the flow's fields."""
    from custom_components.smartchain.config_flow import subentry_schema

    client = await hass_ws_client(hass)
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ):
        await client.send_json_auto_id(
            {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
        )
        msg = await client.receive_json()

    served = {f["name"] for f in msg["result"]["schema"]}
    expected = {
        str(key.schema)
        for key in subentry_schema(hass, UNIQUE_ID_OPENAI, {}, models=["", "gpt-4.1-mini"]).schema
    }
    assert served == expected


async def test_schema_carries_no_credential(hass, hass_ws_client, entry):
    import json

    client = await hass_ws_client(hass)
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ):
        await client.send_json_auto_id(
            {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
        )
        msg = await client.receive_json()

    assert "sekrit-key" not in json.dumps(msg)


async def test_schema_requires_admin(hass, hass_ws_client, hass_admin_user, entry):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"


async def test_unknown_entry_is_reported_not_crashed(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/agent/schema", "entry_id": "does-not-exist"}
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_models_are_cached_until_refresh_is_asked_for(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ) as fetch:
        for _ in range(3):
            await client.send_json_auto_id(
                {"type": "smartchain/agent/schema", "entry_id": entry.entry_id}
            )
            await client.receive_json()
        assert fetch.call_count == 1

        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/schema",
                "entry_id": entry.entry_id,
                "refresh": True,
            }
        )
        await client.receive_json()
        assert fetch.call_count == 2
```

- [ ] **Step 3: Run it to confirm it fails**

Run: `uv run --prerelease=allow pytest tests/test_ws_agent_schema.py -q`
Expected: every test fails — the command is not registered, so the error code is `unknown_command`.

- [ ] **Step 4: Write the websocket module**

Create `custom_components/smartchain/websocket_api.py`:

```python
"""Websocket commands backing the SmartChain panel.

The panel never defines a form. These commands serialise the very schema the
config flow builds, so the field list has one definition rather than two.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol
import voluptuous_serialize
from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .client_util import async_fetch_models
from .const import CONF_ENGINE, DOMAIN, ID_GIGACHAT

_MODEL_CACHE = "panel_model_cache"


@callback
def async_register(hass: HomeAssistant) -> None:
    """Register every panel command."""
    websocket_api.async_register_command(hass, ws_agent_schema)


def _get_entry(hass: HomeAssistant, entry_id: str) -> ConfigEntry | None:
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        return None
    return entry


async def _models_for(
    hass: HomeAssistant, entry: ConfigEntry, *, refresh: bool
) -> list[str]:
    """Model list for an entry, fetched once and reused until asked to refresh.

    A flow dialog pays the network cost once per open. The panel would pay it on
    every click between agents, so the list is cached and an explicit refresh is
    the only invalidation.
    """
    cache: dict[str, list[str]] = hass.data.setdefault(DOMAIN, {}).setdefault(
        _MODEL_CACHE, {}
    )
    if refresh or entry.entry_id not in cache:
        engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
        cache[entry.entry_id] = await async_fetch_models(hass, engine, entry.data)
    return cache[entry.entry_id]


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/agent/schema",
        vol.Required("entry_id"): str,
        vol.Optional("subentry_id"): str,
        vol.Optional("refresh", default=False): bool,
    }
)
@websocket_api.async_response
async def ws_agent_schema(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Serialise the agent form's schema, with current values when editing."""
    from .config_flow import subentry_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    defaults: dict[str, Any] = {}
    subentry_id = msg.get("subentry_id")
    if subentry_id is not None:
        subentry = entry.subentries.get(subentry_id)
        if subentry is None:
            connection.send_error(msg["id"], "not_found", "Unknown agent")
            return
        defaults = dict(subentry.data)

    models = await _models_for(hass, entry, refresh=msg["refresh"])
    schema = subentry_schema(hass, entry.unique_id, defaults, models=models)

    connection.send_result(
        msg["id"],
        {
            "schema": voluptuous_serialize.convert(
                schema, custom_serializer=cv.custom_serializer
            ),
            "data": defaults,
        },
    )
```

The `config_flow` import is inside the function deliberately: importing it at module load would pull the flow's dependencies into `async_setup`'s import path for no benefit.

- [ ] **Step 5: Register it**

In `__init__.py`'s `async_setup`, beside the panel registration:

```python
    from . import websocket_api as smartchain_websocket_api

    smartchain_websocket_api.async_register(hass)
```

- [ ] **Step 6: Run the tests**

Run: `uv run --prerelease=allow pytest tests/test_ws_agent_schema.py -q`
Expected: 6 passed.

Then the full suite: `uv run --prerelease=allow pytest tests/ -q`

- [ ] **Step 7: Add the websocket helper to the panel**

Append to `panel/services.js`:

```javascript
/**
 * Send a SmartChain websocket command and return its result.
 *
 * Throws with the backend's message, which is safe to display — the backend
 * never puts a credential in one.
 */
export async function callWS(hass, type, payload = {}) {
  return await hass.connection.sendMessagePromise({ type, ...payload });
}
```

- [ ] **Step 8: Write the form component**

Create `panel/components/agent-form.js`:

```javascript
import { callWS } from "../services.js";

/**
 * <sc-agent-form> — renders the agent schema the backend serialises.
 *
 * The form's fields are never declared here. <ha-form> is Home Assistant's own
 * element and consumes exactly the payload the backend sends, so adding a field
 * to the config flow makes it appear here with no change to this file.
 *
 * Properties: .hass, .entryId, .subentryId
 */
export class ScAgentForm extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._schema = null;
    this._data = {};
  }

  set hass(val) {
    this._hass = val;
  }

  set entryId(val) {
    this._entryId = val;
  }

  set subentryId(val) {
    this._subentryId = val;
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    this.load();
  }

  async load(refresh = false) {
    if (!this._hass || !this._entryId) return;
    const payload = { entry_id: this._entryId, refresh };
    if (this._subentryId) payload.subentry_id = this._subentryId;
    const result = await callWS(this._hass, "smartchain/agent/schema", payload);
    this._schema = result.schema;
    this._data = result.data || {};
    this._apply();
  }

  _render() {
    this.innerHTML = `
      <style>
        .sc-form-actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }
      </style>
      <ha-form></ha-form>
      <div class="sc-form-actions">
        <mwc-button id="sc-form-save">Save</mwc-button>
      </div>
    `;
    this.querySelector("ha-form").addEventListener("value-changed", (ev) => {
      this._data = ev.detail.value;
    });
    this.querySelector("#sc-form-save").addEventListener("click", () => {
      // Task 1 proves rendering only; Task 6 wires this to the save command.
      console.info("SmartChain agent form value", this._data);
    });
  }

  _apply() {
    const form = this.querySelector("ha-form");
    if (!form || !this._schema) return;
    form.hass = this._hass;
    form.schema = this._schema;
    form.data = this._data;
    form.computeLabel = (field) => field.name;
  }
}

customElements.define("sc-agent-form", ScAgentForm);
```

- [ ] **Step 9: Show it in the panel, temporarily**

In `panel/smartchain-panel.js`, import the component and render it above the camera container, passing the first SmartChain entry's id. Getting that id in the browser without the overview command (Task 2) is awkward, so for this task hard-code it: read it from the URL hash, e.g. `#entry=<id>`, and log a clear message when absent.

```javascript
import "./components/agent-form.js";
```

and in `_initialize()`:

```javascript
    const entryId = new URLSearchParams(location.hash.slice(1)).get("entry");
    this.innerHTML = `
      <style>${SC_STYLES}</style>
      ${entryId ? `<sc-agent-form></sc-agent-form>` : ""}
      <div class="sc-camera-container">
        <sc-camera-tab></sc-camera-tab>
      </div>
    `;
    if (entryId) {
      const form = this.querySelector("sc-agent-form");
      form.entryId = entryId;
    }
```

Extend `_propagateHass()` to set `.hass` on `sc-agent-form` too.

**This scaffolding is temporary** and Task 5 replaces it with the tab shell. Leave a comment saying so.

- [ ] **Step 10: Hand the browser check to the user — do not attempt it**

**There is no browser and no running Home Assistant in the development
environment.** Do not try to start one, do not simulate the check, and do not
report the assumption as a result. Whether `<ha-form>` renders this schema can
only be answered on a real Home Assistant instance, by the person who has one.

Your job is to leave that check ready to run. In your report, write the exact
instructions for it:

1. Restart Home Assistant with this branch installed and at least one SmartChain
   entry configured.
2. Find the entry id under Settings → Devices & Services → SmartChain, reading it
   from the browser's URL.
3. Open `/smartchain#entry=<that id>`.

And what the user should look for:
- A form renders, with more than one field.
- The model field is a dropdown carrying the model names.
- The temperature field is a slider or number input.
- Changing a field and clicking Save logs an object in the browser console.
- The field labels are raw names like `chat_model` rather than "Model" — expected
  at this stage, see the note at the end of this plan.

Report status **DONE**, with a clearly marked section saying the browser check is
outstanding and belongs to the user.

**What happens if the check fails is the controller's call, not yours.** The spec
names a fallback — the panel hand-renders the same serialized schema — and only
Tasks 5 and 6 depend on the answer. Tasks 2, 3 and 4 are pure backend and are
unaffected either way, so work continues while the check is pending.

- [ ] **Step 11: Commit**

```bash
git add custom_components/smartchain/websocket_api.py custom_components/smartchain/__init__.py custom_components/smartchain/config_flow.py custom_components/smartchain/panel tests/test_ws_agent_schema.py
git commit -m "feat(panel): serve the agent form schema over websocket

The panel does not define the form. The backend serialises the schema the
config flow already builds and ha-form renders it, so a field added to the
flow appears in the panel with no second declaration to keep in step.

Model lists are cached per entry; an explicit refresh is the invalidation."
```

---

### Task 2: The overview command

**Files:**
- Modify: `custom_components/smartchain/websocket_api.py`
- Test: `tests/test_ws_overview.py` (create)

**Interfaces:**
- Consumes: `_get_entry` from Task 1.
- Produces: `smartchain/overview` returning `{"entries": [{entry_id, title, engine, engine_label, supports_embeddings, agents: [{subentry_id, title, model, tool_count}]}]}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_overview.py`:

```python
"""The overview command that lists entries and their agents."""

import json

import pytest
from homeassistant.config_entries import ConfigSubentryData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_FOLDER_ID,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    UNIQUE_ID_OPENAI,
)

SECRET = "sk-do-not-leak-me"
FOLDER = "folder-do-not-leak-me"


@pytest.fixture
async def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET, CONF_FOLDER_ID: FOLDER},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_overview_lists_the_entry_and_its_agent(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    assert msg["success"], msg
    entries = msg["result"]["entries"]
    assert len(entries) == 1
    served = entries[0]
    assert served["entry_id"] == entry.entry_id
    assert served["engine"] == ID_OPENAI
    assert served["engine_label"] == UNIQUE_ID_OPENAI
    assert served["supports_embeddings"] is True

    agents = served["agents"]
    assert len(agents) == 1
    assert agents[0]["title"] == "Home"
    assert agents[0]["model"] == "gpt-4.1-mini"
    assert "tool_count" in agents[0]


async def test_overview_never_carries_a_credential(hass, hass_ws_client, entry):
    """The whole response, serialised, must contain no secret from entry data."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    body = json.dumps(msg)
    assert SECRET not in body
    assert FOLDER not in body
    # Nor the key names, which would mean entry data was forwarded wholesale.
    assert CONF_API_KEY not in body


async def test_overview_requires_admin(hass, hass_ws_client, hass_admin_user, entry):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"


async def test_overview_with_no_entries_is_an_empty_list(hass, hass_ws_client):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["entries"] == []


async def test_embeddings_capability_follows_the_provider(hass, hass_ws_client):
    """A provider without embeddings must say so — D2 hides a tab on this."""
    from custom_components.smartchain.const import ID_ANTHROPIC, UNIQUE_ID_ANTHROPIC

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_ANTHROPIC, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_ANTHROPIC,
        title=UNIQUE_ID_ANTHROPIC,
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    served = next(e for e in msg["result"]["entries"] if e["entry_id"] == entry.entry_id)
    assert served["supports_embeddings"] is False
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run --prerelease=allow pytest tests/test_ws_overview.py -q`
Expected: failures with error code `unknown_command`.

- [ ] **Step 3: Implement it**

Add to `websocket_api.py`, and register it in `async_register`:

```python
@websocket_api.require_admin
@websocket_api.websocket_command({vol.Required("type"): "smartchain/overview"})
@websocket_api.async_response
async def ws_overview(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """List SmartChain entries and their conversation agents."""
    entries = [
        _describe_entry(hass, entry)
        for entry in hass.config_entries.async_entries(DOMAIN)
    ]
    connection.send_result(msg["id"], {"entries": entries})


def _describe_entry(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Public description of an entry.

    Assembled field by field on purpose. `entry.data` holds the provider
    credential, so forwarding it wholesale — now or by a later edit — would put
    an API key on the wire.
    """
    engine = entry.data.get(CONF_ENGINE, ID_GIGACHAT)
    return {
        "entry_id": entry.entry_id,
        "title": entry.title,
        "engine": engine,
        "engine_label": UNIQUE_ID.get(engine, engine),
        "supports_embeddings": supports(engine, CAPABILITY_EMBEDDINGS),
        "agents": [
            _describe_agent(subentry)
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_TYPE_CONVERSATION
        ],
    }


def _describe_agent(subentry: Any) -> dict[str, Any]:
    data = subentry.data
    model = (data.get(CONF_CHAT_MODEL_USER) or "").strip() or data.get(CONF_CHAT_MODEL, "")
    allowed = data.get(CONF_ALLOWED_TOOLS)
    return {
        "subentry_id": subentry.subentry_id,
        "title": subentry.title,
        "model": model,
        # None means "every tool"; the panel shows a dash rather than a count it
        # cannot know without building the registry.
        "tool_count": len(allowed) if allowed is not None else None,
    }
```

Add the needed imports: `CONF_ALLOWED_TOOLS`, `CONF_CHAT_MODEL`, `CONF_CHAT_MODEL_USER`, `CAPABILITY_EMBEDDINGS`, `SUBENTRY_TYPE_CONVERSATION`, `UNIQUE_ID` from `.const`, and `supports` from `.client_util`.

- [ ] **Step 4: Run the tests**

Run: `uv run --prerelease=allow pytest tests/test_ws_overview.py tests/ -q`

- [ ] **Step 5: Break-it check**

Substitute a wrong value, do not delete code — a deletion only proves the test notices absence, which twice hid a real gap on the previous branch.

Temporarily make `_describe_entry` return `{**entry.data, "entry_id": entry.entry_id, "agents": []}`. `test_overview_never_carries_a_credential` must fail naming the leaked key. Revert.

Then temporarily make `supports_embeddings` always `True`. `test_embeddings_capability_follows_the_provider` must fail. Revert.

- [ ] **Step 6: Lint and commit**

```bash
git add custom_components/smartchain/websocket_api.py tests/test_ws_overview.py
git commit -m "feat(panel): overview command listing entries and agents

Responses are assembled field by field. Entry data holds the provider
credential, so a test asserts the whole serialised response contains
neither the key, the folder id, nor the key's field name."
```

---

### Task 3: Saving an agent

**Files:**
- Modify: `custom_components/smartchain/websocket_api.py`, `custom_components/smartchain/config_flow.py`
- Test: `tests/test_ws_agent_save.py` (create)

**Interfaces:**
- Consumes: `_get_entry`, `_models_for` from Task 1.
- Produces: `smartchain/agent/save` returning `{"subentry_id": str}`; `agent_title(data)` in `config_flow.py`.

- [ ] **Step 1: Extract the title helper**

`ConversationSubentryFlow` computes the agent title twice with the same expression. The websocket handler would be a third copy, and three copies is how titles start to diverge. In `config_flow.py`, above `ConversationSubentryFlow`:

```python
def agent_title(data: Mapping[str, Any]) -> str:
    """Title for an agent subentry: the user's model name, else the picked one."""
    return data.get(CONF_CHAT_MODEL_USER) or data.get(CONF_CHAT_MODEL) or "Agent"
```

Replace both occurrences of `user_input.get(CONF_CHAT_MODEL_USER) or user_input.get(CONF_CHAT_MODEL) or "Agent"` with `agent_title(user_input)`. Import `Mapping` from `collections.abc` if it is not already imported.

- [ ] **Step 2: Write the failing test**

Create `tests/test_ws_agent_save.py`:

```python
"""Creating and updating an agent through the panel's websocket API."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_PROMPT,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    UNIQUE_ID_OPENAI,
)

MODELS = ["", "gpt-4.1-mini", "gpt-4.1"]


@pytest.fixture(autouse=True)
def _models():
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=MODELS,
    ):
        yield


@pytest.fixture
async def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "old"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="gpt-4.1-mini",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_save_creates_an_agent(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1", CONF_PROMPT: "hello"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    # Verify against the real store, not the response.
    created = entry.subentries[msg["result"]["subentry_id"]]
    assert created.subentry_type == SUBENTRY_TYPE_CONVERSATION
    assert created.data[CONF_CHAT_MODEL] == "gpt-4.1"
    assert created.data[CONF_PROMPT] == "hello"
    assert created.title == "gpt-4.1"


async def test_save_updates_an_existing_agent(hass, hass_ws_client, entry):
    existing = next(iter(entry.subentries))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "subentry_id": existing,
            "data": {CONF_CHAT_MODEL: "gpt-4.1", CONF_PROMPT: "new"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["subentry_id"] == existing

    updated = entry.subentries[existing]
    assert updated.data[CONF_PROMPT] == "new"
    assert updated.title == "gpt-4.1"
    assert len(entry.subentries) == 1, "an update must not create a second agent"


async def test_save_rejects_input_with_no_model(hass, hass_ws_client, entry):
    """Validation parity: what the flow rejects, this must reject the same way."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_PROMPT: "no model here"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_data"
    assert "model_required" in msg["error"]["message"]
    assert len(entry.subentries) == 1, "a rejected save must create nothing"


async def test_save_rejects_a_field_the_schema_forbids(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1", "not_a_real_field": 1},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_data"


async def test_save_on_unknown_entry_is_reported(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": "nope",
            "data": {CONF_CHAT_MODEL: "gpt-4.1"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_save_requires_admin(hass, hass_ws_client, hass_admin_user, entry):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/save",
            "entry_id": entry.entry_id,
            "data": {CONF_CHAT_MODEL: "gpt-4.1"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"


async def test_error_message_carries_no_credential(hass, hass_ws_client, entry):
    import json

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/agent/save", "entry_id": entry.entry_id, "data": {}}
    )
    msg = await client.receive_json()
    assert "k" != json.dumps(msg)  # sanity; the real check is the key's absence
    assert CONF_API_KEY not in json.dumps(msg)
```

- [ ] **Step 3: Run to confirm failure**

Run: `uv run --prerelease=allow pytest tests/test_ws_agent_save.py -q`
Expected: `unknown_command` on every test.

- [ ] **Step 4: Implement it**

Add to `websocket_api.py` and register it:

```python
@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/agent/save",
        vol.Required("entry_id"): str,
        vol.Optional("subentry_id"): str,
        vol.Required("data"): dict,
    }
)
@websocket_api.async_response
async def ws_agent_save(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Create or update an agent, validating exactly as the config flow does."""
    from .config_flow import agent_title, normalize_model_input, subentry_schema

    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return

    subentry_id = msg.get("subentry_id")
    subentry = None
    if subentry_id is not None:
        subentry = entry.subentries.get(subentry_id)
        if subentry is None:
            connection.send_error(msg["id"], "not_found", "Unknown agent")
            return

    models = await _models_for(hass, entry, refresh=False)
    schema = subentry_schema(hass, entry.unique_id, dict(msg["data"]), models=models)

    try:
        data = dict(schema(dict(msg["data"])))
    except vol.Invalid as err:
        connection.send_error(msg["id"], "invalid_data", str(err))
        return

    error = normalize_model_input(data)
    if error:
        connection.send_error(msg["id"], "invalid_data", error)
        return

    title = agent_title(data)
    if subentry is None:
        new = ConfigSubentry(
            data=data,
            subentry_type=SUBENTRY_TYPE_CONVERSATION,
            title=title,
            unique_id=None,
        )
        hass.config_entries.async_add_subentry(entry, new)
        connection.send_result(msg["id"], {"subentry_id": new.subentry_id})
        return

    hass.config_entries.async_update_subentry(entry, subentry, data=data, title=title)
    connection.send_result(msg["id"], {"subentry_id": subentry.subentry_id})
```

Import `ConfigSubentry` from `homeassistant.config_entries`.

Note the validation order, which mirrors the flow: the schema runs first and rejects unknown or ill-typed fields, then `normalize_model_input` applies the rule the schema cannot express.

- [ ] **Step 5: Run the tests**

Run: `uv run --prerelease=allow pytest tests/test_ws_agent_save.py tests/ -q`

- [ ] **Step 6: Break-it check**

Substitute wrong values rather than deleting.

- Make `ws_agent_save` always create, never update (ignore `subentry`). `test_save_updates_an_existing_agent` must fail on the agent count. Revert.
- Make it skip `normalize_model_input` by discarding its return value. `test_save_rejects_input_with_no_model` must fail. Revert.
- Make `agent_title` return a constant `"Agent"`. Two tests must fail. Revert.

- [ ] **Step 7: Lint and commit**

```bash
git add custom_components/smartchain/websocket_api.py custom_components/smartchain/config_flow.py tests/test_ws_agent_save.py
git commit -m "feat(panel): create and update agents over websocket

One command for both, because the panel's form is the same either way.
Validation runs the flow's own schema and then the flow's own
normalize_model_input, so nothing is restated. The title expression that
was written twice becomes agent_title, called from all three places."
```

---

### Task 4: Duplicating and deleting an agent

**Files:**
- Modify: `custom_components/smartchain/websocket_api.py`
- Test: `tests/test_ws_agent_copy_delete.py` (create)

**Interfaces:**
- Produces: `smartchain/agent/duplicate` returning `{"subentry_id": str}`; `smartchain/agent/delete` returning `{}`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_agent_copy_delete.py`:

```python
"""Duplicating and deleting agents through the panel's websocket API."""

import pytest
from homeassistant.config_entries import ConfigSubentryData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_PROMPT,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    UNIQUE_ID_OPENAI,
)


@pytest.fixture
async def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "carefully tuned"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_duplicate_copies_the_data_under_a_new_id(hass, hass_ws_client, entry):
    original_id = next(iter(entry.subentries))
    original = entry.subentries[original_id]

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/duplicate",
            "entry_id": entry.entry_id,
            "subentry_id": original_id,
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    copy_id = msg["result"]["subentry_id"]
    assert copy_id != original_id
    copy = entry.subentries[copy_id]
    assert dict(copy.data) == dict(original.data)
    assert copy.subentry_type == SUBENTRY_TYPE_CONVERSATION
    assert len(entry.subentries) == 2


async def test_duplicate_gives_the_copy_a_distinguishable_title(hass, hass_ws_client, entry):
    """Two agents with identical titles are unusable in a list."""
    original_id = next(iter(entry.subentries))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/duplicate",
            "entry_id": entry.entry_id,
            "subentry_id": original_id,
        }
    )
    msg = await client.receive_json()
    copy = entry.subentries[msg["result"]["subentry_id"]]
    assert copy.title != entry.subentries[original_id].title
    assert "Home" in copy.title


async def test_duplicate_leaves_the_original_untouched(hass, hass_ws_client, entry):
    original_id = next(iter(entry.subentries))
    before = dict(entry.subentries[original_id].data)
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/duplicate",
            "entry_id": entry.entry_id,
            "subentry_id": original_id,
        }
    )
    await client.receive_json()
    assert dict(entry.subentries[original_id].data) == before


async def test_delete_removes_the_agent(hass, hass_ws_client, entry):
    target = next(iter(entry.subentries))
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/delete",
            "entry_id": entry.entry_id,
            "subentry_id": target,
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert target not in entry.subentries


async def test_delete_of_an_unknown_agent_is_reported(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/delete",
            "entry_id": entry.entry_id,
            "subentry_id": "not-a-real-id",
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"
    assert len(entry.subentries) == 1


@pytest.mark.parametrize("command", ["duplicate", "delete"])
async def test_both_commands_require_admin(
    hass, hass_ws_client, hass_admin_user, entry, command
):
    target = next(iter(entry.subentries))
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": f"smartchain/agent/{command}",
            "entry_id": entry.entry_id,
            "subentry_id": target,
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"
    assert len(entry.subentries) == 1
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run --prerelease=allow pytest tests/test_ws_agent_copy_delete.py -q`
Expected: `unknown_command`.

- [ ] **Step 3: Implement both**

Add to `websocket_api.py` and register both:

```python
def _resolve_agent(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> tuple[ConfigEntry, Any] | None:
    """Entry and agent subentry named by the message, or None after sending an error."""
    entry = _get_entry(hass, msg["entry_id"])
    if entry is None:
        connection.send_error(msg["id"], "not_found", "Unknown config entry")
        return None
    subentry = entry.subentries.get(msg["subentry_id"])
    if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
        connection.send_error(msg["id"], "not_found", "Unknown agent")
        return None
    return entry, subentry


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/agent/duplicate",
        vol.Required("entry_id"): str,
        vol.Required("subentry_id"): str,
    }
)
@websocket_api.async_response
async def ws_agent_duplicate(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Copy an agent, so a tuned prompt can be reused without retyping it."""
    resolved = _resolve_agent(hass, connection, msg)
    if resolved is None:
        return
    entry, subentry = resolved

    copy = ConfigSubentry(
        data=dict(subentry.data),
        subentry_type=SUBENTRY_TYPE_CONVERSATION,
        # A copy sharing the original's title is indistinguishable in a list.
        title=f"{subentry.title} (copy)",
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, copy)
    connection.send_result(msg["id"], {"subentry_id": copy.subentry_id})


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): "smartchain/agent/delete",
        vol.Required("entry_id"): str,
        vol.Required("subentry_id"): str,
    }
)
@websocket_api.async_response
async def ws_agent_delete(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove an agent."""
    resolved = _resolve_agent(hass, connection, msg)
    if resolved is None:
        return
    entry, subentry = resolved

    hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
    connection.send_result(msg["id"], {})
```

- [ ] **Step 4: Run the tests**

Run: `uv run --prerelease=allow pytest tests/test_ws_agent_copy_delete.py tests/ -q`

- [ ] **Step 5: Break-it check**

- Make the copy reuse the original's title exactly. `test_duplicate_gives_the_copy_a_distinguishable_title` must fail. Revert.
- Make `_resolve_agent` skip its `subentry_type` check. Nothing should fail yet — say so in your report; it guards against deleting an embeddings subentry through the agent command, which D2 will make reachable. Leave the check in.

- [ ] **Step 6: Lint and commit**

```bash
git add custom_components/smartchain/websocket_api.py tests/test_ws_agent_copy_delete.py
git commit -m "feat(panel): duplicate and delete agents over websocket

Duplication is the panel's reason to exist over the flow dialog: a tuned
prompt gets reused without retyping. The copy is titled distinctly, since
two identical titles are unusable in a list."
```

---

### Task 5: The tab shell

**Files:**
- Modify: `custom_components/smartchain/panel/smartchain-panel.js`, `panel/styles.js`

**Interfaces:**
- Produces: a shell rendering a tab bar and one tab at a time, propagating `.hass` to the active tab.

- [ ] **Step 1: Replace the shell**

Rewrite `panel/smartchain-panel.js`'s class body. Remove Task 1's temporary `#entry=` scaffolding entirely — that comment said it would go, and this is where it goes.

```javascript
import { SC_STYLES } from "./styles.js";
import "./components/camera-tab.js";
import "./components/agents-tab.js";

const TABS = [
  { id: "agents", label: "Agents", tag: "sc-agents-tab" },
  { id: "camera", label: "Camera", tag: "sc-camera-tab" },
];

class SmartChainPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._panel = null;
    this._initialized = false;
    this._active = TABS[0].id;
  }

  set panel(panel) {
    this._panel = panel;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._initialized) {
      this._initialize();
      this._initialized = true;
    }
    this._propagateHass();
  }

  _propagateHass() {
    // Only the visible tab is in the DOM, so this reaches whichever it is.
    for (const tab of TABS) {
      const el = this.querySelector(tab.tag);
      if (el) el.hass = this._hass;
    }
  }

  _initialize() {
    this.innerHTML = `
      <style>${SC_STYLES}</style>
      <div class="sc-tabs" role="tablist"></div>
      <div class="sc-tab-body"></div>
    `;
    const bar = this.querySelector(".sc-tabs");
    for (const tab of TABS) {
      const button = document.createElement("button");
      button.className = "sc-tab";
      button.textContent = tab.label;
      button.setAttribute("role", "tab");
      button.addEventListener("click", () => this._select(tab.id));
      bar.appendChild(button);
    }
    this._select(this._active);
  }

  _select(id) {
    this._active = id;
    const tab = TABS.find((t) => t.id === id) || TABS[0];
    const bar = this.querySelector(".sc-tabs");
    [...bar.children].forEach((button, i) => {
      button.classList.toggle("sc-tab-active", TABS[i].id === id);
    });
    const body = this.querySelector(".sc-tab-body");
    body.innerHTML = `<${tab.tag}></${tab.tag}>`;
    this._propagateHass();
  }
}

customElements.define("smartchain-panel", SmartChainPanel);
```

Keep the existing console banner block at the bottom of the file unchanged.

- [ ] **Step 2: Add the tab styles**

Append to the template string in `panel/styles.js`, using the Home Assistant CSS variables the rest of the panel already uses:

```css
.sc-tabs {
  display: flex;
  gap: 4px;
  padding: 0 16px;
  border-bottom: 1px solid var(--divider-color, #e0e0e0);
  background: var(--primary-background-color, #fafafa);
}
.sc-tab {
  appearance: none;
  border: none;
  background: none;
  padding: 14px 16px;
  font-size: 14px;
  font-weight: 500;
  color: var(--secondary-text-color);
  cursor: pointer;
  border-bottom: 2px solid transparent;
}
.sc-tab:hover { color: var(--primary-text-color); }
.sc-tab-active {
  color: var(--primary-color, #03a9f4);
  border-bottom-color: var(--primary-color, #03a9f4);
}
.sc-tab-body { padding: 16px; }
```

- [ ] **Step 3: Create a placeholder agents tab**

Task 6 fills this in. For now `panel/components/agents-tab.js` must exist so the import resolves:

```javascript
/**
 * <sc-agents-tab> — agent list and actions. Filled in by Task 6.
 *
 * Properties: .hass
 */
export class ScAgentsTab extends HTMLElement {
  set hass(val) {
    this._hass = val;
  }
}

customElements.define("sc-agents-tab", ScAgentsTab);
```

- [ ] **Step 4: Run the suite and lint**

No Python changed, but confirm nothing broke: `uv run --prerelease=allow pytest tests/ -q` and the lint command.

- [ ] **Step 5: Write the browser check for the user**

You cannot run this — there is no browser or running Home Assistant here. Put
these steps in your report for the user to run, and report DONE with the check
marked outstanding.

Open `/smartchain`. What must be true:
- Two tabs are shown, Agents and Camera.
- Camera is one click away and **works exactly as before** — pick a camera, pick an agent, run an analysis, see the result.
- Switching tabs back and forth does not throw in the console.

The camera tab regressing is the one thing this task can break. If it does, fix it before committing.

- [ ] **Step 6: Commit**

```bash
git add custom_components/smartchain/panel
git commit -m "feat(panel): tab shell

Camera moves under a tab bar, unchanged. Task 1's temporary #entry=
scaffolding is removed."
```

---

### Task 6: The agents tab

**Files:**
- Modify: `custom_components/smartchain/panel/components/agents-tab.js`, `panel/components/agent-form.js`, `panel/styles.js`

**Interfaces:**
- Consumes: every command from Tasks 1–4, and `callWS` from Task 1.

- [ ] **Step 1: Wire the form's save button**

In `panel/components/agent-form.js`, replace the `console.info` placeholder from Task 1 with a real save, and let the caller react:

```javascript
    this.querySelector("#sc-form-save").addEventListener("click", async () => {
      const payload = {
        entry_id: this._entryId,
        data: this._data,
      };
      if (this._subentryId) payload.subentry_id = this._subentryId;
      try {
        const result = await callWS(this._hass, "smartchain/agent/save", payload);
        showToast("Agent saved", "success");
        this.dispatchEvent(
          new CustomEvent("sc-saved", {
            detail: { subentryId: result.subentry_id },
            bubbles: true,
            composed: true,
          })
        );
      } catch (err) {
        // The backend never puts a credential in a message, so this is safe
        // to show as-is.
        showToast(err.message || "Could not save the agent", "error");
      }
    });
```

Import `showToast` alongside `callWS`. Add a Cancel button beside Save that fires `sc-cancelled`, and a refresh control that calls `this.load(true)` so the model list can be re-fetched without reopening the form.

- [ ] **Step 2: Write the agents tab**

Replace `panel/components/agents-tab.js`:

```javascript
import { callWS, escapeHtml, showToast } from "../services.js";
import "./agent-form.js";

/**
 * <sc-agents-tab> — every agent on one screen, with create, edit,
 * duplicate and delete.
 *
 * Home Assistant's own pages can do all of this too; what they cannot do is
 * show every agent's provider, model and tool count at once, or copy a tuned
 * agent in one click. That overview is why this tab exists.
 *
 * Properties: .hass
 */
export class ScAgentsTab extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._rendered = false;
    this._entries = [];
    this._editing = null; // {entryId, subentryId|null}
  }

  set hass(val) {
    const first = !this._hass;
    this._hass = val;
    if (this._rendered && first) this.reload();
  }

  connectedCallback() {
    if (!this._rendered) {
      this._render();
      this._rendered = true;
    }
    if (this._hass) this.reload();
  }

  async reload() {
    try {
      const result = await callWS(this._hass, "smartchain/overview");
      this._entries = result.entries || [];
    } catch (err) {
      showToast(err.message || "Could not load agents", "error");
      this._entries = [];
    }
    this._paint();
  }

  _render() {
    this.innerHTML = `<div class="sc-agents"></div>`;
  }

  _paint() {
    const root = this.querySelector(".sc-agents");

    if (this._editing) {
      root.innerHTML = `<sc-agent-form></sc-agent-form>`;
      const form = root.querySelector("sc-agent-form");
      form.hass = this._hass;
      form.entryId = this._editing.entryId;
      if (this._editing.subentryId) form.subentryId = this._editing.subentryId;
      form.addEventListener("sc-saved", () => {
        this._editing = null;
        this.reload();
      });
      form.addEventListener("sc-cancelled", () => {
        this._editing = null;
        this._paint();
      });
      return;
    }

    if (!this._entries.length) {
      root.innerHTML = `
        <p class="sc-empty">
          No SmartChain providers are configured yet.
          Add one in Settings &rarr; Devices &amp; Services.
        </p>`;
      return;
    }

    root.innerHTML = this._entries
      .map(
        (entry) => `
        <section class="sc-entry" data-entry="${escapeHtml(entry.entry_id)}">
          <header class="sc-entry-head">
            <span class="sc-entry-title">${escapeHtml(entry.title)}</span>
            <span class="sc-entry-engine">${escapeHtml(entry.engine_label)}</span>
            <button class="sc-add" data-entry="${escapeHtml(entry.entry_id)}">+ Agent</button>
          </header>
          ${
            entry.agents.length
              ? `<ul class="sc-agent-list">${entry.agents
                  .map(
                    (agent) => `
                <li class="sc-agent-row">
                  <span class="sc-agent-name">${escapeHtml(agent.title)}</span>
                  <span class="sc-agent-model">${escapeHtml(agent.model || "—")}</span>
                  <span class="sc-agent-tools">${
                    agent.tool_count === null ? "all tools" : `${agent.tool_count} tools`
                  }</span>
                  <span class="sc-agent-actions">
                    <button data-act="edit" data-entry="${escapeHtml(entry.entry_id)}" data-sub="${escapeHtml(agent.subentry_id)}">Edit</button>
                    <button data-act="copy" data-entry="${escapeHtml(entry.entry_id)}" data-sub="${escapeHtml(agent.subentry_id)}">Duplicate</button>
                    <button data-act="del" data-entry="${escapeHtml(entry.entry_id)}" data-sub="${escapeHtml(agent.subentry_id)}">Delete</button>
                  </span>
                </li>`
                  )
                  .join("")}</ul>`
              : `<p class="sc-empty">No agents on this provider yet.</p>`
          }
        </section>`
      )
      .join("");

    root.querySelectorAll(".sc-add").forEach((button) =>
      button.addEventListener("click", () => {
        this._editing = { entryId: button.dataset.entry, subentryId: null };
        this._paint();
      })
    );

    root.querySelectorAll("[data-act]").forEach((button) =>
      button.addEventListener("click", () => this._act(button.dataset))
    );
  }

  async _act({ act, entry: entryId, sub: subentryId }) {
    if (act === "edit") {
      this._editing = { entryId, subentryId };
      this._paint();
      return;
    }

    if (act === "del") {
      const agent = this._findAgent(entryId, subentryId);
      // Deleting an agent destroys a tuned prompt with no undo.
      if (!confirm(`Delete "${agent ? agent.title : "this agent"}"?`)) return;
    }

    const type = act === "copy" ? "smartchain/agent/duplicate" : "smartchain/agent/delete";
    try {
      await callWS(this._hass, type, { entry_id: entryId, subentry_id: subentryId });
      showToast(act === "copy" ? "Agent duplicated" : "Agent deleted", "success");
    } catch (err) {
      showToast(err.message || "That did not work", "error");
    }
    this.reload();
  }

  _findAgent(entryId, subentryId) {
    const entry = this._entries.find((e) => e.entry_id === entryId);
    return entry && entry.agents.find((a) => a.subentry_id === subentryId);
  }
}

customElements.define("sc-agents-tab", ScAgentsTab);
```

- [ ] **Step 3: Add the list styles**

Append to `panel/styles.js`, matching the variables already used elsewhere in the file:

```css
.sc-entry { margin-bottom: 24px; }
.sc-entry-head {
  display: flex; align-items: center; gap: 12px;
  padding-bottom: 8px; border-bottom: 1px solid var(--divider-color, #e0e0e0);
}
.sc-entry-title { font-weight: 500; }
.sc-entry-engine { color: var(--secondary-text-color); font-size: 13px; }
.sc-entry-head .sc-add { margin-left: auto; }
.sc-agent-list { list-style: none; margin: 0; padding: 0; }
.sc-agent-row {
  display: grid;
  grid-template-columns: 1fr 1fr auto auto;
  gap: 12px; align-items: center;
  padding: 10px 0; border-bottom: 1px solid var(--divider-color, #e0e0e0);
}
.sc-agent-model, .sc-agent-tools {
  color: var(--secondary-text-color); font-size: 13px;
}
.sc-agent-actions { display: flex; gap: 8px; }
.sc-agent-actions button, .sc-add {
  appearance: none; border: 1px solid var(--divider-color, #e0e0e0);
  background: none; border-radius: 6px; padding: 4px 10px;
  font-size: 13px; color: var(--primary-text-color); cursor: pointer;
}
.sc-agent-actions button:hover, .sc-add:hover {
  border-color: var(--primary-color, #03a9f4);
  color: var(--primary-color, #03a9f4);
}
.sc-empty { color: var(--secondary-text-color); font-size: 14px; }
@media (max-width: 600px) {
  .sc-agent-row { grid-template-columns: 1fr; gap: 4px; }
}
```

- [ ] **Step 4: Run the suite and lint**

Run: `uv run --prerelease=allow pytest tests/ -q` and the lint command. No Python changed; this confirms nothing else did either.

- [ ] **Step 5: Write the browser check for the user — the whole feature**

You cannot run this. Put the following in your report as a checklist for the user,
and report DONE with the check marked outstanding.

Open `/smartchain`, Agents tab, and walk the full cycle:

1. The list shows every configured provider, and under each its agents with model and tool count.
2. **Create**: `+ Agent`, fill the form, Save. The list returns and shows the new agent. Confirm it also appears under Settings → Devices & Services → SmartChain — the two surfaces must agree.
3. **Edit**: change the prompt, Save, reopen. The change stuck.
4. **Duplicate**: the copy appears with a distinct title and the same model.
5. **Delete**: confirm the prompt appears, accept, the agent goes.
6. **Validation**: try to save with no model. An error is shown, nothing is created.
7. **Refresh**: the model-list refresh control repopulates the dropdown.
8. Reload the page and confirm everything persisted.
9. Narrow the window to a phone width; the rows must stay readable.

The user reports any step that misbehaves; the controller rules on the fix.

- [ ] **Step 6: Commit**

```bash
git add custom_components/smartchain/panel
git commit -m "feat(panel): agents tab

Every agent on one screen with its model and tool count, plus create,
edit, duplicate and delete. Deleting asks first — a tuned prompt has no
undo. Home Assistant's own pages remain the canonical path."
```

---

## Self-Review

**Spec coverage.** §3 architecture → Tasks 1, 3. §4 commands → Tasks 1–4, one task per command group. §4.1 overview and its credential rule → Task 2, with the containment test and its break-it check. §4.2 errors → Task 3's error-code assertions. §5 model caching → Task 1's cache test. §6 panel structure → Tasks 5, 6. §7 changes to existing code → Task 1 Step 1 (renames) and Task 3 Step 1 (title extraction). §8 the `<ha-form>` risk → Task 1, whose entire purpose is retiring it, with an explicit BLOCKED instruction. §9 testing → each task's tests, including one auth test per command. §10 deferred → nothing to build.

**Placeholder scan.** No "TBD" or "handle errors appropriately"; every code step carries its code. Task 5's placeholder `agents-tab.js` is a real file with real content, replaced in Task 6 — not a plan placeholder.

**Type consistency.** `_get_entry`, `_models_for` and `_resolve_agent` are defined in Tasks 1 and 4 and used with those exact signatures. `subentry_schema`, `normalize_model_input` and `agent_title` are named identically in `config_flow.py` and every call site. The overview's field names (`entry_id`, `title`, `engine`, `engine_label`, `supports_embeddings`, `agents[].subentry_id`, `.title`, `.model`, `.tool_count`) are produced in Task 2 and consumed unchanged in Task 6. `callWS` is defined in Task 1 Step 7 and used in Tasks 1, 6.

**Facts verified while writing this plan, so no implementer need re-check them:** `voluptuous_serialize` is installed and `cv.custom_serializer` renders HA selectors into the `{selector: {...}}` shape `<ha-form>` consumes; `async_add_subentry`, `async_update_subentry` and `async_remove_subentry` exist on `ConfigEntries` with the signatures used here; `ConfigSubentry`'s fields are `data`, `subentry_id`, `subentry_type`, `title`, `unique_id`; `websocket_api.require_admin` and `websocket_command` exist and Home Assistant's own order is `require_admin` → `websocket_command` → `async_response`; `hass_ws_client` is available from the test plugin; `async_setup` is at `__init__.py:213`; the agent-title expression appears exactly twice today.

**One thing deliberately left to the implementer's judgement:** Task 6's `computeLabel` returns the raw field name, so the form shows `chat_model` rather than "Model". Translating those labels means reading the integration's `translations/*.json` from the frontend, which is a larger question than this task. If the raw names look bad in Task 1's browser check, say so in the report and the controller will rule on whether D1 or D2 fixes it.
