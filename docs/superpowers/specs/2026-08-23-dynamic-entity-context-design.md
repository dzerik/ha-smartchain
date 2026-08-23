# Dynamic entity context — design

**Date:** 2026-08-23
**Status:** approved, ready for planning
**Release:** part of v5.0.0 (roadmap subsystem **C**)
**Builds on:** `2026-08-23-entity-indexing-design.md`

---

## 1. Goal

Stop putting the entire home into every system prompt.

`DEFAULT_DEVICES_PROMPT` renders every area, every device and every entity with
its current state, on every turn. In a home with a thousand entities that is
most of the prompt, paid for on every message, and it buries the handful of
entities the user is actually asking about.

This subsystem replaces that dump with a compact **skeleton** of what exists,
plus a per-turn **retrieval** of the entities the message is about.

## 2. Scope

**In scope.** A skeleton renderer over the same preset machinery subsystem B
uses; per-turn retrieval reusing subsystem B's ranking; assembly and caching in
`conversation.py`; a per-subentry option, on by default; an opt-in extension to
the Assist path; extracting subsystem B's ranking into a shared function.

**Not in scope.** Changing what Home Assistant's own Assist API injects — that
is HA's, not ours. Retrieval over conversation memory (`search_memory` already
covers it). Acting on entities. Changing `DEFAULT_DEVICES_PROMPT` itself, which
remains the fallback.

## 3. Why a skeleton, and not retrieval alone

The devices prompt does two jobs: it tells the model the *state* of things, and
it tells the model *what exists*. Retrieval on the user's message replaces the
first well and the second badly.

"Включи свет" matches a dozen lamps. "Выключи всё" matches nothing in
particular. An entity the user describes with unlucky words does not surface at
all — and the model, seeing no such entity in its context, answers that the
device does not exist. That is a worse agent than the one we started with.

So the skeleton is always present and always complete: every in-scope entity
appears by name. Only the details — ids and states — are retrieved. The model
can always see the shape of the home, and `search_entities` remains available
for anything the automatic retrieval missed.

## 4. What the model can actually do without Assist

Worth stating because it shapes the skeleton: **on the non-Assist path the model
has no Home Assistant control tools at all.** `conversation.py` builds its tool
list from `chat_log.llm_api.tools`, and `llm_api` is populated only by
`async_provide_llm_data`, which runs only when `llm_hass_api` is configured.

So on the path this subsystem targets, the devices prompt is purely
informational — the model answers questions about the home rather than acting on
it, except through whatever custom YAML or MCP tools the user defined, which
take their own arguments.

Consequence: **`entity_id` is near-useless in the skeleton.** Names, areas and
states are what the model needs. Ids stay in the retrieved block, where there
are few of them and where the Assist opt-in makes them meaningful.

## 5. Configuration

Three new per-subentry options, alongside `enable_history_tool` and the rest:

| Option | Type | Default | Meaning |
|---|---|---|---|
| `dynamic_entity_context` | bool | **`true`** | Replace the full dump with skeleton + retrieval |
| `dynamic_context_preset` | one of `ENTITY_PRESETS` | `optimal` | Which entities the skeleton covers |
| `dynamic_context_on_assist` | bool | `false` | Also inject the retrieved block when `llm_hass_api` is set |

`dynamic_context_max_entities` is a constant rather than an option — see §12.

**The default is `true`**, so existing agents change behaviour on upgrade. That
is deliberate: v5.0.0 is already a major release, every non-Assist agent gains
the saving without touching anything, and the skeleton means nothing is
forgotten, only abbreviated. The migration note in the changelog says how to
restore the old behaviour with one checkbox.

`dynamic_context_preset` is **independent** of any entity store's preset. A user
running both sets both. Coupling them would make the skeleton's scope change
when someone edited an unrelated store, which is worse than a second setting.

## 6. The skeleton

One line per area, entities grouped by domain, names only:

```
Кухня — свет: Потолочный, Подсветка; розетки: Кофеварка, Чайник; датчики: Температура, Влажность
Спальня — свет: Бра, Люстра; климат: Кондиционер
Без области — Пылесос, Входная дверь
```

Rules:

- Scope comes from `resolve_candidates(hass, EntitySourceConfig(preset=...))` —
  the same function subsystem B uses, so the two subsystems cannot disagree
  about what counts as an entity, and C works with no entity store configured.
- Entities with no area are collected under a final "no area" line rather than
  dropped. An unassigned entity is exactly the kind a user forgets exists.
- Domain labels are the domain itself (`light`, `switch`, `sensor`), lower-cased
  and pluralised only in the sense that the group is a list. No translation
  table — the structural vocabulary stays English as it already does in the
  catalogue documents.
- Names are the same `EntityCandidate.name` the index uses, which already falls
  back `name → original_name → entity_id`.
- No `entity_id`, no `device_class`, no state, no device grouping.

Per entity this is roughly 12–20 characters against 60–90 in the current dump.

**Bounded.** If the rendered skeleton exceeds `ENTITY_SKELETON_MAX_CHARS`, areas
are emitted until the budget is spent and the remainder is replaced by a final
line naming how many areas and entities were omitted, plus a pointer to
`search_entities`. Silently truncating would make the model confidently wrong
about a home it can no longer see; saying so lets it ask.

## 7. Retrieval

Per turn, over the user's message text:

- Ranking is subsystem B's, reused — lexical exact, then prefix, then vector by
  score, deduplicated by `entity_id`. Lexical always; vector only when an entity
  store exists and is available.
- **Which store**, when several entity indexes exist: the vector pass runs only
  when there is exactly one, mirroring how `search_entities` resolves an omitted
  `store` argument. With two or more there is no non-arbitrary choice and no user
  to ask, so the retrieval stays lexical rather than silently preferring one
  index over another. `search_entities` remains available for a deliberate
  choice.
- Top `ENTITY_CONTEXT_MAX_ENTITIES` (§12).
- Rendered with the detail the skeleton omits:

```
Упомянутое в запросе:
- light.kitchen_ceiling — Потолочный свет [Кухня] = on
- switch.kitchen_socket_3 — Кофеварка [Кухня] = off
```

- States are read live from `hass.states` at render time, never from stored
  metadata — the same rule `search_entities` follows.
- An empty result renders nothing at all, not an empty heading.

The query is the user's message alone. Not the conversation history: a
follow-up like "а выключи его" would retrieve on a pronoun, and mixing in older
turns retrieves the *previous* subject, which is at least as often wrong as
right. The model has `search_entities` for the cases automatic retrieval misses,
and that is the honest boundary.

## 8. Assembly and caching

Today `_render_prompt_cached` renders `user_prompt + DEFAULT_DEVICES_PROMPT`
through Jinja and caches the result for `PROMPT_CACHE_TTL` (30 s), keyed on the
raw prompt text.

That cache cannot survive a per-turn block: the key would change every turn and
the Jinja render would run every time. So the composition changes:

1. **The user prompt** goes through Jinja and keeps the existing TTL cache. It
   is the only part that was ever a template.
2. **The skeleton** is plain text, built from the registries, with its own cache
   invalidated by `entity_registry_updated`, `device_registry_updated` and
   `area_registry_updated` — the same three events the entity indexer listens
   to. It does not depend on states, so state changes do not invalidate it.
3. **The retrieved block** is built fresh each turn and never cached.

The three are concatenated into the system message. Nothing else about the
message changes; the skills prompt is still appended afterwards exactly as it is
today.

An entity can appear twice — by name in the skeleton and in full in the
retrieved block. That repetition is deliberate and cheap: the two blocks answer
different questions ("what exists" and "what is this message about"), and
suppressing the skeleton entry would make the home's map change shape depending
on what was asked, which is exactly the instability §3 argues against.

The skeleton cache carries a TTL as well as event invalidation. The events are
the real mechanism; the TTL is a backstop for a rename that somehow does not
raise one, bounded at `ENTITY_SKELETON_CACHE_TTL` so a stale map cannot outlive
a few minutes.

## 9. The Assist path

When `llm_hass_api` is set, Home Assistant injects its own list of exposed
entities and its own control tools. We cannot shrink that, so by default this
subsystem does nothing there.

With `dynamic_context_on_assist` enabled, the **retrieved block only** — never
the skeleton, which would duplicate HA's list — is appended to
`user_input.extra_system_prompt` before it is handed to
`async_provide_llm_data`. Existing content of `extra_system_prompt` is preserved
and the block is appended after it.

The value this adds is the semantic hits HA's name-based exposure does not
surface. The cost is tokens. Hence: off by default.

## 10. Shared ranking

`entity_tool.py` currently holds `_fold` and `_lexical` privately and merges
inline inside `execute_entity_search`. This subsystem needs exactly that merge.
Duplicating it would guarantee the two drift.

Extract it:

```python
async def rank_entities(
    hass: HomeAssistant,
    registry: Any,
    candidates: dict[str, EntityCandidate],
    query: str,
    top_k: int,
    store_name: str | None = None,
) -> list[EntityCandidate]:
    """Lexical-then-vector ranked candidates, deduplicated by entity_id."""
```

`execute_entity_search` becomes a thin renderer over it plus its filters, and
the context builder calls it directly. Behaviour must be unchanged — the
existing `search_entities` tests are the guard, and they must pass untouched.

## 11. Error handling

Layered, so a turn is never lost:

- Retrieval fails → the skeleton alone is used, the failure is logged.
- The skeleton fails → `DEFAULT_DEVICES_PROMPT` is used, the failure is logged.
- Both are wrapped so nothing in this subsystem can raise into
  `_async_handle_message`.

No credential can appear here — this code touches registries, states and the
entity store, none of which carry one — but the rule stands.

## 12. Constants

```python
CONF_DYNAMIC_ENTITY_CONTEXT = "dynamic_entity_context"
DEFAULT_DYNAMIC_ENTITY_CONTEXT = True
CONF_DYNAMIC_CONTEXT_PRESET = "dynamic_context_preset"
CONF_DYNAMIC_CONTEXT_ON_ASSIST = "dynamic_context_on_assist"
DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST = False
ENTITY_CONTEXT_MAX_ENTITIES = 12
ENTITY_SKELETON_MAX_CHARS = 6000
ENTITY_SKELETON_CACHE_TTL = 300  # seconds; registry events invalidate sooner
```

`ENTITY_CONTEXT_MAX_ENTITIES` is a constant, not an option: a user who wants
more should raise it in one place if we learn 12 is wrong, and every extra
option is a support surface. `ENTITY_SKELETON_MAX_CHARS` is generous — roughly
300–500 entities — because exceeding it degrades the model's map of the home.

## 13. Testing

- **Skeleton rendering**: grouping by area and domain; the no-area line; names
  falling back to `entity_id`; an empty home rendering nothing rather than a
  bare header.
- **Skeleton budget**: a home past `ENTITY_SKELETON_MAX_CHARS` truncates, and
  the omission line states real counts. Assert against the constant, not a
  hardcoded length.
- **Skeleton cache**: a second build with no registry change performs no
  re-render; a registry event invalidates it.
- **Preset scope**: `dynamic_context_preset` genuinely narrows the skeleton, and
  works with no entity store configured at all.
- **Retrieval**: lexical-only with no store; lexical + vector with one; states
  read live rather than from metadata; an empty result renders nothing.
- **Assembly**: with the option on, the prompt contains the skeleton and not
  `DEFAULT_DEVICES_PROMPT`; with it off, exactly today's prompt, byte for byte.
- **Assist path**: off by default, nothing is added; on, the retrieved block
  reaches `extra_system_prompt` and any pre-existing content survives.
- **Failure layering**: retrieval raising leaves the skeleton; the skeleton
  raising leaves `DEFAULT_DEVICES_PROMPT`; neither propagates.
- **`rank_entities` extraction**: every existing `search_entities` test passes
  unmodified.

## 14. Global constraints

- **No new dependency.**
- `requires-python >= 3.13`; Home Assistant 2024.12.0+.
- ruff `line-length = 100`, `select = ["E", "F", "W", "I", "UP"]`.
- Credentials never reach a log line, an exception message or a prompt.
- Turning the option off must reproduce today's behaviour exactly.

## 15. Deferred

- Retrieval over conversation history rather than the latest message alone.
- A token budget rather than an entity count, which would need a tokeniser per
  provider.
- Letting the model request a fuller skeleton mid-conversation.
- Translating the skeleton's structural vocabulary; it stays English, as the
  catalogue documents already do.
