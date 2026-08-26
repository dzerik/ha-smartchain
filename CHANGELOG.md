# Changelog

All notable changes to this project are documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
project follows [Semantic Versioning](https://semver.org/).

> **Note:** `5.0.1`–`5.0.7` were released without changelog entries and are not
> reconstructed here.
>
> **Note:** the `5.4.0` section below is a roll-up: it covers `5.4.0` through
> `5.4.7`, which were developed on one branch and are not separated here.

## [5.4.9] - unreleased

### Documentation
- **The user guide told people to click controls that no longer exist.** Four
  subsystems changed between `5.1.0` and `5.4.8` and `docs/USAGE.md` /
  `docs/USAGE-ru.md` had not been touched. Corrected in both languages:
  - `verify_ssl` and `profanity` were listed as **agent** options. They left the
    agent form in `5.4.1` and the `3 -> 4` migration deletes them from an
    agent's storage; they are connection settings on the entry. The agent-options
    table now ends where the form does, and a new **§4.2** documents the two
    connection settings, where they are edited, why they moved and what the
    migration does with a value an agent already stored.
  - **§10.1** said to toggle "Enable multi-agent tools". That switch was deleted
    in `5.4.0`. The section now says to tick `ask_agents` and `critique_response`
    in the agent's **Tools** list, and says plainly that on a migrated agent both
    are **off** — the old switch defaulted to off, so the migration wrote down an
    agent that never had them. Same for `get_state_history` in **§6.1**.
  - **§12** said administrators see five panel tabs. There are six — Agents,
    Embeddings, Stores, Settings, Tools, Camera — and Embeddings is the one that
    can disappear, which the section now explains rather than leaving as a
    surprise.
  - **§9.1** routed embeddings-binding setup through the Devices & Services
    three-dot menu and never mentioned the **Embeddings tab**, which is what a
    user needs before the Stores form will accept anything. Both routes are now
    given, the tab first, with the dependency stated where it bites.
- **§3 is rewritten as "Hubs and agents".** It described sub-entries as "multiple
  agents per provider" and pointed at a menu item ("Add sub-entry") that has not
  existed since there were four sub-entry types. It now states the `5.1.0` model
  — a config entry is a connection and nothing else — tabulates the four
  sub-entry kinds against their real menu names and their sections, and records
  that a hub with no agents is a valid state and what the `1 -> 2` migration does
  to a `5.0.x` entry that had one.
- Swept the chapters the changed subsystems touch. Newly documented, all of it
  reachable behaviour that had no entry anywhere: the `(missing tool)` label and
  the `invalid_data: allowed_tools` dead end it fixed (§7.5); what a migrated
  `allowed_tools` list actually contains (§7.5); the storability guard and why a
  templated target is now safe to re-save (§7.0.1); a broken `tools.yaml` no
  longer disabling UI-built tools and stores, and the banner that reports it
  (§7.7); a disabled imported tool no longer waking its `tools.yaml` twin (§7.7);
  a store save that reports whether the store started (§9.2); a sub-entry write
  that no longer reloads the hub (§9.2); the agent form's `model_user` field,
  which the options table had never listed (§4). Six new troubleshooting entries
  answer the questions the four stale passages would have produced.
- `README.md` / `README-ru.md`: the panel is described as the six tabs it has
  rather than "a camera analysis tab"; the configuration model is the hub/agent
  split; Quick Start's agent fields match the form; the "What's new" table gains
  `5.1.0` through `5.4.x`; the test badge is current. The Russian overview also
  stopped claiming SmartChain ships an AI panel for generating and deploying
  automations from a text description — that feature was removed in `4.0.0`.

## [5.4.8] - unreleased

### Fixed
- **Switching on one ready-made tool reloaded the whole hub.** Measured on a copy
  of a real install: installing three presets cost 3 `async_setup_entry` cycles,
  3 unloads, 6 `conversation.* → offline` transitions and 6 embedding-dimension
  probes — each probe a fresh OAuth exchange under a 30 s timeout — and an Assist
  request landing in one of those windows failed. `update_listener` was doing two
  different jobs and paying for both on every write: a reload is what a change to
  the *entry* needs, while a tool, store or embeddings binding needs none of it
  (`custom_tools_for` reads the live registry at request time, so a tool switched
  on is in the next message without the entity being touched). Each half is now
  gated on its own fingerprint — `_entry_fingerprint` over everything a reload
  would pick up, defined by exclusion so a field added later is reloaded for by
  default, and the subsystem fingerprint moved inside `_reload_registry` under
  the rebuild lock, where two paths reacting to one write can no longer both read
  it stale. After: 0 setup cycles, 0 unloads, 0 entity transitions, 3 rebuilds
  and 3 probes for three presets. Handlers that edit `tools.yaml` still rebuild
  ungated, since no fingerprint can see the file, and a skipped rebuild returns
  the standing `tools.yaml` error rather than clearing the Tools-tab banner on a
  file that is still broken.

## [5.4.0] - unreleased

### Added
- **A normal set of tools you can just switch on.** The **Tools** tab opens with
  a **Ready-made tools** catalogue above your own: eight real tools — weather
  forecast, sun times, calendar events, to-do list items, area summary, who is
  home, look at a camera, notify a device — each a row with a switch. Switching
  one on writes it as an ordinary tool sub-entry: editable, disableable,
  deletable, indistinguishable afterwards from one built in the form.
  The catalogue covers what Assist and the built-in tools do not, on purpose —
  it does not offer a second way to turn a light on. Three things the catalogue
  deliberately omits (energy over a period, sensor min/max/mean, recent logbook
  events) need the recorder's statistics or the logbook, which are websocket-only
  and belong in a built-in tool rather than in a preset.
- Two admin-only commands behind it: `smartchain/tool/presets` lists the
  catalogue with an `installed` flag derived from the tool sub-entries that
  exist, and `smartchain/tool/preset/install` materialises one. Install reuses
  `validate_tool_name` (reserved names, duplicates, a live MCP tool's name), the
  same `_write_subentry` storability guard and the same registry rebuild as
  `smartchain/tool/save`, and reports `shadows_yaml` the same way.
- **A translation key convention for panel text**: `config_panel.presets.<tool
  name>.name` and `.description`, in both locales. The tool's own `description`
  — the sentence the *model* reads — stays English in `tools/presets.py`, since
  that is what the providers are trained on. Different audiences, different
  strings, different places.
- **One place that says what an agent can do.** The **Agents** tab's tools cell
  expands into the agent's whole inventory — the six built-in tools and every
  custom tool together, the ones that are *off* included, each with where it
  comes from and, when it is off, why. Backed by a new admin-only
  `smartchain/agent/tools` command.
- **`tools/inventory.py`** is the single assembly. `_async_handle_message` binds
  the tools this module returns, and the panel reports the same call, so the
  report and the runtime cannot drift. A test drives a real message, captures
  the `bind_tools` argument and asserts the two sets are equal.
- `smartchain/overview` now serves `tool_count` (tools the agent really has) and
  `tool_total` (tools it could have) per agent, so the tab can say "2 of 8".

### Changed
- **"Allowed tools" is now the one control over an agent's tools, and it always
  renders.** It previously appeared only when the tools registry was non-empty,
  so a user who had never written a `tools.yaml` had never seen it. It now lists
  the six built-ins alongside your own tools, labelled as built-in.
- **`enable_history_tool` and `enable_multi_agent_tools` are gone from the agent
  form.** They were a second opinion on a question the list now answers, and two
  controls that can disagree are worse than either alone. Config entries migrate
  to minor version 3, which writes each agent's built-ins into its
  `allowed_tools` list and deletes the switches — every agent keeps exactly the
  tools it had. The two keys are still honoured for an agent that carries no
  list at all, so a subentry built by a downstream integration still works.
- **`ask_agents` and `critique_response` are separable.** One switch used to
  hold both; they hold one list entry each, so an agent may fan out to its
  siblings without also being allowed to ask one for a review.

### Fixed
- **Saving a tool whose target was a template broke Home Assistant's config
  storage — for every integration on the system.** `docs/USAGE.md` §7.1 teaches
  `target: {entity_id: "{{ entity }}"}`, and importing such a tool worked. But
  opening it in the Tools tab and pressing Save handed the string to
  `selector.TargetSelector`, which turns it into a `Template` *object*, and that
  object went into the subentry. From then on every write of
  `core.config_entries` raised `TypeError` inside a delayed-write task that
  discards its buffer and reports nothing — so the file stopped being updated
  for every integration, and a restart read back whatever had last been written:
  the tool gone, and anything configured after it gone with it.
  Every subentry write — tools, stores, agents, embeddings — and the entry's own
  options now pass through one guard (`storable.py`). A value that carries its
  own source text is normalised back to it (a `Template` becomes the string that
  was typed, exactly as Home Assistant's `TemplateSelector` already does);
  anything else JSON cannot hold is refused, naming the field, rather than
  written. Both the panel's websocket commands and Home Assistant's own subentry
  dialogs are covered, the latter by a shared base class so a flow added later
  cannot forget.
- **A `Template` reaching a service action did nothing, silently.**
  `_render_value` templated `str`, `dict` and `list` and passed anything else
  through untouched, so the object went straight into
  `hass.services.async_call(target=…)` and the model's argument never reached
  the service. It is now rendered.
- **The first Save a new user performs said `model_required`.**
  `DEFAULT_CHAT_MODEL` is empty, so **Agents → + Agent** opens with no model
  selected; saving answered with a bare machine key that the panel could not
  attach to a field and toasted verbatim. Every save command now reports a
  rejected field as `invalid_data: <fields> — <reason>`, the panel attaches the
  reason to the control, and the reason for this one is the sentence the config
  flow has always shown, read from the translation files in the user's own
  language.
- **`allowed_tools` did not do what it said.** Every built-in was appended
  unconditionally and only custom tools were filtered, so an agent "restricted
  to one custom tool" still received `search_memory`, `search_entities`,
  `ask_agent` and the history tool. The list now filters built-ins too. Note
  what this means for an agent that *already* had a restricted list: the
  built-ins it never named are dropped from it — which is what the panel had
  been telling users all along, and what minor version 3 writes down explicitly
  so nobody's agent changes silently.
- **`tool_count` in the Agents tab counted a setting, not a capability.** It was
  `len(allowed_tools)`, or "all tools" when unset, and so never mentioned a
  single built-in.
- **`enable_multi_agent_tools` was gated on the wrong condition** — whether *any*
  entry had *any* two subentries, so an embeddings binding made it appear where
  it could not work, and it was hidden while creating the second agent, which is
  when it is first wanted. The field is gone; the inventory answers the real
  question (a second *conversation* agent on *this* entry) and says
  `no_siblings` when the answer is no.
- **Saving an agent could destroy a stored value.** `smartchain/agent/schema`
  strips keys the current schema does not declare, and both save paths then
  replaced `subentry.data` wholesale — so opening and saving an agent deleted
  anything that happened to be out of schema. Both the websocket command and the
  Devices & Services dialog now merge.
- The Tools tab's note on "Allowed tools" is rewritten again: as of this release
  it really does govern built-ins, which 5.3.0 corrected it to deny.
- **The Stores tab dead-ended a first-time user with a machine key.** With no
  embeddings binding configured, the store form's `embeddings` dropdown is
  required and its option list is *empty* — a field no value can satisfy — and
  pressing Save answered `invalid_data: embeddings`, which the panel rendered
  under that unanswerable control. `smartchain/store/save` ran the voluptuous
  schema before the rules, so every sentence `STORE_ERROR_TEXT` has about
  `embeddings` was unreachable. The rules now run first (the same fix
  `model_required` got on the agent form), the sentence is read from the
  translation files in the user's language, and a new one says what to actually
  do: create a binding on the Embeddings tab first. The tab no longer lets the
  Save be pressed into that wall — it already received `embeddings_available`
  from the schema command and ignored it; it now says so above the form and
  holds Save until a binding exists.
- **A store that failed to build was reported as a plain green "Saved".**
  `smartchain/store/save` now carries `store_error`, the same safe text
  `store/status` serves, and the tab says the store did not start. The per-store
  row could not explain itself either: `_describe_store` read the registry's
  failures only when the registry was truthy, and `MemoryRegistry.__len__`
  counts *live* stores — so an install whose every store failed was exactly the
  one told `reason: null`. The row now names the reason.
- **The GigaChat embeddings client ignored "Verify SSL certificates".**
  `verify_ssl_certs=False` was hardcoded, so turning the hub's switch on secured
  the conversation client (fixed in 5.4.1) and left every embedding request
  against the same host unverified. It reads `entry.options` like every other
  client.

### Notes
- **`ALL_TOOLS_SENTINEL` (`*`) still means every *custom* tool**, not every
  tool: a built-in needs its own name in the list. Widening it would make "all
  my tools, but not `search_memory`" inexpressible. Absent still means no
  restriction, and an empty list still means nothing — the ordering that keeps a
  newly added tool from being granted to an agent that already has restrictions.
  That rule now covers built-ins too, so a built-in added in a future release
  will not appear in a migrated agent's list on its own.

## [5.3.0] - unreleased

### Added
- **Custom tools are built in a form, not typed as YAML.** A tool is now a `tool`
  config sub-entry — add one from the rebuilt **Tools** tab in the SmartChain
  panel, or from **Settings > Devices & Services > SmartChain > Add tool**. Name,
  description and enabled are plain fields; the action type is a picker and the
  rest of the form follows it, so a `service` tool asks for a Home Assistant
  action and a target (both pickers) and a `script` tool asks for a script
  entity. Arguments are a row per argument — name, type, description, required —
  which is the `parameters` JSON Schema, built for you.
- **A raw JSON Schema box for the shapes rows cannot express.** `anyOf`, nested
  objects and arrays are still writable: switch the parameter mode to `advanced`.
  Both modes end at the same validator `tools.yaml` passes through, and a tool
  reopened for editing lands in whichever mode can represent it — a schema the
  rows would silently shrink opens in the advanced box instead.
- **The whole constructor is a backend-served schema.** `smartchain/tool/schema`
  serialises every field, its selector, and the two fields that reshape the form;
  `<sc-config-form>` renders it. The Tools tab declares no field name of its own,
  and a test enforces that.
- **Websocket commands** `smartchain/tool/schema|save|delete|list` and
  `smartchain/tools/import|export`, all admin-only, plus a `tools` list on
  `smartchain/overview`.
- **Import / export.** Import turns the tools in `tools.yaml` into editable
  sub-entries, leaving the file untouched; export writes them back out as YAML.

### Changed
- **`ToolRegistry` builds from both sources.** An existing `tools.yaml` keeps
  working unchanged — it is still the only home for `mcp_servers:` — but a name
  defined in both resolves in favour of the sub-entry, the editable one, and the
  shadowing is logged, reported by `smartchain/tool/list` and shown in the panel
  rather than left to be discovered. Same rule, and same reasoning, as stores in
  5.2.0.
- The Tools tab's YAML editor is demoted into an **Import / Export** block. It
  keeps its server-side validation, backup and rollback.
- `smartchain.reload_tools`'s count now covers both sources. It still excludes
  MCP tools, which arrive asynchronously after the reload returns.

### Fixed
- **`smartchain.reload_tools` could print a resolved secret.** It raised
  `HomeAssistantError(str(err))` on a loader failure, and a schema failure's
  message interpolates the offending value — which Home Assistant has already
  resolved from `secrets.yaml`, including for mapping *keys*. Calling the action
  from Developer Tools on a rejected `tools.yaml` therefore put the secret in the
  UI toast and into the automation trace, where it persists. It now goes through
  `_safe_loader_error`, the guard the websocket path already used.
- **Three built-in tool names were shadowable.** `RESERVED_TOOL_NAMES` listed
  three of six, so a custom tool named `search_memory`, `ask_agents` or
  `critique_response` was registered alongside the built-in and appended last:
  the model read the built-in's description while the dispatch resolved to the
  custom tool. All six are reserved now, in `tools.yaml` and in the form.
- **The Rollback button ignored a backup it could see.** The panel kept a local
  "did *this session* make a backup" flag, on the stated belief that the backend
  had no way to answer the question — but `smartchain/tools/get` has returned
  `backup_exists` all along. A backup surviving a restart now surfaces the
  button, which is when it is most wanted.
- The tab's reserved-name note listed three of six names, and its `allowed_tools`
  note claimed the setting restricts an agent to the names listed. It filters
  custom tools only; enabled built-ins are added regardless. Both corrected.

### Security
- **A REST header value is write-only.** A header is where an `Authorization`
  token goes, and it now lives in `.storage` rather than in a file the user knows
  the browser can read. No `tool/*` response carries one back — the form shows the
  header's name with an empty value, and an empty submission keeps what is stored
  (per key, so a header can still be removed). Export blanks them too and names
  the tools affected: an export is a response like any other, and the rule that
  no response carries a credential does not acquire an exception because the user
  asked for it.
- **Importing a `tools.yaml` that uses `!secret` is refused outright**, naming no
  value. Importing would have to resolve the reference and write the resolved
  value into `.storage` as plain text, quietly moving a credential out of
  `secrets.yaml`. The file is also parsed without a secrets store, so nothing can
  resolve even if the scan were bypassed.

## [5.2.0] - unreleased

### Added
- **Memory and vector stores are configurable from the UI.** A store is now a
  `memory_store` config sub-entry — add one from **Settings > Devices & Services >
  SmartChain > Add memory store**, or from the new **Stores** tab in the SmartChain
  panel. The form covers everything the `memory:` block of `tools.yaml` covered:
  the embeddings binding, the description, all four vector backends and their
  settings, retention, conversation ingest, and the entity-index source with its
  preset and include/exclude lists.
- **A store's credentials stop passing through a browser-visible text file.**
  `backend.dsn` (a PostgreSQL connection string, password included) and
  `backend.api_key` (a qdrant token) written in `tools.yaml` are handed to the
  browser by `smartchain/tools/get`, which serves that file's raw text. In a
  sub-entry they live in `.storage` and are **write-only**: no schema, overview or
  error response ever carries one back, only whether one is held. Leaving the
  field empty when editing keeps the stored value; switching backend drops it.
- **Failure visibility.** `MemoryRegistry` contains a failing store so the others
  still start, which used to mean a store that never came up was
  indistinguishable from a working one anywhere but the log. It now records why,
  a new `smartchain/store/status` command reports it, and the Stores tab shows a
  health line per store — including for stores that still live in `tools.yaml`.
- New websocket commands `smartchain/store/schema`, `/save`, `/delete` and
  `/status`, all admin-only. `smartchain/overview` gained a `stores` list per
  entry.

### Changed
- **`tools.yaml` is now one source of stores, not the only one.** An existing
  `memory:` block keeps working exactly as before. When both a file and a
  sub-entry define a store of the same name the **sub-entry wins** — it is the one
  the UI can edit — and the shadowing is reported, both as a warning in the log
  and in the panel, rather than left to be discovered.
- `<sc-config-form>` learned reactive schemas: a schema command may return
  `reactive: ["<field>", ...]`, and changing one of those fields re-requests the
  schema with the values entered so far. That is what lets one store form ask for
  a DSN or a qdrant URL without a wizard. Commands that return no `reactive` key
  are unaffected.

### Fixed
- Adding, editing or deleting an **embeddings** binding through the panel did not
  rebuild the memory registry, so the change did nothing until
  `smartchain.reload_tools` or a restart, with no error to explain why. Both the
  embeddings and the new store commands now rebuild and report a rebuild failure
  alongside the successful write.

### Known limitations
- The store form has **no logbook-ingest switch**. `tools/memory/ingest.py`
  depends on `logbook._get_events` / `logbook.humanify`, which the installed Home
  Assistant no longer exposes, so the poller is a runtime no-op — a toggle would
  advertise something the code cannot do. The YAML `ingest_logbook:` block still
  parses for anyone who set it, and starts working again the day the fetcher does.

## [5.1.0] - unreleased

### ⚠ BREAKING CHANGES

**A config entry is a connection, not an agent.** The entry's **Configure** dialog
used to edit an agent — model, prompt, temperature, tools, entity context — using
the very same form an agent sub-entry uses. Those values drove exactly one thing:
a single "legacy" conversation entity that existed only while the entry had no
agent sub-entries. For anyone who had created an agent they were dead
configuration: a control that looked live and was not.

The dialog now offers **connection settings only**. For GigaChat that is
`verify_ssl` and `profanity`; every other provider has none and the step says so
instead of presenting an empty form. The legacy single-entity path is gone: an
entry with no agents provides no conversation entity, which is a coherent state —
a connection nobody is using yet — and not an error.

**Automatic migration, with the entity id preserved.** On the first start after
upgrading, an entry that has agent-shaped options and no conversation sub-entry
gets one created from those options. The legacy entity's unique id was the config
entry id and an agent's is `{entry_id}_{subentry_id}`, so a naive migration would
have orphaned the old entity and broken every automation, script and dashboard
card naming it. Instead the existing registry rows are rewritten **in place** —
both the `conversation` entity and the `ai_task` one — so the entity id, friendly
name and area survive untouched. If a rewrite is impossible (a colliding unique
id, say) the migration **refuses**: it undoes what it did, leaves the entry exactly
as it was, logs why, and that entry keeps the legacy path until the conflict is
resolved.

An entry that has **both** options and agents is left alone — the options stay in
storage, unread and no longer presented, and a single log line says they were
found and ignored.

### Fixed
- An entry whose only sub-entry was an **embeddings** binding lost its conversation
  entity. The old test was `if entry.subentries:` — the truthiness of the whole
  sub-entry dict — rather than "has a conversation sub-entry".
- Saving the entry's settings replaced `entry.options` wholesale. It now merges, so
  a key the current form does not present cannot be destroyed by a save.

### Changed
- The panel's Settings tab is now connection settings, and prints an honest
  sentence for a provider that has none. Its "Refresh models" button is gone from
  that form — a connection form declares no model.
- `smartchain/settings/get` serves `connection_schema` and a new `empty` flag, and
  no longer fetches a model list; `smartchain/settings/save` refuses a provider
  with no connection settings rather than validating against the agent form.

## [5.0.0] - unreleased

### ⚠ BREAKING CHANGES

**Chroma is removed.** `chromadb` and `langchain-chroma` are gone from the manifest and the codebase. If `<config>/.storage/smartchain_memory/` exists from an earlier version it is now orphaned and can be deleted — no data is converted. In practice the directory is empty on most installations, because HA's pip step could not install `chromadb` (which is why v4.4.1 had to make it optional).

**The `memory:` block has a new shape.** Credentials no longer live in `tools.yaml`, so the flat block with `provider` / `model` / `api_key` is rejected with an error naming the migration steps. There is no automatic migration: until you create an embeddings subentry there is nothing for the config to point at.

Migration:
1. Open the provider's config entry and add an **embeddings** subentry, giving it a name and choosing an embedding model.
2. Replace the `memory:` block with a `stores:` list whose `embeddings:` field holds that name.
3. Call `smartchain.reload_tools`.

### Added
- **Four pluggable vector backends** behind one `VectorBackend` Protocol: `sqlite_numpy` (default), `sqlite_vec`, `pgvector` and `qdrant`. The default needs **no dependency beyond what Home Assistant already ships** — stdlib `sqlite3` for storage and numpy for cosine similarity — so long-term memory now works out of the box on every installation. `qdrant` also adds no dependency: it speaks REST over HA's shared aiohttp session.
- **Embeddings as a provider capability.** A new `embeddings` subentry type sits alongside `conversation` and reuses the config entry's credentials, ending the duplicate credential declaration the flat YAML block required. It is offered only where the provider supports it — DeepSeek and Anthropic expose no embeddings API and do not show the option.
- **Purpose-filtered model discovery.** The existing provider model APIs are now split by purpose, so the embeddings form lists `text-embedding-*` for OpenAI, `Embeddings*` for GigaChat and the embedding families for Ollama, while chat forms stop offering embedding models by mistake.
- **Named memory stores.** `memory.stores[]` binds one embeddings subentry to one backend, each with its own retention, logbook polling and conversation-ingest flag. `search_memory` and `smartchain.clear_memory` take a `store` parameter; with a single store it stays optional.
- **Dimension probing.** The embedding dimension is measured at startup and persisted per store. Changing to a model of a different dimension is detected and reported with exact remediation steps instead of corrupting the index.
- **`!secret` now works in `tools.yaml`.** The loader was never given a `Secrets` object, so any `!secret` tag failed the whole file. It is wired through now, which matters most for a pgvector `dsn` — that belongs in `secrets.yaml`, not inline. A `secrets.yaml` beside `tools.yaml` takes precedence over the one in the config root.
- `smartchain.clear_memory` and `smartchain.reload_tools` are declared in `services.yaml`, so they appear in the Home Assistant service picker with their fields.
- **Entity indexing.** A memory store can carry `source: {type: entities}` and becomes a semantic index of the home, with four scope presets (`minimal` / `optimal` / `maximal` / `paranoid`), `include` / `exclude` overrides, and an optional state-tracking mode. The new `search_entities` tool merges lexical and vector matching, so it stays useful when the embeddings provider is unavailable. Sweeps are incremental — only entities whose catalogue text changed are re-embedded, so a restart costs nothing. Entity names, areas and aliases reach the embeddings provider, so the preset is a privacy decision: `optimal` includes `person`, `maximal` adds `device_tracker`, and `paranoid` sends the whole home including diagnostics. `minimal` plus `include` keeps it tight.
- `smartchain.reindex_entities` forces a sweep; `full: true` re-embeds everything, for when the embedding model changed but the entities did not.
- **Dynamic entity context, on by default.** The system prompt no longer renders every area, device and entity with its state on every turn. It now carries a compact **skeleton** of the home — one line per area, entity names grouped by domain, no ids and no states, always complete for the configured scope — plus a per-turn **retrieved block** naming only the entities the message is about, with their entity ids, areas and live states read from `hass.states`. `dynamic_entity_context` defaults to **`true`**, so existing agents change behaviour on upgrade; unticking it on the sub-entry restores the previous prompt byte for byte. `dynamic_context_preset` (default `optimal`) chooses the skeleton's scope from the same four presets the entity index uses and is deliberately independent of any entity store's preset. The skeleton is bounded at `ENTITY_SKELETON_MAX_CHARS` and announces what it dropped instead of truncating silently, pointing the model at `search_entities`; it is cached per preset and invalidated by the entity, device and area registry events. Retrieval runs on the latest message alone — a follow-up phrased as a pronoun retrieves on that pronoun, which the always-present skeleton is what makes survivable. Failures are layered: retrieval failing leaves the skeleton, the skeleton failing falls back to the full devices dump, and neither can raise into the turn.
- **Dynamic entity context needs no entity index.** The skeleton and the lexical half of retrieval read the entity, device and area registries directly, so the feature is fully operational with no memory store, no embeddings sub-entry and no vector backend. A configured entity index adds a semantic pass on top, and only when exactly one exists — with two or more there is no non-arbitrary choice, so retrieval stays lexical.
- **`dynamic_context_on_assist` (default `false`)** extends the feature to the Assist path. With `llm_hass_api` set, Home Assistant injects its own exposed-entity list and control tools, which we cannot shrink, so nothing is added there by default. Enabling the option appends the **retrieved block only** — never the skeleton, which would duplicate HA's list — to `extra_system_prompt`, preserving anything already in it.
- **New providers**: OpenRouter, Groq, Together, LM Studio and llama.cpp. All OpenAI-compatible providers now share one code path driven by a provider table, and every one of them has an editable base URL — including OpenAI and DeepSeek, which previously had a fixed endpoint. OpenRouter, Groq and Together are hosted; LM Studio and llama.cpp are local and need no API key. Embeddings are available from Together, LM Studio and llama.cpp, but not from OpenRouter or Groq.

### Changed
- `hass.data[DOMAIN]["memory"]` now holds a `MemoryRegistry` rather than a single `MemoryStore`.
- `smartchain_memory_cleared` now carries `{"deleted": <int>, "stores": [<names>]}`.
- The Chroma `$and` filter dialect is replaced by a flat backend-neutral filter, translated per backend.
- `VectorBackend` gained `update_metadata` and `list_metadata`, letting a document's metadata be refreshed without re-embedding it.
- `smartchain.clear_memory` on a store with an entity source now schedules a background sweep, so the index rebuilds itself from the live registries instead of staying empty until an unrelated registry event happens to trigger one. The deletion is therefore not permanent, and the rebuild re-embeds every entity.

### Tests
- 656 passing, none skipped (was 289). The centrepiece is a conformance suite executed against every file-based backend; `sqlite-vec` is now a dev dependency so it runs in CI rather than skipping.

## [4.4.1] - 2026-05-28

### Fixed
- **Installation failure on HA OS / Container** — `chromadb` and `langchain-chroma` were declared in `manifest.json` requirements but HA's pip-install step could not resolve them on many setups (native deps, sqlite version, onnxruntime), causing `Setup failed for custom integration 'smartchain': Requirements for smartchain not found: ['chromadb>=0.5,<1', 'langchain-chroma>=0.1,<1']`. Both are removed from the manifest. `langchain-chroma` was never actually imported — pure dead requirement. `chromadb` becomes an optional runtime dependency: the memory subsystem self-disables with a clear log line if `chromadb` is missing. Users who want long-term memory install it manually with `pip install chromadb` inside the HA Python environment.

### Tests
- 289 passing (unchanged).

## [4.4.2] - 2026-05-28

### Changed
- **LangChain 1.x** — bumped all `langchain-*` constraints to allow the 1.x release line (`<2`):
  - `langchain-core` — pinned via transitive graph, now 1.x
  - `langchain-openai`, `langchain-anthropic`, `langchain-ollama` — `>=0.3,<2`
  - `langchain-community` — `>=0.3,<0.5`
  - `langchain-gigachat` — `>=0.3,<1` (0.5.x line now supports `langchain-core>=1`)
- **GitHub Actions bumps** — `astral-sh/setup-uv@v5 → v7`, `sigstore/gh-action-sigstore-python@v3.0.1 → v3.3.0`.
- `yandexcloud` pin changed from `==0.295.0` to `>=0.295.0` for pip flexibility.

### Fixed
- Two config-flow tests (`test_openai_full_flow`, `test_deepseek_full_flow`) leaked sockets on teardown because `langchain-openai 1.x` performs an eager HTTP check in the `ChatOpenAI` constructor. Both now use the `mock_get_client` fixture.

### Tests
- 289 passing (same count, updated for langchain 1.x behaviour). Closes stale dependabot PRs #1, #3, #4, #5, #6, #7, #8, #9.

## [4.4.1] - 2026-05-28

### Fixed
- **Install fix** — `chromadb` and `langchain-chroma` were listed in `manifest.json` requirements, but HA's pip step cannot always resolve `chromadb` (native deps: sqlite ≥ 3.35, onnxruntime, etc.), which blocked the whole integration from loading. Both removed from the manifest:
  - `langchain-chroma` was a dead requirement — nowhere in the codebase.
  - `chromadb` remains a lazy import inside `MemoryStore._init_collection`. `ImportError` is now caught with a clear WARNING and install hint; the memory subsystem self-disables cleanly while the rest of the integration keeps working.
- USAGE docs updated with the manual `pip install chromadb` step for users who want long-term memory.

## [4.4.0] - 2026-05-27

### Added
- **Multi-agent orchestration tools** — two new built-in LLM tools opt-in per subentry via `enable_multi_agent_tools`:
  - `ask_agents` — parallel fan-out via `asyncio.gather` to up to 5 sibling agents at once; per-agent timeout 60 s; responses returned in a single formatted block for the calling agent to summarise.
  - `critique_response` — ask another sibling to review a draft answer (text-in / text-out, no tool recursion). Useful for safety-critical actions and uncertainty resolution.
- **`enable_multi_agent_tools` option** — appears in the subentry form only when the entry has 2+ subentries; defaults to `false`. The existing `ask_agent` (single-delegate) is unchanged.

### Tests
- ~289 passing (was 272). New: `test_delegate_many_tool.py`, `test_critique_tool.py`, `test_multi_agent_subentry_filter.py`, `test_multi_agent_integration.py`.

## [4.3.0] - 2026-05-27

### Added
- **Long-term memory / RAG** — opt-in `memory:` block in `tools.yaml`. SmartChain now keeps embeddings of conversation turns (and optionally HA logbook events) in a local Chroma vector DB at `.storage/smartchain_memory/`, and the LLM can recall them via a built-in `search_memory` tool. Pluggable embeddings provider: Ollama (default), OpenAI, GigaChat, Yandex. See `docs/superpowers/specs/2026-05-27-rag-memory-design.md` for the full design.
- **Daily retention cleanup** — configurable `retention_days` (default 90, 0 disables).
- **`smartchain.clear_memory` service** — deletes stored memories, filtered by `kind` and/or `agent_id`; fires `smartchain_memory_cleared` with the deleted count.
- **`chromadb` + `langchain-chroma`** added as dependencies (loaded lazily — pulled only when memory is enabled).

### Changed
- `smartchain.reload_tools` now also re-builds the memory subsystem (graceful stop of retention/logbook tasks, fresh build from updated `memory:` block).

### Tests
- ~268 passing (was 217). New: `test_memory_config.py`, `test_memory_embeddings.py`, `test_memory_chunking.py`, `test_memory_store.py`, `test_memory_schema.py`, `test_memory_loader.py`, `test_memory_ingest_conversation.py`, `test_memory_ingest_logbook.py`, `test_memory_retention.py`, `test_memory_search_tool.py`, `test_memory_clear_service.py`, `test_memory_integration.py`.

## [4.2.0] - 2026-05-27

### Added
- **MCP client** — SmartChain can now connect to remote MCP (Model Context Protocol) servers declared in `/config/smartchain/tools.yaml` under a new `mcp_servers` block. Three transports supported: `stdio` (local subprocess), `sse` (Server-Sent Events) and `http` (streamable HTTP). Discovered tools land in the same `ToolRegistry` as YAML tools — `allowed_tools` per-subentry filtering works across both sources. See `docs/superpowers/specs/2026-05-27-mcp-client-design.md` for the full design.
- **Per-server failure isolation + auto-reconnect** — one failing MCP server does not affect others. Exponential backoff from 1 s to 30 s.
- **`mcp` Python SDK** added as a dependency.

### Changed
- `smartchain.reload_tools` now restarts MCP connections too — graceful disconnect, re-read YAML, fresh connect. Atomic on failure (prior registry preserved).
- `tools.yaml` `tools:` key is now optional (was required) — files with only `mcp_servers:` are valid.

### Tests
- 214 passing (was 167). New: `test_mcp_config.py`, `test_mcp_schema.py`, `test_mcp_naming.py`, `test_mcp_client.py`, `test_mcp_manager.py`, `test_mcp_action.py`, `test_mcp_loader.py`, `test_mcp_reload.py`, `test_mcp_integration.py`.

## [4.1.0] - 2026-05-27

### Added
- **Custom tools from YAML** — declarative LLM-callable tools in `/config/smartchain/tools.yaml`. Supports four action types: `service` (HA service-call with Jinja-rendered target/data), `template` (Jinja render), `rest` (HTTP request via the HA aiohttp client session), `script` (HA script call with rendered variables). Each tool has a name (`^[a-z_][a-z0-9_]*$`), description and JSON Schema parameters block; arg validation happens via `jsonschema` before execution. See `docs/superpowers/specs/2026-05-27-custom-tools-yaml-design.md` for the full design.
- **`allowed_tools` per subentry** — each conversation agent can be limited to a subset of registered tools through a multi-select in the subentry options form. Semantics: missing/`None` => all available tools, `[]` => no custom tools.
- **`smartchain.reload_tools` service** — re-reads `tools.yaml` atomically; fires `smartchain_tools_reloaded` event with the new tool count on success. On YAML or validation failure, raises `HomeAssistantError` and leaves the previous registry intact.
- **Built-in tool name protection** — YAML tools cannot shadow `get_state_history` (history tool) or `ask_agent` (delegate tool); duplicates within the YAML are dropped with a logged error rather than crashing setup.
- **`jsonschema` dependency** added for argument validation.

### Tests
- 166 passing (was 123). New: `test_tools_model.py`, `test_tools_schema.py`, `test_tools_loader.py`, `test_tools_action_template.py`, `test_tools_action_service.py`, `test_tools_action_rest.py`, `test_tools_action_script.py`, `test_tools_dispatcher.py`, `test_tools_subentry_filter.py`, `test_tools_reload.py`, `test_tools_integration.py`.

## [4.0.2] - 2026-05-27

### Security
- **Provider error messages no longer leak credentials** — `smartchain.ask` and `smartchain.analyze_image` previously returned `f"Error: {err}"` to callers. LangChain provider exceptions (e.g. `openai.AuthenticationError`) routinely embed key fragments in their text, so any authorised HA user who triggered an auth failure could read part of the API key from the service response. Errors now return a generic message; full details remain in the HA log via `LOGGER.exception`.

### Fixed
- **`entity_id` parameter in `smartchain.ask` / `analyze_image` was always ignored** — the old `_find_client` matched `entity_id.endswith(f"{entry_id}_{sub_id}")`, but the actual `entity_id` is slugified from the subentry title and never contains the UUID, so the routing argument silently fell through to "first available client." Routing now resolves `entity_id → unique_id` via the entity registry, then looks up the matching subentry client.
- **`sensor.smartchain_last_analysis` is now a proper SensorEntity** — previously written via `hass.states.async_set`, which bypassed the entity registry, prevented rename / disable / expose-to-Assist, triggered "Entity does not have a unique_id" warnings, and let unbounded `full_response` text into recorder/WS payloads. The sensor now lives on the new `Platform.SENSOR` platform with `RestoreEntity` support and a 4 KiB cap on `full_response`. Wiring is via the new `SIGNAL_NEW_ANALYSIS` dispatcher signal — automations that subscribe to `sensor.smartchain_last_analysis` keep working unchanged.
- **`manifest.json` `integration_type`** — was `"service"` but the integration registers `conversation`, `ai_task` and now `sensor` platforms. Changed to `"hub"` to match HA's contract; future HA versions may hide entities from settings UI when `"service"` is set on entity-bearing integrations.
- **Panel registration failures now log at WARNING** instead of DEBUG, so a misconfigured frontend doesn't silently disable the SmartChain panel without a visible reason in the log.

### Tests
- 123 passing (was 118). Added: `test_sensor.py` (4 tests covering creation, dispatch update, attribute cap, singleton across entries) and one regression test in `test_service.py` proving `entity_id` now routes through entity_registry.

## [4.0.1] - 2026-04-27

### Fixed
- **GigaChat subentry options silently ignored** — `verify_ssl` and `profanity` toggles set in a subentry's form are now actually applied to the GigaChat client. Previously these were always read from the parent entry's options, so per-subentry values were lost.
- **Event-loop blocking I/O on first message** — `load_skills()` (sync YAML reads from disk) is now awaited via the executor inside the conversation entity, preventing the loop from stalling on the first reply.
- **Event-loop blocking I/O on multimodal messages** — when a chat log carries image attachments, `_chatlog_to_langchain()` (which reads files and may run TurboJPEG) is now offloaded to the executor. Plain text conversations stay on the event loop with no extra hop.
- **`_safe_extract_json` mangling responses** — fence-stripping now drops only the opening ` ``` `/` ```json ` fence and a matching trailing ` ``` `, instead of removing every backtick at either end of the response.

### Refactored
- **Config-flow model validation** — three near-identical model-resolution blocks (`_validate_and_create`, `_validate_and_update`, `OptionsFlow.async_step_settings`) now share a single `_normalize_model_input()` helper.
- **`common_config_option_schema` alias removed** — the dead backwards-compat shim referenced no live consumers after the v4.0.0 cleanup.

## [4.0.0] - 2026-04-27

### ⚠ BREAKING CHANGES

The LLM-driven YAML generation feature has been removed. SmartChain is now focused on conversation, AI Task, and camera analysis only.

### Removed
- **Services** — `smartchain.generate_automation`, `smartchain.deploy_automation`, `smartchain.validate_automation`, `smartchain.list_yaml`, `smartchain.get_yaml`. Existing automations that call these will fail at runtime — remove or replace those calls before upgrading.
- **Options-flow steps** — `generate_automation` and `preview_automation`. The options menu is collapsed: opening the integration's options now goes straight to the model-settings form.
- **Panel components** — the YAML editor (sidebar explorer, code editor, AI bar, toolbar, entity picker). The sidebar panel is now camera-analysis only.
- **Const prompts** — `GENERATE_AUTOMATION_PROMPT`, `GENERATE_SCRIPT_PROMPT`, `GENERATE_SCENE_PROMPT`, `GENERATE_BLUEPRINT_PROMPT`, `GENERATE_PROMPTS`, `IMPROVE_YAML_PROMPT`.
- **`hass.data[DOMAIN]` keys** — `generate_yaml` and `deploy_automation` are no longer registered.
- **Translation keys** (`options.error.{description_required, no_agent, service_not_ready, generation_failed, deploy_failed, empty_yaml}`, `options.abort.{automation_deployed, automation_not_deployed}`, `options.step.{init, generate_automation, preview_automation}`).

### Kept
- Conversation entity, AI Task entity, all 6 LLM providers (GigaChat, YandexGPT, OpenAI, Ollama, DeepSeek, Anthropic).
- `smartchain.ask` and `smartchain.analyze_image` services.
- `helpers.async_generate_structured()` — generic structured-output helper for downstream integrations (not tied to YAML generation).
- Sidebar panel — pruned to the camera analysis tab only.

### Migration
1. Remove any HA automations or scripts that call the deleted services.
2. If you were generating automations through the SmartChain panel, generate them via the LLM directly (`smartchain.ask`) and paste into HA's native automation editor.
3. The integration's options form will appear as a single screen instead of a menu — no action required.

### Tests
- 118 passing (was 128). The 10 dropped tests covered only the removed services.

## [3.0.5] - 2026-03-12

### Fixed
- **Code displayed in fragments** — `_rebuildEditor()` now clears container DOM (`innerHTML = ""`) before creating new editor, preventing leftover elements from previous instance
- **Stale content during rebuild** — `forceNormalMode(newValue)` accepts value parameter to set content atomically with editor rebuild, avoiding flash of old content

## [3.0.4] - 2026-03-12

### Fixed
- **Diff view opens on file load** — `forceNormalMode()` always exits diff when loading/creating files, regardless of flag state
- **"No changes" in diff stats** — replaced unreliable `setTimeout` with Monaco `onDidUpdateDiff` event for accurate stats
- **Diff state desync** — `forceNormalMode()` disposes diff editor even if `_diffMode` flag was already false

## [3.0.3] - 2026-03-12

### Fixed
- **Duplicate automations removed** — removed HA state machine loading, only YAML files are listed (no more duplicates)
- **Blueprints now visible** — removed filter that skipped files without `blueprint` metadata key; all `*.yaml` files under `blueprints/` are now listed via `rglob('*.yaml')`
- **Unsaved changes prompt** — switching files or creating new shows confirm dialog when editor has unsaved changes
- **Cursor blinking at 1:1** — removed `editor.focus()` call after loading YAML to prevent cursor position reset

## [3.0.2] - 2026-03-12

### Changed
- **Diff view redesigned** — full diff toolbar with navigation (prev/next change), inline/side-by-side toggle, diff statistics (+N/-N), Accept/Revert buttons
- `goToDiff('next')` / `goToDiff('previous')` Monaco API for diff navigation
- `renderSideBySide` toggle for inline vs side-by-side diff modes
- Accept applies modified content as new baseline; Revert restores original
- **Agent selector visible** — moved agent and type selectors from hidden options into the main AI bar, always visible

### Fixed
- Agent/subagent selector was hidden inside collapsible options and not discoverable

## [3.0.1] - 2026-03-12

### Fixed
- **Sidebar scroll** — item list now scrollable with proper flex layout on `sc-sidebar-explorer`
- **Tooltips** — type filter buttons (Automations/Scripts/Scenes/Blueprints) now show tooltip labels on hover
- **Blueprints loading** — scan entire `blueprints/` tree (automation + script + custom domains), not just `blueprints/automation/`
- **Load all items** — automations, scripts, scenes now also discovered from HA state machine (UI-defined items in `.storage/`), not only from YAML files
- **Monaco Editor visibility** — fixed zero-height container by setting `display: flex; flex: 1` on host custom elements

## [3.0.0] - 2026-03-12

### Added
- **Monaco Editor** — replaced custom YAML editor with Microsoft Monaco Editor (VS Code engine) loaded from CDN
- Full YAML/JSON syntax highlighting, IntelliSense, bracket matching, folding, find & replace (Ctrl+F)
- **Built-in diff editor** — Monaco's native side-by-side diff view with change navigation, replaces custom LCS diff
- **Jinja2 language support** — custom Monarch tokenizer for HA Jinja2 templates (`{{ }}`, `{% %}`, `{# #}`)
- **Custom keyboard shortcuts**: Ctrl+Shift+V (validate), Ctrl+Shift+D (deploy), Ctrl+Shift+G (diff toggle), Ctrl+Enter (AI focus)
- **Context menu actions** — SmartChain validate/deploy/diff/copy available in editor right-click menu
- SmartChain dark theme (`smartchain-dark`) extending VS Dark with Jinja2 token colors
- Status bar shows keyboard shortcut hints

### Changed
- `code-editor.js` and `diff-viewer.js` replaced by single `monaco-wrapper.js`
- Editor container uses `automaticLayout: true` for responsive resizing
- AI bar result now switches to Monaco diff mode automatically (showing old vs new)
- **MAJOR**: Monaco loaded from CDN (~2MB cached), requires internet on first load

## [2.9.0] - 2026-03-12

### Added
- **IDE-like panel** — complete redesign of SmartChain AI panel into a two-column IDE layout
- Left sidebar: file-explorer with type filters (All/Automations/Scripts/Scenes/Blueprints), search, item list with blueprint badges
- Right panel: full-screen YAML code editor with line numbers, tab-key indent, always-edit mode
- **AI assistant bar** — bottom input for describing changes, Enter to submit, agent/type selectors, entity picker toggle
- **Diff viewer** — inline LCS-based diff with context lines, add/delete highlighting, stats (+N/-N)
- **Toolbar** — Validate, Deploy, Diff toggle, Copy buttons with inline validation status
- Mode tabs: Editor (IDE) and Camera (existing camera analysis)
- Status bar showing line count, type, and item ID

### Changed
- Panel completely rewritten from tab-based generate/camera to IDE layout with 7 ES module components
- New components: `sidebar-explorer.js`, `code-editor.js`, `diff-viewer.js`, `ai-bar.js`, `toolbar.js`
- Existing `generate-tab.js`, `yaml-editor.js`, `yaml-picker.js` replaced by new components
- Camera tab preserved as second mode
- Auto-diff display after AI generates/improves YAML
- Total: 128 tests passing

## [2.8.1] - 2026-03-12

### Security
- **Path traversal fix** — `get_yaml` service now validates resolved blueprint paths stay within the blueprints directory, blocking `../../` traversal attacks
- **Input validation** — `get_yaml` service `id` parameter now restricted to safe characters (`[a-zA-Z0-9_./\- ]`)

### Fixed
- **Race condition** — YAML file writes (deploy) now protected by asyncio Lock to prevent concurrent write corruption
- **Validation on deploy** — `generate_automation` with `deploy=True` now validates YAML before deploying (previously skipped validation)
- **HTTP error handling** — model fetch functions (`_fetch_ollama_models`, `_fetch_openai_compatible_models`, `_fetch_anthropic_models`) now call `raise_for_status()` to properly detect API errors
- Fixed test warnings for `raise_for_status` mock in `test_fetch_models.py`

## [2.8.0] - 2026-03-12

### Added
- **YAML picker** — `list_yaml` and `get_yaml` services to browse and load existing HA items (automations, scripts, scenes, blueprints) into the panel editor
- "Choose from HA" / "Paste YAML" source tabs in the panel editor for flexible input workflow
- Blueprint-based automation detection: panel shows a warning when loaded automation uses a blueprint and recommends editing the blueprint instead
- `get_yaml` service returns raw YAML text of any existing automation, script, scene, or blueprint by ID

### Changed
- Panel editor now has two source modes: browse existing HA items or paste YAML manually
- Total: 128 tests passing

## [2.7.0] - 2026-03-12

### Added
- **"Edit existing YAML" / improve mode** — panel sends `source_yaml` parameter to LLM for targeted improvements to existing automations/scripts/scenes
- `IMPROVE_YAML_PROMPT` dedicated prompt for improve mode, instructing LLM to modify only what is asked while preserving existing structure
- `source_yaml` parameter in `generate_automation` service — when provided, LLM improves the given YAML rather than generating from scratch

### Changed
- Replaced custom `_collect_ha_context()` helper with HA's built-in Jinja2 `DEFAULT_DEVICES_PROMPT` template rendering for richer and more accurate home context in automation generation
- Fixed yaml-editor line numbers display (`white-space: pre` CSS rule to prevent number wrapping)
- Panel YAML editor shows correct line numbers for long files

## [2.6.0] - 2026-03-12

### Added
- **Multi-type YAML generation** — panel and service support `yaml_type` parameter: `automation`, `script`, `scene`, `blueprint`
- Dedicated generation prompts per YAML type (`GENERATE_AUTOMATION_PROMPT`, `GENERATE_SCRIPT_PROMPT`, `GENERATE_SCENE_PROMPT`, `GENERATE_BLUEPRINT_PROMPT`)
- Type-aware YAML validation: structure checks adapted per type (triggers only for automations, etc.)
- Type-aware deploy routing: scripts deploy to `scripts.yaml`, scenes to `scenes.yaml`, blueprints to `blueprints/` directory

### Changed
- Panel JavaScript decomposed from monolithic 430-line file into 7 ES module components for maintainability
- `generate_automation` service now accepts optional `yaml_type` field (defaults to `automation`)
- Validation checks adapted to the target YAML type

## [2.5.0] - 2026-03-12

### Added
- **HA context enrichment** — LLM prompt for automation generation now includes real entity IDs, area names, and device list from the live Home Assistant instance
- **YAML validation** — generated automations are validated for: correct structure (triggers/actions present), entity ID existence in HA, and referenced service availability
- **Entity picker** in panel — browse and insert entity IDs from HA directly into the description field
- **Agent selector** in panel — choose which SmartChain agent handles generation requests
- Validation errors shown inline in the panel before deploying

### Changed
- Panel UI extended with entity picker dropdown and agent selector
- Total: 128 tests passing

## [2.4.1] - 2026-03-12

### Fixed
- `deploy_automation` service now writes to `automations.yaml` instead of `.storage/automations` (correct HA file-based storage path)
- Removed unused imports from `__init__.py`

## [2.4.0] - 2026-03-12

### Added
- **SmartChain AI sidebar panel** — custom web component registered as a Home Assistant sidebar panel at `/smartchain/panel.js`
- Panel has two tabs: **Generate Automation** (natural language → YAML → deploy) and **Analyze Camera** (select camera entity → analyze with LLM → show result)
- Panel uses `hass.connection.sendMessagePromise` for service calls with `return_response`
- Static file served via `async_register_static_paths([StaticPathConfig(...)])`
- Panel registration is graceful — HA without `frontend` platform still loads the integration

### Changed
- `async_setup()` registers panel at domain level alongside existing services
- Total: 128 tests passing

## [2.3.0] - 2026-03-12

### Added
- **Interactive automation wizard** in Options Flow — describe automation in natural language, preview generated YAML, then deploy in one flow
- `deploy_automation` service — accepts raw YAML and writes it to `automations.yaml`, then calls `automation.reload`
- Options Flow now shows a **menu** as init step: "settings" (existing model config) or "generate_automation" (wizard)

### Changed
- `OptionsFlow` init step changed from form to menu (`async_step_init` returns menu)
- Tests must now select menu item first: `{"next_step_id": "settings"}` or `{"next_step_id": "generate_automation"}`

## [2.2.0] - 2026-03-12

### Added
- **`generate_automation` service** — converts natural language description into a Home Assistant automation YAML. Accepts `description` (required) and `entity_id` (optional, selects which agent generates). Returns `yaml` field in response
- `GENERATE_AUTOMATION_PROMPT` — dedicated system prompt instructing LLM to output only valid HA YAML with triggers, conditions, and actions
- 8 new service tests covering `generate_automation` and `analyze_image`

### Changed
- Total: 128 tests passing

## [2.1.0] - 2026-03-12

### Added
- **Security Guard blueprint** (`docs/blueprints/security_guard.yaml`) — ready-to-use HA blueprint that uses `analyze_image` to monitor cameras and send alerts when suspicious activity is detected

### Fixed
- GigaChat vision: `auto_upload_images=True` now correctly passed in `GigaChat()` constructor, enabling image analysis with GigaChat multimodal models

## [2.0.0] - 2026-03-12

### Added
- **`analyze_image` service** — takes a camera entity snapshot, encodes it as base64, sends to a multimodal LLM, and returns the analysis. Supports optional custom prompt
- `_find_client()` in `__init__.py` — shared helper for service handlers to locate the correct LLM client by `entity_id` or use the first available
- Service returns structured response: `{"response": "...", "entity_id": "..."}`

### Changed
- `async_setup()` now registers both `smartchain.ask` and `smartchain.analyze_image`
- Total: 128 tests passing

---

## [1.9.0] - 2026-03-11

### Added
- **v1.9 Dynamic model lists** — model dropdowns in config/options flow are now populated dynamically from provider APIs (Ollama, OpenAI, DeepSeek, Anthropic, GigaChat). YandexGPT uses static list. Falls back to static lists on network errors
- `async_fetch_models()` in `client_util.py` — fetches available models via HTTP (aiohttp) or SDK
- 7 new tests for model fetching (all providers + fallback)

### Changed
- `_subentry_schema()` accepts optional `models` parameter
- `OptionsFlow`, `ConversationSubentryFlow` fetch models before building schema
- Total: 110 tests passing

## [1.8.0] - 2026-03-11

### Added
- **v1.8 Prompt caching** — TTL-based cache (30s) for Jinja2-rendered system prompts. Avoids repeated expensive template rendering for device lists
- **v1.7 Skill system** — load custom skills from YAML files (`config/smartchain/skills/*.yaml`). Skills define name, description, and prompt — appended to system prompt as additional context
- **v1.5 smartchain.ask service** — simple service for automations (Telegram, Slack, etc). Accepts message + optional entity_id, returns LLM response. With services.yaml definition
- **v1.4 Multi-agent delegation** — `ask_agent` tool allows agents to delegate tasks to sibling agents in the same config entry. Tool-based routing without LangGraph dependency
- **v1.3 State history tool** — `get_state_history` tool lets LLM query past device states via HA recorder. Configurable via `enable_history_tool` option. Capped at 24h, last 20 changes
- **v1.2 MCP support** — works through HA native MCP integration + Assist API multi-select. No custom code needed
- **v1.0 Vision** — camera image analysis via multimodal LLM messages. `_attachment_to_base64()` reads images, optional PyTurboJPEG compression for large images

### Changed
- Custom tool calls (history, delegate) marked as `external=True` in stream, handled after `async_add_delta_content_stream`
- `_async_langchain_stream` sets `external` flag for custom tool names
- `async_setup()` added to register `smartchain.ask` service at domain level
- Total: 103 tests passing

## [0.9.0] - 2026-03-10

### Added
- **Sub-entries** — multiple conversation agents per provider via `ConfigSubentryFlow`. Each sub-entry has its own model, prompt, temperature, LLM API, and creates independent ConversationEntity + AITaskEntity
- `ConversationSubentryFlow` with `async_step_user()` and `async_step_reconfigure()` for adding/editing agents
- `async_get_supported_subentry_types()` on ConfigFlow returns `{"conversation": ConversationSubentryFlow}`
- Backward compatible: entries without sub-entries continue working in legacy mode (single agent from `entry.options`)
- **Options Flow tests** — 7 new tests covering form display, model validation, GigaChat-specific fields, LLM API handling
- **E2E tool calling loop test** — full simulation: user request → tool_call → tool execution → final response
- **Sub-entries tests** — 8 tests covering subentry flow, setup with subentries, multiple agents, legacy fallback

### Changed
- `conversation.py` — `SmartChainConversationEntity` now accepts `subentry_id` and `options` params; uses `_agent_options` and `_client` properties
- `ai_task.py` — `SmartChainAITaskEntity` now accepts `subentry_id`; uses `_client` property
- `__init__.py` — `async_setup_entry` creates per-subentry clients dict or single legacy client
- `config_flow.py` — renamed `common_config_option_schema()` → `_subentry_schema()` (backward-compatible alias kept)
- `OptionsFlow` — removed `__init__` (config_entry is read-only property in modern HA)
- Total: 67 tests passing

### Fixed
- `OptionsFlow.__init__` — removed setter for `self.config_entry` (read-only property in HA 2025+)

## [0.8.0] - 2026-03-10

### Added
- **Ollama provider** — local models (Llama 3.3, Qwen3, Gemma 3, T-Pro 2, T-Lite, DeepSeek R1, Phi 4, Home-3B). Config: base_url only, no API key needed
- **DeepSeek provider** — cheapest cloud LLM (deepseek-chat, deepseek-reasoner). Uses ChatOpenAI with DeepSeek base URL
- **Anthropic provider** — Claude models (claude-sonnet-4-6, claude-haiku-4-5, claude-opus-4-6) via ChatAnthropic

### Changed
- **ai_task made optional** — no longer in manifest.json dependencies, detected dynamically. Fixes hang on HA versions without ai_task support
- Config Flow extended with `async_step_ollama`, `async_step_deepseek`, `async_step_anthropic`
- `client_util.py` — new client factories for Ollama (ChatOllama), DeepSeek (ChatOpenAI), Anthropic (ChatAnthropic)
- `manifest.json` — added `langchain-anthropic`, `langchain-ollama` to requirements
- `pyproject.toml` — migrated to `requires-python>=3.13`, added all langchain dev deps

### Fixed
- ResponseError test updated for new gigachat API signature
- Dependency resolution: pinned langchain packages to compatible ranges (core<1)

## [0.7.0] - 2026-03-10

### Changed
- **Project renamed: GigaChain -> SmartChain** — reflects multi-provider nature (not GigaChat-only)
- Domain: `gigachain` -> `smartchain`
- Entity classes: `GigaChainConversationEntity` -> `SmartChainConversationEntity`
- New GitHub repository: `ha-smartchain`
- HACS name: SmartChain
- Version bumped to 0.7.0

### Added
- **AI Task entity** — `SmartChainAITaskEntity` implements `ai_task.AITaskEntity` with `_async_generate_data()` for automation-driven text generation via `ai_task.generate_data` service
- Structured output support in AI Task (JSON parsing with `task.structure`)
- Tool calling support in AI Task (reuses conversation entity's LangChain integration)

## [0.6.0] - 2026-03-10

### Added
- **Assist API for device control** — integration with HA LLM API (`async_provide_llm_data`) allows LLM to call Home Assistant services (turn on/off lights, locks, etc.)
- `llm_hass_api` option in Options Flow — select HA API for LLM (Assist, custom APIs)
- HA `llm.Tool` (voluptuous schema) -> LangChain tools conversion via `voluptuous_openapi` + `client.bind_tools()`
- Tool calling loop with `MAX_TOOL_ITERATIONS = 10`
- `tool_calls` in `AIMessageChunk` -> HA `ToolInput` in stream deltas
- `ToolResultContent` <-> LangChain `ToolMessage` conversion in `_chatlog_to_langchain()`

### Changed
- `_async_handle_message` — uses `async_provide_llm_data` when LLM API configured, manual prompt otherwise
- Options Flow: `common_config_option_schema` takes `hass` to list available LLM APIs

## [0.5.0] - 2026-03-10

### Added
- **Streaming responses** — `_attr_supports_streaming = True`, responses streamed via `ChatLog.async_add_delta_content_stream()`
- Async generator `_async_langchain_stream()` for `AIMessageChunk` -> HA delta dicts

### Changed
- `client.invoke()` via `async_add_executor_job` replaced with `client.astream()` (async, no executor)

## [0.4.0] - 2026-03-10

### Changed
- **ChatLog for history** — removed custom `OrderedDict`, uses native HA `ChatLog`
- **Migration to langchain-gigachat/langchain-openai** — proper package imports

## [0.3.0] - 2026-03-10

### Added
- **Migration to ConversationEntity** — entity-based conversation agent with `_async_handle_message(user_input, chat_log)`

## [0.2.0] - 2026-03-10

### Fixed
- Blocking LLM calls, deprecated LangChain API, memory leaks, model defaults

### Removed
- Anyscale support completely removed

## [0.1.8] - 2024-12-01

### Fixed
- Compatibility with Home Assistant 2024.12.1+

## [0.1.1] - 2024-03-01

### Added
- Initial release with GigaChat, YandexGPT support
- Config Flow and Options Flow
- Chat history and Jinja2 system prompts
