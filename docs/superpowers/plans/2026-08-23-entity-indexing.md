# Entity Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Index the home's entities into a named memory store so the model can find a device by describing it, and expose that through a `search_entities` tool that merges lexical and vector matching.

**Architecture:** An entity index is an ordinary `memory.stores[]` entry carrying a `source:` block. `MemoryRegistry` attaches an `EntityIndexer` to such a store instead of the conversation-ingest plumbing. The indexer reconciles rather than rebuilds: it compares a fingerprint of each entity's catalogue text against what `list_metadata` reports and embeds only what changed, so an unchanged home costs zero embeddings per restart.

**Tech Stack:** Home Assistant helpers (`entity_registry`, `device_registry`, `area_registry`, `async_track_state_change_event`), voluptuous, the existing `VectorBackend` backends, stdlib `hashlib` / `unicodedata`. No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-23-entity-indexing-design.md`

## Global Constraints

- **No new dependency.** `manifest.json` requirements must be byte-identical at the end of this plan.
- **Do not touch the `version` field** in `pyproject.toml` or `manifest.json`. It is already `5.0.0`; this subsystem ships inside that release. This overrides any global convention about bumping the version per commit.
- Credentials (`api_key`, `dsn`, URL userinfo) must never reach a log line, an exception message, a service-call error, or an LLM tool result. Entity ids, area names and device names are **not** credentials and may appear.
- Existing configs with no `source:` block must behave exactly as they do today.
- `requires-python >= 3.13`; Home Assistant 2024.12.0+.
- ruff `line-length = 100`, `select = ["E", "F", "W", "I", "UP"]`. `const.py` carries a per-file `E501` ignore.
- Test runner `uv run --prerelease=allow pytest tests/ -q`; lint `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .`.
- Baseline at plan start: **467 passed, 0 skipped**.

## File Structure

| File | Responsibility |
|---|---|
| `tools/memory/backends/base.py` | Protocol gains `update_metadata` + `list_metadata` |
| `tools/memory/backends/{sqlite_numpy,sqlite_vec,pgvector,qdrant}.py` | four implementations |
| `tools/memory/store.py` | timeout-bounded pass-throughs |
| `tools/memory/config.py` | `EntitySourceConfig`, `StoreConfig.source` |
| `tools/schema.py` | `_SOURCE_SCHEMA`, incompatible-key rejection |
| `tools/loader.py` | parse `source:` into `EntitySourceConfig` |
| `tools/memory/entity_filter.py` | `EntityCandidate`, presets, `resolve_candidates` |
| `tools/memory/entity_doc.py` | catalogue rendering + fingerprint |
| `tools/memory/entity_index.py` | `EntityIndexer` — sweep, subscriptions, state flush |
| `tools/memory/entity_tool.py` | `search_entities` definition + executor |
| `tools/memory/registry.py` | owns indexers alongside retention/pollers |
| `__init__.py` | `reindex_entities` service |
| `conversation.py` | advertise and dispatch the tool |

---

# Phase 1 — Protocol extension

### Task 1: `update_metadata` and `list_metadata` on the Protocol and both SQLite backends

**Files:**
- Modify: `custom_components/smartchain/tools/memory/backends/base.py`
- Modify: `custom_components/smartchain/tools/memory/backends/sqlite_numpy.py`
- Modify: `custom_components/smartchain/tools/memory/backends/sqlite_vec.py`
- Test: `tests/test_memory_backend_conformance.py`

**Interfaces:**
- Produces: `VectorBackend.update_metadata(doc_id, metadata) -> bool` and `VectorBackend.list_metadata(where=None) -> dict[str, dict]`. Tasks 2, 3 and 8 depend on both.

- [ ] **Step 1: Write the failing conformance tests**

Append to `tests/test_memory_backend_conformance.py`, inside the existing parametrised class:

```python
async def test_list_metadata_returns_every_stored_doc(backend) -> None:
    await backend.initialize(3)
    await backend.upsert(
        [
            VectorRecord(doc_id="a", vector=[1.0, 0.0, 0.0], text="a", metadata={"kind": "x"}),
            VectorRecord(doc_id="b", vector=[0.0, 1.0, 0.0], text="b", metadata={"kind": "y"}),
        ]
    )
    everything = await backend.list_metadata()
    assert set(everything) == {"a", "b"}
    assert everything["a"]["kind"] == "x"


async def test_list_metadata_honours_the_filter(backend) -> None:
    await backend.initialize(3)
    await backend.upsert(
        [
            VectorRecord(doc_id="a", vector=[1.0, 0.0, 0.0], text="a", metadata={"kind": "x"}),
            VectorRecord(doc_id="b", vector=[0.0, 1.0, 0.0], text="b", metadata={"kind": "y"}),
        ]
    )
    assert set(await backend.list_metadata({"kind": "x"})) == {"a"}


async def test_update_metadata_replaces_without_touching_the_vector(backend) -> None:
    await backend.initialize(3)
    await backend.upsert(
        [VectorRecord(doc_id="a", vector=[1.0, 0.0, 0.0], text="a", metadata={"kind": "x"})]
    )
    assert await backend.update_metadata("a", {"kind": "x", "state": "on"}) is True

    stored = await backend.list_metadata({"kind": "x"})
    assert stored["a"]["state"] == "on"

    # the vector survived: an identical query still finds the document
    hits = await backend.query([1.0, 0.0, 0.0], top_k=1, where=None)
    assert hits[0].doc_id == "a"


async def test_update_metadata_reports_a_missing_doc(backend) -> None:
    await backend.initialize(3)
    assert await backend.update_metadata("nope", {"kind": "x"}) is False
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_conformance.py -v`
Expected: `AttributeError` on `list_metadata`.

- [ ] **Step 3: Extend the Protocol**

In `custom_components/smartchain/tools/memory/backends/base.py`, add to the `VectorBackend` Protocol body, after `query`:

```python
    async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
        """Replace one document's metadata without touching its vector.

        Returns True when the document existed. Never re-embeds — being able
        to refresh metadata cheaply is the entire reason this method exists.
        """
        ...

    async def list_metadata(self, where: Filter | None = None) -> dict[str, dict[str, Any]]:
        """Every stored document's metadata, keyed by doc_id.

        For reconciliation, not for serving queries: callers must pass a
        `where` narrow enough to keep the result bounded.
        """
        ...
```

- [ ] **Step 4: Implement in `sqlite_numpy.py`**

```python
    async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
        def _run() -> bool:
            with closing(self._connect()) as conn, conn:
                cur = conn.execute(
                    "UPDATE docs SET metadata = ? WHERE doc_id = ?",
                    (json.dumps(metadata), doc_id),
                )
                return cur.rowcount > 0

        return await self.hass.async_add_executor_job(_run)

    async def list_metadata(self, where: Filter | None = None) -> dict[str, dict[str, Any]]:
        clause, params = build_where_clause(where)

        def _run() -> dict[str, dict[str, Any]]:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    f"SELECT doc_id, metadata FROM docs WHERE 1=1{clause}", params
                ).fetchall()
            return {row["doc_id"]: json.loads(row["metadata"]) for row in rows}

        return await self.hass.async_add_executor_job(_run)
```

- [ ] **Step 5: Implement in `sqlite_vec.py`**

Both statements touch only the `docs` table — the `vec_docs` virtual table holds vectors and is untouched, which is exactly why the vector survives a metadata update. The code is the same two methods as Step 4, with `build_where_clause` imported from the sibling module as it already is elsewhere in this file:

```python
    async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
        def _run() -> bool:
            with closing(self._connect()) as conn, conn:
                cur = conn.execute(
                    "UPDATE docs SET metadata = ? WHERE doc_id = ?",
                    (json.dumps(metadata), doc_id),
                )
                return cur.rowcount > 0

        return await self.hass.async_add_executor_job(_run)

    async def list_metadata(self, where: Filter | None = None) -> dict[str, dict[str, Any]]:
        clause, params = build_where_clause(where)

        def _run() -> dict[str, dict[str, Any]]:
            with closing(self._connect()) as conn:
                rows = conn.execute(
                    f"SELECT doc_id, metadata FROM docs WHERE 1=1{clause}", params
                ).fetchall()
            return {row["doc_id"]: json.loads(row["metadata"]) for row in rows}

        return await self.hass.async_add_executor_job(_run)
```

- [ ] **Step 6: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_conformance.py -v`
Expected: the four new tests pass against both `sqlite_numpy` and `sqlite_vec`.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/backends/ tests/test_memory_backend_conformance.py
git commit -m "feat(memory): metadata read and update on the VectorBackend Protocol"
```

---

### Task 2: `update_metadata` and `list_metadata` for pgvector and qdrant

**Files:**
- Modify: `custom_components/smartchain/tools/memory/backends/pgvector.py`
- Modify: `custom_components/smartchain/tools/memory/backends/qdrant.py`
- Test: `tests/test_memory_backend_pgvector.py`, `tests/test_memory_backend_qdrant.py`

**Interfaces:**
- Consumes: the Protocol signatures from Task 1.
- Produces: nothing new; completes the four implementations.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_memory_backend_pgvector.py`:

```python
async def test_pgvector_update_metadata_issues_a_scoped_update(hass) -> None:
    backend, conn = _initialised_backend(hass)
    conn.execute.return_value = "UPDATE 1"

    assert await backend.update_metadata("a", {"kind": "entity"}) is True

    sql = conn.execute.await_args.args[0]
    assert "UPDATE" in sql and "metadata" in sql
    assert "WHERE doc_id = $2" in sql


async def test_pgvector_update_metadata_reports_a_missing_doc(hass) -> None:
    backend, conn = _initialised_backend(hass)
    conn.execute.return_value = "UPDATE 0"
    assert await backend.update_metadata("nope", {"kind": "entity"}) is False


async def test_pgvector_list_metadata_filters_and_keys_by_doc_id(hass) -> None:
    backend, conn = _initialised_backend(hass)
    conn.fetch.return_value = [
        {"doc_id": "a", "metadata": '{"kind": "entity"}'},
        {"doc_id": "b", "metadata": '{"kind": "entity"}'},
    ]

    result = await backend.list_metadata({"kind": "entity"})

    assert set(result) == {"a", "b"}
    assert result["a"]["kind"] == "entity"
    assert "metadata->" in conn.fetch.await_args.args[0]
```

Append to `tests/test_memory_backend_qdrant.py`:

```python
async def test_qdrant_list_metadata_follows_the_scroll_cursor(hass) -> None:
    backend = _backend(hass)
    pages = [
        (200, {"result": {"points": [{"payload": {"metadata": {"kind": "entity"},
                                                  "doc_id": "a"}}],
                          "next_page_offset": "cur1"}}),
        (200, {"result": {"points": [{"payload": {"metadata": {"kind": "entity"},
                                                  "doc_id": "b"}}],
                          "next_page_offset": None}}),
    ]
    with patch.object(backend, "_request", new=AsyncMock(side_effect=pages)) as req:
        result = await backend.list_metadata({"kind": "entity"})

    assert set(result) == {"a", "b"}
    assert req.await_count == 2
    assert req.await_args_list[1].args[2]["offset"] == "cur1"


async def test_qdrant_update_metadata_sets_payload_and_waits(hass) -> None:
    backend = _backend(hass)
    with patch.object(backend, "_request", new=AsyncMock(return_value=(200, {}))) as req:
        assert await backend.update_metadata("a", {"kind": "entity", "state": "on"}) is True

    path = req.await_args.args[1]
    assert "points/payload" in path
    assert "wait=true" in path


async def test_qdrant_update_metadata_raises_on_a_bad_status(hass) -> None:
    backend = _backend(hass)
    with (
        patch.object(backend, "_request", new=AsyncMock(return_value=(500, {}))),
        pytest.raises(QdrantError),
    ):
        await backend.update_metadata("a", {"kind": "entity"})
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_pgvector.py tests/test_memory_backend_qdrant.py -v`
Expected: `AttributeError`.

- [ ] **Step 3: Implement in `pgvector.py`**

```python
    async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            status = await conn.execute(
                f"UPDATE {self.table} SET metadata = $1::jsonb WHERE doc_id = $2",
                json.dumps(metadata),
                doc_id,
            )
        return _rowcount(status) > 0

    async def list_metadata(self, where: Filter | None = None) -> dict[str, dict[str, Any]]:
        clause, params = build_pg_where(where, start_index=1)
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT doc_id, metadata FROM {self.table} WHERE TRUE{clause}", *params
            )
        return {row["doc_id"]: json.loads(row["metadata"]) for row in rows}
```

Reuse whatever accessor the file already uses to obtain the pool; if it inlines `self._pool` with a guard rather than a `_require_pool` helper, follow that existing shape instead of introducing a new one.

- [ ] **Step 4: Implement in `qdrant.py`**

Mirror the retention sweep's existing scroll loop:

```python
    async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
        status, _ = await self._request(
            "POST",
            f"/collections/{self.collection}/points/payload?wait=true",
            {"payload": {"metadata": metadata}, "points": [point_id_for(doc_id)]},
        )
        self._check_status(status, "update_metadata")
        return True

    async def list_metadata(self, where: Filter | None = None) -> dict[str, dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        offset: Any = None
        while True:
            payload: dict[str, Any] = {
                "limit": 256,
                "with_payload": True,
                "with_vector": False,
            }
            if where:
                payload["filter"] = build_qdrant_filter(where)
            if offset is not None:
                payload["offset"] = offset

            status, body = await self._request(
                "POST", f"/collections/{self.collection}/points/scroll", payload
            )
            self._check_status(status, "list_metadata scroll")

            result = body.get("result") or {}
            for point in result.get("points") or []:
                point_payload = point.get("payload") or {}
                doc_id = point_payload.get("doc_id")
                if doc_id:
                    found[doc_id] = point_payload.get("metadata") or {}

            offset = result.get("next_page_offset")
            if offset is None:
                return found
```

Qdrant's payload-set endpoint reports success for a point id that does not exist, so `update_metadata` returning `True` there is a known and accepted divergence from the SQL backends. Note it in the method's docstring rather than faking a pre-check — the indexer never calls it for an unknown doc.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_memory_backend_pgvector.py tests/test_memory_backend_qdrant.py -v`
Expected: all pass.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/backends/ tests/
git commit -m "feat(memory): metadata read and update for pgvector and qdrant"
```

---

### Task 3: `MemoryStore` pass-throughs — Phase 1 checkpoint

**Files:**
- Modify: `custom_components/smartchain/tools/memory/store.py`
- Test: `tests/test_memory_store.py`

**Interfaces:**
- Produces: `MemoryStore.update_metadata(doc_id, metadata) -> bool` and `MemoryStore.list_metadata(where=None) -> dict[str, dict]`. Task 8 consumes both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_memory_store.py`:

```python
async def test_store_list_metadata_round_trips(hass, tmp_path) -> None:
    store = await _sqlite_store(hass, tmp_path)
    await store.add("hello", {"kind": "entity", "entity_id": "light.a"}, doc_id="entity:light.a")

    stored = await store.list_metadata({"kind": "entity"})

    assert set(stored) == {"entity:light.a"}
    assert stored["entity:light.a"]["entity_id"] == "light.a"


async def test_store_update_metadata_round_trips(hass, tmp_path) -> None:
    store = await _sqlite_store(hass, tmp_path)
    await store.add("hello", {"kind": "entity", "entity_id": "light.a"}, doc_id="entity:light.a")

    assert await store.update_metadata(
        "entity:light.a", {"kind": "entity", "entity_id": "light.a", "state": "on"}
    ) is True
    stored = await store.list_metadata({"kind": "entity"})
    assert stored["entity:light.a"]["state"] == "on"


async def test_store_metadata_helpers_are_safe_when_unavailable(hass, tmp_path) -> None:
    store = await _sqlite_store(hass, tmp_path)
    store.is_available = False

    assert await store.list_metadata() == {}
    assert await store.update_metadata("entity:light.a", {"kind": "entity"}) is False


async def test_store_metadata_helpers_swallow_backend_failures(hass, tmp_path, caplog) -> None:
    store = await _sqlite_store(hass, tmp_path)
    store.backend.list_metadata = AsyncMock(side_effect=RuntimeError("boom"))
    store.backend.update_metadata = AsyncMock(side_effect=RuntimeError("boom"))

    assert await store.list_metadata() == {}
    assert await store.update_metadata("x", {}) is False
    assert store.is_available is True
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_store.py -v`
Expected: `AttributeError` on `list_metadata`.

- [ ] **Step 3: Implement the pass-throughs**

Add to `MemoryStore`, following the shape every other runtime method already uses — bounded by the timeout, failures logged and swallowed, a safe empty value returned, and `is_available` untouched:

```python
    async def list_metadata(self, where: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
        """Stored metadata by doc_id. Returns {} on any failure."""
        if not self.is_available:
            return {}
        try:
            async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
                return await self.backend.list_metadata(where)
        except Exception:
            LOGGER.exception("memory list_metadata failed")
            return {}

    async def update_metadata(self, doc_id: str, metadata: dict[str, Any]) -> bool:
        """Refresh one document's metadata. Returns False on any failure."""
        if not self.is_available:
            return False
        try:
            async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
                return await self.backend.update_metadata(doc_id, metadata)
        except Exception:
            LOGGER.exception("memory update_metadata failed")
            return False
```

- [ ] **Step 4: Full suite and commit — Phase 1 checkpoint**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .
uv run --prerelease=allow pytest tests/ -q
```
Expected: fully green, zero skips.

```bash
git add custom_components/smartchain/tools/memory/store.py tests/test_memory_store.py
git commit -m "feat(memory): MemoryStore metadata helpers

Phase 1 checkpoint: every backend can now have its metadata read and
refreshed without re-embedding, which is what makes an incremental
entity sweep possible."
```

---

# Phase 2 — Configuration and candidate selection

### Task 4: Constants and `EntitySourceConfig`

**Files:**
- Modify: `custom_components/smartchain/const.py`
- Modify: `custom_components/smartchain/tools/memory/config.py`
- Test: `tests/test_memory_config.py`

**Interfaces:**
- Produces: `EntitySourceConfig(type, preset, index_states, include, exclude)` and `StoreConfig.source: EntitySourceConfig | None`. Tasks 5, 6, 8, 11 and 12 all consume them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_memory_config.py`:

```python
def test_entity_source_defaults() -> None:
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    cfg = EntitySourceConfig()
    assert cfg.type == "entities"
    assert cfg.preset == "optimal"
    assert cfg.index_states is False
    assert cfg.include == []
    assert cfg.exclude == []


def test_store_config_source_defaults_to_none() -> None:
    from custom_components.smartchain.tools.memory.config import StoreConfig

    assert StoreConfig(name="a", embeddings="E").source is None


def test_store_config_carries_a_source() -> None:
    from custom_components.smartchain.tools.memory.config import (
        EntitySourceConfig,
        StoreConfig,
    )

    cfg = StoreConfig(
        name="entities",
        embeddings="E",
        source=EntitySourceConfig(preset="paranoid", index_states=True),
    )
    assert cfg.source is not None
    assert cfg.source.preset == "paranoid"
    assert cfg.source.index_states is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_memory_config.py -v`
Expected: `ImportError` for `EntitySourceConfig`.

- [ ] **Step 3: Append the constants**

Append to `custom_components/smartchain/const.py`:

```python

# Entity indexing (v5.0.0)
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

# Only what a person controls.
ENTITY_MINIMAL_DOMAINS = [
    "light", "switch", "cover", "climate", "lock", "fan", "media_player",
    "scene", "script", "vacuum", "water_heater", "humidifier", "valve",
]
# `optimal` adds these whole domains on top of the minimal set.
ENTITY_OPTIMAL_EXTRA_DOMAINS = [
    "button", "input_boolean", "input_select", "input_number",
    "select", "number", "alarm_control_panel", "person", "weather",
]
# ...and these sensor / binary_sensor device classes. Battery level, signal
# strength and the like are deliberately absent: they dominate a real home by
# count and carry no meaning a user would ever search for.
ENTITY_MEANINGFUL_DEVICE_CLASSES = [
    "temperature", "humidity", "illuminance", "pressure",
    "motion", "occupancy", "presence", "door", "window", "opening",
    "garage_door", "smoke", "gas", "moisture", "carbon_monoxide",
    "carbon_dioxide", "power", "energy", "sound", "vibration", "problem",
]
```

`RESERVED_TOOL_NAMES` must also gain `ENTITY_TOOL_NAME`, so a custom YAML tool cannot shadow it:

```python
RESERVED_TOOL_NAMES = frozenset(
    {HISTORY_TOOL_NAME, DELEGATE_TOOL_NAME, MEMORY_TOOL_NAME, ENTITY_TOOL_NAME}
)
```

Read the existing definition first: keep whatever names it already lists and add `ENTITY_TOOL_NAME`. `ENTITY_TOOL_NAME` is defined below that line, so move the `RESERVED_TOOL_NAMES` assignment to the end of the entity block rather than forward-referencing.

- [ ] **Step 4: Add the dataclass**

Append to `custom_components/smartchain/tools/memory/config.py`, after `StoreConfig`:

```python
@dataclass(frozen=True)
class EntitySourceConfig:
    """Turns a store into an index of Home Assistant entities.

    `include` and `exclude` accept either a bare domain (`sensor`) or a full
    entity_id (`sensor.kitchen_temperature`). `exclude` is applied last and
    wins over both the preset and `include`.
    """

    type: str = "entities"
    preset: str = "optimal"
    index_states: bool = False
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
```

and add the field to `StoreConfig`:

```python
    source: EntitySourceConfig | None = None
```

`EntitySourceConfig` must be declared **above** `StoreConfig` so the annotation resolves without a string forward reference, matching how `BackendConfig` and `LogbookConfig` are already ordered in this file.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_memory_config.py tests/test_tools_schema.py -v`
Expected: all pass.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/const.py custom_components/smartchain/tools/memory/config.py tests/test_memory_config.py
git commit -m "feat(entities): EntitySourceConfig and the entity-indexing constants"
```

---

### Task 5: `source:` schema, incompatible-key rejection, loader

**Files:**
- Modify: `custom_components/smartchain/tools/schema.py`
- Modify: `custom_components/smartchain/tools/loader.py`
- Test: `tests/test_memory_schema.py`, `tests/test_memory_loader.py`
- Test fixture: `tests/fixtures/entity_store.yaml`

**Interfaces:**
- Consumes: `EntitySourceConfig`, `ENTITY_PRESETS`, `ENTITY_SOURCE_TYPE`.
- Produces: a validated `source` block reaching `StoreConfig.source`. Task 11 reads it off the parsed settings.

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/entity_store.yaml`:

```yaml
tools: []
memory:
  stores:
    - name: entities
      description: "Devices and sensors"
      embeddings: "GigaChat Embeddings"
      backend:
        type: sqlite_numpy
      source:
        type: entities
        preset: paranoid
        index_states: true
        include: [sensor.special_one]
        exclude: [update]

    - name: conversations
      embeddings: "GigaChat Embeddings"
      retention_days: 30
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_memory_schema.py`:

```python
def test_source_block_validates() -> None:
    result = MEMORY_SCHEMA(
        {"stores": [{"name": "e", "embeddings": "E", "source": {"type": "entities"}}]}
    )
    source = result["stores"][0]["source"]
    assert source["preset"] == "optimal"
    assert source["index_states"] is False
    assert source["include"] == []


def test_source_rejects_an_unknown_type() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA(
            {"stores": [{"name": "e", "embeddings": "E", "source": {"type": "automations"}}]}
        )


def test_source_rejects_an_unknown_preset() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA(
            {
                "stores": [
                    {"name": "e", "embeddings": "E",
                     "source": {"type": "entities", "preset": "aggressive"}}
                ]
            }
        )


@pytest.mark.parametrize("key,value", [
    ("retention_days", 30),
    ("ingest_conversation", True),
    ("ingest_conversation", False),
    ("ingest_logbook", {"enabled": True}),
])
def test_entity_store_rejects_incompatible_keys(key: str, value: object) -> None:
    """Retention would delete the index by age; ingest would pollute it."""
    with pytest.raises(vol.Invalid, match="do not apply"):
        MEMORY_SCHEMA(
            {
                "stores": [
                    {"name": "e", "embeddings": "E",
                     "source": {"type": "entities"}, key: value}
                ]
            }
        )


def test_entity_store_tolerates_defaulted_ingest_conversation() -> None:
    """The check must look at the raw keys, not at post-default values.

    `ingest_conversation` defaults to True, so a validator running after
    defaults were applied would reject every entity store ever written.
    """
    MEMORY_SCHEMA(
        {"stores": [{"name": "e", "embeddings": "E", "source": {"type": "entities"}}]}
    )


def test_conversation_store_keeps_its_keys() -> None:
    result = MEMORY_SCHEMA(
        {"stores": [{"name": "c", "embeddings": "E", "retention_days": 7}]}
    )
    assert result["stores"][0]["retention_days"] == 7
    assert result["stores"][0].get("source") is None


@pytest.mark.parametrize("bad", ["Sensor", "sensor.", ".x", "sensor x", "a.b.c"])
def test_source_include_rejects_malformed_entries(bad: str) -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA(
            {
                "stores": [
                    {"name": "e", "embeddings": "E",
                     "source": {"type": "entities", "include": [bad]}}
                ]
            }
        )
```

Append to `tests/test_memory_loader.py`:

```python
def test_loader_parses_an_entity_source(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text((FIXTURE_DIR / "entity_store.yaml").read_text())
    result = load_tools_file(target)

    entities, conversations = result.memory_settings.stores
    assert entities.source is not None
    assert entities.source.type == "entities"
    assert entities.source.preset == "paranoid"
    assert entities.source.index_states is True
    assert entities.source.include == ["sensor.special_one"]
    assert entities.source.exclude == ["update"]

    assert conversations.source is None
    assert conversations.retention_days == 30
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_schema.py tests/test_memory_loader.py -v`
Expected: the source block is rejected as an extra key.

- [ ] **Step 4: Extend the schema**

In `custom_components/smartchain/tools/schema.py`, add `ENTITY_PRESETS`, `ENTITY_DEFAULT_PRESET` and `ENTITY_SOURCE_TYPE` to the `..const` import, then define above `_STORE_SCHEMA`:

```python
# A domain (`sensor`) or a full entity_id (`sensor.kitchen_temperature`).
_ENTITY_SELECTOR = vol.Match(r"^[a-z_]+(\.[a-z0-9_]+)?\Z")

_SOURCE_SCHEMA = vol.Schema(
    {
        vol.Required("type"): vol.In([ENTITY_SOURCE_TYPE]),
        vol.Optional("preset", default=ENTITY_DEFAULT_PRESET): vol.In(ENTITY_PRESETS),
        vol.Optional("index_states", default=False): bool,
        vol.Optional("include", default=list): [_ENTITY_SELECTOR],
        vol.Optional("exclude", default=list): [_ENTITY_SELECTOR],
    }
)
```

Add one key to `_STORE_SCHEMA`, left without a default so an absent block stays absent rather than becoming an empty dict:

```python
        vol.Optional("source"): _SOURCE_SCHEMA,
```

- [ ] **Step 5: Reject the incompatible keys**

In `_validate_memory`, between the legacy-block guard and the `vol.Schema(...)` call, add a pass over the **raw** stores:

```python
    raw_stores = value.get("stores")
    if isinstance(raw_stores, list):
        for raw in raw_stores:
            if not isinstance(raw, dict):
                continue
            source = raw.get("source")
            if not isinstance(source, dict) or source.get("type") != ENTITY_SOURCE_TYPE:
                continue
            clashing = sorted(
                {"retention_days", "ingest_conversation", "ingest_logbook"} & set(raw)
            )
            if clashing:
                raise vol.Invalid(
                    f"memory store {raw.get('name')!r} declares source.type: "
                    f"{ENTITY_SOURCE_TYPE}, so these keys do not apply and were "
                    f"rejected: {clashing}. Retention would delete indexed entities "
                    "by age, and conversation or logbook ingest would write "
                    "non-entity documents into the index."
                )
```

This runs against the raw mapping deliberately: `_STORE_SCHEMA` defaults `ingest_conversation` to `True`, so a check performed after validation could not tell a user's explicit `true` from the default and would reject every entity store.

- [ ] **Step 6: Parse it in the loader**

In `custom_components/smartchain/tools/loader.py`, add `EntitySourceConfig` to the `.memory.config` import and build it inside `_memory_from_validated`'s per-store loop, before constructing `StoreConfig`:

```python
        source_raw = entry.get("source")
        source = (
            EntitySourceConfig(
                type=source_raw["type"],
                preset=source_raw.get("preset", "optimal"),
                index_states=source_raw.get("index_states", False),
                include=list(source_raw.get("include") or []),
                exclude=list(source_raw.get("exclude") or []),
            )
            if isinstance(source_raw, dict)
            else None
        )
```

and pass `source=source` to `StoreConfig(...)`.

- [ ] **Step 7: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_memory_schema.py tests/test_memory_loader.py tests/test_tools_loader.py -v`
Expected: all pass.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/ tests/
git commit -m "feat(entities): source: block in the store schema and loader"
```

---

### Task 6: `entity_filter.py` — presets and `resolve_candidates`

**Files:**
- Create: `custom_components/smartchain/tools/memory/entity_filter.py`
- Test: `tests/test_entity_filter.py`

**Interfaces:**
- Consumes: `EntitySourceConfig`, the `ENTITY_*` constants.
- Produces: `EntityCandidate` and `resolve_candidates(hass, config) -> dict[str, EntityCandidate]`. Tasks 7, 8 and 12 all consume both. Task 12 in particular calls it **without** a running indexer, which is what makes the tool's lexical fallback real.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entity_filter.py`:

```python
"""Preset expansion decides what the home looks like to the model."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.config import EntitySourceConfig
from custom_components.smartchain.tools.memory.entity_filter import (
    EntityCandidate,
    resolve_candidates,
)


def _entry(
    entity_id: str,
    *,
    name: str = "",
    area_id: str | None = None,
    device_id: str | None = None,
    device_class: str | None = None,
    entity_category: EntityCategory | None = None,
    hidden: bool = False,
    disabled: bool = False,
    aliases: set[str] | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.name = name or None
    entry.original_name = name or entity_id
    entry.area_id = area_id
    entry.device_id = device_id
    entry.device_class = device_class
    entry.original_device_class = device_class
    entry.entity_category = entity_category
    entry.hidden_by = "user" if hidden else None
    entry.disabled_by = "user" if disabled else None
    entry.aliases = aliases or set()
    return entry


@pytest.fixture
def home(hass: HomeAssistant):
    """A small home covering every branch the presets can take."""
    entries = [
        _entry("light.ceiling", name="Потолок", area_id="kitchen", aliases={"люстра"}),
        _entry("switch.socket", name="Кофеварка", area_id="kitchen"),
        _entry("sensor.temp", name="Температура", area_id="kitchen",
               device_class="temperature"),
        _entry("sensor.battery", name="Батарея", device_class="battery"),
        _entry("sensor.uptime", name="Аптайм", entity_category=EntityCategory.DIAGNOSTIC),
        _entry("update.firmware", name="Прошивка"),
        _entry("light.hidden_one", name="Скрытый", hidden=True),
        _entry("light.disabled_one", name="Отключённый", disabled=True),
    ]
    ent_reg = MagicMock()
    ent_reg.entities = {e.entity_id: e for e in entries}

    area = MagicMock()
    area.name = "Кухня"
    area_reg = MagicMock()
    area_reg.async_get_area.side_effect = lambda aid: area if aid == "kitchen" else None

    dev_reg = MagicMock()
    dev_reg.async_get.return_value = None

    # A template sensor that exists only in the state machine.
    hass.states.async_set(
        "sensor.template_only", "42", {"friendly_name": "Шаблонный", "device_class": "humidity"}
    )
    for e in entries:
        if not e.disabled_by:
            hass.states.async_set(e.entity_id, "on", {"friendly_name": e.original_name})

    with (
        patch("custom_components.smartchain.tools.memory.entity_filter.er.async_get",
              return_value=ent_reg),
        patch("custom_components.smartchain.tools.memory.entity_filter.ar.async_get",
              return_value=area_reg),
        patch("custom_components.smartchain.tools.memory.entity_filter.dr.async_get",
              return_value=dev_reg),
    ):
        yield


def _ids(hass, **kwargs) -> set[str]:
    return set(resolve_candidates(hass, EntitySourceConfig(**kwargs)))


def test_minimal_is_controllables_only(hass: HomeAssistant, home) -> None:
    assert _ids(hass, preset="minimal") == {"light.ceiling", "switch.socket"}


def test_optimal_adds_meaningful_sensors(hass: HomeAssistant, home) -> None:
    assert _ids(hass, preset="optimal") == {
        "light.ceiling", "switch.socket", "sensor.temp", "sensor.template_only",
    }


def test_optimal_drops_noise_and_diagnostics(hass: HomeAssistant, home) -> None:
    got = _ids(hass, preset="optimal")
    assert "sensor.battery" not in got
    assert "sensor.uptime" not in got
    assert "update.firmware" not in got


def test_maximal_takes_everything_visible(hass: HomeAssistant, home) -> None:
    got = _ids(hass, preset="maximal")
    assert "update.firmware" in got
    assert "sensor.battery" in got
    assert "sensor.uptime" in got
    assert "light.hidden_one" not in got
    assert "light.disabled_one" not in got


def test_paranoid_takes_hidden_and_disabled_too(hass: HomeAssistant, home) -> None:
    got = _ids(hass, preset="paranoid")
    assert "light.hidden_one" in got
    assert "light.disabled_one" in got


def test_state_only_entities_are_not_lost(hass: HomeAssistant, home) -> None:
    """Template sensors have no registry entry and would otherwise vanish."""
    assert "sensor.template_only" in _ids(hass, preset="maximal")


def test_include_adds_on_top_of_the_preset(hass: HomeAssistant, home) -> None:
    got = _ids(hass, preset="minimal", include=["sensor.battery"])
    assert "sensor.battery" in got
    assert "sensor.temp" not in got


def test_include_accepts_a_bare_domain(hass: HomeAssistant, home) -> None:
    assert "update.firmware" in _ids(hass, preset="minimal", include=["update"])


def test_exclude_wins_over_the_preset(hass: HomeAssistant, home) -> None:
    assert "light.ceiling" not in _ids(hass, preset="minimal", exclude=["light.ceiling"])


def test_exclude_wins_over_include(hass: HomeAssistant, home) -> None:
    got = _ids(hass, preset="minimal", include=["sensor.battery"], exclude=["sensor.battery"])
    assert "sensor.battery" not in got


def test_exclude_accepts_a_bare_domain(hass: HomeAssistant, home) -> None:
    assert not [e for e in _ids(hass, preset="maximal", exclude=["update"])
               if e.startswith("update.")]


def test_candidate_carries_the_searchable_fields(hass: HomeAssistant, home) -> None:
    cand = resolve_candidates(hass, EntitySourceConfig(preset="minimal"))["light.ceiling"]
    assert isinstance(cand, EntityCandidate)
    assert cand.domain == "light"
    assert cand.name == "Потолок"
    assert cand.area == "Кухня"
    assert cand.aliases == ("люстра",)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_entity_filter.py -v`
Expected: `ModuleNotFoundError` for `entity_filter`.

- [ ] **Step 3: Implement `entity_filter.py`**

Create `custom_components/smartchain/tools/memory/entity_filter.py`:

```python
"""Decide which Home Assistant entities belong in an entity index.

Deliberately free of I/O and of any dependency on a running indexer: the
`search_entities` tool calls this directly when its store is unavailable, and
that fallback is only real if candidate selection needs nothing but the
registries and the state machine.
"""

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from ...const import (
    ENTITY_MEANINGFUL_DEVICE_CLASSES,
    ENTITY_MINIMAL_DOMAINS,
    ENTITY_OPTIMAL_EXTRA_DOMAINS,
)
from .config import EntitySourceConfig

_HIDDEN_CATEGORIES = {"config", "diagnostic"}


@dataclass(frozen=True)
class EntityCandidate:
    """One entity as the index and the tool both see it."""

    entity_id: str
    domain: str
    name: str
    area: str
    device: str
    device_class: str
    aliases: tuple[str, ...]


def _category_value(entity_category: object) -> str:
    """EntityCategory is an enum in the registry and absent for state-only entities."""
    if entity_category is None:
        return ""
    return getattr(entity_category, "value", str(entity_category))


def _preset_allows(
    preset: str,
    domain: str,
    device_class: str,
    category: str,
    *,
    hidden: bool,
    disabled: bool,
) -> bool:
    if preset == "paranoid":
        return True
    if hidden or disabled:
        return False
    if preset == "maximal":
        return True

    if category in _HIDDEN_CATEGORIES:
        return False
    if domain in ENTITY_MINIMAL_DOMAINS:
        return True
    if preset == "minimal":
        return False

    if domain in ENTITY_OPTIMAL_EXTRA_DOMAINS:
        return True
    if domain in ("sensor", "binary_sensor"):
        return device_class in ENTITY_MEANINGFUL_DEVICE_CLASSES
    return False


def _selected(selectors: list[str], entity_id: str, domain: str) -> bool:
    """A selector is a bare domain or a full entity_id."""
    return entity_id in selectors or domain in selectors


def resolve_candidates(
    hass: HomeAssistant, config: EntitySourceConfig
) -> dict[str, EntityCandidate]:
    """Every entity this source should index, keyed by entity_id."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)

    def _area_name(area_id: str | None) -> str:
        if not area_id:
            return ""
        area = area_reg.async_get_area(area_id)
        return area.name if area else ""

    raw: dict[str, tuple[EntityCandidate, str, bool, bool]] = {}

    for entry in ent_reg.entities.values():
        domain = entry.entity_id.split(".")[0]
        device = dev_reg.async_get(entry.device_id) if entry.device_id else None
        area_id = entry.area_id or (device.area_id if device else None)
        device_class = entry.device_class or entry.original_device_class or ""
        raw[entry.entity_id] = (
            EntityCandidate(
                entity_id=entry.entity_id,
                domain=domain,
                name=entry.name or entry.original_name or entry.entity_id,
                area=_area_name(area_id),
                device=(device.name_by_user or device.name) if device else "",
                device_class=device_class,
                aliases=tuple(sorted(entry.aliases or ())),
            ),
            _category_value(entry.entity_category),
            entry.hidden_by is not None,
            entry.disabled_by is not None,
        )

    # Entities created by legacy YAML platforms, templates and groups never
    # reach the entity registry. Skipping them would silently gut `maximal`.
    for state in hass.states.async_all():
        if state.entity_id in raw:
            continue
        domain = state.entity_id.split(".")[0]
        raw[state.entity_id] = (
            EntityCandidate(
                entity_id=state.entity_id,
                domain=domain,
                name=state.attributes.get("friendly_name") or state.entity_id,
                area="",
                device="",
                device_class=state.attributes.get("device_class") or "",
                aliases=(),
            ),
            "",
            False,
            False,
        )

    chosen: dict[str, EntityCandidate] = {}
    for entity_id, (cand, category, hidden, disabled) in raw.items():
        keep = _preset_allows(
            config.preset,
            cand.domain,
            cand.device_class,
            category,
            hidden=hidden,
            disabled=disabled,
        )
        if not keep and _selected(config.include, entity_id, cand.domain):
            keep = True
        if keep and _selected(config.exclude, entity_id, cand.domain):
            keep = False
        if keep:
            chosen[entity_id] = cand
    return chosen
```

- [ ] **Step 4: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_entity_filter.py -v`
Expected: 13 passed.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/entity_filter.py tests/test_entity_filter.py
git commit -m "feat(entities): preset expansion and candidate resolution

Phase 2 checkpoint: the shape of the index is decided, but nothing
writes to a store yet."
```

---

# Phase 3 — The indexer

### Task 7: `entity_doc.py` — catalogue text and fingerprint

**Files:**
- Create: `custom_components/smartchain/tools/memory/entity_doc.py`
- Test: `tests/test_entity_doc.py`

**Interfaces:**
- Consumes: `EntityCandidate`.
- Produces: `render_catalogue(cand) -> str`, `fingerprint(text) -> str`, `doc_id_for(entity_id) -> str`, `build_metadata(cand, text, state=None) -> dict[str, str]`. Task 8 uses all four.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entity_doc.py`:

```python
"""What gets embedded, and how a change in it is detected."""

from custom_components.smartchain.tools.memory.entity_doc import (
    build_metadata,
    doc_id_for,
    fingerprint,
    render_catalogue,
)
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate


def _cand(**kw) -> EntityCandidate:
    base = dict(
        entity_id="light.ceiling",
        domain="light",
        name="Потолок",
        area="Кухня",
        device="Yeelight",
        device_class="",
        aliases=(),
    )
    base.update(kw)
    return EntityCandidate(**base)


def test_doc_id_is_namespaced() -> None:
    assert doc_id_for("light.ceiling") == "entity:light.ceiling"


def test_catalogue_has_the_two_fixed_lines() -> None:
    text = render_catalogue(_cand())
    lines = text.split("\n")
    assert len(lines) == 2
    assert lines[0] == "light.ceiling — Потолок"
    assert lines[1] == "Area: Кухня | Device: Yeelight | Domain: light | Class: —"


def test_aliases_add_a_third_line() -> None:
    text = render_catalogue(_cand(aliases=("люстра", "верхний свет")))
    assert text.split("\n")[2] == "Also known as: люстра, верхний свет"


def test_absent_fields_render_as_a_dash_not_dropped() -> None:
    """Clearing a field must change the fingerprint, so the slot has to stay."""
    text = render_catalogue(_cand(area="", device=""))
    assert "Area: — | Device: —" in text
    assert len(text.split("\n")) == 2


def test_clearing_a_field_changes_the_fingerprint() -> None:
    before = fingerprint(render_catalogue(_cand()))
    after = fingerprint(render_catalogue(_cand(area="")))
    assert before != after


def test_fingerprint_is_stable_and_short() -> None:
    text = render_catalogue(_cand())
    assert fingerprint(text) == fingerprint(text)
    assert len(fingerprint(text)) == 16


def test_metadata_shape_without_state() -> None:
    cand = _cand(device_class="illuminance")
    meta = build_metadata(cand, render_catalogue(cand))
    assert meta["kind"] == "entity"
    assert meta["entity_id"] == "light.ceiling"
    assert meta["domain"] == "light"
    assert meta["area"] == "Кухня"
    assert meta["device_class"] == "illuminance"
    assert len(meta["fingerprint"]) == 16
    assert "state" not in meta


def test_metadata_carries_state_when_given() -> None:
    cand = _cand()
    meta = build_metadata(cand, render_catalogue(cand), state="on")
    assert meta["state"] == "on"
    assert meta["state_updated"]


def test_every_metadata_value_is_a_string() -> None:
    """The Filter contract is equality over scalars; keep it to str."""
    cand = _cand()
    meta = build_metadata(cand, render_catalogue(cand), state="on")
    assert all(isinstance(v, str) for v in meta.values())
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_entity_doc.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement it**

Create `custom_components/smartchain/tools/memory/entity_doc.py`:

```python
"""The document one entity becomes: what is embedded, and how change is spotted."""

import hashlib

from homeassistant.util import dt as dt_util

from .entity_filter import EntityCandidate

_ABSENT = "—"


def doc_id_for(entity_id: str) -> str:
    return f"entity:{entity_id}"


def render_catalogue(cand: EntityCandidate) -> str:
    """The text that gets embedded.

    Catalogue only — the state is deliberately absent. If the state were in
    here, every state change would force a re-embed, which is the cost the
    whole design exists to avoid.

    Structural labels stay in English; names, areas and aliases are whatever
    Home Assistant holds, in the user's own language.
    """
    lines = [
        f"{cand.entity_id} — {cand.name or cand.entity_id}",
        (
            f"Area: {cand.area or _ABSENT} | Device: {cand.device or _ABSENT} "
            f"| Domain: {cand.domain} | Class: {cand.device_class or _ABSENT}"
        ),
    ]
    if cand.aliases:
        lines.append("Also known as: " + ", ".join(cand.aliases))
    return "\n".join(lines)


def fingerprint(text: str) -> str:
    """Short digest of the catalogue text — the whole basis of incremental sweeps."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def build_metadata(
    cand: EntityCandidate, text: str, state: str | None = None
) -> dict[str, str]:
    """Metadata for one entity document. Every value is a str by contract."""
    meta = {
        "kind": "entity",
        "entity_id": cand.entity_id,
        "domain": cand.domain,
        "area": cand.area,
        "device_class": cand.device_class,
        "fingerprint": fingerprint(text),
    }
    if state is not None:
        meta["state"] = state
        meta["state_updated"] = dt_util.utcnow().isoformat()
    return meta
```

- [ ] **Step 4: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_entity_doc.py -v`
Expected: 9 passed.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/entity_doc.py tests/test_entity_doc.py
git commit -m "feat(entities): catalogue document rendering and fingerprint"
```

---

### Task 8: `EntityIndexer` — the reconciling sweep

**Files:**
- Create: `custom_components/smartchain/tools/memory/entity_index.py`
- Test: `tests/test_entity_index.py`

**Interfaces:**
- Consumes: `MemoryStore.list_metadata` / `.add` / `.delete_where`, `resolve_candidates`, `render_catalogue`, `fingerprint`, `build_metadata`, `doc_id_for`.
- Produces: `EntityIndexer(hass, store, config)` with `async reconcile(full=False) -> SweepResult` and the `SweepResult(new, changed, removed, unchanged)` dataclass. Tasks 9, 10, 11 and 13 build on it.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entity_index.py`:

```python
"""The sweep reconciles; it never blindly rebuilds."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.config import EntitySourceConfig
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str, name: str = "Name", area: str = "Кухня") -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        area=area,
        device="",
        device_class="",
        aliases=(),
    )


def _store() -> MagicMock:
    store = MagicMock()
    store.is_available = True
    store.add = AsyncMock(return_value=["id"])
    store.delete_where = AsyncMock(return_value=1)
    store.list_metadata = AsyncMock(return_value={})
    store.update_metadata = AsyncMock(return_value=True)
    return store


def _indexer(hass: HomeAssistant, store, candidates, **cfg) -> EntityIndexer:
    indexer = EntityIndexer(hass, store, EntitySourceConfig(**cfg))
    patcher = patch(
        "custom_components.smartchain.tools.memory.entity_index.resolve_candidates",
        return_value={c.entity_id: c for c in candidates},
    )
    indexer._patcher = patcher  # kept alive for the test's duration
    patcher.start()
    return indexer


async def test_first_sweep_indexes_everything(hass: HomeAssistant) -> None:
    store = _store()
    indexer = _indexer(hass, store, [_cand("light.a"), _cand("light.b")])

    result = await indexer.reconcile()

    assert result.new == 2
    assert result.changed == 0
    assert store.add.await_count == 2
    assert store.add.await_args_list[0].kwargs["doc_id"] == "entity:light.a"


async def test_second_sweep_of_an_unchanged_home_embeds_nothing(hass: HomeAssistant) -> None:
    """The central promise: a restart costs zero embeddings."""
    store = _store()
    cands = [_cand("light.a"), _cand("light.b")]
    indexer = _indexer(hass, store, cands)

    await indexer.reconcile()
    stored = {
        call.kwargs["doc_id"]: call.args[1] for call in store.add.await_args_list
    }
    store.add.reset_mock()
    store.list_metadata = AsyncMock(return_value=stored)

    result = await indexer.reconcile()

    assert store.add.await_count == 0
    assert result.unchanged == 2
    assert result.new == 0


async def test_a_renamed_entity_re_embeds_exactly_one(hass: HomeAssistant) -> None:
    store = _store()
    indexer = _indexer(hass, store, [_cand("light.a"), _cand("light.b")])
    await indexer.reconcile()
    stored = {call.kwargs["doc_id"]: call.args[1] for call in store.add.await_args_list}
    store.add.reset_mock()
    store.list_metadata = AsyncMock(return_value=stored)

    indexer._patcher.stop()
    with patch(
        "custom_components.smartchain.tools.memory.entity_index.resolve_candidates",
        return_value={
            "light.a": _cand("light.a", name="Переименован"),
            "light.b": _cand("light.b"),
        },
    ):
        result = await indexer.reconcile()

    assert store.add.await_count == 1
    assert store.add.await_args.kwargs["doc_id"] == "entity:light.a"
    assert result.changed == 1
    assert result.unchanged == 1


async def test_a_vanished_entity_is_deleted(hass: HomeAssistant) -> None:
    store = _store()
    store.list_metadata = AsyncMock(
        return_value={
            "entity:light.a": {"kind": "entity", "entity_id": "light.a", "fingerprint": "x"},
            "entity:light.gone": {"kind": "entity", "entity_id": "light.gone",
                                  "fingerprint": "y"},
        }
    )
    indexer = _indexer(hass, store, [_cand("light.a")])

    result = await indexer.reconcile()

    assert result.removed == 1
    store.delete_where.assert_awaited_once_with(
        {"kind": "entity", "entity_id": "light.gone"}
    )


async def test_a_narrowed_preset_removes_what_dropped_out(hass: HomeAssistant) -> None:
    store = _store()
    store.list_metadata = AsyncMock(
        return_value={
            f"entity:{eid}": {"kind": "entity", "entity_id": eid, "fingerprint": "x"}
            for eid in ("light.a", "sensor.temp", "update.fw")
        }
    )
    indexer = _indexer(hass, store, [_cand("light.a")])

    result = await indexer.reconcile()

    assert result.removed == 2


async def test_full_ignores_fingerprints(hass: HomeAssistant) -> None:
    """For when the embedding model changed but the catalogue text did not."""
    store = _store()
    indexer = _indexer(hass, store, [_cand("light.a")])
    await indexer.reconcile()
    stored = {call.kwargs["doc_id"]: call.args[1] for call in store.add.await_args_list}
    store.add.reset_mock()
    store.list_metadata = AsyncMock(return_value=stored)

    result = await indexer.reconcile(full=True)

    assert store.add.await_count == 1
    assert result.changed == 1


async def test_state_is_indexed_only_when_asked(hass: HomeAssistant) -> None:
    hass.states.async_set("light.a", "on", {})
    store = _store()

    indexer = _indexer(hass, store, [_cand("light.a")], index_states=False)
    await indexer.reconcile()
    assert "state" not in store.add.await_args.args[1]

    store.add.reset_mock()
    indexer._patcher.stop()
    indexer2 = _indexer(hass, store, [_cand("light.a")], index_states=True)
    await indexer2.reconcile()
    assert store.add.await_args.args[1]["state"] == "on"


async def test_a_failing_sweep_never_raises(hass: HomeAssistant, caplog) -> None:
    store = _store()
    store.list_metadata = AsyncMock(side_effect=RuntimeError("boom"))
    indexer = _indexer(hass, store, [_cand("light.a")])

    result = await indexer.reconcile()

    assert result.new == 0
    assert "entity index" in caplog.text.lower()


async def test_an_unavailable_store_is_skipped(hass: HomeAssistant) -> None:
    store = _store()
    store.is_available = False
    indexer = _indexer(hass, store, [_cand("light.a")])

    await indexer.reconcile()

    assert store.add.await_count == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_entity_index.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement the sweep**

Create `custom_components/smartchain/tools/memory/entity_index.py`:

```python
"""Keeps an entity store in step with the home, embedding only what changed."""

import asyncio
import logging
from dataclasses import dataclass

from homeassistant.core import HomeAssistant

from ...const import ENTITY_INDEX_BATCH_PAUSE_SECONDS, ENTITY_INDEX_BATCH_SIZE
from .config import EntitySourceConfig
from .entity_doc import build_metadata, doc_id_for, render_catalogue
from .entity_filter import EntityCandidate, resolve_candidates
from .store import MemoryStore

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class SweepResult:
    new: int = 0
    changed: int = 0
    removed: int = 0
    unchanged: int = 0


class EntityIndexer:
    """One entity-source store's view of the home.

    Failures are logged and swallowed: a broken sweep leaves the previous
    index in place rather than emptying it.
    """

    def __init__(
        self, hass: HomeAssistant, store: MemoryStore, config: EntitySourceConfig
    ) -> None:
        self.hass = hass
        self.store = store
        self.config = config
        self._lock = asyncio.Lock()

    def _state_of(self, entity_id: str) -> str | None:
        if not self.config.index_states:
            return None
        state = self.hass.states.get(entity_id)
        return state.state if state else "unavailable"

    async def reconcile(self, *, full: bool = False) -> SweepResult:
        """Bring the store in line with the home. Never raises."""
        if not self.store.is_available:
            return SweepResult()

        async with self._lock:
            try:
                return await self._reconcile()  # noqa: BLE001 handled below
            except Exception:  # noqa: BLE001 — a sweep must never break setup
                LOGGER.exception("entity index sweep failed")
                return SweepResult()

    async def _reconcile(self, full: bool = False) -> SweepResult:
        candidates = resolve_candidates(self.hass, self.config)
        stored = await self.store.list_metadata({"kind": "entity"})

        pending: list[tuple[EntityCandidate, str, dict[str, str]]] = []
        new = changed = unchanged = 0

        for entity_id, cand in candidates.items():
            text = render_catalogue(cand)
            metadata = build_metadata(cand, text, state=self._state_of(entity_id))
            existing = stored.get(doc_id_for(entity_id))
            if existing is None:
                new += 1
            elif full or existing.get("fingerprint") != metadata["fingerprint"]:
                changed += 1
            else:
                unchanged += 1
                continue
            pending.append((cand, text, metadata))

        await self._write(pending)

        removed = 0
        for doc_id, meta in stored.items():
            entity_id = meta.get("entity_id", "")
            if entity_id and entity_id not in candidates:
                await self.store.delete_where({"kind": "entity", "entity_id": entity_id})
                removed += 1

        LOGGER.info(
            "entity index: %d new, %d changed, %d removed, %d unchanged",
            new,
            changed,
            removed,
            unchanged,
        )
        return SweepResult(new=new, changed=changed, removed=removed, unchanged=unchanged)

    async def _write(self, pending: list[tuple[EntityCandidate, str, dict[str, str]]]) -> None:
        """Embed and store in batches, yielding between them.

        A first sweep over a large home is hundreds of embedding calls; it must
        not monopolise the executor while HA is still coming up.
        """
        for index in range(0, len(pending), ENTITY_INDEX_BATCH_SIZE):
            batch = pending[index : index + ENTITY_INDEX_BATCH_SIZE]
            for cand, text, metadata in batch:
                await self.store.add(text, metadata, doc_id=doc_id_for(cand.entity_id))
            if index + ENTITY_INDEX_BATCH_SIZE < len(pending):
                await asyncio.sleep(ENTITY_INDEX_BATCH_PAUSE_SECONDS)
```

Note the `full` flag must reach `_reconcile`; wire `reconcile(full=...)` through to `self._reconcile(full)` rather than leaving the inner default in place.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_entity_index.py -v`
Expected: 9 passed.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/entity_index.py tests/test_entity_index.py
git commit -m "feat(entities): incremental reconciling sweep"
```

---

### Task 9: Lifecycle and registry subscriptions

**Files:**
- Modify: `custom_components/smartchain/tools/memory/entity_index.py`
- Test: `tests/test_entity_index_lifecycle.py`

**Interfaces:**
- Produces: `EntityIndexer.start() -> None` (synchronous) and `async stop() -> None`, matching `RetentionTask` and `MemoryLogbookPoller` so `MemoryRegistry` can own it the same way. Task 11 depends on that exact shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entity_index_lifecycle.py`:

```python
"""Startup timing and registry-driven refreshes."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.smartchain.tools.memory.config import EntitySourceConfig
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _indexer(hass: HomeAssistant, **cfg) -> tuple[EntityIndexer, AsyncMock]:
    store = MagicMock()
    store.is_available = True
    indexer = EntityIndexer(hass, store, EntitySourceConfig(**cfg))
    sweep = AsyncMock(return_value=None)
    indexer.reconcile = sweep
    return indexer, sweep


async def test_start_defers_the_sweep_until_hass_is_up(hass: HomeAssistant) -> None:
    """A thousand embeddings must not delay HA's startup."""
    indexer, sweep = _indexer(hass)

    with patch.object(type(hass), "state", CoreState.not_running):
        indexer.start()
        assert sweep.await_count == 0

        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED, {})
        await hass.async_block_till_done()

    assert sweep.await_count == 1
    await indexer.stop()


async def test_running_hass_sweeps_in_the_background(hass: HomeAssistant) -> None:
    """On reload_tools HA is already up, so waiting for the event would hang."""
    indexer, sweep = _indexer(hass)

    indexer.start()
    await hass.async_block_till_done()

    assert sweep.await_count == 1
    await indexer.stop()


async def test_entity_removal_deletes_immediately(hass: HomeAssistant) -> None:
    indexer, _ = _indexer(hass)
    indexer.store.delete_where = AsyncMock(return_value=1)
    indexer.start()
    await hass.async_block_till_done()

    hass.bus.async_fire(
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        {"action": "remove", "entity_id": "light.gone"},
    )
    await hass.async_block_till_done()

    indexer.store.delete_where.assert_awaited_with(
        {"kind": "entity", "entity_id": "light.gone"}
    )
    await indexer.stop()


async def test_registry_changes_are_debounced_into_one_sweep(hass: HomeAssistant) -> None:
    indexer, sweep = _indexer(hass)
    indexer.start()
    await hass.async_block_till_done()
    sweep.reset_mock()

    for name in ("a", "b", "c"):
        hass.bus.async_fire(
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            {"action": "update", "entity_id": f"light.{name}"},
        )
    await hass.async_block_till_done()
    await indexer._flush_debounce()

    assert sweep.await_count == 1
    await indexer.stop()


@pytest.mark.parametrize(
    "event",
    [dr.EVENT_DEVICE_REGISTRY_UPDATED, ar.EVENT_AREA_REGISTRY_UPDATED],
)
async def test_device_and_area_changes_schedule_a_sweep(
    hass: HomeAssistant, event: str
) -> None:
    """Renaming an area touches every entity in it, so the sweep is the cheap
    way to catch it — fingerprints keep it incremental."""
    indexer, sweep = _indexer(hass)
    indexer.start()
    await hass.async_block_till_done()
    sweep.reset_mock()

    hass.bus.async_fire(event, {"action": "update", "device_id": "d1"})
    await hass.async_block_till_done()
    await indexer._flush_debounce()

    assert sweep.await_count == 1
    await indexer.stop()


async def test_stop_cancels_pending_work(hass: HomeAssistant) -> None:
    indexer, sweep = _indexer(hass)
    indexer.start()
    await hass.async_block_till_done()
    sweep.reset_mock()

    hass.bus.async_fire(
        er.EVENT_ENTITY_REGISTRY_UPDATED, {"action": "update", "entity_id": "light.a"}
    )
    await indexer.stop()
    await hass.async_block_till_done()

    assert sweep.await_count == 0


async def test_stop_is_idempotent(hass: HomeAssistant) -> None:
    indexer, _ = _indexer(hass)
    indexer.start()
    await indexer.stop()
    await indexer.stop()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_entity_index_lifecycle.py -v`
Expected: `AttributeError` on `start`.

- [ ] **Step 3: Add the lifecycle**

Extend `EntityIndexer` with imports:

```python
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, Event, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later

from ...const import ENTITY_REGISTRY_DEBOUNCE_SECONDS
```

and these members:

```python
    def start(self) -> None:
        """Subscribe and schedule the first sweep. Never sweeps inline."""
        if self._unsubs:
            return

        self._unsubs.append(
            self.hass.bus.async_listen(
                er.EVENT_ENTITY_REGISTRY_UPDATED, self._on_entity_registry
            )
        )
        for event in (dr.EVENT_DEVICE_REGISTRY_UPDATED, ar.EVENT_AREA_REGISTRY_UPDATED):
            self._unsubs.append(self.hass.bus.async_listen(event, self._on_broad_change))

        if self.hass.state is CoreState.running:
            self._schedule_sweep()
        else:
            self._unsubs.append(
                self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED, lambda _event: self._schedule_sweep()
                )
            )

    async def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cancel_debounce()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

    @callback
    def _schedule_sweep(self, *, full: bool = False) -> None:
        self._task = self.hass.async_create_background_task(
            self.reconcile(full=full), name="smartchain_entity_index"
        )

    @callback
    def _on_entity_registry(self, event: Event) -> None:
        data = event.data
        if data.get("action") == "remove":
            entity_id = data.get("entity_id")
            if entity_id:
                self.hass.async_create_background_task(
                    self.store.delete_where({"kind": "entity", "entity_id": entity_id}),
                    name="smartchain_entity_index_remove",
                )
            return
        self._debounce()

    @callback
    def _on_broad_change(self, _event: Event) -> None:
        self._debounce()

    @callback
    def _debounce(self) -> None:
        self._cancel_debounce()
        self._unsub_debounce = async_call_later(
            self.hass,
            ENTITY_REGISTRY_DEBOUNCE_SECONDS,
            lambda _now: self._schedule_sweep(),
        )

    @callback
    def _cancel_debounce(self) -> None:
        if self._unsub_debounce is not None:
            self._unsub_debounce()
            self._unsub_debounce = None

    async def _flush_debounce(self) -> None:
        """Run a pending debounced sweep now. Test seam — production waits."""
        if self._unsub_debounce is None:
            return
        self._cancel_debounce()
        await self.reconcile()
```

Initialise in `__init__`: `self._unsubs: list = []`, `self._task: asyncio.Task | None = None`, `self._unsub_debounce = None`.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_entity_index_lifecycle.py tests/test_entity_index.py -v`
Expected: all pass.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/entity_index.py tests/test_entity_index_lifecycle.py
git commit -m "feat(entities): indexer lifecycle and registry subscriptions"
```

---

### Task 10: State tracking behind the toggle

**Files:**
- Modify: `custom_components/smartchain/tools/memory/entity_index.py`
- Test: `tests/test_entity_index_states.py`

**Interfaces:**
- Consumes: `MemoryStore.update_metadata`.
- Produces: nothing new; `start()` gains a conditional state subscription.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entity_index_states.py`:

```python
"""State tracking must cost embeddings nothing at all."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.config import EntitySourceConfig
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str) -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name="Name",
        area="",
        device="",
        device_class="",
        aliases=(),
    )


def _make(hass: HomeAssistant, *, index_states: bool):
    store = MagicMock()
    store.is_available = True
    store.add = AsyncMock(return_value=["id"])
    store.list_metadata = AsyncMock(return_value={})
    store.update_metadata = AsyncMock(return_value=True)
    store.delete_where = AsyncMock(return_value=0)
    indexer = EntityIndexer(hass, store, EntitySourceConfig(index_states=index_states))
    patcher = patch(
        "custom_components.smartchain.tools.memory.entity_index.resolve_candidates",
        return_value={"light.a": _cand("light.a")},
    )
    patcher.start()
    return indexer, store, patcher


async def test_toggle_off_registers_no_state_listener(hass: HomeAssistant) -> None:
    indexer, _, patcher = _make(hass, index_states=False)
    with patch(
        "custom_components.smartchain.tools.memory.entity_index."
        "async_track_state_change_event"
    ) as track:
        indexer.start()
        await hass.async_block_till_done()
    assert track.call_count == 0
    await indexer.stop()
    patcher.stop()


async def test_toggle_on_tracks_only_the_candidate_set(hass: HomeAssistant) -> None:
    indexer, _, patcher = _make(hass, index_states=True)
    with patch(
        "custom_components.smartchain.tools.memory.entity_index."
        "async_track_state_change_event"
    ) as track:
        indexer.start()
        await hass.async_block_till_done()
    assert track.call_count == 1
    assert list(track.call_args.args[1]) == ["light.a"]
    await indexer.stop()
    patcher.stop()


async def test_flush_coalesces_and_never_embeds(hass: HomeAssistant) -> None:
    """Three events for one entity produce one metadata write and zero adds."""
    indexer, store, patcher = _make(hass, index_states=True)
    indexer.start()
    await hass.async_block_till_done()
    store.add.reset_mock()

    for value in ("on", "off", "on"):
        hass.states.async_set("light.a", value, {})
        await hass.async_block_till_done()

    await indexer._flush_states()

    assert store.update_metadata.await_count == 1
    assert store.update_metadata.await_args.args[0] == "entity:light.a"
    assert store.update_metadata.await_args.args[1]["state"] == "on"
    assert store.add.await_count == 0
    await indexer.stop()
    patcher.stop()


async def test_flush_with_nothing_pending_is_a_noop(hass: HomeAssistant) -> None:
    indexer, store, patcher = _make(hass, index_states=True)
    indexer.start()
    await hass.async_block_till_done()

    await indexer._flush_states()

    assert store.update_metadata.await_count == 0
    await indexer.stop()
    patcher.stop()


async def test_a_failing_flush_does_not_raise(hass: HomeAssistant, caplog) -> None:
    indexer, store, patcher = _make(hass, index_states=True)
    store.update_metadata = AsyncMock(side_effect=RuntimeError("boom"))
    indexer.start()
    await hass.async_block_till_done()
    hass.states.async_set("light.a", "on", {})
    await hass.async_block_till_done()

    await indexer._flush_states()

    await indexer.stop()
    patcher.stop()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_entity_index_states.py -v`
Expected: `AttributeError` on `_flush_states`.

- [ ] **Step 3: Implement state tracking**

Add the imports:

```python
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.util import dt as dt_util
from datetime import timedelta

from ...const import ENTITY_STATE_FLUSH_SECONDS
```

and, inside `start()`, after the registry subscriptions:

```python
        if self.config.index_states:
            tracked = list(resolve_candidates(self.hass, self.config))
            if tracked:
                self._unsubs.append(
                    async_track_state_change_event(self.hass, tracked, self._on_state)
                )
            self._unsubs.append(
                async_track_time_interval(
                    self.hass,
                    self._on_flush_interval,
                    timedelta(seconds=ENTITY_STATE_FLUSH_SECONDS),
                )
            )
```

plus:

```python
    @callback
    def _on_state(self, event: Event) -> None:
        """Coalesce by entity_id — a flapping sensor must not cost a write per event."""
        new_state = event.data.get("new_state")
        if new_state is not None:
            self._pending_states[new_state.entity_id] = new_state.state

    @callback
    def _on_flush_interval(self, _now) -> None:
        self.hass.async_create_background_task(
            self._flush_states(), name="smartchain_entity_state_flush"
        )

    async def _flush_states(self) -> None:
        """Write coalesced states as metadata. Issues no embedding call at all."""
        if not self._pending_states or not self.store.is_available:
            return
        batch, self._pending_states = self._pending_states, {}

        stored = await self.store.list_metadata({"kind": "entity"})
        now = dt_util.utcnow().isoformat()
        for entity_id, state in batch.items():
            doc_id = doc_id_for(entity_id)
            metadata = stored.get(doc_id)
            if metadata is None:
                continue
            try:
                await self.store.update_metadata(
                    doc_id, {**metadata, "state": state, "state_updated": now}
                )
            except Exception:  # noqa: BLE001 — one entity must not stop the flush
                LOGGER.exception("entity state flush failed for %s", entity_id)
```

Initialise `self._pending_states: dict[str, str] = {}` in `__init__`.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_entity_index_states.py -v`
Expected: 5 passed.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/entity_index.py tests/test_entity_index_states.py
git commit -m "feat(entities): optional state tracking as metadata only"
```

---

### Task 11: Wire indexers into `MemoryRegistry` — Phase 3 checkpoint

**Files:**
- Modify: `custom_components/smartchain/tools/memory/registry.py`
- Test: `tests/test_memory_registry.py`

**Interfaces:**
- Produces: `MemoryRegistry.indexers: dict[str, EntityIndexer]`, `entity_store_names() -> list[str]` and `indexer_for(name) -> EntityIndexer | None`. Tasks 12 and 13 consume all three.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_memory_registry.py`:

```python
async def test_an_entity_source_gets_an_indexer_not_ingest_plumbing(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    with patch(
        "custom_components.smartchain.tools.memory.registry.EntityIndexer"
    ) as indexer_cls:
        await registry.build(
            MemorySettings(
                stores=[
                    StoreConfig(name="entities", embeddings="E",
                                source=EntitySourceConfig()),
                    StoreConfig(name="talk", embeddings="E"),
                ]
            ),
            tmp_path,
        )

    assert registry.entity_store_names() == ["entities"]
    assert registry.indexer_for("entities") is not None
    assert registry.indexer_for("talk") is None
    indexer_cls.return_value.start.assert_called_once()
    await registry.shutdown()


async def test_an_entity_store_is_excluded_from_conversation_ingest(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    """Even if the flag defaulted true, an entity store must never take turns."""
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    with patch("custom_components.smartchain.tools.memory.registry.EntityIndexer"):
        await registry.build(
            MemorySettings(
                stores=[
                    StoreConfig(name="entities", embeddings="E",
                                source=EntitySourceConfig()),
                    StoreConfig(name="talk", embeddings="E"),
                ]
            ),
            tmp_path,
        )

    targets = registry.stores_for_conversation_ingest()
    assert targets == [registry.get("talk")]
    await registry.shutdown()


async def test_shutdown_stops_every_indexer(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    with patch(
        "custom_components.smartchain.tools.memory.registry.EntityIndexer"
    ) as indexer_cls:
        indexer_cls.return_value.stop = AsyncMock()
        await registry.build(
            MemorySettings(
                stores=[StoreConfig(name="entities", embeddings="E",
                                    source=EntitySourceConfig())]
            ),
            tmp_path,
        )
        await registry.shutdown()

    indexer_cls.return_value.stop.assert_awaited()
    assert registry.entity_store_names() == []


async def test_an_entity_store_gets_no_retention_or_poller(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    """Retention on an entity index would delete it by age."""
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    with (
        patch("custom_components.smartchain.tools.memory.registry.EntityIndexer"),
        patch("custom_components.smartchain.tools.memory.registry.RetentionTask") as ret,
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryLogbookPoller"
        ) as poll,
    ):
        await registry.build(
            MemorySettings(
                stores=[StoreConfig(name="entities", embeddings="E",
                                    source=EntitySourceConfig())]
            ),
            tmp_path,
        )

    assert ret.call_count == 0
    assert poll.call_count == 0
    await registry.shutdown()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_memory_registry.py -v`
Expected: `AttributeError` on `entity_store_names`.

- [ ] **Step 3: Attach indexers in `build()`**

Import `EntityIndexer` in `registry.py`, add `self.indexers: dict[str, EntityIndexer] = {}` to `__init__`, and replace the tail of the per-store loop — the part that currently constructs `RetentionTask` and `MemoryLogbookPoller` — with a branch:

```python
            self.stores[config.name] = store
            self._configs[config.name] = config

            if config.source is not None:
                # An entity index has no conversation turns to retain and no
                # logbook to poll; retention in particular would delete the
                # index by age.
                indexer = EntityIndexer(self.hass, store, config.source)
                indexer.start()
                self.indexers[config.name] = indexer
                LOGGER.info(
                    "Entity index %r ready on backend %s (preset %s, states %s)",
                    config.name,
                    backend.name,
                    config.source.preset,
                    "on" if config.source.index_states else "off",
                )
                continue

            retention = RetentionTask(self.hass, store, config.retention_days)
            ...
```

Extend `shutdown()` to stop indexers before the retention tasks, and to clear `self.indexers`.

Narrow `stores_for_conversation_ingest` so a source-bearing store can never be a target regardless of its flag:

```python
    def stores_for_conversation_ingest(self) -> list[MemoryStore]:
        return [
            store
            for name, store in self.stores.items()
            if self._configs[name].source is None
            and self._configs[name].ingest_conversation
        ]
```

Add the two lookups:

```python
    def entity_store_names(self) -> list[str]:
        return list(self.indexers)

    def indexer_for(self, name: str) -> EntityIndexer | None:
        return self.indexers.get(name)
```

- [ ] **Step 4: Full suite and commit — Phase 3 checkpoint**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .
uv run --prerelease=allow pytest tests/ -q
```
Expected: fully green, zero skips.

```bash
git add custom_components/smartchain/tools/memory/registry.py tests/test_memory_registry.py
git commit -m "feat(entities): registry owns entity indexers

Phase 3 checkpoint: entity stores are built, indexed and torn down
alongside conversation stores, but nothing reads them yet."
```

---

# Phase 4 — Surface

### Task 12: `search_entities`

**Files:**
- Create: `custom_components/smartchain/tools/memory/entity_tool.py`
- Modify: `custom_components/smartchain/conversation.py`
- Test: `tests/test_entity_tool.py`

**Interfaces:**
- Consumes: `MemoryRegistry.entity_store_names` / `indexer_for` / `get`, `resolve_candidates`.
- Produces: `get_entity_tool_definition(registry) -> dict` and `execute_entity_search(hass, query, top_k, domain, area, state, store) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entity_tool.py`:

```python
"""Lexical and vector matching, merged; the tool must survive a dead store."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import DOMAIN, ENTITY_TOOL_NAME
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.entity_tool import (
    execute_entity_search,
    get_entity_tool_definition,
)
from custom_components.smartchain.tools.memory.store import MemorySnippet

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str, name: str, area: str = "Кухня", aliases=()) -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        area=area,
        device="",
        device_class="",
        aliases=tuple(aliases),
    )


def _registry(hass, candidates, *, hits=None, store_available=True):
    store = MagicMock()
    store.is_available = store_available
    store.search = AsyncMock(return_value=hits or [])

    indexer = MagicMock()
    indexer.config = MagicMock(index_states=False)

    reg = MagicMock()
    reg.entity_store_names.return_value = ["entities"]
    reg.indexer_for.side_effect = lambda n: indexer if n == "entities" else None
    reg.get.side_effect = lambda n: store if n in ("entities", None) else None
    hass.data.setdefault(DOMAIN, {})["memory"] = reg

    patcher = patch(
        "custom_components.smartchain.tools.memory.entity_tool.resolve_candidates",
        return_value={c.entity_id: c for c in candidates},
    )
    patcher.start()
    return reg, store, patcher


def test_definition_names_the_tool_and_requires_a_query() -> None:
    reg = MagicMock()
    reg.entity_store_names.return_value = ["entities"]
    spec = get_entity_tool_definition(reg)
    assert spec["name"] == ENTITY_TOOL_NAME
    assert spec["parameters"]["required"] == ["query"]
    assert "store" not in spec["parameters"].get("required", [])


def test_definition_requires_store_with_two_entity_stores() -> None:
    reg = MagicMock()
    reg.entity_store_names.return_value = ["a", "b"]
    spec = get_entity_tool_definition(reg)
    assert spec["parameters"]["properties"]["store"]["enum"] == ["a", "b"]
    assert "store" in spec["parameters"]["required"]


async def test_lexical_match_finds_by_name(hass: HomeAssistant) -> None:
    hass.states.async_set("light.ceiling", "on", {})
    _, _, patcher = _registry(hass, [_cand("light.ceiling", "Потолочный свет")])

    result = await execute_entity_search(hass, query="потолочный")

    assert "light.ceiling" in result
    patcher.stop()


async def test_lexical_match_finds_by_alias(hass: HomeAssistant) -> None:
    hass.states.async_set("light.ceiling", "on", {})
    _, _, patcher = _registry(
        hass, [_cand("light.ceiling", "Потолок", aliases=("люстра",))]
    )

    assert "light.ceiling" in await execute_entity_search(hass, query="люстра")
    patcher.stop()


async def test_exact_lexical_outranks_a_better_vector_hit(hass: HomeAssistant) -> None:
    """The whole reason lexical stays in the loop."""
    hass.states.async_set("light.ceiling", "on", {})
    hass.states.async_set("switch.socket", "off", {})
    hit = MemorySnippet(
        text="switch.socket — Кофеварка",
        score=0.99,
        metadata={"kind": "entity", "entity_id": "switch.socket"},
    )
    _, _, patcher = _registry(
        hass,
        [_cand("light.ceiling", "Кофеварка"), _cand("switch.socket", "Розетка")],
        hits=[hit],
    )

    result = await execute_entity_search(hass, query="Кофеварка")

    assert result.index("light.ceiling") < result.index("switch.socket")
    patcher.stop()


async def test_results_are_deduplicated_by_entity_id(hass: HomeAssistant) -> None:
    hass.states.async_set("light.ceiling", "on", {})
    hit = MemorySnippet(
        text="…", score=0.9, metadata={"kind": "entity", "entity_id": "light.ceiling"}
    )
    _, _, patcher = _registry(hass, [_cand("light.ceiling", "Потолок")], hits=[hit])

    result = await execute_entity_search(hass, query="потолок")

    assert result.count("light.ceiling") == 1
    patcher.stop()


async def test_state_comes_from_hass_not_from_stale_metadata(hass: HomeAssistant) -> None:
    hass.states.async_set("light.ceiling", "off", {})
    hit = MemorySnippet(
        text="…",
        score=0.9,
        metadata={"kind": "entity", "entity_id": "light.ceiling", "state": "on"},
    )
    _, _, patcher = _registry(hass, [_cand("light.ceiling", "Потолок")], hits=[hit])

    result = await execute_entity_search(hass, query="потолок")

    assert "= off" in result
    patcher.stop()


async def test_it_still_works_with_the_store_unavailable(hass: HomeAssistant) -> None:
    """No indexer ever ran; resolve_candidates is what saves the fallback."""
    hass.states.async_set("light.ceiling", "on", {})
    _, store, patcher = _registry(
        hass, [_cand("light.ceiling", "Потолок")], store_available=False
    )

    result = await execute_entity_search(hass, query="потолок")

    assert "light.ceiling" in result
    assert store.search.await_count == 0
    patcher.stop()


async def test_domain_and_area_filter_the_result(hass: HomeAssistant) -> None:
    hass.states.async_set("light.ceiling", "on", {})
    hass.states.async_set("switch.socket", "on", {})
    _, _, patcher = _registry(
        hass,
        [_cand("light.ceiling", "Свет"), _cand("switch.socket", "Свет", area="Спальня")],
    )

    result = await execute_entity_search(hass, query="свет", domain="light")
    assert "switch.socket" not in result

    result = await execute_entity_search(hass, query="свет", area="Спальня")
    assert "light.ceiling" not in result
    patcher.stop()


async def test_state_filter_works_without_index_states(hass: HomeAssistant) -> None:
    """Applied after enrichment rather than as a metadata filter — not an error."""
    hass.states.async_set("cover.a", "open", {})
    hass.states.async_set("cover.b", "closed", {})
    _, _, patcher = _registry(hass, [_cand("cover.a", "Штора A"), _cand("cover.b", "Штора B")])

    result = await execute_entity_search(hass, query="штора", state="open")

    assert "cover.a" in result
    assert "cover.b" not in result
    patcher.stop()


async def test_no_match_names_the_filters(hass: HomeAssistant) -> None:
    _, _, patcher = _registry(hass, [])
    result = await execute_entity_search(hass, query="ничего", domain="light")
    assert "light" in result
    patcher.stop()


async def test_unknown_store_is_reported_back(hass: HomeAssistant) -> None:
    _, _, patcher = _registry(hass, [])
    result = await execute_entity_search(hass, query="x", store="ghost")
    assert "ghost" in result
    assert "entities" in result
    patcher.stop()


async def test_no_entity_store_configured(hass: HomeAssistant) -> None:
    reg = MagicMock()
    reg.entity_store_names.return_value = []
    hass.data.setdefault(DOMAIN, {})["memory"] = reg
    result = await execute_entity_search(hass, query="x")
    assert "not configured" in result.lower()


async def test_failures_return_a_fixed_string(hass: HomeAssistant) -> None:
    _, store, patcher = _registry(hass, [_cand("light.a", "A")])
    store.search = AsyncMock(side_effect=RuntimeError("boom"))

    result = await execute_entity_search(hass, query="a")

    assert "boom" not in result
    patcher.stop()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_entity_tool.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `entity_tool.py`**

Create `custom_components/smartchain/tools/memory/entity_tool.py`:

```python
"""`search_entities` — find a device by describing it.

Lexical matching runs first and outranks vector hits, because on the most
common query ("свет на кухне") a name match is both faster and more accurate
than cosine similarity. The vector pass earns its keep on the semantic tail.
"""

import logging
import unicodedata
from typing import Any

from homeassistant.core import HomeAssistant

from ...const import (
    DOMAIN,
    ENTITY_LEXICAL_CANDIDATES,
    ENTITY_SEARCH_DEFAULT_TOP_K,
    ENTITY_SEARCH_MAX_TOP_K,
    ENTITY_TOOL_NAME,
)
from .entity_filter import EntityCandidate, resolve_candidates

LOGGER = logging.getLogger(__name__)

_EXACT, _PREFIX, _VECTOR = 0, 1, 2


def _fold(text: str) -> str:
    """Case- and accent-insensitive comparison key."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def get_entity_tool_definition(registry: Any) -> dict[str, Any]:
    names = registry.entity_store_names()
    properties: dict[str, Any] = {
        "query": {"type": "string", "description": "What the device is or does."},
        "top_k": {
            "type": "integer",
            "default": ENTITY_SEARCH_DEFAULT_TOP_K,
            "minimum": 1,
            "maximum": ENTITY_SEARCH_MAX_TOP_K,
        },
        "domain": {"type": "string", "description": "Restrict to one domain, e.g. light."},
        "area": {"type": "string", "description": "Restrict to one area by name."},
        "state": {"type": "string", "description": "Restrict to a current state, e.g. on."},
    }
    required = ["query"]
    if names:
        properties["store"] = {
            "type": "string",
            "enum": names,
            "description": "Which entity index to search.",
        }
        if len(names) > 1:
            required.append("store")

    return {
        "name": ENTITY_TOOL_NAME,
        "description": (
            "Find Home Assistant entities by describing them, when the exact "
            "entity_id is unknown. Returns entity_ids that can be used directly "
            "in service calls."
        ),
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


def _lexical(
    candidates: dict[str, EntityCandidate], query: str
) -> list[tuple[int, float, EntityCandidate]]:
    needle = _fold(query)
    if not needle:
        return []
    ranked: list[tuple[int, float, EntityCandidate]] = []
    for cand in candidates.values():
        haystacks = [cand.name, cand.entity_id, cand.area, *cand.aliases]
        folded = [_fold(h) for h in haystacks if h]
        if any(h == needle for h in folded):
            ranked.append((_EXACT, 1.0, cand))
        elif any(h.startswith(needle) or needle in h for h in folded):
            ranked.append((_PREFIX, 0.5, cand))
        if len(ranked) >= ENTITY_LEXICAL_CANDIDATES:
            break
    return ranked


async def execute_entity_search(
    hass: HomeAssistant,
    query: str,
    top_k: int = ENTITY_SEARCH_DEFAULT_TOP_K,
    domain: str | None = None,
    area: str | None = None,
    state: str | None = None,
    store: str | None = None,
) -> str:
    registry = (hass.data.get(DOMAIN) or {}).get("memory")
    names = registry.entity_store_names() if registry is not None else []
    if not names:
        return "No entity index is configured for this installation."

    if store is not None and store not in names:
        return f"Unknown entity index {store!r}. Configured: {', '.join(names)}."
    target_name = store or (names[0] if len(names) == 1 else None)
    if target_name is None:
        return f"Several entity indexes exist — pass `store`. Available: {', '.join(names)}."

    indexer = registry.indexer_for(target_name)
    candidates = resolve_candidates(hass, indexer.config)

    ranked = _lexical(candidates, query)
    seen = {cand.entity_id for _tier, _score, cand in ranked}

    target = registry.get(target_name)
    if target is not None and target.is_available:
        where: dict[str, Any] = {"kind": "entity"}
        if domain:
            where["domain"] = domain
        if area:
            where["area"] = area
        if state and indexer.config.index_states:
            where["state"] = state
        try:
            for snippet in await target.search(query, top_k=top_k * 2, where=where):
                entity_id = (snippet.metadata or {}).get("entity_id", "")
                cand = candidates.get(entity_id)
                if cand is not None and entity_id not in seen:
                    ranked.append((_VECTOR, snippet.score, cand))
                    seen.add(entity_id)
        except Exception:
            LOGGER.exception("entity search failed")
            return "Entity lookup failed; see logs."

    ranked.sort(key=lambda item: (item[0], -item[1]))

    lines: list[str] = []
    for _tier, _score, cand in ranked:
        if domain and cand.domain != domain:
            continue
        if area and cand.area != area:
            continue
        live = hass.states.get(cand.entity_id)
        current = live.state if live else "unavailable"
        if state and current != state:
            continue
        lines.append(
            f"{len(lines) + 1}. {cand.entity_id} — {cand.name} "
            f"[{cand.domain}, {cand.area or '—'}] = {current}"
        )
        if len(lines) >= top_k:
            break

    if not lines:
        applied = [f"{k}={v!r}" for k, v in
                   (("domain", domain), ("area", area), ("state", state)) if v]
        suffix = f" Filters applied: {', '.join(applied)}." if applied else ""
        return f"No entities matched the query.{suffix}"

    return f"Found {len(lines)} entities:\n" + "\n".join(lines)
```

- [ ] **Step 4: Wire it into `conversation.py`**

Mirror exactly how `search_memory` is handled. Import both functions, then next to the memory-tool append:

```python
        entity_enabled = memory_registry is not None and bool(
            memory_registry.entity_store_names()
        )
        if entity_enabled:
            tools.append(get_entity_tool_definition(memory_registry))
```

add `ENTITY_TOOL_NAME` to the external-tool name set alongside `MEMORY_TOOL_NAME`, and add a dispatch branch beside the memory one:

```python
                            result_text = await execute_entity_search(
                                self.hass,
                                query=args.get("query", ""),
                                top_k=int(args.get("top_k", ENTITY_SEARCH_DEFAULT_TOP_K)),
                                domain=args.get("domain"),
                                area=args.get("area"),
                                state=args.get("state"),
                                store=args.get("store"),
                            )
```

- [ ] **Step 5: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_entity_tool.py tests/test_conversation.py -v`
Expected: all pass.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/entity_tool.py custom_components/smartchain/conversation.py tests/test_entity_tool.py
git commit -m "feat(entities): search_entities merging lexical and vector matching"
```

---

### Task 13: `smartchain.reindex_entities`

**Files:**
- Modify: `custom_components/smartchain/__init__.py`
- Modify: `custom_components/smartchain/services.yaml`
- Test: `tests/test_entity_reindex_service.py`

**Interfaces:**
- Consumes: `MemoryRegistry.entity_store_names` / `indexer_for`.
- Produces: the service and the `smartchain_entities_reindexed` event.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_entity_reindex_service.py`:

```python
"""Forcing a sweep, and failing loudly when asked to sweep nothing."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.smartchain import async_setup
from custom_components.smartchain.const import (
    DOMAIN,
    EVENT_ENTITIES_REINDEXED,
    SERVICE_REINDEX_ENTITIES,
)
from custom_components.smartchain.tools.memory.entity_index import SweepResult

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _registry(hass: HomeAssistant, names: list[str]) -> dict[str, MagicMock]:
    indexers = {}
    for name in names:
        indexer = MagicMock()
        indexer.reconcile = AsyncMock(
            return_value=SweepResult(new=1, changed=2, removed=3, unchanged=4)
        )
        indexers[name] = indexer

    reg = MagicMock()
    reg.entity_store_names.return_value = names
    reg.indexer_for.side_effect = indexers.get
    hass.data.setdefault(DOMAIN, {})["memory"] = reg
    return indexers


async def test_reindex_sweeps_every_store_by_default(
    hass: HomeAssistant, tools_dir
) -> None:
    await async_setup(hass, {})
    indexers = _registry(hass, ["entities", "rooms"])

    events: list = []
    hass.bus.async_listen(EVENT_ENTITIES_REINDEXED, lambda e: events.append(e))

    await hass.services.async_call(DOMAIN, SERVICE_REINDEX_ENTITIES, {}, blocking=True)
    await hass.async_block_till_done()

    assert all(i.reconcile.await_count == 1 for i in indexers.values())
    assert sorted(events[0].data["stores"]) == ["entities", "rooms"]
    assert events[0].data["new"] == 2
    assert events[0].data["unchanged"] == 8


async def test_reindex_targets_one_store(hass: HomeAssistant, tools_dir) -> None:
    await async_setup(hass, {})
    indexers = _registry(hass, ["entities", "rooms"])

    await hass.services.async_call(
        DOMAIN, SERVICE_REINDEX_ENTITIES, {"store": "entities"}, blocking=True
    )
    await hass.async_block_till_done()

    assert indexers["entities"].reconcile.await_count == 1
    assert indexers["rooms"].reconcile.await_count == 0


async def test_full_is_passed_through(hass: HomeAssistant, tools_dir) -> None:
    await async_setup(hass, {})
    indexers = _registry(hass, ["entities"])

    await hass.services.async_call(
        DOMAIN, SERVICE_REINDEX_ENTITIES, {"full": True}, blocking=True
    )
    await hass.async_block_till_done()

    assert indexers["entities"].reconcile.await_args.kwargs["full"] is True


async def test_unknown_store_raises_and_names_the_real_ones(
    hass: HomeAssistant, tools_dir
) -> None:
    await async_setup(hass, {})
    _registry(hass, ["entities"])

    with pytest.raises(HomeAssistantError, match="entities"):
        await hass.services.async_call(
            DOMAIN, SERVICE_REINDEX_ENTITIES, {"store": "ghost"}, blocking=True
        )


async def test_no_entity_store_raises(hass: HomeAssistant, tools_dir) -> None:
    await async_setup(hass, {})
    _registry(hass, [])

    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, SERVICE_REINDEX_ENTITIES, {}, blocking=True
        )
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --prerelease=allow pytest tests/test_entity_reindex_service.py -v`
Expected: the service is not registered.

- [ ] **Step 3: Register the service**

In `async_setup`, beside `_handle_clear_memory`:

```python
    async def _handle_reindex_entities(call: ServiceCall) -> None:
        registry = hass.data.get(DOMAIN, {}).get("memory")
        names = registry.entity_store_names() if registry is not None else []
        if not names:
            raise HomeAssistantError("no entity index is configured")

        requested = call.data.get("store")
        if requested is not None and requested not in names:
            raise HomeAssistantError(
                f"unknown entity index {requested!r}; configured: {names}"
            )
        targets = [requested] if requested else names
        full = bool(call.data.get("full", False))

        totals = {"new": 0, "changed": 0, "removed": 0, "unchanged": 0}
        for name in targets:
            indexer = registry.indexer_for(name)
            if indexer is None:
                continue
            result = await indexer.reconcile(full=full)
            for key in totals:
                totals[key] += getattr(result, key)

        hass.bus.async_fire(EVENT_ENTITIES_REINDEXED, {"stores": targets, **totals})
```

registered with:

```python
    hass.services.async_register(
        DOMAIN,
        SERVICE_REINDEX_ENTITIES,
        _handle_reindex_entities,
        schema=vol.Schema(
            {vol.Optional("store"): str, vol.Optional("full", default=False): bool}
        ),
    )
```

- [ ] **Step 4: Declare it in `services.yaml`**

Follow the structure of the `clear_memory` entry added earlier in this release:

```yaml
reindex_entities:
  name: Reindex entities
  description: >-
    Rebuild an entity index from the current registries. Only entities whose
    catalogue text changed are re-embedded, so this is cheap to call.
  fields:
    store:
      name: Store
      description: Which entity index to sweep. Omit to sweep all of them.
      required: false
      selector:
        text:
    full:
      name: Full
      description: >-
        Re-embed every entity even if nothing changed. Needed only after
        switching to a different embedding model.
      required: false
      default: false
      selector:
        boolean:
```

- [ ] **Step 5: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_entity_reindex_service.py tests/test_memory_clear_service.py -v`
Expected: all pass.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/__init__.py custom_components/smartchain/services.yaml tests/test_entity_reindex_service.py
git commit -m "feat(entities): reindex_entities service"
```

---

### Task 14: Documentation and CHANGELOG

**Files:**
- Modify: `docs/USAGE.md`, `docs/USAGE-ru.md`
- Modify: `README.md`, `README-ru.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything.

- [ ] **Step 1: Add §9.10 "Индекс сущностей" to both guides**

A new subsection at the end of §9, covering, in this order:

1. What it is for, with the two worked examples that motivate it: "что варит кофе" and "чем посушить волосы".
2. The YAML, byte-identical between the English and Russian guides:

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
```

3. A preset table with the exact membership from §4.3 of the spec, stating that
   `paranoid` includes hidden and disabled entities and that disabled entities
   contribute a catalogue entry only, because they have no state.
4. `include` / `exclude`, noting that `exclude` wins.
5. The keys that are **rejected** on an entity store — `retention_days`,
   `ingest_conversation`, `ingest_logbook` — and why.
6. `index_states`: what it buys (filtering, `state: open`), what it does not
   (semantic search over state strings is weak), and that states shown by the
   tool are read live either way, so leaving it off costs nothing in freshness.
7. `search_entities` with its parameters and a sample result block.
8. `smartchain.reindex_entities`, including when `full: true` is the answer.
9. Cost: the first sweep embeds every selected entity once; later sweeps embed
   only what changed, so restarts are free. Name the count a typical home
   produces so a paid-provider user can estimate.
10. **Privacy** — a short, direct paragraph: entity names, areas and aliases go
    to the embeddings provider; `optimal` includes `person` and
    `device_tracker`; `paranoid` sends the whole home including diagnostics.
    Point at `minimal` plus `include` for anyone who wants to keep it tight.

Russian must be orthographically correct with every `ё` present.

- [ ] **Step 2: Update the README feature lists**

In both READMEs, extend the memory bullet to mention entity indexing and
`search_entities`, and update the v5.0.0 row of the "What's new" table to name
it alongside the vector backends.

- [ ] **Step 3: Extend the unreleased CHANGELOG entry**

Add to the existing `## [5.0.0] - unreleased` **Added** section:

```markdown
- **Entity indexing.** A memory store can carry `source: {type: entities}` and
  becomes a semantic index of the home, with four scope presets
  (`minimal` / `optimal` / `maximal` / `paranoid`), `include` / `exclude`
  overrides, and an optional state-tracking mode. The new `search_entities`
  tool merges lexical and vector matching, so it stays useful when the
  embeddings provider is unavailable. Sweeps are incremental — only entities
  whose catalogue text changed are re-embedded, so a restart costs nothing.
- `smartchain.reindex_entities` forces a sweep; `full: true` re-embeds
  everything, for when the embedding model changed but the entities did not.
```

and to **Changed**:

```markdown
- `VectorBackend` gained `update_metadata` and `list_metadata`, letting a
  document's metadata be refreshed without re-embedding it.
```

- [ ] **Step 4: Final smoke**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .
uv run --prerelease=allow pytest tests/ -q
```
Expected: fully green, zero skips. Confirm the version is still `5.0.0` in both
manifests and that `manifest.json` requirements are unchanged from the start of
this plan.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: entity indexing in both guides, READMEs and the changelog"
```

---

## Out of scope (deferred)

- Replacing `DEFAULT_DEVICES_PROMPT` with retrieved context — subsystem **C**.
- Area and device documents in their own right, so "что есть в гостиной"
  resolves without enumerating entities.
- Automatic re-embedding when a store's embeddings subentry changes model —
  `reindex_entities` with `full: true` is the manual answer for now.
- Source types other than `entities`; the `source.type` enum exists so adding
  one later is not a breaking change.
- Fuzzy lexical matching (edit distance). The current pass is exact, prefix and
  substring only.
