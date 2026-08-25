# Panel configuration, parts 2 and 3 — design

**Date:** 2026-08-25
**Status:** approved, ready for planning
**Release:** part of v5.0.0 (roadmap subsystem **D**, completing it)

---

## 1. Goal

Finish subsystem D. Add the two remaining configuration surfaces to the panel —
entry settings and embeddings bindings — and a read-only view of `tools.yaml`.
Then pay the two debts D1 deferred by explicit ruling: translated field labels,
and per-field validation errors.

D1 built the machinery. Both new forms go through the same pipeline it
established — the backend serialises the config flow's own schema, `<ha-form>`
renders it — so this spec is mostly about what is *different* about each, not
about how forms work.

## 2. Scope

**D2.** A settings tab editing what `OptionsFlow.async_step_settings` edits
today, and an embeddings tab creating, editing and deleting embeddings
subentries. Translated labels for every form in the panel. Per-field validation
errors.

**D3.** A tools tab showing `tools.yaml` as text, with a syntax-and-schema check
and a reload button.

**Out of scope.** Writing `tools.yaml` from the panel (§7). Creating a config
entry — that is the one flow carrying credentials, and Home Assistant's own
dialog handles it; the panel links to it. Removing Home Assistant's config
pages, which stay canonical.

## 3. D2 settings — smaller than it looks

`OptionsFlow.async_step_settings` calls **the same `subentry_schema`** the agent
form uses, with `entry.options` as defaults instead of a subentry's data. So the
settings tab is the existing pipeline pointed at a different store:

| | agent | settings |
|---|---|---|
| defaults from | `subentry.data` | `entry.options` |
| written by | `async_add_subentry` / `async_update_subentry` | `async_update_entry(entry, options=...)` |
| schema | `subentry_schema` | `subentry_schema` — identical |

Two commands, `smartchain/settings/get` and `smartchain/settings/save`, mirroring
`agent/schema` and `agent/save`. The same field-filtering rule D1 arrived at
applies: serve only the fields the schema declares, because the schema is
conditional and a stale key would make the form permanently unsavable.

## 4. D2 embeddings

`_embeddings_subentry_schema(models, defaults)` already exists and is small — a
name, a model and a free-text model override. It becomes public as
`embeddings_subentry_schema`, the way D1's helpers did when they crossed a
module boundary.

Three differences from agents, each of which the plan must handle:

- **Models come from a different purpose.** `async_fetch_models(...,
  purpose=CAPABILITY_EMBEDDINGS)`. D1's cache is already keyed by
  `(entry_id, purpose)`, so this needs no cache change — that fix was made for
  exactly this.
- **The tab exists only for providers that serve embeddings.** `overview`
  already reports `supports_embeddings` per entry; the tab is hidden when no
  configured entry supports it.
- **The title is the binding, and it is fragile in two directions.** A memory
  store binds to an embeddings subentry by its **title**. `MemoryRegistry`
  collects them by title *across all SmartChain entries*, and — this is the part
  worth knowing — **a title claimed by more than one subentry maps to `None`**,
  so a collision breaks the binding just as thoroughly as a rename does.

  So the panel must warn in three places, not one: before renaming a subentry a
  store refers to, before deleting one, and before **saving a title that another
  subentry already uses**, including on a different entry. The panel makes that
  collision easier to reach than the flow dialog did, because it shows every
  entry at once and invites creating bindings side by side.

  A backend command reports which stores reference a given title and whether a
  proposed title is already claimed; the panel asks the question before writing,
  never after. This is the one place in subsystem D where an edit can break
  something outside the entry being edited.

## 5. The two debts D1 deferred

### 5.1 Translated labels

Every form in the panel currently shows raw field names — `model`, `llm_hass_api`
— although the integration ships full translations for all sixteen agent fields
and all three embeddings fields, in both locales.

The field names in the schema **are** the keys in the translation files. So the
backend resolves them and sends them: each schema-serving command returns a
`labels` map, `{field_name: translated_label}`, built with
`homeassistant.helpers.translation.async_get_translations(hass,
hass.config.language, category, [DOMAIN])`. The panel's `computeLabel` looks a
field up in that map and falls back to the raw name.

Falling back rather than failing matters: a field added to the schema without a
translation must still render, exactly as it does today.

### 5.2 Per-field validation errors

D1's spec asked for Home Assistant's `{field_name: error_key}` error shape and
the plan silently reduced it to a flat message. That was recorded as a ruling and
deferred here.

**Planning changed this decision, and the reason is worth recording.** Home
Assistant's `connection.send_error(msg_id, code, message, translation_key,
translation_domain, translation_placeholders)` cannot carry an arbitrary
per-field map. Delivering the `{field_name: error_key}` shape therefore means
moving every save command off `send_error` and onto a `{"ok": false, …}` result —
changing the error contract of five working, tested D1 commands, for a benefit
that depends on `<ha-form>` consuming the map, which nobody has confirmed.

That is a bad trade, so **the map is not built here.** What is built instead
costs nothing and breaks nothing: the flat message **names the offending field**.
Today a missing model reports `model_required` without saying which control to
look at; after this it says which. That is most of the practical value of
per-field errors, on the existing contract.

The `{field_name: error_key}` shape stays deferred, now with a concrete
precondition rather than a vague one: it is worth doing once the browser check
confirms `<ha-form>` consumes an error map, and not before.

## 6. D3 tools.yaml, read-only — and the reason it is read-only

Three commands: `smartchain/tools/get` returns the file's **raw text**;
`smartchain/tools/validate` parses and validates it; `smartchain/tools/reload`
calls the existing reload path.

**The raw text is the whole point, and sending anything else would leak
secrets.** `load_tools_file` resolves `!secret` references against Home
Assistant's secret store, so the parsed result contains real credentials. The
panel therefore receives the file as it sits on disk — where `!secret openai_key`
is a *reference*, not a value — and never the parsed structure.

The same trap applies to error messages. `LoaderError` wraps voluptuous errors,
and voluptuous embeds the offending value in its message. A secret that
resolved and then failed validation would appear in that text. So
`tools/validate` returns the error's **location and type**, not its raw string,
unless the raw string can be shown to contain no resolved value. The plan must
settle this concretely; the safe default is to return the exception type and the
YAML path, and log the detail server-side.

Validation reuses `load_tools_file` rather than reimplementing checks. It runs
in an executor — the loader does blocking file I/O and says so.

**Why no editing.** A wrong keystroke in this file disables every custom tool,
every MCP server and the memory subsystem at once. The file also carries
`!secret` references that an editor would either expose or overwrite. Viewing
with a validity check and a reload button covers the common need — "did my edit
take, and is it valid" — at a fraction of the risk. Editing can be a considered
step later, with backups and a rollback, if it turns out to be wanted.

## 7. Commands added

| Command | Returns |
|---|---|
| `smartchain/settings/get` | serialized schema, current values, labels |
| `smartchain/settings/save` | `{}`; validation errors per field |
| `smartchain/embeddings/schema` | serialized schema, current values, labels |
| `smartchain/embeddings/save` | `{subentry_id}` |
| `smartchain/embeddings/delete` | `{}` |
| `smartchain/tools/get` | `{text, path, exists}` |
| `smartchain/tools/validate` | `{valid, error?}` — never a resolved secret |
| `smartchain/tools/reload` | `{}` |

All admin-only, all assembled field by field, like D1's five.

## 8. Panel structure

Three new tabs beside Agents and Camera: Settings, Embeddings, Tools. The
embeddings tab is hidden when no configured provider supports embeddings; all
three are admin-only, like Agents.

```
panel/components/
  settings-tab.js     one entry's options, using <sc-agent-form>'s shape
  embeddings-tab.js   list + form, mirroring agents-tab.js
  tools-tab.js        text view, validate, reload
```

`agent-form.js` is generalised rather than copied: it already takes a schema and
data and knows nothing about agents, so it becomes `sc-config-form` with the
command names passed in as properties. Copying it three times is how the panel
would start to drift.

## 9. Testing

Same shape as D1: one test per command for the success path, one per command for
admin-only, and one asserting the serialised response carries no credential.
Beyond that, the cases specific to this spec:

- **Settings write to `entry.options`, not `entry.data`** — a test asserting
  `entry.data` is untouched after a settings save. Writing options into data
  would put settings where credentials live.
- **The stale-conditional-field trap D1 hit** — settings uses the same
  conditional schema, so it needs the same test: change what the schema declares,
  then confirm the served data still round-trips through save.
- **Embeddings model purpose** — a test asserting the embeddings schema command
  fetches with `purpose=CAPABILITY_EMBEDDINGS` and not the chat list.
- **The rename warning** — a test that the backend reports which memory stores
  reference an embeddings subentry, so the panel can warn before a rename.
- **The title-collision warning** — a test with the same title on two embeddings
  subentries across two entries, asserting the backend reports the collision.
  `MemoryRegistry` maps such a title to `None`, so this silently disables the
  store, and it is the failure the panel makes easiest to cause.
- **`tools/get` returns raw text** — a test with a `!secret` reference in the
  file asserting the response contains the literal `!secret` token and not the
  resolved value.
- **`tools/validate` on a broken file** — asserting the response reports the
  failure without embedding a resolved secret. Give the fixture a secret that
  fails validation and assert its value is absent from the whole response.
- **Labels** — a test that every field the schema declares has a label, and that
  a field with no translation falls back to its raw name rather than vanishing.

## 10. The unverified assumption, still

Nothing in the panel has been rendered in a browser. D1 shipped with that
outstanding and this spec does not change it: there is no browser in the
development environment, and the check belongs to the user.

D2 and D3 add three tabs to that same unverified surface. The fallback remains
contained — `<ha-form>` is used in one component, which §8 generalises rather
than duplicates, so the fallback stays a single-file change even after this
spec.

## 11. Deferred beyond subsystem D

- Editing `tools.yaml` (§6).
- Creating a config entry from the panel.
- Reordering or grouping agents — no storage exists for an order.
- A settings surface for anything not already in `OptionsFlow`.
