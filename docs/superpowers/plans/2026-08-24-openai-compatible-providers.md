# OpenAI-compatible providers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add OpenRouter, Groq, Together, LM Studio and llama.cpp by folding every OpenAI-compatible provider — including the existing OpenAI and DeepSeek — onto one table and one code path.

**Architecture:** A frozen dataclass `OpenAICompatible` and a dict `OPENAI_COMPATIBLE` in `const.py` hold the six facts a provider needs. The existing dicts (`UNIQUE_ID`, `ENGINE_MODELS`, `DEFAULT_MODEL`, `CONF_ENGINE_OPTIONS`) are populated from it at import, so every existing consumer keeps working untouched. `client_util` gains one table branch each in `validate_client`, `get_client` and `async_fetch_models`, replacing the per-provider ones. The config flow keeps a named `async_step_<id>` per provider — Home Assistant dispatches by method name — but its schema comes from the table.

**Tech Stack:** Python 3.13, Home Assistant custom integration, `langchain-openai` (`ChatOpenAI`, `OpenAIEmbeddings`), voluptuous, pytest + pytest-homeassistant-custom-component.

**Spec:** `docs/superpowers/specs/2026-08-24-openai-compatible-providers-design.md`

## Global Constraints

- **No new runtime dependencies.** All five providers use `langchain-openai`, already in `manifest.json`. `manifest.json` requirements must not change.
- `requires-python>=3.13`; `langchain-core<1`; `langchain-community<0.4`.
- **These four test files must pass unmodified.** If one has to change, the fold changed behaviour and the change is wrong: `tests/test_fetch_models.py`, `tests/test_config_flow.py`, `tests/test_provider_capabilities.py`, `tests/test_embeddings_model_discovery.py`.
- Version stays `5.0.0` — it is unreleased, so tasks in this plan do not bump it.
- Test runner: `uv run --prerelease=allow pytest tests/ -q`
- Lint: `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .`
- Both translation files — `custom_components/smartchain/translations/en.json` and `ru.json` — must carry every new step and field. There are exactly two; there is no third locale.
- Never use ASCII box-drawing for diagrams; use Mermaid.
- Every commit message ends with the project's standard trailer:
  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)

  Co-Authored-By: Claude <noreply@anthropic.com>
  ```

---

## File Structure

| File | Responsibility | Task |
|---|---|---|
| `custom_components/smartchain/const.py` | The table, the five new ids, the derived dicts | 1 |
| `tests/test_provider_table.py` | The table's own invariants (new file) | 1 |
| `custom_components/smartchain/client_util.py` | Capabilities, name classifier, client build, discovery | 2, 3 |
| `tests/test_provider_table_client.py` | Client build and discovery for table providers (new file) | 3 |
| `custom_components/smartchain/config_flow.py` | Step schemas and named steps | 4 |
| `custom_components/smartchain/translations/{en,ru}.json` | Step titles and field labels | 4 |
| `tests/test_new_provider_flow.py` | Flow for a hosted and a local provider (new file) | 4 |
| `custom_components/smartchain/tools/memory/embeddings.py` | Embeddings for table providers | 5 |
| `tests/test_embeddings_table_providers.py` | Embeddings build for a table provider (new file) | 5 |
| `README.md`, `CHANGELOG.md` | User-facing provider list | 6 |

---

### Task 1: The provider table

**Files:**
- Modify: `custom_components/smartchain/const.py`
- Test: `tests/test_provider_table.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `OpenAICompatible` (frozen dataclass with fields `label: str`, `default_base_url: str`, `requires_api_key: bool`, `serves_embeddings: bool`, `embedding_rule: str`, `static_models: list[str]`, `default_model: str | None`); `OPENAI_COMPATIBLE: dict[str, OpenAICompatible]`; ids `ID_OPENROUTER`, `ID_GROQ`, `ID_TOGETHER`, `ID_LMSTUDIO`, `ID_LLAMACPP`; unique ids `UNIQUE_ID_OPENROUTER`, `UNIQUE_ID_GROQ`, `UNIQUE_ID_TOGETHER`, `UNIQUE_ID_LMSTUDIO`, `UNIQUE_ID_LLAMACPP`; rule constants `EMBEDDING_RULE_OPENAI_PREFIX = "openai_prefix"`, `EMBEDDING_RULE_HEURISTIC = "heuristic"`, `EMBEDDING_RULE_NONE = "none"`. After this task `UNIQUE_ID`, `ENGINE_MODELS`, `DEFAULT_MODEL` and `CONF_ENGINE_OPTIONS` contain an entry for all eleven engines.

- [ ] **Step 1: Write the failing test**

Create `tests/test_provider_table.py`:

```python
"""The OpenAI-compatible provider table and the dicts derived from it."""

from custom_components.smartchain.const import (
    CONF_ENGINE_OPTIONS,
    DEFAULT_MODEL,
    EMBEDDING_RULE_HEURISTIC,
    EMBEDDING_RULE_NONE,
    EMBEDDING_RULE_OPENAI_PREFIX,
    ENGINE_MODELS,
    ID_DEEPSEEK,
    ID_GROQ,
    ID_LLAMACPP,
    ID_LMSTUDIO,
    ID_OPENAI,
    ID_OPENROUTER,
    ID_TOGETHER,
    OPENAI_COMPATIBLE,
    UNIQUE_ID,
)

VALID_RULES = {
    EMBEDDING_RULE_OPENAI_PREFIX,
    EMBEDDING_RULE_HEURISTIC,
    EMBEDDING_RULE_NONE,
}


def test_table_covers_the_seven_expected_providers():
    assert set(OPENAI_COMPATIBLE) == {
        ID_OPENAI,
        ID_DEEPSEEK,
        ID_OPENROUTER,
        ID_GROQ,
        ID_TOGETHER,
        ID_LMSTUDIO,
        ID_LLAMACPP,
    }


def test_every_row_is_well_formed():
    for engine, row in OPENAI_COMPATIBLE.items():
        assert row.label, engine
        assert row.default_base_url.startswith("http"), engine
        assert row.embedding_rule in VALID_RULES, engine
        assert row.static_models and row.static_models[0] == "", engine


def test_labels_are_unique():
    labels = [row.label for row in OPENAI_COMPATIBLE.values()]
    assert len(labels) == len(set(labels))


def test_local_providers_need_no_api_key():
    assert OPENAI_COMPATIBLE[ID_LMSTUDIO].requires_api_key is False
    assert OPENAI_COMPATIBLE[ID_LLAMACPP].requires_api_key is False


def test_hosted_providers_need_an_api_key():
    for engine in (ID_OPENAI, ID_DEEPSEEK, ID_OPENROUTER, ID_GROQ, ID_TOGETHER):
        assert OPENAI_COMPATIBLE[engine].requires_api_key is True, engine


def test_openai_is_the_only_prefix_rule():
    prefixed = [
        engine
        for engine, row in OPENAI_COMPATIBLE.items()
        if row.embedding_rule == EMBEDDING_RULE_OPENAI_PREFIX
    ]
    assert prefixed == [ID_OPENAI]


def test_deepseek_keeps_the_none_rule():
    # It falls through to `return False` today; the heuristic would change that.
    assert OPENAI_COMPATIBLE[ID_DEEPSEEK].embedding_rule == EMBEDDING_RULE_NONE


def test_new_rows_carry_no_default_model():
    for engine in (ID_OPENROUTER, ID_GROQ, ID_TOGETHER, ID_LMSTUDIO, ID_LLAMACPP):
        assert OPENAI_COMPATIBLE[engine].default_model is None, engine


def test_existing_rows_keep_their_default_model():
    assert OPENAI_COMPATIBLE[ID_OPENAI].default_model == "gpt-4.1-mini"
    assert OPENAI_COMPATIBLE[ID_DEEPSEEK].default_model == "deepseek-chat"


def test_derived_dicts_gained_every_row():
    for engine, row in OPENAI_COMPATIBLE.items():
        assert UNIQUE_ID[engine] == row.label, engine
        assert ENGINE_MODELS[row.label] == row.static_models, engine
        assert DEFAULT_MODEL[engine] == row.default_model, engine


def test_picker_offers_every_row():
    values = {option["value"] for option in CONF_ENGINE_OPTIONS}
    assert set(OPENAI_COMPATIBLE) <= values


def test_picker_has_no_duplicates():
    values = [option["value"] for option in CONF_ENGINE_OPTIONS]
    assert len(values) == len(set(values))
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run --prerelease=allow pytest tests/test_provider_table.py -q`
Expected: collection error — `cannot import name 'OPENAI_COMPATIBLE'`.

- [ ] **Step 3: Add the ids and the rule constants**

In `const.py`, directly after `ID_ANTHROPIC = "anthropic"` (currently line 60):

```python
ID_OPENROUTER = "openrouter"
ID_GROQ = "groq"
ID_TOGETHER = "together"
ID_LMSTUDIO = "lmstudio"
ID_LLAMACPP = "llamacpp"
```

And after `UNIQUE_ID_ANTHROPIC = "Anthropic"`:

```python
UNIQUE_ID_OPENROUTER = "OpenRouter"
UNIQUE_ID_GROQ = "Groq"
UNIQUE_ID_TOGETHER = "Together"
UNIQUE_ID_LMSTUDIO = "LM Studio"
UNIQUE_ID_LLAMACPP = "llama.cpp"
```

- [ ] **Step 4: Add the dataclass and the table**

`const.py` does **not** currently import it, so add `from dataclasses import dataclass` to the imports at the top of the file.

Place this block **after** `DEFAULT_MODEL` and `DEFAULT_DEEPSEEK_BASE_URL` are defined (currently around line 148), because the rows reference `MODELS_OPENAI`, `MODELS_DEEPSEEK` and `DEFAULT_DEEPSEEK_BASE_URL`:

```python
# --- OpenAI-compatible providers (v5.0.0) -------------------------------
#
# Every provider reachable through the OpenAI API shape lives in one table.
# Adding a provider is one row here, one three-line config-flow step, and
# two translation entries. See the design doc for why the base URLs are all
# user-editable and why five rows carry no default model.

EMBEDDING_RULE_OPENAI_PREFIX = "openai_prefix"
EMBEDDING_RULE_HEURISTIC = "heuristic"
EMBEDDING_RULE_NONE = "none"


@dataclass(frozen=True)
class OpenAICompatible:
    """One provider reachable through the OpenAI API shape."""

    label: str
    """Display name, and the config entry's unique id."""

    default_base_url: str
    """Pre-filled in the config flow, and always editable there."""

    requires_api_key: bool
    """False for a local server, which gets an optional key field instead."""

    serves_embeddings: bool
    """Whether an embeddings sub-entry is offered for this provider."""

    embedding_rule: str
    """How to tell an embedding model name from a chat one."""

    static_models: list[str]
    """Fallback when the provider's /models endpoint is unreachable."""

    default_model: str | None
    """None means the provider decides; the model argument is then omitted."""


OPENAI_COMPATIBLE: dict[str, OpenAICompatible] = {
    ID_OPENAI: OpenAICompatible(
        label=UNIQUE_ID_OPENAI,
        default_base_url="https://api.openai.com/v1",
        requires_api_key=True,
        serves_embeddings=True,
        embedding_rule=EMBEDDING_RULE_OPENAI_PREFIX,
        static_models=MODELS_OPENAI,
        default_model="gpt-4.1-mini",
    ),
    ID_DEEPSEEK: OpenAICompatible(
        label=UNIQUE_ID_DEEPSEEK,
        default_base_url=DEFAULT_DEEPSEEK_BASE_URL,
        requires_api_key=True,
        serves_embeddings=False,
        # Falls through to `return False` today; the heuristic would change
        # which names count as chat models.
        embedding_rule=EMBEDDING_RULE_NONE,
        static_models=MODELS_DEEPSEEK,
        default_model="deepseek-chat",
    ),
    ID_OPENROUTER: OpenAICompatible(
        label=UNIQUE_ID_OPENROUTER,
        default_base_url="https://openrouter.ai/api/v1",
        requires_api_key=True,
        serves_embeddings=False,
        embedding_rule=EMBEDDING_RULE_HEURISTIC,
        # OpenRouter proxies hundreds of models; any list written here is
        # wrong within weeks, so discovery does the work.
        static_models=[""],
        default_model=None,
    ),
    ID_GROQ: OpenAICompatible(
        label=UNIQUE_ID_GROQ,
        default_base_url="https://api.groq.com/openai/v1",
        requires_api_key=True,
        serves_embeddings=False,
        embedding_rule=EMBEDDING_RULE_HEURISTIC,
        static_models=[""],
        default_model=None,
    ),
    ID_TOGETHER: OpenAICompatible(
        label=UNIQUE_ID_TOGETHER,
        default_base_url="https://api.together.xyz/v1",
        requires_api_key=True,
        serves_embeddings=True,
        embedding_rule=EMBEDDING_RULE_HEURISTIC,
        static_models=[""],
        default_model=None,
    ),
    ID_LMSTUDIO: OpenAICompatible(
        label=UNIQUE_ID_LMSTUDIO,
        default_base_url="http://localhost:1234/v1",
        requires_api_key=False,
        serves_embeddings=True,
        embedding_rule=EMBEDDING_RULE_HEURISTIC,
        static_models=[""],
        default_model=None,
    ),
    ID_LLAMACPP: OpenAICompatible(
        label=UNIQUE_ID_LLAMACPP,
        default_base_url="http://localhost:8080/v1",
        requires_api_key=False,
        serves_embeddings=True,
        embedding_rule=EMBEDDING_RULE_HEURISTIC,
        static_models=[""],
        default_model=None,
    ),
}
```

- [ ] **Step 5: Derive the existing dicts from the table**

Immediately after the table, add the loop that populates the four dicts. It must sit **after** `UNIQUE_ID`, `CONF_ENGINE_OPTIONS`, `ENGINE_MODELS` and `DEFAULT_MODEL` are all defined; if any of them is defined earlier in the file than the table, the loop still works because it mutates rather than redefines.

```python
# The table is the single source for these; the dicts stay so that existing
# consumers (config flow, model fetch, tests) keep reading what they always
# read. A row's label IS its unique id, so the two cannot drift.
for _engine, _row in OPENAI_COMPATIBLE.items():
    UNIQUE_ID[_engine] = _row.label
    ENGINE_MODELS[_row.label] = _row.static_models
    DEFAULT_MODEL[_engine] = _row.default_model
    if not any(_option["value"] == _engine for _option in CONF_ENGINE_OPTIONS):
        CONF_ENGINE_OPTIONS.append(
            selector.SelectOptionDict(value=_engine, label=_row.label)
        )
del _engine, _row
```

Note the guard on `CONF_ENGINE_OPTIONS`: `openai` and `deepseek` are already listed there, and appending them again would show each twice in the picker.

- [ ] **Step 6: Run the new test**

Run: `uv run --prerelease=allow pytest tests/test_provider_table.py -q`
Expected: 11 passed.

- [ ] **Step 7: Run the whole suite and lint**

Run: `uv run --prerelease=allow pytest tests/ -q`
Expected: every test passes, including the four preservation files, unmodified.

Run: `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .`
Expected: clean.

- [ ] **Step 8: Break-it check**

Temporarily change `ID_DEEPSEEK`'s `embedding_rule` to `EMBEDDING_RULE_HEURISTIC` and re-run `tests/test_provider_table.py`. `test_deepseek_keeps_the_none_rule` must fail. Revert.

Then temporarily delete the `if not any(...)` guard in Step 5 and re-run. `test_picker_has_no_duplicates` must fail. Revert.

A test that cannot fail is not a test — confirm both before committing.

- [ ] **Step 9: Commit**

```bash
git add custom_components/smartchain/const.py tests/test_provider_table.py
git commit -m "feat(providers): table of OpenAI-compatible providers

Five new ids and one frozen-dataclass row each, with the existing OpenAI
and DeepSeek folded in. UNIQUE_ID, ENGINE_MODELS, DEFAULT_MODEL and the
provider picker are now populated from the table, so every consumer keeps
reading what it always read."
```

---

### Task 2: Capabilities and the name classifier

**Files:**
- Modify: `custom_components/smartchain/client_util.py:39-46` (`PROVIDER_CAPABILITIES`) and `:176-186` (`is_embedding_model`)
- Test: `tests/test_provider_table.py` (extend)

**Interfaces:**
- Consumes: `OPENAI_COMPATIBLE`, `EMBEDDING_RULE_*` from Task 1.
- Produces: `supports(engine, capability)` answers for all eleven engines; `is_embedding_model` dispatches on the row's rule.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_provider_table.py`:

```python
from custom_components.smartchain.client_util import is_embedding_model, supports
from custom_components.smartchain.const import (
    CAPABILITY_CHAT,
    CAPABILITY_EMBEDDINGS,
    ID_GIGACHAT,
)


def test_every_row_supports_chat():
    for engine in OPENAI_COMPATIBLE:
        assert supports(engine, CAPABILITY_CHAT), engine


def test_embeddings_capability_follows_the_row():
    for engine, row in OPENAI_COMPATIBLE.items():
        assert supports(engine, CAPABILITY_EMBEDDINGS) is row.serves_embeddings, engine


def test_hand_written_providers_keep_their_capabilities():
    assert supports(ID_GIGACHAT, CAPABILITY_EMBEDDINGS) is True
    assert supports(ID_GIGACHAT, CAPABILITY_CHAT) is True


def test_unknown_engine_supports_nothing():
    assert supports("nope", CAPABILITY_CHAT) is False


def test_openai_still_uses_the_prefix_rule():
    assert is_embedding_model(ID_OPENAI, "text-embedding-3-small") is True
    assert is_embedding_model(ID_OPENAI, "gpt-4.1-mini") is False
    # The heuristic would match this; the prefix rule must not.
    assert is_embedding_model(ID_OPENAI, "some-bge-model") is False


def test_deepseek_calls_every_name_a_chat_name():
    assert is_embedding_model(ID_DEEPSEEK, "deepseek-chat") is False
    assert is_embedding_model(ID_DEEPSEEK, "deepseek-embed") is False


def test_heuristic_rule_matches_the_embedding_families():
    for name in ("nomic-embed-text", "bge-m3", "gte-large", "e5-base", "all-minilm"):
        assert is_embedding_model(ID_LMSTUDIO, name) is True, name


def test_heuristic_rule_passes_chat_names_through():
    for name in ("llama-3.3-70b", "qwen2.5-coder", "mistral-small"):
        assert is_embedding_model(ID_OPENROUTER, name) is False, name
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run --prerelease=allow pytest tests/test_provider_table.py -q`
Expected: failures on the capability tests (the five new engines are absent from `PROVIDER_CAPABILITIES`, so `supports` returns `False`) and on the heuristic tests (`is_embedding_model` returns `False` for unknown engines).

- [ ] **Step 3: Build the capability matrix from the table**

In `client_util.py`, replace the `PROVIDER_CAPABILITIES` literal (lines 39-46) with:

```python
# The four hand-written providers are literal; every OpenAI-compatible one
# contributes its row's capabilities.
PROVIDER_CAPABILITIES: dict[str, frozenset[str]] = {
    ID_GIGACHAT: frozenset({CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS}),
    ID_YANDEX_GPT: frozenset({CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS}),
    ID_OLLAMA: frozenset({CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS}),
    ID_ANTHROPIC: frozenset({CAPABILITY_CHAT}),
    **{
        engine: frozenset(
            {CAPABILITY_CHAT, CAPABILITY_EMBEDDINGS}
            if row.serves_embeddings
            else {CAPABILITY_CHAT}
        )
        for engine, row in OPENAI_COMPATIBLE.items()
    },
}
```

`ID_OPENAI` and `ID_DEEPSEEK` are no longer listed explicitly — they arrive from the table, with the same values they had.

Add `OPENAI_COMPATIBLE` to the `from .const import (...)` block at the top of the file.

- [ ] **Step 4: Dispatch the classifier on the rule**

Replace `is_embedding_model` (lines 176-186) with:

```python
def is_embedding_model(engine: str, name: str) -> bool:
    """Whether `name` is an embedding model for `engine`."""
    row = OPENAI_COMPATIBLE.get(engine)
    if row is not None:
        if row.embedding_rule == EMBEDDING_RULE_OPENAI_PREFIX:
            return name.startswith("text-embedding-")
        if row.embedding_rule == EMBEDDING_RULE_HEURISTIC:
            return bool(_OLLAMA_EMBEDDING_HINT.search(name))
        return False
    if engine == ID_GIGACHAT:
        return name.startswith("Embeddings")
    if engine == ID_OLLAMA:
        return bool(_OLLAMA_EMBEDDING_HINT.search(name))
    if engine == ID_YANDEX_GPT:
        return name.startswith("text-search-")
    return False
```

The `ID_OPENAI` branch is gone — the table answers for it now, with the same prefix test.

Import `EMBEDDING_RULE_HEURISTIC` and `EMBEDDING_RULE_OPENAI_PREFIX` from `.const`.

- [ ] **Step 5: Run the tests**

Run: `uv run --prerelease=allow pytest tests/test_provider_table.py tests/test_provider_capabilities.py tests/test_embeddings_model_discovery.py -q`
Expected: all pass, and the latter two are unmodified.

- [ ] **Step 6: Run the whole suite and lint**

Run: `uv run --prerelease=allow pytest tests/ -q`
Run: `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .`

- [ ] **Step 7: Break-it check**

Temporarily make the `EMBEDDING_RULE_NONE` path fall through to the heuristic (delete the bare `return False` in the `row is not None` block so control reaches the `ID_GIGACHAT` chain). `test_deepseek_calls_every_name_a_chat_name` must fail. Revert.

- [ ] **Step 8: Commit**

```bash
git add custom_components/smartchain/client_util.py tests/test_provider_table.py
git commit -m "feat(providers): capabilities and name classifier read the table

PROVIDER_CAPABILITIES gains its OpenAI-compatible rows from the table, and
is_embedding_model dispatches on each row's rule. OpenAI keeps the prefix
test; DeepSeek keeps answering False for every name."
```

---

### Task 3: Client construction, validation and model discovery

**Files:**
- Modify: `custom_components/smartchain/client_util.py` — `validate_client` (lines 54-105), `get_client` (lines 109-167), `async_fetch_models` (lines 188-240)
- Test: `tests/test_provider_table_client.py` (create)

**Interfaces:**
- Consumes: `OPENAI_COMPATIBLE` from Task 1.
- Produces: a table branch in all three functions. A table provider's base URL comes from `entry.data[CONF_BASE_URL]` when set, else the row's `default_base_url`. When `requires_api_key` is `False` and no key is given, the key passed to `ChatOpenAI` is the literal `"not-needed"` — `ChatOpenAI` rejects `None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_provider_table_client.py`:

```python
"""Client build, validation and discovery for OpenAI-compatible providers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.client_util import (
    async_fetch_models,
    get_client,
    validate_client,
)
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    CONF_SKIP_VALIDATION,
    DOMAIN,
    ID_GROQ,
    ID_LMSTUDIO,
    ID_OPENROUTER,
    OPENAI_COMPATIBLE,
)

PLACEHOLDER_KEY = "not-needed"


def _entry(hass, engine: str, data: dict) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_ENGINE: engine, **data})
    entry.add_to_hass(hass)
    return entry


async def test_hosted_provider_uses_its_default_base_url(hass):
    entry = _entry(hass, ID_GROQ, {CONF_API_KEY: "k"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_GROQ, entry, {"model": "llama-3.3-70b"})
    kwargs = chat.call_args.kwargs
    assert kwargs["openai_api_base"] == OPENAI_COMPATIBLE[ID_GROQ].default_base_url
    assert kwargs["openai_api_key"] == "k"
    assert kwargs["model"] == "llama-3.3-70b"


async def test_entry_base_url_overrides_the_default(hass):
    entry = _entry(hass, ID_GROQ, {CONF_API_KEY: "k", CONF_BASE_URL: "http://mirror/v1"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_GROQ, entry, {"model": "m"})
    assert chat.call_args.kwargs["openai_api_base"] == "http://mirror/v1"


async def test_local_provider_gets_a_placeholder_key(hass):
    entry = _entry(hass, ID_LMSTUDIO, {CONF_BASE_URL: "http://localhost:1234/v1"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_LMSTUDIO, entry, {"model": "m"})
    assert chat.call_args.kwargs["openai_api_key"] == PLACEHOLDER_KEY


async def test_local_provider_honours_a_supplied_key(hass):
    entry = _entry(hass, ID_LMSTUDIO, {CONF_API_KEY: "real", CONF_BASE_URL: "http://x/v1"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_LMSTUDIO, entry, {"model": "m"})
    assert chat.call_args.kwargs["openai_api_key"] == "real"


async def test_row_without_a_default_model_omits_the_argument(hass):
    entry = _entry(hass, ID_OPENROUTER, {CONF_API_KEY: "k"})
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await get_client(hass, ID_OPENROUTER, entry, {"model": None})
    assert "model" not in chat.call_args.kwargs


async def test_validate_uses_the_row_base_url(hass):
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        chat.return_value.invoke = MagicMock()
        await validate_client(hass, {CONF_ENGINE: ID_GROQ, CONF_API_KEY: "k"})
    assert chat.call_args.kwargs["openai_api_base"] == OPENAI_COMPATIBLE[ID_GROQ].default_base_url


async def test_validate_is_skippable(hass):
    with patch("custom_components.smartchain.client_util.ChatOpenAI") as chat:
        await validate_client(
            hass, {CONF_ENGINE: ID_GROQ, CONF_API_KEY: "k", CONF_SKIP_VALIDATION: True}
        )
    chat.assert_not_called()


async def test_discovery_hits_the_row_models_endpoint(hass):
    fetch = AsyncMock(return_value=["llama-3.3-70b", "mixtral"])
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models", fetch
    ):
        models = await async_fetch_models(hass, ID_GROQ, {CONF_API_KEY: "k"})
    assert fetch.call_args.args[2] == (
        f"{OPENAI_COMPATIBLE[ID_GROQ].default_base_url}/models"
    )
    assert models == ["", "llama-3.3-70b", "mixtral"]


async def test_discovery_honours_an_overridden_base_url(hass):
    fetch = AsyncMock(return_value=["m"])
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models", fetch
    ):
        await async_fetch_models(
            hass, ID_GROQ, {CONF_API_KEY: "k", CONF_BASE_URL: "http://mirror/v1"}
        )
    assert fetch.call_args.args[2] == "http://mirror/v1/models"


async def test_discovery_falls_back_to_the_static_list(hass):
    fetch = AsyncMock(side_effect=RuntimeError("down"))
    with patch(
        "custom_components.smartchain.client_util._fetch_openai_compatible_models", fetch
    ):
        models = await async_fetch_models(hass, ID_OPENROUTER, {CONF_API_KEY: "k"})
    assert models == OPENAI_COMPATIBLE[ID_OPENROUTER].static_models
```

Note: `hass` comes from `pytest_homeassistant_custom_component`, and `pyproject.toml` sets `asyncio_mode = "auto"` — async tests need no marker. `_fetch_openai_compatible_models(hass, data, url)` takes its URL positionally, which is why the assertions read `call_args.args[2]`.

- [ ] **Step 2: Run to confirm failure**

Run: `uv run --prerelease=allow pytest tests/test_provider_table_client.py -q`
Expected: failures — Groq falls into the `else` (OpenAI) branch, so `openai_api_base` is absent from the kwargs.

- [ ] **Step 3: Add a base-URL helper**

In `client_util.py`, above `validate_client`:

```python
# A local server needs no credential, but ChatOpenAI rejects a None key.
_PLACEHOLDER_API_KEY = "not-needed"


def _compatible_base_url(row: OpenAICompatible, data: Mapping[str, Any]) -> str:
    """The provider's endpoint: the user's if set, else the row's default."""
    return (data.get(CONF_BASE_URL) or "").strip() or row.default_base_url


def _compatible_api_key(row: OpenAICompatible, data: Mapping[str, Any]) -> str:
    """The credential to send, with a placeholder for keyless local servers."""
    key = (data.get(CONF_API_KEY) or "").strip()
    if key:
        return key
    if row.requires_api_key:
        # The flow makes this field required, so an empty one means a
        # hand-edited entry; let the provider return its own auth error.
        return ""
    return _PLACEHOLDER_API_KEY
```

Import `OpenAICompatible` from `.const`, and `Mapping` from `collections.abc` and `Any` from `typing` if they are not already imported.

- [ ] **Step 4: Add the table branch to `validate_client`**

In `validate_client`, insert this branch **before** the `elif engine == ID_DEEPSEEK` branch, and **delete** the `ID_DEEPSEEK` branch entirely (the table now covers it):

```python
    elif engine in OPENAI_COMPATIBLE:
        row = OPENAI_COMPATIBLE[engine]
        client = ChatOpenAI(
            max_tokens=10,
            model=row.default_model or DEFAULT_VALIDATION_MODEL,
            openai_api_key=_compatible_api_key(row, user_input),
            openai_api_base=_compatible_base_url(row, user_input),
        )
```

`DEFAULT_VALIDATION_MODEL` does not exist yet. Validation sends a ten-token probe and the model name only has to be one the provider accepts, but a row with no default has no such name. Define beside the placeholder key:

```python
# Rows with no default model still need a name for the validation probe.
# It is never used for real traffic, and a wrong name surfaces as a clear
# provider error at setup rather than a silent misconfiguration later.
DEFAULT_VALIDATION_MODEL = "gpt-3.5-turbo"
```

Then the `else` clause at the end of `validate_client` (which builds `ChatOpenAI` for OpenAI) becomes unreachable for known engines. Keep it, and make it loud:

```python
    else:
        LOGGER.warning(
            "Unrecognised engine %r during validation; treating it as OpenAI", engine
        )
        client = ChatOpenAI(
            max_tokens=10,
            model=DEFAULT_MODEL[ID_OPENAI],
            openai_api_key=user_input[CONF_API_KEY],
        )
```

- [ ] **Step 5: Add the table branch to `get_client`**

In `get_client`, insert before the `elif engine == ID_DEEPSEEK` branch and **delete** that branch:

```python
    elif engine in OPENAI_COMPATIBLE:
        row = OPENAI_COMPATIBLE[engine]
        if not common_args.get("model"):
            if row.default_model is None:
                # Let the provider pick, the way GigaChat and YandexGPT do.
                common_args.pop("model", None)
            else:
                common_args["model"] = row.default_model
        common_args["openai_api_key"] = _compatible_api_key(row, entry.data)
        common_args["openai_api_base"] = _compatible_base_url(row, entry.data)
        client = ChatOpenAI(**common_args)
```

And make the trailing `else` loud in the same way:

```python
    else:
        LOGGER.warning("Unrecognised engine %r; treating it as OpenAI", engine)
        if common_args["model"] is None:
            common_args["model"] = DEFAULT_MODEL[ID_OPENAI]
        common_args["openai_api_key"] = entry.data[CONF_API_KEY]
        client = ChatOpenAI(**common_args)
```

- [ ] **Step 6: Point discovery at the row's endpoint**

In `async_fetch_models`, replace the `elif engine == ID_OPENAI:` and `elif engine == ID_DEEPSEEK:` branches with a single one placed first inside the `try`:

```python
        if engine in OPENAI_COMPATIBLE:
            row = OPENAI_COMPATIBLE[engine]
            models = await _fetch_openai_compatible_models(
                hass, data, f"{_compatible_base_url(row, data)}/models"
            )
        elif engine == ID_OLLAMA:
            models = await _fetch_ollama_models(hass, data)
        elif engine == ID_ANTHROPIC:
            models = await _fetch_anthropic_models(hass, data)
        elif engine == ID_GIGACHAT:
            models = await _fetch_gigachat_models(hass, data)
        else:
            # YandexGPT has no list endpoint.
            return static
```

The `static` fallback above it already reads `ENGINE_MODELS[UNIQUE_ID[engine]]`, which Task 1 populated for every row — no change needed there.

- [ ] **Step 7: Run the new test and the preservation tests**

Run: `uv run --prerelease=allow pytest tests/test_provider_table_client.py tests/test_fetch_models.py tests/test_config_flow.py -q`
Expected: all pass, with `test_fetch_models.py` and `test_config_flow.py` unmodified.

If `test_fetch_models.py` fails on the OpenAI URL, check the row: its `default_base_url` is `https://api.openai.com/v1`, so the endpoint is `https://api.openai.com/v1/models` — byte-identical to the hard-coded string being replaced.

- [ ] **Step 8: Run the whole suite and lint**

Run: `uv run --prerelease=allow pytest tests/ -q`
Run: `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .`

- [ ] **Step 9: Break-it check**

Temporarily make `_compatible_base_url` ignore the user's value (`return row.default_base_url`). Both `test_entry_base_url_overrides_the_default` and `test_discovery_honours_an_overridden_base_url` must fail. Revert.

- [ ] **Step 10: Commit**

```bash
git add custom_components/smartchain/client_util.py tests/test_provider_table_client.py
git commit -m "feat(providers): one client path for every OpenAI-compatible provider

validate_client, get_client and async_fetch_models each lose their OpenAI
and DeepSeek branches to a single table branch. Base URLs are read from
the entry with the row's default as fallback, so a user behind a mirror
can reach any of them. The unknown-engine fallback now logs instead of
silently treating the engine as OpenAI."
```

---

### Task 4: Config flow and translations

**Files:**
- Modify: `custom_components/smartchain/config_flow.py` — schemas (lines 92-118), `ENGINE_SCHEMA` (lines 111-118), named steps (after line 186)
- Modify: `custom_components/smartchain/translations/en.json`, `custom_components/smartchain/translations/ru.json`
- Test: `tests/test_new_provider_flow.py` (create)

**Interfaces:**
- Consumes: `OPENAI_COMPATIBLE` from Task 1, the client path from Task 3.
- Produces: `async_step_openrouter`, `async_step_groq`, `async_step_together`, `async_step_lmstudio`, `async_step_llamacpp`; `ENGINE_SCHEMA` covering all eleven engines.

- [ ] **Step 1: Write the failing test**

Create `tests/test_new_provider_flow.py`:

```python
"""Config flow for the providers added by the table."""

from unittest.mock import patch

from homeassistant.data_entry_flow import FlowResultType

from custom_components.smartchain.config_flow import ENGINE_SCHEMA
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    CONF_SKIP_VALIDATION,
    DOMAIN,
    ID_GROQ,
    ID_LMSTUDIO,
    OPENAI_COMPATIBLE,
    UNIQUE_ID,
)


def test_every_row_has_a_step_schema():
    for engine in OPENAI_COMPATIBLE:
        assert engine in ENGINE_SCHEMA, engine


def test_every_row_has_a_named_step():
    from custom_components.smartchain.config_flow import ConfigFlow

    for engine in OPENAI_COMPATIBLE:
        assert hasattr(ConfigFlow, f"async_step_{engine}"), engine


async def test_hosted_provider_flow_creates_an_entry(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_GROQ}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == ID_GROQ

    with patch("custom_components.smartchain.client_util.validate_client"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "k", CONF_SKIP_VALIDATION: True},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == UNIQUE_ID[ID_GROQ]
    assert result["data"][CONF_ENGINE] == ID_GROQ


async def test_local_provider_flow_needs_no_api_key(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_LMSTUDIO}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_BASE_URL: "http://localhost:1234/v1",
            CONF_SKIP_VALIDATION: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BASE_URL] == "http://localhost:1234/v1"


async def test_local_step_prefills_the_row_default(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_LMSTUDIO}
    )
    defaults = {
        key.schema: key.default()
        for key in result["data_schema"].schema
        if getattr(key, "default", None) is not None and callable(key.default)
    }
    assert defaults[CONF_BASE_URL] == OPENAI_COMPATIBLE[ID_LMSTUDIO].default_base_url


def test_every_row_has_translations_in_both_locales():
    import json
    from pathlib import Path

    root = Path("custom_components/smartchain/translations")
    for locale in ("en", "ru"):
        data = json.loads((root / f"{locale}.json").read_text(encoding="utf-8"))
        steps = data["config"]["step"]
        for engine in OPENAI_COMPATIBLE:
            assert engine in steps, f"{locale}: {engine}"
            assert steps[engine].get("title"), f"{locale}: {engine} title"
            fields = steps[engine].get("data", {})
            for field in ENGINE_SCHEMA[engine].schema:
                assert field.schema in fields, f"{locale}: {engine}.{field.schema}"
```

- [ ] **Step 2: Run to confirm failure**

Run: `uv run --prerelease=allow pytest tests/test_new_provider_flow.py -q`
Expected: failures — the new engines are absent from `ENGINE_SCHEMA` and the class has no steps for them.

- [ ] **Step 3: Add the two schema builders**

In `config_flow.py`, after `STEP_OLLAMA_SCHEMA`:

```python
def _compatible_schema(engine: str) -> vol.Schema:
    """Step schema for an OpenAI-compatible provider.

    The base URL is always editable and pre-filled from the table, so a stale
    default or a mirror costs the user one field rather than the integration.
    A local server's key is optional; a hosted one's is required.
    """
    row = OPENAI_COMPATIBLE[engine]
    fields: dict[Any, Any] = {}
    if row.requires_api_key:
        fields[vol.Required(CONF_API_KEY)] = str
    fields[vol.Required(CONF_BASE_URL, default=row.default_base_url)] = str
    if not row.requires_api_key:
        # Some local deployments sit behind a proxy that still wants one.
        fields[vol.Optional(CONF_API_KEY)] = str
    fields[vol.Optional(CONF_SKIP_VALIDATION, default=DEFAULT_SKIP_VALIDATION)] = bool
    return vol.Schema(fields)
```

- [ ] **Step 4: Build `ENGINE_SCHEMA` from the table**

Replace the `ENGINE_SCHEMA` literal with:

```python
ENGINE_SCHEMA = {
    ID_GIGACHAT: STEP_API_KEY_SCHEMA,
    ID_YANDEX_GPT: STEP_YANDEXGPT_SCHEMA,
    ID_OLLAMA: STEP_OLLAMA_SCHEMA,
    ID_ANTHROPIC: STEP_API_KEY_SCHEMA,
    **{engine: _compatible_schema(engine) for engine in OPENAI_COMPATIBLE},
}
```

This changes OpenAI's and DeepSeek's step: both gain an editable `base_url` field. That is the intended gain from the spec (§7) — their defaults are unchanged, so a user who leaves the field alone gets today's behaviour.

`tests/test_config_flow.py` may submit those steps without `base_url`. Since the field is `vol.Required` with a default, voluptuous fills it in, so the test still passes. **If it does not**, that is a real regression in the flow, not a test to update — fix the schema.

- [ ] **Step 5: Add the five named steps**

After `async_step_anthropic` in the `ConfigFlow` class:

```python
    # Home Assistant dispatches a flow step by method name, so each provider
    # needs its own even though the bodies are identical. A setattr loop would
    # work until HA introspects the class.

    async def async_step_openrouter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_OPENROUTER, user_input)

    async def async_step_groq(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_GROQ, user_input)

    async def async_step_together(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_TOGETHER, user_input)

    async def async_step_lmstudio(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_LMSTUDIO, user_input)

    async def async_step_llamacpp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._common_model_async_step(ID_LLAMACPP, user_input)
```

Add the five `ID_*` names and `OPENAI_COMPATIBLE` to the `from .const import (...)` block.

- [ ] **Step 6: Add the translations**

In `custom_components/smartchain/translations/en.json`, under `config.step`, add five entries and extend the existing `openai` and `deepseek` entries with the new `base_url` field:

```json
"openrouter": {
  "title": "OpenRouter configuration",
  "data": {
    "api_key": "API Key",
    "base_url": "API base URL",
    "skip_validation": "Skip validation"
  }
},
"groq": {
  "title": "Groq configuration",
  "data": {
    "api_key": "API Key",
    "base_url": "API base URL",
    "skip_validation": "Skip validation"
  }
},
"together": {
  "title": "Together configuration",
  "data": {
    "api_key": "API Key",
    "base_url": "API base URL",
    "skip_validation": "Skip validation"
  }
},
"lmstudio": {
  "title": "LM Studio configuration",
  "data": {
    "base_url": "Server URL",
    "api_key": "API Key (optional)",
    "skip_validation": "Skip validation"
  }
},
"llamacpp": {
  "title": "llama.cpp configuration",
  "data": {
    "base_url": "Server URL",
    "api_key": "API Key (optional)",
    "skip_validation": "Skip validation"
  }
}
```

The same five in `ru.json`, with Russian labels:

```json
"openrouter": {
  "title": "Настройка OpenRouter",
  "data": {
    "api_key": "API-ключ",
    "base_url": "Базовый URL API",
    "skip_validation": "Пропустить проверку"
  }
},
"groq": {
  "title": "Настройка Groq",
  "data": {
    "api_key": "API-ключ",
    "base_url": "Базовый URL API",
    "skip_validation": "Пропустить проверку"
  }
},
"together": {
  "title": "Настройка Together",
  "data": {
    "api_key": "API-ключ",
    "base_url": "Базовый URL API",
    "skip_validation": "Пропустить проверку"
  }
},
"lmstudio": {
  "title": "Настройка LM Studio",
  "data": {
    "base_url": "URL сервера",
    "api_key": "API-ключ (необязательно)",
    "skip_validation": "Пропустить проверку"
  }
},
"llamacpp": {
  "title": "Настройка llama.cpp",
  "data": {
    "base_url": "URL сервера",
    "api_key": "API-ключ (необязательно)",
    "skip_validation": "Пропустить проверку"
  }
}
```

Also add `"base_url"` to the existing `openai` and `deepseek` step `data` blocks in **both** files — `en.json` gets `"API base URL"`, `ru.json` gets `"Базовый URL API"`. Without this the last test in Step 1 fails for those two engines, and HA would show the raw key.

- [ ] **Step 7: Run the tests**

Run: `uv run --prerelease=allow pytest tests/test_new_provider_flow.py tests/test_config_flow.py tests/test_subentries.py -q`
Expected: all pass, with `test_config_flow.py` unmodified.

- [ ] **Step 8: Run the whole suite and lint**

Run: `uv run --prerelease=allow pytest tests/ -q`
Run: `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .`

- [ ] **Step 9: Break-it check**

Temporarily delete the `groq` entry from `en.json` and re-run. `test_every_row_has_translations_in_both_locales` must fail naming the locale and engine. Revert.

Then temporarily delete `async_step_groq` and re-run. Both `test_every_row_has_a_named_step` and `test_hosted_provider_flow_creates_an_entry` must fail. Revert.

- [ ] **Step 10: Commit**

```bash
git add custom_components/smartchain/config_flow.py custom_components/smartchain/translations/ tests/test_new_provider_flow.py
git commit -m "feat(providers): config flow for the five new providers

Step schemas come from the table, with a required key for hosted providers
and an optional one for local servers. The base URL is editable everywhere,
which also gives OpenAI and DeepSeek a field they lacked. A test asserts
every row has a step, a schema and labels in both locales."
```

---

### Task 5: Embeddings for table providers

**Files:**
- Modify: `custom_components/smartchain/tools/memory/embeddings.py:84-87` (the `ID_OPENAI` branch)
- Test: `tests/test_embeddings_table_providers.py` (create)

**Interfaces:**
- Consumes: `OPENAI_COMPATIBLE` from Task 1, `supports` from Task 2.
- Produces: `create_embeddings_from_subentry` builds `OpenAIEmbeddings` against the row's base URL for any table provider whose row serves embeddings.

- [ ] **Step 1: Write the failing test**

Create `tests/test_embeddings_table_providers.py`:

```python
"""Embeddings for OpenAI-compatible providers."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigSubentry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    DOMAIN,
    ID_GROQ,
    ID_LMSTUDIO,
    ID_TOGETHER,
    OPENAI_COMPATIBLE,
    SUBENTRY_TYPE_EMBEDDINGS,
)
from custom_components.smartchain.tools.memory.embeddings import (
    EmbeddingsConfigError,
    create_embeddings_from_subentry,
)


def _subentry(model: str) -> ConfigSubentry:
    return ConfigSubentry(
        data={"model": model},
        subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
        title="emb",
        unique_id=None,
    )


def _entry(hass, engine: str, data: dict) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={CONF_ENGINE: engine, **data})
    entry.add_to_hass(hass)
    return entry


async def test_table_provider_uses_its_base_url(hass):
    entry = _entry(hass, ID_TOGETHER, {CONF_API_KEY: "k"})
    with patch(
        "custom_components.smartchain.tools.memory.embeddings.OpenAIEmbeddings"
    ) as emb:
        create_embeddings_from_subentry(hass, entry, _subentry("bge-m3"))
    kwargs = emb.call_args.kwargs
    assert kwargs["model"] == "bge-m3"
    assert kwargs["base_url"] == OPENAI_COMPATIBLE[ID_TOGETHER].default_base_url
    assert kwargs["api_key"] == "k"


async def test_local_provider_gets_a_placeholder_key(hass):
    entry = _entry(hass, ID_LMSTUDIO, {CONF_BASE_URL: "http://localhost:1234/v1"})
    with patch(
        "custom_components.smartchain.tools.memory.embeddings.OpenAIEmbeddings"
    ) as emb:
        create_embeddings_from_subentry(hass, entry, _subentry("nomic-embed-text"))
    assert emb.call_args.kwargs["api_key"] == "not-needed"
    assert emb.call_args.kwargs["base_url"] == "http://localhost:1234/v1"


async def test_provider_without_embeddings_is_refused(hass):
    entry = _entry(hass, ID_GROQ, {CONF_API_KEY: "k"})
    with pytest.raises(EmbeddingsConfigError, match="does not provide embeddings"):
        create_embeddings_from_subentry(hass, entry, _subentry("bge-m3"))


async def test_openai_still_builds_without_a_base_url_override(hass):
    from custom_components.smartchain.const import ID_OPENAI

    entry = _entry(hass, ID_OPENAI, {CONF_API_KEY: "k"})
    with patch(
        "custom_components.smartchain.tools.memory.embeddings.OpenAIEmbeddings"
    ) as emb:
        create_embeddings_from_subentry(hass, entry, _subentry("text-embedding-3-small"))
    assert emb.call_args.kwargs["model"] == "text-embedding-3-small"
    assert emb.call_args.kwargs["api_key"] == "k"
```

`create_embeddings_from_subentry` is **synchronous** — the calls above correctly omit `await`. The test functions are still `async def` so they receive the `hass` fixture.

- [ ] **Step 2: Run to confirm failure**

Run: `uv run --prerelease=allow pytest tests/test_embeddings_table_providers.py -q`
Expected: Together and LM Studio fall through every branch and the function returns `None`, so the assertions on `emb.call_args` fail.

- [ ] **Step 3: Replace the OpenAI branch with a table branch**

In `embeddings.py`, replace:

```python
    if engine == ID_OPENAI:
        return _ExecutorBacked(
            hass, OpenAIEmbeddings(model=model, api_key=entry.data[CONF_API_KEY])
        )
```

with:

```python
    row = OPENAI_COMPATIBLE.get(engine)
    if row is not None:
        kwargs: dict[str, Any] = {
            "model": model,
            "api_key": _compatible_api_key(row, entry.data),
        }
        base_url = (entry.data.get(CONF_BASE_URL) or "").strip()
        if engine != ID_OPENAI or base_url:
            # OpenAI keeps its client default when the user set nothing, so
            # its behaviour is unchanged; every other row needs the endpoint.
            kwargs["base_url"] = base_url or row.default_base_url
        return _ExecutorBacked(hass, OpenAIEmbeddings(**kwargs))
```

Import `OPENAI_COMPATIBLE` and `CONF_BASE_URL` from the const module, and `_compatible_api_key` from `...client_util` (adjust the relative depth — `embeddings.py` sits at `tools/memory/`, so it is `from ...client_util import _compatible_api_key`).

The `supports(...)` guard at the top of the function already refuses Groq and OpenRouter, so `serves_embeddings=False` rows never reach this branch.

- [ ] **Step 4: Run the tests**

Run: `uv run --prerelease=allow pytest tests/test_embeddings_table_providers.py tests/test_memory_embeddings.py -q`
Expected: all pass.

- [ ] **Step 5: Run the whole suite and lint**

Run: `uv run --prerelease=allow pytest tests/ -q`
Run: `uv run --prerelease=allow ruff check . && uv run --prerelease=allow ruff format --check .`

- [ ] **Step 6: Break-it check**

Temporarily drop the `base_url` key from `kwargs` unconditionally. `test_table_provider_uses_its_base_url` must fail. Revert.

- [ ] **Step 7: Commit**

```bash
git add custom_components/smartchain/tools/memory/embeddings.py tests/test_embeddings_table_providers.py
git commit -m "feat(providers): embeddings for OpenAI-compatible providers

Together, LM Studio and llama.cpp can now back the memory and entity index.
OpenAI keeps its client default when no base URL is set, so its behaviour
is unchanged."
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: everything above. Produces: nothing code-facing.

- [ ] **Step 1: Update the provider list in `README.md`**

Find the section listing the six providers and extend it to eleven. Group them so the reader sees the shape:

```markdown
### Providers

**Hosted:** GigaChat, YandexGPT, OpenAI, Anthropic, DeepSeek, OpenRouter, Groq, Together

**Local:** Ollama, LM Studio, llama.cpp

Every provider except GigaChat, YandexGPT, Ollama and Anthropic speaks the
OpenAI API, and each one's base URL is editable — point it at a mirror, a
proxy, or a self-hosted gateway.

Embeddings for long-term memory and the entity index are available from
GigaChat, YandexGPT, OpenAI, Ollama, Together, LM Studio and llama.cpp.
```

Adjust the wording to match the README's existing voice and heading levels — read the surrounding section first rather than pasting this verbatim.

- [ ] **Step 2: Add the CHANGELOG entry**

Under the unreleased `5.0.0` heading, add a bullet in the style of the existing entries:

```markdown
- **New providers**: OpenRouter, Groq, Together, LM Studio and llama.cpp.
  All OpenAI-compatible providers now share one code path driven by a
  provider table, and every one of them has an editable base URL — including
  OpenAI and DeepSeek, which previously had a fixed endpoint.
```

- [ ] **Step 3: Verify no stale count**

Run: `grep -rn "6 providers\|six providers\|шесть провайдеров\|6 провайдеров" README.md CHANGELOG.md docs/ custom_components/`
Expected: no hits. Fix any that appear — the count is now eleven.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: eleven providers, and the editable base URL

Groups the list into hosted and local, and names which providers can serve
embeddings for memory and the entity index."
```

---

## Self-Review

**Spec coverage.** §3 table → Task 1. §3.1 editable base URLs → Tasks 3, 4. §3.2 `default_model` → Task 1 Step 4, Task 3 Step 5. §3.3 derived dicts → Task 1 Step 5. §4 capabilities, classifier, client, discovery, `ENGINE_SCHEMA`, picker → Tasks 1-3. §5 config flow → Task 4. §6 discovery over curated lists → Task 1 (`static_models=[""]` for the proxies). §7 behaviour preservation → the Global Constraint plus Task 3 Step 7. §8 embeddings sub-entry → Task 5. §9 testing → the test file in each task. §10 deferred → nothing to build.

**Placeholder scan.** No "TBD" or "handle edge cases"; every code step carries the code.

**Type consistency.** `OpenAICompatible` field names are identical in Tasks 1, 3, 4 and 5. `_compatible_base_url` and `_compatible_api_key` are defined in Task 3 Step 3 and reused in Tasks 3 and 5, with Task 5 naming the import path. `static_models` is `list[str]` throughout, matching `ENGINE_MODELS`'s existing list values — not the `tuple` the spec's sketch showed, because `ENGINE_MODELS` consumers index and concatenate lists.

**Facts checked while writing this plan, so the implementer need not:** `const.py` does not yet import `dataclass`; `_fetch_openai_compatible_models` takes its URL as the third positional argument; `create_embeddings_from_subentry` is synchronous; `asyncio_mode = "auto"` is set, so async tests need no marker; `SUBENTRY_TYPE_EMBEDDINGS` exists in `const.py`; `CONF_ENGINE_OPTIONS` is a plain list, so Task 1 Step 5 can append to it; and `UNIQUE_ID`, `CONF_ENGINE_OPTIONS`, `ENGINE_MODELS`, `DEFAULT_MODEL`, `MODELS_OPENAI`, `MODELS_DEEPSEEK` and `DEFAULT_DEEPSEEK_BASE_URL` are all defined above line 148, which is why the table goes there.
