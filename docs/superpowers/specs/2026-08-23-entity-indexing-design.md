# Entity indexing — design

**Date:** 2026-08-23
**Status:** approved, ready for planning
**Release:** part of v5.0.0 (roadmap subsystem **B**)
**Builds on:** `2026-08-23-vector-backends-and-embedding-providers-design.md`

---

## 1. Goal

Let the model find a Home Assistant entity by describing it rather than naming
it. "Что варит кофе" should resolve to `switch.kitchen_socket_3`, and "чем
посушить волосы" to the socket the hair dryer is plugged into — queries where
lexical matching has nothing to work with.

The vector store, the embeddings binding and the backend abstraction already
exist from subsystem A. This subsystem adds the thing that fills such a store
with the home's entities, and the tool that reads it.

## 2. Scope

**In scope.** An entity source for a named memory store; four scope presets;
an incremental indexer driven by the HA registries; an optional state-tracking
mode; a `search_entities` LLM tool combining lexical and vector matching; a
`smartchain.reindex_entities` service; two additions to the `VectorBackend`
Protocol.

**Not in scope.** Replacing `DEFAULT_DEVICES_PROMPT` with retrieved context —
that is subsystem **C** and depends on this one. Acting on entities (the model
already has HA's own tool APIs for that). Indexing automations, scripts as
documents, or the entity *history* (`get_state_history` covers history).

## 3. Why lexical matching stays in the loop

Vector search is not uniformly better than string matching for this task. On
"свет на кухне" a normalised substring match over names, aliases and areas is
both faster and more accurate than cosine similarity, and it is what HA's own
agent does through hassil. Embeddings earn their place only on the semantic
tail.

`search_entities` therefore runs both and merges, with lexical exact and prefix
hits ranked above vector hits. This also means the tool degrades to something
still useful when the embeddings provider is down or the store failed to come
up, instead of silently returning nothing.

## 4. Configuration

An entity index is an ordinary named store with a `source:` block:

```yaml
memory:
  stores:
    - name: entities
      description: "Devices and sensors in the home"
      embeddings: "GigaChat Embeddings"
      backend:
        type: sqlite_numpy
      source:
        type: entities
        preset: optimal
        index_states: false
        include: []
        exclude: []
```

`source` is optional. A store without it is a conversation store and behaves
exactly as it does today — this subsystem changes nothing for existing configs.

### 4.1 Schema

`_SOURCE_SCHEMA` in `tools/schema.py`:

| Key | Type | Default | Notes |
|---|---|---|---|
| `type` | `vol.In(["entities"])` | required | the only source type today |
| `preset` | `vol.In(ENTITY_PRESETS)` | `"optimal"` | |
| `index_states` | `bool` | `false` | |
| `include` | `[str]` | `[]` | domain (`sensor`) or full `entity_id` |
| `exclude` | `[str]` | `[]` | same forms; applied after `include` |

Added to `_STORE_SCHEMA` as `vol.Optional("source"): _SOURCE_SCHEMA`.

### 4.2 Rejected combinations

When a store declares `source.type: entities`, these keys are **rejected**, not
ignored:

- `retention_days` — retention would delete indexed entities by age. An entity
  is not stale because it is old.
- `ingest_conversation` — conversation turns must not land in an entity index.
- `ingest_logbook` — same.

The check runs in `_validate_memory` against the **raw** store mapping, before
voluptuous applies defaults, so a defaulted `ingest_conversation: true` does not
trip it and only an explicit declaration does. This mirrors how the pre-5.0.0
flat `memory:` block is rejected.

Message shape:

```
memory store 'entities' declares source.type: entities, so these keys do not
apply and were rejected: ['retention_days']. Retention would delete indexed
entities by age.
```

### 4.3 Presets

Expanded in code, from `const.py`. Never written out in YAML.

**`minimal`** — only what a person controls:

```
light, switch, cover, climate, lock, fan, media_player,
scene, script, vacuum, water_heater, humidifier, valve
```

**`optimal`** (default) — `minimal` plus:

```
button, input_boolean, input_select, input_number,
select, number, alarm_control_panel, person, weather
```

plus `sensor` and `binary_sensor` whose device class is meaningful:

```
temperature, humidity, illuminance, pressure, motion, occupancy, presence,
door, window, opening, garage_door, smoke, gas, moisture,
carbon_monoxide, carbon_dioxide, power, energy, sound, vibration, problem
```

`minimal` and `optimal` both exclude entities whose `entity_category` is
`config` or `diagnostic`.

**`maximal`** — every entity that is neither hidden nor disabled, regardless of
domain, device class or entity category. Diagnostics and `update.*` included.

**`paranoid`** — `maximal` plus hidden and disabled entities. Disabled entities
have no state at all, so they contribute a catalogue document only; this is
noted in the docs because it is otherwise surprising.

### 4.4 `include` / `exclude`

Both accept a bare domain or a full `entity_id`. `include` is additive on top of
the preset; `exclude` is applied last and wins over both. An entry that is
neither a valid domain nor a valid `entity_id` is a schema error.

### 4.5 Entities outside the registry

`entity_registry` does **not** hold every entity. Entities created by legacy
YAML platforms, template entities and groups exist only in `hass.states`. The
candidate set is therefore the union of `entity_registry` entries and
`hass.states.async_all()`, keyed by `entity_id`. A state-only entity has no
aliases, no area and no entity category; it is treated as `entity_category:
None` and is included by `maximal` and `paranoid`, and by `minimal`/`optimal`
when its domain qualifies.

Missing this union would silently drop every template sensor from `maximal`,
which is the exact opposite of what the preset promises.

## 5. Document shape

One document per entity. `doc_id = f"entity:{entity_id}"`, so re-indexing
overwrites rather than duplicating — `MemoryStore.add` already takes `doc_id`
and the backends already `ON CONFLICT DO UPDATE`.

### 5.1 Embedded text

Catalogue only. The state never enters the embedded text — if it did, every
state change would require re-embedding, which is the cost this design exists
to avoid.

```
light.kitchen_ceiling — Потолочный свет
Area: Кухня | Device: Yeelight Ceiling | Domain: light | Class: —
Also known as: люстра, верхний свет
```

Structural labels stay in English; entity names, areas and aliases are whatever
HA holds, in whatever language the user configured. Aliases come from
`RegistryEntry.aliases` and are the single most valuable field here: they are
the user's own words for the thing.

Exactly two lines are always present: the identity line and the attribute line.
Within the attribute line an absent field renders as `—` rather than being
dropped, so the fingerprint changes when a field is *cleared*, not only when it
is set. The `Also known as:` line is present only when the entity has aliases.

### 5.2 Metadata

```python
{
    "kind": "entity",
    "entity_id": "light.kitchen_ceiling",
    "domain": "light",
    "area": "Кухня",              # "" when unassigned
    "device_class": "",           # "" when none
    "fingerprint": "9f2ac1…",     # sha256 of the embedded text, first 16 hex
    # present only when index_states is true:
    "state": "on",
    "state_updated": "2026-08-23T18:04:11+00:00",
}
```

`kind: "entity"` keeps entity documents addressable: `search_memory` can filter
them out, and `smartchain.clear_memory` with `kind: entity` targets exactly
them. Every value is `str`, matching the `Filter` contract's equality-only
dialect.

`fingerprint` is what makes restarts free — see §7.1.

## 6. Protocol additions

Two methods join `VectorBackend` in `tools/memory/backends/base.py`. Both are
implemented by all four backends and covered by the existing conformance suite.

```python
async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
    """Replace one document's metadata without touching its vector.

    Returns True if the document existed. Never re-embeds — this is the
    whole point of the method.
    """

async def list_metadata(self, where: Filter | None = None) -> dict[str, dict[str, Any]]:
    """Every stored document's metadata, keyed by doc_id.

    Intended for reconciliation, not for serving queries. Callers must pass
    a `where` narrow enough to keep the result bounded.
    """
```

Implementations:

- `sqlite_numpy`, `sqlite_vec` — `SELECT doc_id, metadata FROM docs [WHERE …]`
  and `UPDATE docs SET metadata = ? WHERE doc_id = ?`, reusing the existing
  `build_where_clause`.
- `pgvector` — the same two statements, reusing `build_pg_where`.
- `qdrant` — `POST /collections/{c}/points/scroll` with `with_payload=true` and
  `with_vector=false`, following the `next_page_offset` cursor to exhaustion;
  and `POST /collections/{c}/points/payload` with `wait=true`.

`MemoryStore` gains thin pass-throughs for both, bounded by
`MEMORY_BACKEND_TIMEOUT_SECONDS` and following the same rule as every other
runtime method: failures are logged and swallowed, returning `False` / `{}`,
and the store stays available.

## 7. The indexer

`EntityIndexer` lives in `tools/memory/entity_index.py`, one per entity-source
store, owned and lifecycled by `MemoryRegistry` exactly as `RetentionTask` and
`MemoryLogbookPoller` are: constructed in `build()`, `start()` synchronously,
`await stop()` in `shutdown()`.

### 7.1 Reconciling sweep

The core operation. Never a blind full re-index.

1. Build the candidate set from the registries and `hass.states`, apply the
   preset, then `include`, then `exclude`.
2. Render each candidate's catalogue text and compute its fingerprint.
3. `stored = await store.list_metadata({"kind": "entity"})` — one call.
4. Diff:
   - **new** — a candidate with no stored document → embed and `add`.
   - **changed** — fingerprint differs → embed and `add` (overwrites by
     `doc_id`).
   - **unchanged** — skip entirely. No embedding call.
   - **orphaned** — stored but no longer a candidate → `delete_where({"kind":
     "entity", "entity_id": …})`.
5. Log a single summary line: `indexed N new, M changed, K removed, U unchanged`.

A restart with an unchanged home therefore performs exactly one
`list_metadata` call and zero embeddings. A narrowed preset removes the entities
that dropped out of scope on the next sweep, without a manual purge.

Embedding work is batched at `ENTITY_INDEX_BATCH_SIZE` with
`ENTITY_INDEX_BATCH_PAUSE_SECONDS` between batches, so a first sweep over a
large home does not monopolise the executor.

### 7.2 When a sweep runs

- Once at startup, as a background task scheduled on `EVENT_HOMEASSISTANT_STARTED`
  (or immediately if HA is already running, which is the case on
  `reload_tools`). Never inline in `async_setup_entry` — a thousand embeddings
  must not delay HA's startup.
- On `smartchain.reindex_entities`.
- Debounced after registry changes that are too broad for a targeted update
  (see below).

### 7.3 Registry changes

Subscriptions, all with a `ENTITY_REGISTRY_DEBOUNCE_SECONDS` debounce:

- `EVENT_ENTITY_REGISTRY_UPDATED` — `create` and `update` re-index that one
  entity; `remove` deletes its document immediately.
- `EVENT_DEVICE_REGISTRY_UPDATED` — a device's name or area changed, so every
  entity of that device is re-indexed.
- `EVENT_AREA_REGISTRY_UPDATED` — an area rename touches everything in it;
  this schedules a full reconciling sweep, which is cheap precisely because
  fingerprints make it incremental.

### 7.4 State tracking (`index_states: true`)

Off by default.

When on, the indexer subscribes with `async_track_state_change_event` to the
**filtered candidate set only**, never to all states. Events are coalesced into
a dict keyed by `entity_id` and flushed every `ENTITY_STATE_FLUSH_SECONDS`, so a
flapping sensor produces one write per flush rather than one per event. Each
flush issues `update_metadata` per changed entity — **no embedding calls at
all.**

The value this buys is filtering, not searching: `search_entities(query="…",
state="open")` becomes a metadata equality filter. Semantic similarity over
state strings is weak and is not what this mode is for; the documentation says
so plainly.

When off, no state listener is registered and `state` is absent from metadata.
The tool still reports live states — see §8.

## 8. `search_entities`

Lives in `tools/memory/entity_tool.py`. Registered when at least one store has
an entity source, mirroring how `search_memory` appears when the memory registry
is non-empty.

```python
{
  "name": "search_entities",
  "parameters": {
    "query":  {"type": "string"},                       # required
    "top_k":  {"type": "integer", "default": 10, "minimum": 1, "maximum": 50},
    "domain": {"type": "string"},                       # optional filter
    "area":   {"type": "string"},                       # optional filter
    "state":  {"type": "string"},                       # optional; index_states only
    "store":  {"type": "string", "enum": [...]},        # required with 2+ entity stores
  }
}
```

Execution:

1. **Lexical pass** — case-folded, accent-normalised token and prefix matching
   against the friendly name, the aliases, the area name and the `entity_id`.
   Bounded at `ENTITY_LEXICAL_CANDIDATES`.

   It does **not** read the indexer's in-memory state. Candidate selection lives
   in a module-level `resolve_candidates(hass, source_config)` used by both the
   indexer and the tool; it only reads the registries and `hass.states`, so it
   works when the indexer never started. That is what makes the §10 fallback
   real rather than nominal — a tool that depended on a live indexer would
   return nothing in exactly the situation the fallback exists for.
2. **Vector pass** over the store, with `domain` / `area` / `state` translated
   into a metadata filter. Skipped when the store is unavailable.

   `state` is a metadata filter only when the store has `index_states: true`.
   Otherwise it is applied after enrichment, against the live state read in
   step 4. Either way the caller gets the same answer; passing `state` to a
   store that does not index states is not an error.
3. **Merge** — exact lexical match first, then prefix, then vector by score.
   Deduplicated by `entity_id`, truncated to `top_k`.
4. **Enrich** — each hit's current state is read from `hass.states` at answer
   time, so the state reported to the model is always fresh regardless of
   `index_states`.

Result:

```
Found 2 entities:
1. light.kitchen_ceiling — Потолочный свет [light, Кухня] = on
2. switch.kitchen_socket_3 — Кофеварка [switch, Кухня] = off
```

No matches returns a sentence saying so, naming the filters that were applied so
the model can retry with fewer.

`store` follows the same rule as `search_memory`: optional with one entity
store, required with two or more.

## 9. Service

`smartchain.reindex_entities`, declared in `services.yaml`:

| Field | Type | Notes |
|---|---|---|
| `store` | string, optional | omit to sweep every entity store |
| `full` | boolean, default `false` | `true` ignores fingerprints and re-embeds everything |

A named `store` that does not exist, or that exists but has no entity source,
raises `HomeAssistantError` naming the entity stores that are configured — the
same shape `clear_memory` already uses for an unknown store. Silently sweeping
nothing would be indistinguishable from success.

Fires `smartchain_entities_reindexed` with `{"stores": [...], "new": n,
"changed": m, "removed": k, "unchanged": u}`.

`full: true` exists for the case where the embedding model changed but the
catalogue text did not — fingerprints would otherwise report everything
unchanged while the stored vectors came from a different model.

## 10. Error handling

Consistent with the rest of the memory subsystem:

- Indexer failures are logged and never propagate. A failing sweep leaves the
  previous index in place.
- A store whose backend or embeddings fail to build is skipped by
  `MemoryRegistry` like any other store; its indexer is never started and
  `search_entities` falls back to the lexical pass.
- Tool failures return a fixed string; detail goes to `LOGGER.exception`.

## 11. Security

The v4.0.2 boundary is unchanged and applies here in a new place: entity names,
areas and aliases are user data and go to an external embeddings provider. This
is inherent to the feature, but it must be **stated in the documentation** —
including that `paranoid` sends the entire home, diagnostics included, and that
`person` and `device_tracker` entities are in `optimal`'s scope.

No credential may appear in an indexer log line, in a tool result, or in the
`smartchain_entities_reindexed` payload. Entity ids and area names are not
credentials and may appear.

## 12. Constants

Appended to `const.py`:

```python
ENTITY_SOURCE_TYPE = "entities"
ENTITY_PRESETS = ["minimal", "optimal", "maximal", "paranoid"]
ENTITY_DEFAULT_PRESET = "optimal"
ENTITY_TOOL_NAME = "search_entities"
SERVICE_REINDEX_ENTITIES = "reindex_entities"
EVENT_ENTITIES_REINDEXED = f"{DOMAIN}_entities_reindexed"
ENTITY_INDEX_BATCH_SIZE = 32
ENTITY_INDEX_BATCH_PAUSE_SECONDS = 0.5
ENTITY_REGISTRY_DEBOUNCE_SECONDS = 5
ENTITY_STATE_FLUSH_SECONDS = 30
ENTITY_SEARCH_DEFAULT_TOP_K = 10
ENTITY_SEARCH_MAX_TOP_K = 50
ENTITY_LEXICAL_CANDIDATES = 200
```

`ENTITY_MINIMAL_DOMAINS`, `ENTITY_OPTIMAL_EXTRA_DOMAINS` and
`ENTITY_MEANINGFUL_DEVICE_CLASSES` carry the lists from §4.3.

## 13. Testing

Beyond per-unit coverage, these are the tests that must exist:

- **Preset expansion**, one per preset, against a fake registry that includes a
  state-only entity with no registry entry, a hidden entity, a disabled entity
  and a diagnostic entity. Each preset's membership is asserted exactly.
- **`include` / `exclude`** precedence, including `exclude` overriding a preset
  and an `include`.
- **Schema rejections** for `retention_days`, `ingest_conversation` and
  `ingest_logbook` on an entity store, and the proof that a *defaulted*
  `ingest_conversation` does not trip them.
- **Reconciling sweep** — the central test: a second sweep with an unchanged
  home performs **zero** embedding calls; a renamed entity re-embeds exactly
  one; a removed entity is deleted; a narrowed preset removes what dropped out.
- **`update_metadata` and `list_metadata`** in the conformance suite, so all
  file-based backends are checked, plus mock-level tests for pgvector and
  qdrant including qdrant's scroll pagination.
- **State flush** coalesces multiple events for one entity into a single
  `update_metadata`, and issues no embedding call.
- **`index_states: false`** registers no state listener at all.
- **Merge ranking** — an exact lexical match outranks a higher-scoring vector
  hit; and the tool still returns results with the store unavailable **and with
  no indexer ever started**, which is the case `resolve_candidates` exists for.
- **Live state enrichment** — a hit's reported state comes from `hass.states`,
  not from stale metadata, proven by making the two disagree.
- **`state` filter without `index_states`** — filtering still works, applied
  post-enrichment rather than as a metadata filter.
- **Service errors** — `reindex_entities` on an unknown store, and on a store
  that exists but has no entity source, both raise and name the real ones.

## 14. Global constraints

- **No new dependency.** Everything here uses HA helpers, the stdlib and the
  existing backends. Accent normalisation uses `unicodedata`.
- `requires-python >= 3.13`; Home Assistant 2024.12.0+.
- ruff `line-length = 100`, `select = ["E", "F", "W", "I", "UP"]`.
- Credentials never reach a log line, an exception message, a service error or a
  tool result.
- Existing configs without a `source:` block must behave identically to today.

## 15. Deferred

- Replacing `DEFAULT_DEVICES_PROMPT` with retrieved context — subsystem **C**.
- Indexing area and device documents in their own right, so "что есть в
  гостиной" resolves without enumerating entities.
- Re-embedding automatically when a store's embeddings subentry changes model.
- Sources other than `entities` — the `source.type` enum exists so adding one
  later is not a breaking change.
