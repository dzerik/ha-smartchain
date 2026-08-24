# OpenAI-compatible providers — design

**Date:** 2026-08-24
**Status:** approved, ready for planning
**Release:** part of v5.0.0 (roadmap subsystem **E**)

---

## 1. Goal

Add five providers — OpenRouter, Groq, Together, LM Studio and llama.cpp — and
stop paying nine edits across five files for the next one.

All five speak the OpenAI API. So does DeepSeek, which the integration already
supports by constructing `ChatOpenAI` with a fixed `openai_api_base`. Adding
five more the same way would grow two `elif` chains to eleven links each and
duplicate the same five facts — id, label, base URL, models, capabilities — in
five different places.

This subsystem replaces those chains with **one table and one code path**.

## 2. Scope

**In scope.** A provider table covering every OpenAI-compatible engine,
including the existing OpenAI and DeepSeek; one branch each in client
construction, validation, model discovery and the embedding-name classifier;
config-flow step schemas derived from the table; the capability matrix built
from it; translations for the five new providers.

**Not in scope.** GigaChat, YandexGPT, Ollama and Anthropic keep their
hand-written branches — none of them is OpenAI-compatible and folding them in
would mean a table field per quirk. Changing what any existing provider does.
Adding a generic "bring your own endpoint" provider (§10).

## 3. The table

In `const.py`:

```python
@dataclass(frozen=True)
class OpenAICompatible:
    """One provider reachable through the OpenAI API shape."""

    label: str                     # shown in the provider picker
    default_base_url: str          # pre-filled, always editable
    requires_api_key: bool         # False for a local server
    serves_embeddings: bool        # whether an embeddings sub-entry is offered
    embedding_rule: str            # "openai_prefix" | "heuristic"
    static_models: tuple[str, ...] # fallback when /models is unreachable


OPENAI_COMPATIBLE: dict[str, OpenAICompatible] = { ... }
```

Rows: `openai`, `deepseek`, `openrouter`, `groq`, `together`, `lmstudio`,
`llamacpp`.

Everything else reads this table. Adding a provider is one row plus a
three-line config-flow step (§5) and three translation strings.

### 3.1 The values, and how much they are worth trusting

| id | base URL | key | embeddings | rule |
|---|---|---|---|---|
| `openai` | `https://api.openai.com/v1` | yes | yes | `openai_prefix` |
| `deepseek` | `https://api.deepseek.com` | yes | no | `heuristic` |
| `openrouter` | `https://openrouter.ai/api/v1` | yes | no | `heuristic` |
| `groq` | `https://api.groq.com/openai/v1` | yes | no | `heuristic` |
| `together` | `https://api.together.xyz/v1` | yes | yes | `heuristic` |
| `lmstudio` | `http://localhost:1234/v1` | no | yes | `heuristic` |
| `llamacpp` | `http://localhost:8080/v1` | no | yes | `heuristic` |

`openai` and `deepseek` reproduce today's behaviour exactly.

**The five new rows are stated from knowledge, not from a live check**, and
both the base URLs and the embeddings flags can be wrong. Two decisions follow
from that:

- **Every base URL is editable in the config flow**, not just the local ones.
  A stale default then costs the user one field rather than a dead
  integration. This is the mitigation, and it is why the table has no
  `base_url_editable` flag — the answer is always yes.
- **`serves_embeddings` errs toward `False` for hosted proxies.** A false
  negative means the embeddings sub-entry is not offered for that provider;
  a false positive means a user creates one that fails at first use. Neither
  is good, but the first is quieter and reversible by a one-line table edit,
  and the entity index and memory work fine on another provider meanwhile.

## 4. What reads the table

- **`client_util.get_client` and `validate_client`** — one branch replacing the
  per-provider ones: `ChatOpenAI` with `openai_api_base` from the entry's
  `base_url` (falling back to the row's default) and `openai_api_key` from the
  entry, or a placeholder when `requires_api_key` is `False`.
- **`PROVIDER_CAPABILITIES`** — the rows contribute `{chat}` or
  `{chat, embeddings}`; the four hand-written providers keep their literal
  entries. Built once at import.
- **`async_fetch_models`** — one branch calling the existing
  `_fetch_openai_compatible_models` against `{base_url}/models`.
- **`is_embedding_model`** — dispatches on `embedding_rule`. `openai_prefix`
  is today's `text-embedding-` test; `heuristic` is the regex already used for
  Ollama (`embed|bge-|gte-|e5-|minilm`), which is the right default because
  these providers serve whatever the user or the proxy names, not a curated
  OpenAI catalogue.
- **`config_flow.ENGINE_SCHEMA`** — built from the table, `requires_api_key`
  choosing between the key-and-URL schema and the URL-only one.
- **`CONF_ENGINE_OPTIONS`** — the provider picker, extended from the table.

## 5. Config flow

Home Assistant dispatches a config-flow step by **method name**, so each
provider still needs its own `async_step_<id>`. That is three lines delegating
to the existing `_common_model_async_step`, and it stays explicit rather than
being generated — a `setattr` loop would work until HA introspects the class.

The step schemas are new, and there are two:

```python
STEP_OPENAI_COMPATIBLE_SCHEMA   # api_key required, base_url pre-filled, skip_validation
STEP_LOCAL_COMPATIBLE_SCHEMA    # base_url pre-filled, api_key optional, skip_validation
```

The local one keeps `api_key` optional rather than absent: LM Studio and
llama.cpp accept any string and some deployments sit behind a proxy that wants
one.

`base_url` is `vol.Required` with the row's default pre-filled in both.

## 6. Model discovery

All five serve `GET /models`, so the static lists stay deliberately short — a
placeholder empty option and nothing else for the proxies. **OpenRouter in
particular must not carry a curated list**: it fronts hundreds of models and
any list we write is wrong within weeks. Discovery is the answer, and the
existing fallback-to-static path covers an unreachable endpoint.

`static_models` therefore holds `("",)` for the new rows, and the existing
`MODELS_OPENAI` and `MODELS_DEEPSEEK` for the two rows that already had one.

## 7. Behaviour preservation

`openai` and `deepseek` are folded into the table, which means their code path
changes even though their behaviour must not. The existing tests are the guard:

- `tests/test_fetch_models.py` covers discovery for both.
- `tests/test_config_flow.py` covers their flow steps.
- `tests/test_provider_capabilities.py` covers the matrix.
- `tests/test_embeddings_model_discovery.py` covers `is_embedding_model`.

**None of these may be modified.** If one has to change, the fold changed
behaviour and the change is wrong.

One deliberate difference: DeepSeek's base URL becomes editable, where today it
is a constant. That is a strict gain — a user behind a mirror can now reach it
— and its default is unchanged.

## 8. Capabilities and the embeddings sub-entry

The embeddings sub-entry type (subsystem A) is offered when
`supports(engine, CAPABILITY_EMBEDDINGS)`. With the table, three of the five
new providers offer it — Together, LM Studio, llama.cpp — and OpenRouter and
Groq do not, per §3.1.

`create_embeddings_from_subentry` needs a branch for the table too: it
currently switches on `ID_OPENAI`, `ID_GIGACHAT`, `ID_OLLAMA`, `ID_YANDEX_GPT`.
An OpenAI-compatible provider uses `OpenAIEmbeddings` with the row's base URL,
exactly as the OpenAI branch does today plus the URL.

## 9. Testing

- **The table itself**: every row has a non-empty label and base URL; ids are
  unique and match their `ID_*` constant; a row claiming `openai_prefix` is
  actually OpenAI.
- **Fold preservation**: the four existing test files above pass unmodified.
- **One new provider end to end**: config-flow step renders, client is built
  with the right base URL and key, discovery hits `{base_url}/models`, and the
  capability matrix answers correctly.
- **Local providers**: a flow submitted with no API key succeeds, and the
  client is constructed with a placeholder rather than `None`.
- **`base_url` override**: an entry whose `base_url` differs from the row's
  default is honoured everywhere — client, validation and discovery.
- **Embeddings**: `create_embeddings_from_subentry` builds against the row's
  base URL for a table provider; a provider whose row says no embeddings does
  not offer the sub-entry type.
- **Translations**: the existing AST-driven parity test already covers the
  sub-entry form. The provider picker's labels come from `CONF_ENGINE_OPTIONS`
  and need their own check that every table row has one.

## 10. Deferred

- A generic "OpenAI-compatible endpoint" provider where the user names it.
  Every table row is already that plus a default, so the gap is small, and a
  nameless row in the picker is a poor first impression.
- T-Bank: its models run locally through Ollama or LM Studio today, so a hosted
  row would need an endpoint nobody has confirmed. Dropped on the user's call.
- Folding Ollama into the table. It is OpenAI-compatible at `/v1` in recent
  versions, but it has its own client, its own model-listing API and shipped
  behaviour that a fold would put at risk for no user-visible gain.
- Per-provider rate-limit or context-window metadata.
