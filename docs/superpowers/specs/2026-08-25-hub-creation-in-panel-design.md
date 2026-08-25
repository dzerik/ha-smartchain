# Adding a provider from the panel — design

**Date:** 2026-08-25
**Status:** approved, ready for planning
**Supersedes:** the deferral in `2026-08-24-panel-config-d1-design.md` §10

---

## 1. Goal

Let a user connect a new LLM provider — a "hub" — from the SmartChain panel,
instead of leaving for Settings → Devices & Services. This was deliberately
deferred in D1 because it is the one flow that carries a credential; the user
has since asked for it, choosing the full in-panel form over a button that opens
Home Assistant's own dialog.

## 2. The decision that makes this safe

**The command drives Home Assistant's real config flow. It does not create the
entry itself.**

`hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})`
followed by `async_configure(flow_id, user_input)` is exactly what Home
Assistant's own frontend does. Everything the flow already does keeps working
without being restated:

- `validate_client` actually contacts the provider before an entry is created
- `_abort_if_unique_id_configured` refuses a provider that is already connected
- the schema is `ENGINE_SCHEMA[engine]`, the same object the native dialog uses
- errors come back as **translation keys** — `cannot_connect`,
  `invalid_response`, `unknown` — never as provider text

That last point is the one that matters most. SmartChain shipped a fix in v4.0.2
because provider exceptions embed the offending key fragment in their messages,
and the flow has since returned keys rather than text. By routing through the
flow, this feature inherits that fix instead of needing its own.

**So the honest risk statement changed during design.** The concern recorded in
D1 was that moving hub creation into the panel widens the surface on which a
credential could leak. Driving the real flow makes our path **equivalent** to
Home Assistant's own rather than wider: the same dict reaches the same handler
over a websocket connection either way. What our code adds is a pass-through,
and the rules below keep it one.

## 3. What our code must never do

- **Never echo the submitted data.** No response includes `data`, not even on
  success, and not in an error.
- **Never log the message.** No `LOGGER.debug("%s", msg)` anywhere on this path;
  the key is in `msg["data"]`.
- **Never forward an exception's text.** The flow returns keys; if our handler
  catches anything itself, it reports a code, not `str(err)`.
- **Never persist it anywhere but the entry.** No cache, no `hass.data`.

A test asserts the credential's value appears in no response on any path,
including the failure ones, exactly as the other thirteen commands are tested.

## 4. Commands

| Command | Input | Returns |
|---|---|---|
| `smartchain/hub/providers` | — | `[{id, label, supports_embeddings}]` |
| `smartchain/hub/schema` | `engine` | `{schema, labels, descriptions}` |
| `smartchain/hub/create` | `engine`, `data` | `{ok: true, entry_id}` or `{ok: false, reason, errors?}` |

`providers` comes from `CONF_ENGINE_OPTIONS` and already exists as data; it is
served rather than hard-coded in the panel so a provider added to the table
appears in the panel with no frontend change — the same single-source rule the
rest of the panel follows.

`schema` serialises `ENGINE_SCHEMA[engine]` through the existing pipeline, and
carries the labels and help text added for every other form. Nothing new is
needed there: the config steps already have both.

`create` runs the three flow steps in one call — init, pick the engine, submit
the fields — because the panel has already collected everything and a
three-round-trip conversation would only expose more places to leave a flow
half-finished.

**A flow left open is a leak of a different kind.** If `create` fails at the
last step, the handler must abort the flow rather than leave it dangling in
`hass.config_entries.flow`, where it would hold the submitted credential in
memory indefinitely. This is the one piece of bookkeeping the native path does
for us and ours must do itself.

### 4.1 Failure reasons

`already_configured` when the flow aborts on a duplicate; `invalid_auth` and
friends passed through as the flow's own `errors` mapping so the panel can show
them against a field; `unknown` for anything else. The panel translates them —
the keys already exist in both locales, because the native dialog shows the same
ones.

## 5. The panel

The Settings tab gains an "Add provider" action. It opens a two-step form: pick
a provider, then fill its fields — the second step's schema arrives from
`hub/schema` and renders through `<sc-config-form>`, the same component every
other form uses. No new component.

On success the shell refreshes its overview, so the new provider's agents tab
and settings appear without a reload.

**Home Assistant's own dialog stays.** As with the rest of subsystem D, the
panel is an additional surface, not a replacement: a defect here must never be
the reason a user cannot connect a provider.

## 6. What this does not do

- **No editing of an existing hub's credential.** Changing a key is rarer than
  setting one, and it needs a re-authentication flow with different semantics
  — `async_step_reauth` — which the integration does not currently implement.
  Deleting and re-adding works today and the panel already lists entries.
- **No deletion of a hub from the panel.** Removing a config entry removes every
  agent under it. That belongs behind Home Assistant's own confirmation, which
  spells out what is attached.

## 7. Testing

- **`hub/create` creates a real entry**, verified by reading
  `hass.config_entries.async_entries(DOMAIN)` rather than trusting the response.
- **A duplicate provider is refused** with `already_configured`, and no second
  entry appears.
- **A provider that fails validation creates nothing**, and the reason is a key
  the translations define.
- **No response carries the credential** — assert the submitted key's value is
  absent from the whole serialised response on the success path, the duplicate
  path and the validation-failure path.
- **A failed create leaves no dangling flow**: assert
  `hass.config_entries.flow.async_progress()` is empty afterwards, on every
  failure path. This is the property most likely to be missed, because nothing
  visible breaks when it is.
- **`hub/schema` serves a schema for every provider in `hub/providers`** — the
  two must not drift, and a provider added to the table must appear in both.
- All three commands admin-only.
