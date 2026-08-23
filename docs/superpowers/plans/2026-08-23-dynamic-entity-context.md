# Dynamic Entity Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the full devices dump in the system prompt with a compact always-present skeleton of what exists, plus a per-turn retrieval of what the message is about.

**Architecture:** A new `entity_context.py` builds two plain-text blocks. The skeleton comes from `resolve_candidates` — subsystem B's scoping — cached and invalidated by registry events. The retrieved block reuses subsystem B's ranking, extracted into a shared `rank_entities`. `conversation.py` composes user prompt (Jinja, cached) + skeleton + retrieval instead of running Jinja over the whole thing.

**Tech Stack:** Home Assistant registries and state machine, the existing entity index, voluptuous, stdlib. No new dependency.

**Spec:** `docs/superpowers/specs/2026-08-23-dynamic-entity-context-design.md`

## Global Constraints

- **No new dependency.** `manifest.json` requirements must be byte-identical at the end of this plan.
- **Do not touch the `version` field** in `pyproject.toml` or `manifest.json`. It is already `5.0.0` and this subsystem ships inside that release. This overrides any global convention about bumping the version per commit.
- **Turning `dynamic_entity_context` off must reproduce today's behaviour exactly** — the same prompt, byte for byte.
- Credentials never reach a log line, an exception message or a prompt.
- Nothing in this subsystem may raise into `_async_handle_message`. The failure layering in §11 of the spec is a hard requirement, not an aspiration.
- `requires-python >= 3.13`; Home Assistant 2024.12.0+.
- ruff `line-length = 100`, `select = ["E", "F", "W", "I", "UP"]`. `const.py` has a per-file `E501` ignore.
- Test runner `uv run --prerelease=allow pytest tests/ -q`; lint `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .`.
- Baseline at plan start: **598 passed, 0 skipped**.

## Standing cautions, learned in the two preceding plans

These cost eight fix rounds between them. Every task in this plan inherits them:

1. **A brief may name a helper that does not exist.** Read the file before relying on any name. Three briefs in the entity-indexing plan named fixtures that were not there, and one named a `MemoryStore.delete_where` that has never existed — it survived nine green tests because a bare `MagicMock` answers to any attribute.
2. **Build test doubles with a spec** (`MagicMock(spec=SomeClass)`) wherever they stand in for a real class.
3. **Anything handed to a Home Assistant scheduling or event API must be `@callback`-decorated or an `async def`.** A plain lambda is dispatched to the executor thread pool and raises `RuntimeError: loop ... is not the running loop`.
4. **A teardown or timing test that never advances the clock proves nothing.** Use `async_fire_time_changed`.
5. **Where a test guards a specific mechanism, verify it fails when that mechanism is broken.** Five tests across the last two plans passed with the logic they claimed to guard entirely removed.

## File Structure

| File | Responsibility |
|---|---|
| `const.py` | three options, three tuning constants |
| `config_flow.py` | the three fields on the conversation subentry form |
| `strings.json`, `translations/{en,ru}.json` | their labels |
| `tools/memory/entity_tool.py` | `rank_entities` extracted; `execute_entity_search` becomes its renderer |
| `tools/memory/entity_context.py` | skeleton, retrieval block, assembly, failure layering |
| `conversation.py` | prompt composition; the Assist opt-in |
| `docs/USAGE.md`, `docs/USAGE-ru.md`, `README*.md`, `CHANGELOG.md` | documentation |

---

# Phase 1 — Foundations

### Task 1: Options and constants

**Files:**
- Modify: `custom_components/smartchain/const.py`
- Modify: `custom_components/smartchain/config_flow.py`
- Modify: `custom_components/smartchain/strings.json`, `translations/en.json`, `translations/ru.json`
- Test: `tests/test_dynamic_context_options.py`

**Interfaces:**
- Produces: `CONF_DYNAMIC_ENTITY_CONTEXT`, `DEFAULT_DYNAMIC_ENTITY_CONTEXT`, `CONF_DYNAMIC_CONTEXT_PRESET`, `CONF_DYNAMIC_CONTEXT_ON_ASSIST`, `DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST`, `ENTITY_CONTEXT_MAX_ENTITIES`, `ENTITY_SKELETON_MAX_CHARS`, `ENTITY_SKELETON_CACHE_TTL`. Tasks 3–7 consume them.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dynamic_context_options.py`:

```python
"""The three dynamic-context options reach the subentry form and its data."""

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.config_flow import ConfigFlow
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_DYNAMIC_CONTEXT_ON_ASSIST,
    CONF_DYNAMIC_CONTEXT_PRESET,
    CONF_DYNAMIC_ENTITY_CONTEXT,
    CONF_ENGINE,
    DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST,
    DEFAULT_DYNAMIC_ENTITY_CONTEXT,
    DOMAIN,
    ENTITY_DEFAULT_PRESET,
    ENTITY_PRESETS,
    ID_GIGACHAT,
    SUBENTRY_TYPE_CONVERSATION,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def test_defaults_are_what_the_spec_says() -> None:
    """On by default; Assist off by default; preset matches subsystem B's."""
    assert DEFAULT_DYNAMIC_ENTITY_CONTEXT is True
    assert DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST is False
    assert ENTITY_DEFAULT_PRESET in ENTITY_PRESETS


async def test_the_three_fields_appear_on_the_conversation_form(
    hass: HomeAssistant, mock_get_client
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_CONVERSATION), context={"source": "user"}
    )

    keys = {str(k.schema) for k in result["data_schema"].schema}
    assert CONF_DYNAMIC_ENTITY_CONTEXT in keys
    assert CONF_DYNAMIC_CONTEXT_PRESET in keys
    assert CONF_DYNAMIC_CONTEXT_ON_ASSIST in keys


async def test_the_options_round_trip_into_subentry_data(
    hass: HomeAssistant, mock_get_client
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_CONVERSATION), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "model": "",
            "model_user": "",
            CONF_DYNAMIC_ENTITY_CONTEXT: False,
            CONF_DYNAMIC_CONTEXT_PRESET: "minimal",
            CONF_DYNAMIC_CONTEXT_ON_ASSIST: True,
        },
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_DYNAMIC_ENTITY_CONTEXT] is False
    assert result["data"][CONF_DYNAMIC_CONTEXT_PRESET] == "minimal"
    assert result["data"][CONF_DYNAMIC_CONTEXT_ON_ASSIST] is True
```

The `mock_get_client` fixture exists in `tests/conftest.py` and prevents the provider constructor from opening a socket — check its exact name before using it, and check what else the conversation subentry form requires as required fields; the submitted dict above may need more keys.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_dynamic_context_options.py -v`
Expected: `ImportError` for `CONF_DYNAMIC_ENTITY_CONTEXT`.

- [ ] **Step 3: Append the constants**

Append to `custom_components/smartchain/const.py`:

```python

# Dynamic entity context (v5.0.0, roadmap subsystem C)
CONF_DYNAMIC_ENTITY_CONTEXT = "dynamic_entity_context"
DEFAULT_DYNAMIC_ENTITY_CONTEXT = True
CONF_DYNAMIC_CONTEXT_PRESET = "dynamic_context_preset"
CONF_DYNAMIC_CONTEXT_ON_ASSIST = "dynamic_context_on_assist"
DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST = False

# How many entities the per-turn retrieval may add. A constant rather than an
# option: every extra option is a support surface, and if 12 proves wrong it
# should change in one place for everyone.
ENTITY_CONTEXT_MAX_ENTITIES = 12
# Generous — roughly 300-500 entities. Past this the skeleton stops being a map
# and starts being the dump it replaced.
ENTITY_SKELETON_MAX_CHARS = 6000
# Registry events are the real invalidation; this is the backstop.
ENTITY_SKELETON_CACHE_TTL = 300  # seconds
```

- [ ] **Step 4: Add the three fields to the conversation subentry form**

In `custom_components/smartchain/config_flow.py`, extend the `.const` import with the five new names plus `ENTITY_DEFAULT_PRESET` and `ENTITY_PRESETS`, keeping it alphabetically sorted. Then add to the schema built in `_subentry_schema`, immediately after the `CONF_ENABLE_HISTORY_TOOL` entry:

```python
            vol.Optional(
                CONF_DYNAMIC_ENTITY_CONTEXT,
                description={
                    "suggested_value": options.get(
                        CONF_DYNAMIC_ENTITY_CONTEXT, DEFAULT_DYNAMIC_ENTITY_CONTEXT
                    )
                },
                default=DEFAULT_DYNAMIC_ENTITY_CONTEXT,
            ): bool,
            vol.Optional(
                CONF_DYNAMIC_CONTEXT_PRESET,
                description={
                    "suggested_value": options.get(
                        CONF_DYNAMIC_CONTEXT_PRESET, ENTITY_DEFAULT_PRESET
                    )
                },
                default=ENTITY_DEFAULT_PRESET,
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    mode=SelectSelectorMode("dropdown"), options=ENTITY_PRESETS
                )
            ),
            vol.Optional(
                CONF_DYNAMIC_CONTEXT_ON_ASSIST,
                description={
                    "suggested_value": options.get(
                        CONF_DYNAMIC_CONTEXT_ON_ASSIST, DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST
                    )
                },
                default=DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST,
            ): bool,
```

`selector` and `SelectSelectorMode` are already imported in this file.

- [ ] **Step 5: Add the labels**

In `strings.json`, `translations/en.json` and `translations/ru.json`, add three keys to **both** the `user` and `reconfigure` step's `data` object under `config_subentries.conversation`. All three files must end with the same key set; only the values differ.

English:

```json
        "dynamic_entity_context": "Dynamic entity context (send a compact map of the home plus what the message is about, instead of every entity)",
        "dynamic_context_preset": "Which entities the map covers",
        "dynamic_context_on_assist": "Also add matched entities when the Assist API is enabled"
```

Russian:

```json
        "dynamic_entity_context": "Динамический контекст сущностей (отправлять компактную карту дома и то, о чём спрашивают, вместо всех сущностей)",
        "dynamic_context_preset": "Какие сущности попадают в карту",
        "dynamic_context_on_assist": "Добавлять найденные сущности и при включённом Assist API"
```

Home Assistant's hassfest validation is strict about these three files agreeing. After editing, verify programmatically that the `config_subentries.conversation` key sets are identical across all three, and report what you ran.

- [ ] **Step 6: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_dynamic_context_options.py tests/test_subentries.py tests/test_config_flow.py -v`
Expected: all pass.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/ tests/test_dynamic_context_options.py
git commit -m "feat(context): options and constants for dynamic entity context"
```

---

### Task 2: Extract `rank_entities`

**Files:**
- Modify: `custom_components/smartchain/tools/memory/entity_tool.py`
- Test: `tests/test_entity_ranking.py`

**Interfaces:**
- Produces: `rank_entities(hass, registry, candidates, query, top_k, store_name=None) -> list[EntityCandidate]`. Task 5 consumes it.
- **`execute_entity_search`'s behaviour must not change.** The existing `tests/test_entity_tool.py` is the guard and must pass **unmodified**.

- [ ] **Step 1: Write the failing test**

Create `tests/test_entity_ranking.py`:

```python
"""The shared ranking both search_entities and the prompt context use."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate
from custom_components.smartchain.tools.memory.entity_tool import rank_entities
from custom_components.smartchain.tools.memory.registry import MemoryRegistry
from custom_components.smartchain.tools.memory.store import MemorySnippet, MemoryStore

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str, name: str, area: str = "Кухня") -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        area=area,
        device="",
        device_class="",
        aliases=(),
    )


def _registry(names: list[str], hits: list[MemorySnippet] | None = None):
    store = MagicMock(spec=MemoryStore)
    store.is_available = True
    store.search = AsyncMock(return_value=hits or [])
    reg = MagicMock(spec=MemoryRegistry)
    reg.entity_store_names.return_value = names
    reg.get.return_value = store
    return reg, store


async def test_lexical_only_without_a_store(hass: HomeAssistant) -> None:
    reg, store = _registry([])
    cands = {"light.a": _cand("light.a", "Потолок")}

    ranked = await rank_entities(hass, reg, cands, "потолок", top_k=5)

    assert [c.entity_id for c in ranked] == ["light.a"]
    assert store.search.await_count == 0


async def test_exact_lexical_outranks_a_higher_scored_vector_hit(
    hass: HomeAssistant,
) -> None:
    """The ranking's whole reason for existing."""
    hit = MemorySnippet(
        text="…", score=0.99, metadata={"kind": "entity", "entity_id": "switch.b"}
    )
    reg, _ = _registry(["entities"], [hit])
    cands = {
        "light.a": _cand("light.a", "Кофеварка"),
        "switch.b": _cand("switch.b", "Розетка"),
    }

    ranked = await rank_entities(hass, reg, cands, "Кофеварка", top_k=5, store_name="entities")

    assert [c.entity_id for c in ranked] == ["light.a", "switch.b"]


async def test_a_vector_hit_outside_the_candidate_set_is_dropped(
    hass: HomeAssistant,
) -> None:
    """A stale document must not resurrect an entity that no longer exists."""
    hit = MemorySnippet(
        text="…", score=0.99, metadata={"kind": "entity", "entity_id": "light.gone"}
    )
    reg, _ = _registry(["entities"], [hit])

    ranked = await rank_entities(
        hass, reg, {"light.a": _cand("light.a", "Потолок")}, "что-нибудь",
        top_k=5, store_name="entities",
    )

    assert "light.gone" not in [c.entity_id for c in ranked]


async def test_top_k_is_respected(hass: HomeAssistant) -> None:
    reg, _ = _registry([])
    cands = {f"light.{i}": _cand(f"light.{i}", "Свет") for i in range(10)}

    assert len(await rank_entities(hass, reg, cands, "свет", top_k=3)) == 3


async def test_results_are_deduplicated(hass: HomeAssistant) -> None:
    hit = MemorySnippet(
        text="…", score=0.9, metadata={"kind": "entity", "entity_id": "light.a"}
    )
    reg, _ = _registry(["entities"], [hit])

    ranked = await rank_entities(
        hass, reg, {"light.a": _cand("light.a", "Потолок")}, "потолок",
        top_k=5, store_name="entities",
    )

    assert [c.entity_id for c in ranked] == ["light.a"]


async def test_a_failing_store_degrades_to_lexical(hass: HomeAssistant) -> None:
    reg, store = _registry(["entities"])
    store.search = AsyncMock(side_effect=RuntimeError("boom"))

    ranked = await rank_entities(
        hass, reg, {"light.a": _cand("light.a", "Потолок")}, "потолок",
        top_k=5, store_name="entities",
    )

    assert [c.entity_id for c in ranked] == ["light.a"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_entity_ranking.py -v`
Expected: `ImportError` for `rank_entities`.

- [ ] **Step 3: Extract the function**

In `entity_tool.py`, lift the lexical pass, the vector pass and the merge out of `execute_entity_search` into:

```python
async def rank_entities(
    hass: HomeAssistant,
    registry: Any,
    candidates: dict[str, EntityCandidate],
    query: str,
    top_k: int,
    store_name: str | None = None,
    where_extra: dict[str, Any] | None = None,
) -> list[EntityCandidate]:
    """Candidates ranked lexical-first, then by vector score, deduplicated.

    Lexical matching always runs; the vector pass runs only when `store_name`
    names an available store. A vector hit for an entity outside `candidates`
    is dropped — a stale document must not resurrect an entity that no longer
    exists, or that the caller's preset excludes.

    A failing store degrades to lexical rather than failing the caller: this is
    on the path that builds a system prompt, and a prompt without vector hits is
    far better than no prompt.
    """
```

Notes for the implementer:

- The existing merge sorts on `(tier, -score)` where the tiers are `_EXACT`, `_PREFIX`, `_VECTOR`. Keep that ordering exactly — `tests/test_entity_tool.py` has a test that fails if the tier leaves the sort key.
- `where_extra` carries `execute_entity_search`'s `domain` / `area` metadata filters so it can keep passing them. The context builder passes nothing.
- **The store failure must be caught inside `rank_entities`**, degrading to lexical. `execute_entity_search` currently returns a fixed failure string on a search exception; that behaviour is asserted by `test_failures_return_a_fixed_string`. Decide how to preserve both: either `rank_entities` grows a flag, or `execute_entity_search` keeps its own try/except around the call. Say which you chose and why. **Do not change what the existing test asserts.**

Then rewrite `execute_entity_search` to resolve its store, build its candidates, call `rank_entities`, apply its `domain` / `area` / `state` filters and render. Its early returns — not configured, unknown store, ambiguous store — stay exactly as they are.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_entity_ranking.py tests/test_entity_tool.py -v`
Expected: all pass, and **`tests/test_entity_tool.py` must be unmodified**. If you had to change it, the extraction changed behaviour — stop and report rather than adjusting the test.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/entity_tool.py tests/test_entity_ranking.py
git commit -m "refactor(entities): extract rank_entities for reuse by the prompt context"
```

---

# Phase 2 — The context builder

### Task 3: The skeleton renderer

**Files:**
- Create: `custom_components/smartchain/tools/memory/entity_context.py`
- Test: `tests/test_entity_skeleton.py`

**Interfaces:**
- Consumes: `EntityCandidate`, `ENTITY_SKELETON_MAX_CHARS`.
- Produces: `render_skeleton(candidates: dict[str, EntityCandidate]) -> str`. Tasks 4 and 5 consume it.

**Correction to the spec:** §6's example writes the no-area label in Russian
(`Без области`) while the same section states that the structural vocabulary
stays English, as it does in the catalogue documents. The English label wins —
otherwise the line is half-translated with no rule saying when to translate.
Use `No area`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_entity_skeleton.py`:

```python
"""The always-present map of what exists."""

from custom_components.smartchain.const import ENTITY_SKELETON_MAX_CHARS
from custom_components.smartchain.tools.memory.entity_context import render_skeleton
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate


def _cand(entity_id: str, name: str, area: str = "") -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        area=area,
        device="",
        device_class="",
        aliases=(),
    )


def _skeleton(*cands: EntityCandidate) -> str:
    return render_skeleton({c.entity_id: c for c in cands})


def test_empty_home_renders_nothing() -> None:
    assert render_skeleton({}) == ""


def test_one_area_groups_by_domain() -> None:
    text = _skeleton(
        _cand("light.a", "Потолочный", "Кухня"),
        _cand("light.b", "Подсветка", "Кухня"),
        _cand("switch.c", "Кофеварка", "Кухня"),
    )
    assert "Кухня — light: Потолочный, Подсветка; switch: Кофеварка" in text


def test_areas_are_separate_lines() -> None:
    text = _skeleton(
        _cand("light.a", "Потолочный", "Кухня"),
        _cand("light.b", "Бра", "Спальня"),
    )
    lines = [ln for ln in text.split("\n") if ln.strip()]
    assert len(lines) == 2


def test_entities_without_an_area_get_their_own_line_last() -> None:
    """An unassigned entity is exactly the kind a user forgets exists."""
    text = _skeleton(
        _cand("light.a", "Потолочный", "Кухня"),
        _cand("vacuum.v", "Пылесос"),
    )
    lines = [ln for ln in text.split("\n") if ln.strip()]
    assert lines[-1].startswith("No area —")
    assert "Пылесос" in lines[-1]


def test_no_entity_ids_or_states_appear() -> None:
    """Ids are near-useless without HA control tools; states are retrieved."""
    text = _skeleton(_cand("light.kitchen_ceiling", "Потолочный", "Кухня"))
    assert "light.kitchen_ceiling" not in text
    assert "=" not in text


def test_a_nameless_entity_falls_back_to_its_entity_id() -> None:
    text = _skeleton(_cand("light.orphan", "light.orphan", "Кухня"))
    assert "light.orphan" in text


def test_output_is_deterministic() -> None:
    cands = [
        _cand("switch.c", "Кофеварка", "Кухня"),
        _cand("light.a", "Потолочный", "Кухня"),
        _cand("light.b", "Бра", "Спальня"),
    ]
    assert _skeleton(*cands) == _skeleton(*reversed(cands))


def test_a_huge_home_is_truncated_within_the_budget() -> None:
    cands = [
        _cand(f"light.a{i}", f"Светильник номер {i}", f"Комната {i // 5}")
        for i in range(4000)
    ]
    text = _skeleton(*cands)
    assert len(text) <= ENTITY_SKELETON_MAX_CHARS


def test_truncation_says_what_it_omitted_and_points_at_the_tool() -> None:
    """Silent truncation would make the model confidently wrong about the home."""
    cands = [
        _cand(f"light.a{i}", f"Светильник номер {i}", f"Комната {i // 5}")
        for i in range(4000)
    ]
    last = _skeleton(*cands).rstrip().split("\n")[-1]
    assert "more area" in last
    assert "search_entities" in last


def test_a_home_that_fits_has_no_omission_line() -> None:
    text = _skeleton(_cand("light.a", "Потолочный", "Кухня"))
    assert "search_entities" not in text
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_entity_skeleton.py -v`
Expected: `ModuleNotFoundError` for `entity_context`.

- [ ] **Step 3: Implement the renderer**

Create `custom_components/smartchain/tools/memory/entity_context.py`:

```python
"""Builds the entity context a conversation turn puts in its system prompt.

Two blocks. The skeleton says what exists and is always complete for the
configured scope; the retrieved block says what this message is about, in
detail. Splitting them this way is what keeps the model from concluding a
device does not exist merely because the query worded it badly.
"""

import logging

from ...const import ENTITY_SKELETON_MAX_CHARS
from .entity_filter import EntityCandidate

LOGGER = logging.getLogger(__name__)

_NO_AREA = "No area"


def render_skeleton(candidates: dict[str, EntityCandidate]) -> str:
    """A compact map of the home: areas, then names grouped by domain.

    No entity ids, no device classes, no states, no device grouping. Without
    the Assist API the model has no Home Assistant control tools, so an
    entity id buys it nothing here; names, areas and — from the retrieved
    block — states are what it can actually use.
    """
    if not candidates:
        return ""

    by_area: dict[str, dict[str, list[str]]] = {}
    for cand in candidates.values():
        area = cand.area or _NO_AREA
        by_area.setdefault(area, {}).setdefault(cand.domain, []).append(
            cand.name or cand.entity_id
        )

    # Named areas alphabetically, the unassigned bucket last: it is the one a
    # user is most likely to have forgotten, so it should not be buried.
    ordered = sorted(a for a in by_area if a != _NO_AREA)
    if _NO_AREA in by_area:
        ordered.append(_NO_AREA)

    lines: list[str] = []
    budget = ENTITY_SKELETON_MAX_CHARS
    omitted_areas = 0
    omitted_entities = 0

    for area in ordered:
        domains = by_area[area]
        groups = "; ".join(
            f"{domain}: {', '.join(sorted(names))}"
            for domain, names in sorted(domains.items())
        )
        line = f"{area} — {groups}"
        # Leave room for the omission line itself.
        if len(line) + 1 > budget - 120 and lines:
            omitted_areas += 1
            omitted_entities += sum(len(n) for n in domains.values())
            continue
        lines.append(line)
        budget -= len(line) + 1

    if omitted_areas:
        lines.append(
            f"… and {omitted_areas} more area(s) holding {omitted_entities} "
            "entities — use search_entities to look any of them up."
        )
    return "\n".join(lines)
```

Note the budget arithmetic reserves room for the omission line, and that an
area is skipped rather than partially rendered — half an area reads as though
the rest of it does not exist, which is the failure this whole design avoids.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_entity_skeleton.py -v`
Expected: 10 passed.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/entity_context.py tests/test_entity_skeleton.py
git commit -m "feat(context): skeleton renderer for the home's entity map"
```

---

### Task 4: The skeleton cache

**Files:**
- Modify: `custom_components/smartchain/tools/memory/entity_context.py`
- Modify: `custom_components/smartchain/__init__.py`
- Test: `tests/test_entity_skeleton_cache.py`

**Interfaces:**
- Produces: `SkeletonCache(hass)` with `get(preset: str) -> str | None`, `invalidate() -> None`, `start() -> None` (sync) and `async stop() -> None`, stored at `hass.data[DOMAIN]["entity_skeleton"]`. Task 5 reads it from `hass.data`.

**Why this is shared and not per-agent:** every agent with the same preset wants
the same string, and the registry subscriptions should exist once regardless of
how many conversation agents are configured. `SmartChainConversationEntity` also
has no `async_added_to_hass` override today, and adding one to manage
subscriptions would mean overriding a base-class method that registers the
agent — a footgun for a cache.

- [ ] **Step 1: Write the failing test**

Create `tests/test_entity_skeleton_cache.py`:

```python
"""One cached map per preset, invalidated by the registries."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.smartchain.tools.memory.entity_context import SkeletonCache
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str) -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name="Имя",
        area="Кухня",
        device="",
        device_class="",
        aliases=(),
    )


def _patched(entity_ids: list[str]):
    return patch(
        "custom_components.smartchain.tools.memory.entity_context.resolve_candidates",
        return_value={e: _cand(e) for e in entity_ids},
    )


async def test_a_second_get_does_not_recompute(hass: HomeAssistant) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    with _patched(["light.a"]) as resolve:
        first = cache.get("optimal")
        second = cache.get("optimal")
    assert first == second
    assert resolve.call_count == 1
    await cache.stop()


async def test_different_presets_are_cached_separately(hass: HomeAssistant) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    with _patched(["light.a"]) as resolve:
        cache.get("optimal")
        cache.get("minimal")
    assert resolve.call_count == 2
    await cache.stop()


@pytest.mark.parametrize(
    "event",
    [
        er.EVENT_ENTITY_REGISTRY_UPDATED,
        dr.EVENT_DEVICE_REGISTRY_UPDATED,
        ar.EVENT_AREA_REGISTRY_UPDATED,
    ],
)
async def test_a_registry_event_invalidates(hass: HomeAssistant, event: str) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    with _patched(["light.a"]) as resolve:
        cache.get("optimal")
        hass.bus.async_fire(event, {"action": "update", "entity_id": "light.a"})
        await hass.async_block_till_done()
        cache.get("optimal")
    assert resolve.call_count == 2
    await cache.stop()


async def test_stop_unsubscribes(hass: HomeAssistant) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    with _patched(["light.a"]) as resolve:
        cache.get("optimal")
        await cache.stop()
        hass.bus.async_fire(
            er.EVENT_ENTITY_REGISTRY_UPDATED, {"action": "update", "entity_id": "light.a"}
        )
        await hass.async_block_till_done()
        cache.get("optimal")
    assert resolve.call_count == 1


async def test_start_is_idempotent(hass: HomeAssistant) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    cache.start()
    with _patched(["light.a"]) as resolve:
        cache.get("optimal")
        hass.bus.async_fire(
            er.EVENT_ENTITY_REGISTRY_UPDATED, {"action": "update", "entity_id": "light.a"}
        )
        await hass.async_block_till_done()
        cache.get("optimal")
    # One invalidation, not two — a doubled subscription would still give 2
    # here, so also assert the subscription count directly.
    assert resolve.call_count == 2
    assert len(cache._unsubs) == 3
    await cache.stop()


async def test_a_resolve_failure_returns_none_not_an_empty_map(
    hass: HomeAssistant, caplog
) -> None:
    """None means "could not build" so the caller can fall back to the dump.

    An empty string would be indistinguishable from a genuinely empty home,
    and the spec's failure layering turns on exactly that distinction.
    """
    cache = SkeletonCache(hass)
    cache.start()
    with patch(
        "custom_components.smartchain.tools.memory.entity_context.resolve_candidates",
        side_effect=RuntimeError("boom"),
    ):
        assert cache.get("optimal") is None
    await cache.stop()


async def test_a_genuinely_empty_home_returns_an_empty_string(hass: HomeAssistant) -> None:
    cache = SkeletonCache(hass)
    cache.start()
    with patch(
        "custom_components.smartchain.tools.memory.entity_context.resolve_candidates",
        return_value={},
    ):
        assert cache.get("optimal") == ""
    await cache.stop()


async def test_a_failure_is_not_cached(hass: HomeAssistant) -> None:
    """A transient registry error must not blind the agent for five minutes."""
    cache = SkeletonCache(hass)
    cache.start()
    with patch(
        "custom_components.smartchain.tools.memory.entity_context.resolve_candidates",
        side_effect=RuntimeError("boom"),
    ):
        cache.get("optimal")
    with _patched(["light.a"]) as resolve:
        assert cache.get("optimal") != ""
    assert resolve.call_count == 1
    await cache.stop()
```

The TTL is deliberately not tested here — registry events are the real
mechanism and the TTL is a backstop. If you add a TTL test, it must advance the
clock with `async_fire_time_changed`; a timing test that never advances the
clock proves nothing.

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_entity_skeleton_cache.py -v`
Expected: `ImportError` for `SkeletonCache`.

- [ ] **Step 3: Implement the cache**

Append to `entity_context.py`, extending its imports with `time`, `Any`,
`HomeAssistant`, `callback`, `Event`, the three registries, `EntitySourceConfig`,
`resolve_candidates` and `ENTITY_SKELETON_CACHE_TTL`:

```python
class SkeletonCache:
    """One rendered map per preset, shared by every conversation agent.

    Registry events are the real invalidation; the TTL is a backstop for a
    change that somehow raises none.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._cache: dict[str, tuple[str, float]] = {}
        self._unsubs: list[Any] = []

    def start(self) -> None:
        if self._unsubs:
            return
        for event in (
            er.EVENT_ENTITY_REGISTRY_UPDATED,
            dr.EVENT_DEVICE_REGISTRY_UPDATED,
            ar.EVENT_AREA_REGISTRY_UPDATED,
        ):
            self._unsubs.append(self.hass.bus.async_listen(event, self._on_registry))

    async def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self._cache.clear()

    @callback
    def _on_registry(self, _event: Event) -> None:
        self.invalidate()

    @callback
    def invalidate(self) -> None:
        self._cache.clear()

    def get(self, preset: str) -> str | None:
        """The map for `preset`, or None if it could not be built.

        The tri-state matters: "" is a genuinely empty home, None is a
        failure, and the caller falls back to the full devices dump only for
        the second. A failure is never cached — a transient registry error
        must not blind the agent for the whole TTL.
        """
        now = time.monotonic()
        cached = self._cache.get(preset)
        if cached is not None and (now - cached[1]) < ENTITY_SKELETON_CACHE_TTL:
            return cached[0]

        try:
            candidates = resolve_candidates(
                self.hass, EntitySourceConfig(preset=preset)
            )
            rendered = render_skeleton(candidates)
        except Exception:  # noqa: BLE001 — a prompt must never fail to build
            LOGGER.exception("entity skeleton could not be built")
            return None

        self._cache[preset] = (rendered, now)
        return rendered
```

`_on_registry` **must** carry `@callback`. A plain function handed to
`bus.async_listen` is dispatched to the executor thread pool and raises
`RuntimeError: loop ... is not the running loop`; this cost a fix round in the
entity-indexing plan.

- [ ] **Step 4: Wire it into `__init__.py`**

Follow the memory registry's existing pattern exactly — read that code first.
In `async_setup`, beside where `hass.data[DOMAIN]["memory"]` is seeded:

```python
    if "entity_skeleton" not in hass.data[DOMAIN]:
        cache = SkeletonCache(hass)
        cache.start()
        hass.data[DOMAIN]["entity_skeleton"] = cache
```

In `async_unload_entry`'s `if not remaining:` branch, beside the memory
registry's shutdown:

```python
        skeleton: SkeletonCache | None = hass.data.get(DOMAIN, {}).get("entity_skeleton")
        if skeleton is not None:
            await skeleton.stop()
```

That branch already sets the `subsystems_stopped` marker, and
`async_setup_entry` already rebuilds on it — confirm the rebuild path restores
this cache too, and if it does not, make it. A cache torn down with no way back
would silently return `""` for the rest of the HA run, which reads as an empty
home.

Also call `invalidate()` from `_reload_registry`: a reload should not serve a
map built before it.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_entity_skeleton_cache.py tests/test_memory_multi_store.py -v`
Expected: all pass. The second file exercises the setup and reload paths you touched.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/ tests/test_entity_skeleton_cache.py
git commit -m "feat(context): shared skeleton cache invalidated by the registries"
```

---

### Task 5: The retrieved block and the assembled context

**Files:**
- Modify: `custom_components/smartchain/tools/memory/entity_context.py`
- Test: `tests/test_entity_context.py`

**Interfaces:**
- Consumes: `rank_entities` (Task 2), `SkeletonCache` (Task 4), `resolve_candidates`, `ENTITY_CONTEXT_MAX_ENTITIES`.
- Produces: `async build_entity_context(hass, preset, query) -> str | None`. Tasks 6 and 7 consume it. `None` means "could not build — use the full dump"; `""` means "nothing to say".

- [ ] **Step 1: Write the failing test**

Create `tests/test_entity_context.py`:

```python
"""Skeleton plus what this turn is about, and what happens when either fails."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import DOMAIN
from custom_components.smartchain.tools.memory.entity_context import (
    SkeletonCache,
    build_entity_context,
)
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _cand(entity_id: str, name: str, area: str = "Кухня") -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        area=area,
        device="",
        device_class="",
        aliases=(),
    )


def _install_cache(hass: HomeAssistant, skeleton: str | None) -> MagicMock:
    cache = MagicMock(spec=SkeletonCache)
    cache.get.return_value = skeleton
    hass.data.setdefault(DOMAIN, {})["entity_skeleton"] = cache
    return cache


def _patch_ranking(ranked: list[EntityCandidate]):
    return patch(
        "custom_components.smartchain.tools.memory.entity_context.rank_entities",
        new=AsyncMock(return_value=ranked),
    )


def _patch_candidates(cands: list[EntityCandidate]):
    return patch(
        "custom_components.smartchain.tools.memory.entity_context.resolve_candidates",
        return_value={c.entity_id: c for c in cands},
    )


async def test_both_blocks_appear(hass: HomeAssistant) -> None:
    hass.states.async_set("light.a", "on", {})
    _install_cache(hass, "Кухня — light: Потолочный")
    cand = _cand("light.a", "Потолочный")

    with _patch_candidates([cand]), _patch_ranking([cand]):
        text = await build_entity_context(hass, preset="optimal", query="потолок")

    assert "Кухня — light: Потолочный" in text
    assert "light.a" in text
    assert "= on" in text


async def test_state_is_read_live_not_from_the_index(hass: HomeAssistant) -> None:
    hass.states.async_set("light.a", "off", {})
    _install_cache(hass, "Кухня — light: Потолочный")
    cand = _cand("light.a", "Потолочный")

    with _patch_candidates([cand]), _patch_ranking([cand]):
        text = await build_entity_context(hass, preset="optimal", query="потолок")

    assert "= off" in text


async def test_an_entity_with_no_state_reads_unavailable(hass: HomeAssistant) -> None:
    _install_cache(hass, "Кухня — light: Потолочный")
    cand = _cand("light.gone", "Пропавший")

    with _patch_candidates([cand]), _patch_ranking([cand]):
        text = await build_entity_context(hass, preset="optimal", query="пропавший")

    assert "unavailable" in text


async def test_no_matches_renders_no_heading(hass: HomeAssistant) -> None:
    _install_cache(hass, "Кухня — light: Потолочный")

    with _patch_candidates([]), _patch_ranking([]):
        text = await build_entity_context(hass, preset="optimal", query="ничего")

    assert "Кухня — light: Потолочный" in text
    assert ":" not in text.split("\n")[-1] or "light." not in text


async def test_the_retrieval_is_capped(hass: HomeAssistant) -> None:
    from custom_components.smartchain.const import ENTITY_CONTEXT_MAX_ENTITIES

    _install_cache(hass, "skeleton")
    cands = [_cand(f"light.a{i}", f"Свет {i}") for i in range(40)]
    for c in cands:
        hass.states.async_set(c.entity_id, "on", {})

    captured = {}

    async def _fake_rank(hass_, registry, candidates, query, top_k, **kw):
        captured["top_k"] = top_k
        return cands[:top_k]

    with (
        _patch_candidates(cands),
        patch(
            "custom_components.smartchain.tools.memory.entity_context.rank_entities",
            new=_fake_rank,
        ),
    ):
        await build_entity_context(hass, preset="optimal", query="свет")

    assert captured["top_k"] == ENTITY_CONTEXT_MAX_ENTITIES


async def test_a_failing_retrieval_leaves_the_skeleton(
    hass: HomeAssistant, caplog
) -> None:
    """Layer one of the failure ladder."""
    _install_cache(hass, "Кухня — light: Потолочный")

    with (
        _patch_candidates([_cand("light.a", "Потолочный")]),
        patch(
            "custom_components.smartchain.tools.memory.entity_context.rank_entities",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        text = await build_entity_context(hass, preset="optimal", query="потолок")

    assert text == "Кухня — light: Потолочный"
    assert "boom" not in text


async def test_a_failing_skeleton_returns_none(hass: HomeAssistant) -> None:
    """Layer two: the caller falls back to the full dump."""
    _install_cache(hass, None)

    with _patch_candidates([]), _patch_ranking([]):
        assert await build_entity_context(hass, preset="optimal", query="x") is None


async def test_a_missing_cache_returns_none(hass: HomeAssistant) -> None:
    """Nothing installed in hass.data must not raise into a conversation."""
    hass.data.setdefault(DOMAIN, {}).pop("entity_skeleton", None)
    assert await build_entity_context(hass, preset="optimal", query="x") is None


async def test_an_empty_home_is_not_a_failure(hass: HomeAssistant) -> None:
    _install_cache(hass, "")

    with _patch_candidates([]), _patch_ranking([]):
        assert await build_entity_context(hass, preset="optimal", query="x") == ""


async def test_the_vector_pass_is_used_only_with_exactly_one_entity_store(
    hass: HomeAssistant,
) -> None:
    """With several there is no non-arbitrary choice and nobody to ask."""
    _install_cache(hass, "skeleton")
    cand = _cand("light.a", "Потолочный")
    hass.states.async_set("light.a", "on", {})

    registry = MagicMock()
    registry.entity_store_names.return_value = ["a", "b"]
    hass.data[DOMAIN]["memory"] = registry

    captured = {}

    async def _fake_rank(hass_, reg, candidates, query, top_k, store_name=None, **kw):
        captured["store_name"] = store_name
        return [cand]

    with (
        _patch_candidates([cand]),
        patch(
            "custom_components.smartchain.tools.memory.entity_context.rank_entities",
            new=_fake_rank,
        ),
    ):
        await build_entity_context(hass, preset="optimal", query="потолок")

    assert captured["store_name"] is None

    registry.entity_store_names.return_value = ["only"]
    with (
        _patch_candidates([cand]),
        patch(
            "custom_components.smartchain.tools.memory.entity_context.rank_entities",
            new=_fake_rank,
        ),
    ):
        await build_entity_context(hass, preset="optimal", query="потолок")

    assert captured["store_name"] == "only"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_entity_context.py -v`
Expected: `ImportError` for `build_entity_context`.

- [ ] **Step 3: Implement the retrieved block and the assembly**

Append to `entity_context.py`:

```python
_RETRIEVED_HEADING = "Mentioned in this request:"


def render_retrieved(hass: HomeAssistant, ranked: list[EntityCandidate]) -> str:
    """The matched entities in full: id, name, area and live state.

    States come from `hass.states` at render time, never from stored index
    metadata, which is stale by construction and absent entirely when the
    store does not track states.
    """
    if not ranked:
        return ""
    lines = [_RETRIEVED_HEADING]
    for cand in ranked:
        live = hass.states.get(cand.entity_id)
        state = live.state if live else "unavailable"
        lines.append(
            f"- {cand.entity_id} — {cand.name} [{cand.area or '—'}] = {state}"
        )
    return "\n".join(lines)


async def build_entity_context(
    hass: HomeAssistant, preset: str, query: str
) -> str | None:
    """The whole entity context for one turn. Never raises.

    Returns None when the skeleton could not be built, which is the caller's
    signal to fall back to the full devices dump. An empty string means the
    home is genuinely empty, which is not a failure.
    """
    cache: Any = (hass.data.get(DOMAIN) or {}).get("entity_skeleton")
    if cache is None:
        LOGGER.warning("entity skeleton cache is not installed; falling back")
        return None

    skeleton = cache.get(preset)
    if skeleton is None:
        return None

    retrieved = ""
    try:
        registry = (hass.data.get(DOMAIN) or {}).get("memory")
        names = registry.entity_store_names() if registry is not None else []
        # Exactly one index, or no vector pass: with several there is no
        # non-arbitrary choice and no user to ask. search_entities remains
        # available for a deliberate one.
        store_name = names[0] if len(names) == 1 else None

        candidates = resolve_candidates(hass, EntitySourceConfig(preset=preset))
        ranked = await rank_entities(
            hass,
            registry,
            candidates,
            query,
            top_k=ENTITY_CONTEXT_MAX_ENTITIES,
            store_name=store_name,
        )
        retrieved = render_retrieved(hass, ranked)
    except Exception:  # noqa: BLE001 — degrade to the skeleton, never fail a turn
        LOGGER.exception("entity retrieval failed; using the skeleton alone")

    if skeleton and retrieved:
        return f"{skeleton}\n\n{retrieved}"
    return skeleton or retrieved
```

`resolve_candidates` is called a second time here rather than reusing the
skeleton cache's: the cache stores rendered text, not candidates, and holding
candidate objects for every preset would trade a real memory cost for a
registry read that is already cheap and synchronous. Note this in the docstring
if you keep it, and say so in your report if you find a better shape.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/test_entity_context.py tests/test_entity_skeleton.py tests/test_entity_skeleton_cache.py -v`
Expected: all pass.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/tools/memory/entity_context.py tests/test_entity_context.py
git commit -m "feat(context): retrieved block and the assembled entity context

Phase 2 checkpoint: the context can be built, but nothing uses it yet."
```

---

# Phase 3 — Wiring and documentation

### Task 6: Compose the prompt from it

**Files:**
- Modify: `custom_components/smartchain/conversation.py`
- Test: `tests/test_dynamic_context_prompt.py`

**Interfaces:**
- Consumes: `build_entity_context`, `CONF_DYNAMIC_ENTITY_CONTEXT`, `CONF_DYNAMIC_CONTEXT_PRESET`.

**The constraint that outranks everything else here:** with
`dynamic_entity_context` off, the prompt must be **byte-for-byte what it is
today**. Today's line is
`prompt = self._render_prompt_cached(user_prompt + DEFAULT_DEVICES_PROMPT)`, and
the off path must still produce exactly that, through the same cache.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dynamic_context_prompt.py`. Read `tests/test_conversation*.py`
(whatever exists) first and reuse its way of driving a turn; do not invent a new
harness. The assertions that must exist:

```python
async def test_off_reproduces_todays_prompt_exactly(...):
    """The single most important test in this task."""
    # option off -> the system message equals
    # render(user_prompt + DEFAULT_DEVICES_PROMPT), byte for byte.


async def test_on_uses_the_skeleton_and_not_the_dump(...):
    # option on -> the system message contains the skeleton text and does NOT
    # contain a rendered fragment unique to DEFAULT_DEVICES_PROMPT.


async def test_on_appends_the_retrieved_block(...):
    # the matched entity's id and live state appear in the system message.


async def test_a_none_context_falls_back_to_the_dump(...):
    """Layer two of the failure ladder, at the call site."""
    # build_entity_context patched to return None -> the system message is
    # exactly today's prompt.


async def test_the_user_prompt_is_still_rendered_through_jinja(...):
    # a user prompt containing {{ ha_name }} still resolves with the option on.


async def test_the_skills_prompt_is_still_appended_after(...):
    # ordering is unchanged: user prompt, context, then skills.


async def test_the_query_is_the_users_message(...):
    # build_entity_context is awaited with query == user_input.text.
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_dynamic_context_prompt.py -v`

- [ ] **Step 3: Change the composition**

In `_async_handle_message`, replace the `else` branch:

```python
        else:
            dynamic = options.get(
                CONF_DYNAMIC_ENTITY_CONTEXT, DEFAULT_DYNAMIC_ENTITY_CONTEXT
            )
            context = None
            if dynamic:
                context = await build_entity_context(
                    self.hass,
                    preset=options.get(
                        CONF_DYNAMIC_CONTEXT_PRESET, ENTITY_DEFAULT_PRESET
                    ),
                    query=user_input.text or "",
                )

            if context is None:
                # Either the option is off, or the skeleton could not be built.
                # Both mean: behave exactly as this integration always has.
                prompt = self._render_prompt_cached(user_prompt + DEFAULT_DEVICES_PROMPT)
            else:
                # Only the user prompt is a template; the context is plain text
                # and varies per turn, so running Jinja over the pair would bust
                # the cache on every message for no gain.
                prompt = self._render_prompt_cached(user_prompt)
                if context:
                    prompt = f"{prompt}\n\n{context}"

            chat_log.content[0] = SystemContent(content=prompt)
```

Add the imports: `build_entity_context` from `.tools.memory.entity_context`, and
`CONF_DYNAMIC_ENTITY_CONTEXT`, `DEFAULT_DYNAMIC_ENTITY_CONTEXT`,
`CONF_DYNAMIC_CONTEXT_PRESET`, `ENTITY_DEFAULT_PRESET` from `.const`. Keep both
blocks alphabetically sorted.

Everything after this branch — the skills prompt, the builtin-sentence path,
the tool assembly — is untouched.

- [ ] **Step 4: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/ -q`
Expected: fully green, zero skips. **Any existing conversation test that breaks
is a real regression**, not a test to adjust — the off path is supposed to be
identical and the on path is new.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/conversation.py tests/test_dynamic_context_prompt.py
git commit -m "feat(context): compose the prompt from skeleton and retrieval"
```

---

### Task 7: The Assist opt-in

**Files:**
- Modify: `custom_components/smartchain/tools/memory/entity_context.py`
- Modify: `custom_components/smartchain/conversation.py`
- Test: `tests/test_dynamic_context_assist.py`

**Interfaces:**
- Produces: `async build_retrieved_context(hass, preset, query) -> str` — the retrieved block alone, no skeleton.

**Why no skeleton on this path:** Home Assistant's Assist API already injects
its own list of exposed entities. Adding ours would duplicate it and grow a
prompt we cannot shrink. The only thing worth adding is the semantic hits that
a name-based exposure list does not surface.

- [ ] **Step 1: Write the failing test**

Create `tests/test_dynamic_context_assist.py` with these assertions:

```python
async def test_off_by_default_nothing_is_added(...):
    # llm_hass_api set, dynamic_context_on_assist unset -> the
    # extra_system_prompt handed to async_provide_llm_data is unchanged.


async def test_on_appends_the_retrieved_block(...):
    # -> extra_system_prompt ends with the block; the matched entity id is in it.


async def test_pre_existing_extra_system_prompt_survives(...):
    """Overwriting the user's own extra prompt would be a data-losing bug."""
    # user_input.extra_system_prompt = "Будь краток." -> that text is still
    # present, and the block follows it.


async def test_the_skeleton_is_not_added_on_this_path(...):
    # the area/domain map must NOT appear — HA already listed the entities.


async def test_a_retrieval_failure_leaves_the_extra_prompt_untouched(...):
    # build_retrieved_context raising -> the original extra_system_prompt is
    # passed through unchanged and the turn proceeds.
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --prerelease=allow pytest tests/test_dynamic_context_assist.py -v`

- [ ] **Step 3: Extract the retrieval and expose it alone**

In `entity_context.py`, lift the retrieval body out of `build_entity_context`
into a helper both callers share:

```python
async def build_retrieved_context(
    hass: HomeAssistant, preset: str, query: str
) -> str:
    """The retrieved block alone. Returns "" on any failure — never raises."""
```

`build_entity_context` then calls it and concatenates with the skeleton. Its
behaviour must not change; `tests/test_entity_context.py` is the guard and must
pass unmodified.

- [ ] **Step 4: Wire the Assist branch**

In `_async_handle_message`, before `async_provide_llm_data`:

```python
        if llm_hass_api:
            extra = user_input.extra_system_prompt or ""
            if options.get(
                CONF_DYNAMIC_CONTEXT_ON_ASSIST, DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST
            ):
                block = await build_retrieved_context(
                    self.hass,
                    preset=options.get(
                        CONF_DYNAMIC_CONTEXT_PRESET, ENTITY_DEFAULT_PRESET
                    ),
                    query=user_input.text or "",
                )
                if block:
                    extra = f"{extra}\n\n{block}" if extra else block
            try:
                await chat_log.async_provide_llm_data(
                    user_input.as_llm_context(DOMAIN),
                    llm_hass_api,
                    user_prompt,
                    extra,
                )
            except conversation.ConverseError as err:
                return err.as_conversation_result()
```

Note the fourth argument changes from `user_input.extra_system_prompt` to the
composed `extra`. Nothing else about this branch moves.

- [ ] **Step 5: Run tests and commit**

Run: `uv run --prerelease=allow pytest tests/ -q`
Expected: fully green, zero skips.

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format .
git add custom_components/smartchain/ tests/test_dynamic_context_assist.py
git commit -m "feat(context): opt-in retrieved block on the Assist path

Phase 3 checkpoint: dynamic context is live on both paths."
```

---

### Task 8: Documentation and CHANGELOG

**Files:**
- Modify: `docs/USAGE.md`, `docs/USAGE-ru.md`
- Modify: `README.md`, `README-ru.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: A new section in both guides**

Append a subsection at the end of §9, without renumbering anything, covering in
this order:

1. What changes: the system prompt stops carrying every entity and carries a
   map plus what the message is about. State plainly that **this is on by
   default** and that one checkbox restores the old behaviour.
2. The skeleton's shape, with a real rendered example.
3. That the map's scope is `dynamic_context_preset`, using the same four
   presets as the entity index, and that it is **independent** of any entity
   store's preset — read `const.py` for the membership rather than restating it
   from memory.
4. That **no entity index is required**: lexical matching works from the
   registries alone, and a configured index adds semantic matching. This is the
   part most likely to be missed by a reader who assumes the feature needs the
   whole vector stack.
5. `search_entities` remains available for anything the automatic retrieval
   missed, and the skeleton's truncation line says so too.
6. The Assist path: off by default, what turning it on adds, and why it cannot
   shrink anything there.
7. The limitation, stated honestly: retrieval runs on the latest message alone.
   A follow-up like "а выключи его" retrieves on a pronoun. The skeleton is why
   that degrades gracefully rather than failing.

Keep the rendered examples byte-identical between the English and Russian
guides. Russian must be orthographically correct with every `ё` present.

- [ ] **Step 2: README**

Update the memory/context bullet in both READMEs to mention dynamic entity
context, and add it to the v5.0.0 row of the "What's new" table. Update both
test badges to the real final number — read them first, do not assume.

- [ ] **Step 3: CHANGELOG**

Append to the existing `## [5.0.0] - unreleased` **Added** section. Do not
create a new heading. Cover: the feature, that it is on by default, how to turn
it off, that it needs no entity index, and the Assist opt-in. Update the test
count line to the real final number.

- [ ] **Step 4: Final smoke and commit**

```bash
uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .
uv run --prerelease=allow pytest tests/ -q
```
Expected: fully green, zero skips. Confirm the version is still `5.0.0` in both
manifests and that `manifest.json` requirements are unchanged.

```bash
git add -A
git commit -m "docs: dynamic entity context in both guides, READMEs and the changelog"
```

---

## Out of scope (deferred)

- Retrieval over conversation history rather than the latest message alone.
- A token budget instead of an entity count, which would need a per-provider
  tokeniser.
- Letting the model ask for a fuller skeleton mid-conversation.
- Translating the skeleton's structural vocabulary; it stays English, as the
  catalogue documents already do.
