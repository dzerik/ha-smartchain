# SmartChain — User Guide

[![en](https://img.shields.io/badge/lang-en-green.svg)](USAGE.md) [![ru](https://img.shields.io/badge/lang-ru-red.svg)](USAGE-ru.md)

This document covers every SmartChain feature with a running example for each. For an overview and feature list, see [README.md](../README.md).

## Table of contents

1. [Installation](#1-installation)
2. [Providers and credentials](#2-providers-and-credentials)
3. [Sub-entries — multiple agents per provider](#3-sub-entries--multiple-agents-per-provider)
4. [Conversation entity options](#4-conversation-entity-options)
5. [Services reference](#5-services-reference)
6. [Built-in conversation tools](#6-built-in-conversation-tools)
7. [Custom tools from YAML](#7-custom-tools-from-yaml)
8. [MCP client — external tool servers](#8-mcp-client--external-tool-servers)
9. [Long-term memory / RAG](#9-long-term-memory--rag)
10. [Multi-agent orchestration](#10-multi-agent-orchestration)
11. [AI Task entity](#11-ai-task-entity)
12. [Sidebar panel — camera analysis](#12-sidebar-panel--camera-analysis)
13. [Skills system](#13-skills-system)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Installation

**Requirements:**
- Home Assistant 2024.12.0 or newer
- [HACS](https://hacs.xyz/) installed

**Via HACS:**
1. Add this repository as a [custom HACS repository](https://hacs.xyz/docs/faq/custom_repositories): `https://github.com/dzerik/ha-smartchain`
2. Search for "SmartChain" in HACS and install
3. Restart Home Assistant
4. **Settings > Devices & Services > Add Integration > SmartChain**

Or click [![Open via HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dzerik&repository=ha-smartchain&category=integration).

---

## 2. Providers and credentials

| Provider | Required field | Where to get it |
|---|---|---|
| GigaChat | `api_key` (Authorization Data) | [developers.sber.ru/studio](https://developers.sber.ru/studio) |
| YandexGPT | `api_key` + `folder_id` | [Yandex Cloud Console](https://cloud.yandex.com) |
| OpenAI | `api_key` | [platform.openai.com](https://platform.openai.com/account/api-keys) |
| Ollama | `base_url` (e.g. `http://localhost:11434`) | local install |
| DeepSeek | `api_key` | [platform.deepseek.com](https://platform.deepseek.com) |
| Anthropic | `api_key` | [console.anthropic.com](https://console.anthropic.com) |

After choosing a provider during setup, SmartChain auto-validates the credentials by making a tiny test call. If it fails the config flow reports the error before creating the entry.

---

## 3. Sub-entries — multiple agents per provider

Each SmartChain config entry can hold **multiple conversation agents** under it ("sub-entries"). Different sub-entries can run different models, system prompts and option sets while sharing the same credentials.

**Create a sub-entry:**

**Settings > Devices & Services > SmartChain > 3-dot menu > Add sub-entry** — fill the form below.

Each sub-entry becomes its own `conversation.smartchain_*` entity. You can assign different sub-entries to different rooms / users / Voice pipelines.

---

## 4. Conversation entity options

These options live on **each sub-entry**:

| Option | Default | Effect |
|---|---|---|
| `model` | provider default | Override the chat model |
| `temperature` | 0.1 | Sampling temperature |
| `max_tokens` | provider default | Response cap |
| `prompt` | system prompt template | Jinja2 system prompt — see §4.1 |
| `llm_hass_api` | unset | Enable HA Assist API (device control via tool calling) |
| `process_builtin_sentences` | true | Try HA's built-in intent parser first; fall back to LLM if no intent matched |
| `chat_history` | true | Send multi-turn history (vs. just current message) |
| `enable_history_tool` | false | Expose `get_state_history` LLM tool |
| `allowed_tools` *(v4.1.0+)* | all | Restrict which custom YAML / MCP tools this agent sees |
| `enable_multi_agent_tools` *(v4.4.0+)* | false | Expose `ask_agents` + `critique_response` tools (only when ≥2 sub-entries exist) |
| `verify_ssl` (GigaChat only) | false | TLS verify toggle for self-signed Sber certs |
| `profanity` (GigaChat only) | false | Enable GigaChat's profanity filter |

### 4.1. Custom system prompt

The default prompt declares the assistant's role and lists the home's rooms / devices via `{{ states }}` and `{{ areas() }}` Jinja helpers. Override it freely:

```jinja2
You are {{ ha_name }} — a helpful home assistant in {{ states('zone.home') }}.
Be concise. Time of day: {{ now().strftime('%H:%M') }}.
{% if states('binary_sensor.someone_home') == 'on' %}
Someone is home. Use a casual tone.
{% else %}
House is empty. Keep responses brief.
{% endif %}
```

`{{ ha_name }}` is provided automatically. All HA template functions (`states`, `state_attr`, `area_devices`, `area_name`, `now`, etc.) are available.

---

## 5. Services reference

### 5.1. `smartchain.ask`

Send a text prompt to a SmartChain agent from any automation, Telegram bot, REST call, etc.

```yaml
service: smartchain.ask
data:
  message: "What is the temperature in the kitchen?"
  entity_id: conversation.smartchain_main   # optional — routes to a specific agent
```

Returns `{"response": "<text>"}`. If `entity_id` is omitted the first available agent is used. Provider-side auth errors return a generic message (full detail in the HA log) — your API keys never leak into the response.

### 5.2. `smartchain.analyze_image`

Take a camera snapshot and feed it to a multimodal LLM (GigaChat, OpenAI gpt-4o, Anthropic Claude, etc.).

```yaml
service: smartchain.analyze_image
data:
  camera_entity_id: camera.front_door
  message: "Who is at the door? Describe in 1-2 sentences."
  entity_id: conversation.smartchain_vision   # optional — agent to use
  notify_entity: notify.mobile_app_phone      # optional — also send via notify
```

Side effects:
- Returns `{"response": "<analysis text>"}`
- Fires bus event `smartchain_image_analyzed` with the response, camera entity, query and timestamp
- Updates `sensor.smartchain_last_analysis` via dispatcher signal — the state is the first 255 chars, attribute `full_response` is capped at 4 KiB

**Automation example — motion-triggered porch check:**

```yaml
automation:
  - alias: "Porch motion — describe scene"
    trigger:
      - platform: state
        entity_id: binary_sensor.porch_motion
        to: "on"
    action:
      - service: smartchain.analyze_image
        data:
          camera_entity_id: camera.porch
          message: "Briefly describe what's happening on the porch."
          notify_entity: notify.mobile_app_phone
```

### 5.3. `smartchain.reload_tools` *(v4.1.0+)*

Re-reads `/config/smartchain/tools.yaml`, restarts MCP server connections, rebuilds the long-term memory subsystem — atomically. On YAML validation failure the previous state is preserved.

```yaml
service: smartchain.reload_tools
```

Fires `smartchain_tools_reloaded` with the new tool count on success. Use after editing `tools.yaml` or `memory:` config.

### 5.4. `smartchain.clear_memory` *(v4.3.0+)*

Delete stored memories with optional filters.

```yaml
service: smartchain.clear_memory
data:
  store: conversations  # optional (v4.5.0+) — omit to clear every store
  kind: conversation    # any | conversation | logbook (default: any)
  agent_id: conversation.smartchain_main   # optional — limit to one agent
```

Fires `smartchain_memory_cleared` with `{"deleted": <int>, "stores": [<names>]}`. Raises `HomeAssistantError` if the memory subsystem isn't configured, or if `store` names a store that isn't.

---

## 6. Built-in conversation tools

Every conversation turn that involves the LLM may call these tools. Each is gated by an option or by repository state.

| Tool | Enabled when | What it does |
|---|---|---|
| HA Assist API tools (lights, switches, climate…) | `llm_hass_api` set on subentry | Control devices via tool calls |
| `get_state_history` | `enable_history_tool: true` | Read past device states from the recorder |
| `ask_agent` | ≥ 2 sub-entries | Delegate the question to a specific sibling |
| `ask_agents` *(v4.4.0+)* | `enable_multi_agent_tools: true` + ≥ 2 sub-entries | Parallel fan-out to several siblings (see §10) |
| `critique_response` *(v4.4.0+)* | same | Ask a sibling to review a draft answer (see §10) |
| `search_memory` *(v4.3.0+)* | at least one store in the `memory:` block | Semantic search over conversation + logbook embeddings (see §9) |
| Custom YAML tools | `tools:` block in YAML | User-declared tools (see §7) |
| MCP tools | `mcp_servers:` block in YAML | Discovered automatically per server (see §8) |

The LLM decides on its own when to call each tool — you don't dispatch them directly. The tool result is returned to the model, which may produce a follow-up tool call or a final text answer.

### 6.1. `get_state_history` example

Turn it on per sub-entry. Then:

> User: *"Was the front door opened in the last 2 hours?"*
>
> Assistant calls `get_state_history(entity_id="binary_sensor.front_door", hours=2)`, gets back the state-change list, and answers:
> *"Yes — it opened at 17:43 and closed at 17:45."*

---

## 7. Custom tools from YAML

Declare your own LLM-callable tools in `/config/smartchain/tools.yaml`. Each tool has a name, description, JSON-Schema parameters block, and an `action` describing what to do when the tool is called.

Four action types: `service`, `template`, `rest`, `script`. Arguments are validated against the JSON Schema before execution; templated strings inside the action are Jinja-rendered with the LLM-supplied arguments as the variable scope.

### 7.1. Minimal example — `service` action

```yaml
tools:
  - name: turn_on_light
    description: Turn on a light in a specific room.
    parameters:
      type: object
      properties:
        area:
          type: string
          enum: [kitchen, living_room, bedroom]
        brightness_pct:
          type: integer
          minimum: 1
          maximum: 100
      required: [area]
    action:
      type: service
      domain: light
      service: turn_on
      target:
        area_id: "{{ area }}"
      data:
        brightness_pct: "{{ brightness_pct | default(100) }}"
```

After saving, call `smartchain.reload_tools` (or restart). Now the LLM can pick this tool whenever the user says something like *"Turn the kitchen lights to 30%"*.

### 7.2. `template` action — return rendered Jinja string

```yaml
- name: list_recent_motion
  description: Get rooms with motion in the last hour.
  parameters:
    type: object
    properties: {}
  action:
    type: template
    value_template: |
      {%- set sensors = states.binary_sensor | selectattr('attributes.device_class', 'eq', 'motion') -%}
      {%- for s in sensors if (now() - s.last_changed).total_seconds() < 3600 -%}
      {{ s.attributes.friendly_name }}{% if not loop.last %}, {% endif %}
      {%- endfor -%}
```

### 7.3. `rest` action — HTTP request to external service

```yaml
- name: get_weather_forecast
  description: Fetch weather forecast for a city.
  parameters:
    type: object
    properties:
      city: { type: string }
    required: [city]
  action:
    type: rest
    method: GET
    url: "https://api.example.com/forecast?q={{ city }}"
    headers:
      Authorization: !secret weather_api_authorization
    timeout: 10
    response_format: json   # or "text"
```

`!secret` is resolved by HA's loader against `secrets.yaml` (§9.2). It is a **whole-value** tag: it replaces one entire YAML scalar and cannot be spliced into the middle of a string, and it must not be quoted — `"Bearer !secret my_key"` is just a literal string that would be sent verbatim. Put the complete value in `secrets.yaml` instead, `Bearer ` prefix included:

```yaml
# <config>/secrets.yaml
weather_api_authorization: "Bearer 0123456789abcdef"
```

Non-2xx responses become `"Error: HTTP <status>"`. Network failures and timeouts likewise yield clean error strings — no exception text reaches the LLM.

### 7.4. `script` action — invoke an HA script

```yaml
- name: morning_routine
  description: Run the morning routine script.
  parameters:
    type: object
    properties:
      name: { type: string }
  action:
    type: script
    script: script.morning_routine
    variables:
      user_name: "{{ name }}"
```

### 7.5. Per-agent visibility

By default every sub-entry sees every YAML tool. To restrict, set `allowed_tools` on a sub-entry:

```yaml
# In the SmartChain sub-entry options UI:
allowed_tools:
  - turn_on_light
  - list_recent_motion
```

Semantics: missing/`None` = all tools available; empty list `[]` = no custom tools; explicit list = only those names.

### 7.6. Reserved names

`get_state_history` and `ask_agent` are reserved built-in tool names — using them in YAML drops the entry with an error logged at startup.

---

## 8. MCP client — external tool servers

SmartChain can connect to remote MCP (Model Context Protocol) servers and surface their tools alongside YAML and built-in tools. Three transports: `stdio` (subprocess), `sse` (Server-Sent Events) and `http` (streamable HTTP).

### 8.1. Configure in `tools.yaml`

```yaml
mcp_servers:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/config/notes"]
    env:
      NODE_ENV: production
    prefix: filesystem            # default = name; "" disables prefixing
    include_tools: ["list_directory", "read_file"]
    exclude_tools: []
    enabled: true

  - name: brave_search
    transport: sse
    url: https://example.com/mcp/brave
    headers:
      # Whole-value tag, unquoted; secrets.yaml holds "Bearer <token>".
      Authorization: !secret brave_authorization
    timeout: 30
    verify_ssl: true

  - name: github
    transport: http
    url: https://api.example.com/mcp/github
    headers:
      Authorization: !secret github_authorization
```

After saving, call `smartchain.reload_tools`.

### 8.2. Tool naming

Each MCP server's tools are registered as `<prefix>__<sanitised_name>` to avoid collisions. Example: a tool called `list-directory` on server `filesystem` becomes `filesystem__list_directory`. Set `prefix: ""` to skip prefixing (advanced).

### 8.3. Reliability

- One slow or failed server doesn't affect the others.
- Auto-reconnect with exponential backoff (1 s → 30 s).
- Per-call timeout (default 30 s).
- `verify_ssl: false` is honoured for SSE/HTTP transports via a custom httpx client factory.

### 8.4. Per-agent visibility

The same `allowed_tools` filter from §7.5 applies — list MCP tools by their **registered name** (`<prefix>__<tool>`) to limit which agents can use them.

---

## 9. Long-term memory / RAG

Persist conversation turns and (opt-in) HA logbook entries as embeddings in a vector store. The LLM recalls them through the built-in `search_memory` tool.

**v4.5.0 reshaped this feature.** Embeddings are now a **provider capability** configured as a sub-entry — credentials never appear in `tools.yaml`. The vector store is **pluggable**, and the default backend needs nothing installed beyond what Home Assistant already ships. If you are upgrading from v4.3.x / v4.4.x, read §9.8 first: the old flat `memory:` block is rejected on purpose.

Setting it up is two steps: create an embeddings sub-entry (§9.1), then declare one or more stores that reference it (§9.2).

### 9.1. Step 1 — create an embeddings sub-entry

**Settings > Devices & Services > SmartChain > 3-dot menu > Add embeddings binding.**

The form asks for three fields, of which you fill in two:

- **Name** — the sub-entry title. This is the handle `tools.yaml` refers to, so pick something stable and unique across *all* SmartChain config entries. If two sub-entries share a title, SmartChain refuses to bind either rather than guessing, and logs an error naming the clash.
- **Embedding model** — a dropdown of the provider's embedding models.
- **Custom model name** — a free-text field for a model the provider's API doesn't advertise (a local Ollama pull, for example). Leave it empty to use the dropdown.

**A model is mandatory.** Fill in exactly one of the two model fields: leaving both empty is rejected with *"Either Model or Custom Model required"* and the form is redisplayed. When both are filled the non-empty custom name wins over the dropdown selection.

Credentials are inherited from the config entry. There is nothing else to fill in — an embeddings binding has no prompt, no tools and no temperature.

> **Capability caveat.** The **Add embeddings binding** option is only offered by providers that actually expose an embeddings API. **DeepSeek and Anthropic do not**, so the menu entry is absent on their config entries. If those are your only providers, add a second config entry for a provider that does — a local Ollama entry costs nothing and can serve embeddings only.

| Provider | Embedding models offered |
|---|---|
| GigaChat | `Embeddings`, `EmbeddingsGigaR` |
| YandexGPT | `text-search-doc`, `text-search-query` |
| OpenAI | `text-embedding-3-small`, `text-embedding-3-large` |
| Ollama | `nomic-embed-text`, `mxbai-embed-large`, `bge-m3` |
| DeepSeek, Anthropic | — no embeddings API |

Model lists are fetched live from the provider where possible and filtered by purpose, so chat forms no longer offer embedding models and vice versa. The table above is the built-in fallback used when the provider's API is unreachable.

Recommended starting point: **Ollama + `nomic-embed-text`** — local, free, privacy-friendly. Cloud providers receive the full text of everything you embed.

### 9.2. Step 2 — declare stores in `tools.yaml`

A **store** binds one embeddings sub-entry to one vector backend and carries its own retention and ingest settings. The smallest working configuration is two lines:

```yaml
memory:
  stores:
    - name: conversations
      embeddings: "Ollama nomic"
```

That gives you the `sqlite_numpy` backend, 90-day retention, conversation ingest on and logbook ingest off.

A fuller, two-store example:

```yaml
memory:
  stores:
    - name: conversations
      description: "Past conversations with the household"
      embeddings: "Ollama nomic"
      backend:
        type: sqlite_numpy
      retention_days: 30
      ingest_conversation: true
      ingest_logbook:
        enabled: true
        domains: [light, climate, lock, alarm_control_panel]
        poll_interval_minutes: 60

    - name: house_events
      description: "Long-lived history of device events"
      embeddings: "OpenAI embeddings"
      backend:
        type: pgvector
        dsn: "postgresql://smartchain:CHANGE_ME@db.example.local:5432/smartchain"
        table: smartchain_memory
      retention_days: 0
      ingest_conversation: false
      ingest_logbook:
        enabled: true
        domains: [binary_sensor, lock, cover]
        poll_interval_minutes: 120
```

| Field | Required | Default | Meaning |
|---|---|---|---|
| `name` | yes | — | Store identifier, must match `^[a-z_][a-z0-9_]*$` and be unique in the list. Also names the SQLite file for file-based backends. |
| `embeddings` | yes | — | Title of the embeddings sub-entry to bind (§9.1). |
| `description` | no | `""` | Shown to the LLM in the `search_memory` schema — write it so the model can pick the right store. |
| `backend` | no | `{type: sqlite_numpy}` | Vector backend selection, see §9.3. |
| `retention_days` | no | `90` | Daily cleanup horizon, 0–3650. `0` disables cleanup for that store. |
| `ingest_conversation` | no | `true` | Whether conversation turns are written to this store. |
| `ingest_logbook` | no | disabled | `enabled` (bool), `domains` (list), `poll_interval_minutes` (5–1440, default 60). |

Call `smartchain.reload_tools` after editing. Validation errors are raised there with a message naming the offending key, and the previous configuration stays live.

> **`!secret` works in `tools.yaml`.** SmartChain reads the file through Home Assistant's YAML loader with a secrets store rooted at the configuration directory, so a `!secret` tag resolves from `<config>/smartchain/secrets.yaml` if present and otherwise from `<config>/secrets.yaml` — the same lookup HA uses for `configuration.yaml`. A pgvector `dsn` or a Qdrant `api_key` belongs there rather than in `tools.yaml`:
>
> ```yaml
> # <config>/secrets.yaml
> smartchain_pg_dsn: "postgresql://smartchain:CHANGE_ME@db.example.local:5432/smartchain"
> ```
> ```yaml
> # <config>/smartchain/tools.yaml
>       backend:
>         type: pgvector
>         dsn: !secret smartchain_pg_dsn
> ```
>
> Two rules: the tag replaces **one whole scalar**, so it cannot be spliced into the middle of a string, and it must **not** be quoted — `"!secret x"` is an ordinary string, not a tag. A name that is missing from `secrets.yaml` fails the reload with *"Secret \<name\> not defined"*; the message names the key, never any value.

### 9.3. Vector backends

Every store picks its own backend. All four implement the same contract, so you can start on the default and move a store later without changing anything else.

| Backend | Extra install | When to use |
|---|---|---|
| `sqlite_numpy` | none | Default. Every installation. Up to ~50 000 records per store. |
| `sqlite_vec` | `pip install sqlite-vec` | Same file layout, native KNN. Needs a Python build with extension loading. |
| `pgvector` | `pip install asyncpg` + PostgreSQL | Large stores; natural if HA's recorder already runs on PostgreSQL. |
| `qdrant` | a Qdrant server | Large stores without PostgreSQL. No Python dependency. |

**`sqlite_numpy` (default) — no installation step at all.** Storage is stdlib `sqlite3`, similarity is a numpy cosine over the candidate rows, and both ship with Home Assistant. Long-term memory therefore works out of the box on every install.

```yaml
      backend:
        type: sqlite_numpy
        path: /config/smartchain/conversations.db   # optional
```

Without `path` the database lands at `<config>/.storage/smartchain_memory/<store name>.db`, so several stores coexist without colliding. Past ~50 000 records the backend logs a one-off warning suggesting `pgvector` or `qdrant`; it keeps working, just more slowly.

**`sqlite_vec`** — same file layout and same `path` option, but the search runs in the `vec0` virtual table instead of numpy. It needs `pip install sqlite-vec` **and** a Python build compiled with `enable_load_extension`, which is not universally true. If either is missing the store is disabled with a log line naming `sqlite_numpy` as the drop-in replacement.

**`pgvector`** — needs `pip install asyncpg` in Home Assistant's Python environment and a PostgreSQL database whose user is allowed to run `CREATE EXTENSION`: SmartChain issues `CREATE EXTENSION IF NOT EXISTS vector` at startup. If your user is not a superuser, have an administrator run that statement once against the database beforehand, and the startup call then becomes a no-op. An HNSW cosine index is created when the server supports it.

```yaml
      backend:
        type: pgvector
        dsn: "postgresql://smartchain:CHANGE_ME@db.example.local:5432/smartchain"
        table: smartchain_memory
```

`table` defaults to `smartchain_memory`; give each store its own table when they share a database. Connection failures are logged in full but reported without the DSN, so credentials never reach the LLM or a service response.

**`qdrant`** — no Python dependency: SmartChain speaks Qdrant's REST API over Home Assistant's shared aiohttp session. You only need a reachable Qdrant server. The collection is created on first start with cosine distance.

```yaml
      backend:
        type: qdrant
        url: "https://qdrant.example.local:6333"
        api_key: "CHANGE_ME"
        collection: smartchain_memory
        verify_ssl: true
```

`collection` defaults to `smartchain_memory`; `api_key` is optional for an unauthenticated server; set `verify_ssl: false` for a self-signed certificate.

Every backend operation is bounded by a 30 s timeout, and a backend that fails to start disables only its own store.

### 9.4. Embedding dimension is pinned per store

At startup SmartChain embeds a short probe string, measures the vector length and hands that width to the backend, which records it. If the store's embeddings sub-entry later points at a model of a different width, the mismatch is detected *before* anything is written:

> `stored embedding dimension is 768 but the configured model produces 1536. Delete the database file /config/.storage/smartchain_memory/conversations.db, then call smartchain.reload_tools.`

That store is disabled and the others keep running. Vectors of different widths are never mixed, so the index cannot be silently corrupted.

**`smartchain.clear_memory` cannot fix a dimension mismatch.** A store that fails to initialise never enters the registry, so the service answers *"unknown memory store"* — and clearing rows would not help anyway, because the recorded dimension (the `vector(N)` column type, the `vec0` table, the Qdrant collection's vector size) outlives a row delete. The stored artefact has to be removed by hand. Each backend's error message names exactly which one:

| Backend | What the message tells you to remove |
|---|---|
| `sqlite_numpy` | *Delete the database file `<path>`* — the `.db` file, at `path:` or `<config>/.storage/smartchain_memory/<store name>.db`. |
| `sqlite_vec` | *Delete the database file `<path>`* — same file and same default location. |
| `pgvector` | *Drop the table `<table>` in the configured database* — e.g. `DROP TABLE smartchain_memory;`. |
| `qdrant` | *Delete the collection `<collection>` on the Qdrant server* — e.g. `DELETE /collections/smartchain_memory`. |

Then call `smartchain.reload_tools` and the store rebuilds at the new width.

To change a store's embedding model deliberately — there is no automatic re-embedding, so the old vectors have to go:

1. Remove the store's artefact as in the table above (file, table or collection).
2. Point the binding at the new model (**3-dot menu > Reconfigure embeddings binding**).
3. `smartchain.reload_tools`.

`smartchain.clear_memory` is the right tool for emptying a *working* store — see §9.7 — not for a width change.

### 9.5. How it surfaces to the LLM

Every conversation turn schedules a background task per store that has `ingest_conversation: true`. Each task embeds and stores `User: <q>\n\nAssistant: <a>` with metadata `{kind: conversation, timestamp, agent_id, subentry_id, conversation_id}`. One slow provider cannot hold up another store.

The `search_memory` tool is added to the LLM's tool list whenever at least one store came up. Its schema lists the store names and their descriptions, so the model can choose:

> User: *"Remind me what I said yesterday evening about the dishwasher."*
>
> Assistant calls `search_memory(query="dishwasher", kind="conversation", store="conversations")`, gets back the relevant past turns, and answers using them.

- `store` is **required when two or more stores are configured** and optional with exactly one — with a single store there is nothing to disambiguate.
- The tool also filters by the calling agent's `subentry_id`, so agents retrieve only their own memories (privacy guard).
- `kind` is `conversation`, `logbook` or `any` (default); `top_k` defaults to 5 and is capped at 20.

### 9.6. Logbook ingest (opt-in)

Set `ingest_logbook.enabled: true` on a store and SmartChain periodically imports HA logbook entries — filtered to the configured `domains` — as `kind: logbook` memories. The LLM can then ask `search_memory(query="…", kind="logbook")`, or leave `kind` at `any` to search both.

Polling is per store, so one store can follow the logbook while another stays conversation-only.

> **Note:** logbook ingest depends on HA logbook internals (`logbook.humanify` / `_get_events`). On HA versions where those names are absent the poller silently imports nothing. Conversation ingest is unaffected.

### 9.7. Clearing memory

Use the `smartchain.clear_memory` service (§5.4). It filters by `kind` and/or `agent_id`, and takes an optional `store`:

```yaml
service: smartchain.clear_memory
data:
  store: conversations   # optional — omit to clear every store
  kind: conversation     # any | conversation | logbook (default: any)
```

Omitting `store` clears every configured store. The `smartchain_memory_cleared` event carries `{"deleted": <int>, "stores": [<names>]}`.

File-based stores live at `<config>/.storage/smartchain_memory/<store name>.db` unless the store set `backend.path`.

### 9.8. Migrating from v4.4.x

The v4.3.0 / v4.4.x block looked like this and is **no longer accepted**:

```yaml
memory:
  enabled: true
  provider: ollama
  model: nomic-embed-text
  api_key: "…"
```

Because credentials moved out of YAML, there is nothing to migrate it *to* until an embeddings sub-entry exists, so SmartChain rejects the old shape loudly instead of guessing. `smartchain.reload_tools` fails with a message naming the offending keys and the three steps:

1. Create an embeddings sub-entry on the provider's config entry (§9.1), giving it a name and an embedding model.
2. Replace the `memory:` block with a `stores:` list whose `embeddings:` field holds that name (§9.2).
3. Call `smartchain.reload_tools`.

**Chroma is gone.** `chromadb` and `langchain-chroma` are removed from the manifest and from the codebase — the `pip install chromadb` step older versions of this guide described no longer applies, and is exactly the failure v4.4.1 had to work around. If `<config>/.storage/smartchain_memory/` holds a Chroma directory from an earlier version it is now orphaned and can be deleted; no data is converted. On most installations it is empty anyway, because HA's pip step could not install `chromadb`.

### 9.9. Persistence and resilience

- Embeddings are computed via `hass.async_add_executor_job` (no event-loop blocking) with a 30 s timeout per call; backend operations get their own 30 s bound.
- A failure is contained to one store: a missing sub-entry title, a duplicated title, an unreachable backend or a dimension clash disables that store, logs the reason, and lets every other store start.
- A failing embeddings provider does not crash the conversation — the failure is logged at WARNING and the turn is not ingested.
- A per-store daily retention task deletes entries older than `retention_days` (timestamps normalised to UTC). `retention_days: 0` disables it.
- `smartchain.reload_tools` rebuilds the registry atomically: the new one is built first and only swapped in on success, so a bad edit leaves the running stores untouched.

---

## 10. Multi-agent orchestration

When you have **two or more conversation sub-entries** in a single SmartChain config entry, they can talk to each other via three tools.

### 10.1. Enable

On each sub-entry that should be allowed to *initiate* multi-agent calls:

- Open the sub-entry options.
- Toggle **Enable multi-agent tools** *(v4.4.0+, hidden when there's only one sub-entry)*.

This adds `ask_agents` and `critique_response` to that agent's tool list. The single-delegation `ask_agent` tool is always available when siblings exist (no opt-in required).

### 10.2. `ask_agent` — single delegation

> Agent A: I don't have the kitchen sensor in scope. Let me ask "Kitchen Specialist".
>
> `ask_agent(agent_name="Kitchen Specialist", message="What's the oven temperature?")` → returns the answer.

### 10.3. `ask_agents` *(v4.4.0+)* — parallel fan-out

> User: *"Plan tomorrow — weather, what to buy, calendar?"*
>
> Agent: `ask_agents(agents=["weather", "shopping", "calendar"], query="What's on for tomorrow?")`
>
> Both 3 siblings run in parallel via `asyncio.gather`. Result:
> ```
> Responses from 3 agents:
>
> [weather] Sunny, 18°C.
> [shopping] You need milk, bread and eggs.
> [calendar] 14:00 dentist appointment.
> ```
> Agent then summarises for the user.

Bounds: `MULTI_AGENT_MAX_PARALLEL = 5`, per-agent timeout 60 s, duplicates de-duplicated, failures become `"[<agent>] Error: …"` strings.

### 10.4. `critique_response` *(v4.4.0+)* — second-opinion review

> Main agent has a draft answer. Before sending it for a safety-critical action it asks:
>
> `critique_response(reviewer="security", original_question="…", candidate_answer="…")`
>
> Reviewer replies with a 3-5 sentence assessment. Main agent reads it and decides whether to revise the answer or proceed.

### 10.5. Recursion guard

When you delegate to a sibling through `ask_agent` / `ask_agents` / `critique_response`, the sibling is invoked with a plain text prompt and **no tools attached** — they cannot recursively delegate further. Depth is bounded at 1.

---

## 11. AI Task entity

When the `ai_task` integration is present in HA, SmartChain registers an AI Task entity per sub-entry. This is the recommended way to produce **structured data** from LLM responses in automations.

```yaml
automation:
  - alias: "Daily fridge inventory"
    trigger:
      - platform: time
        at: "20:00:00"
    action:
      - service: ai_task.generate_data
        data:
          entity_id: ai_task.smartchain_main
          task_name: "fridge_inventory"
          instructions: "List items in the fridge based on the latest camera image."
          attachments:
            media_content_id: media-source://camera/camera.fridge
          structure:
            type: object
            properties:
              items:
                type: array
                items: { type: string }
              expiring_soon:
                type: array
                items: { type: string }
        response_variable: result
      - service: persistent_notification.create
        data:
          message: "Items: {{ result.items | join(', ') }}"
```

The response is validated against `structure` and returned as a dict.

For downstream integrations, `smartchain.async_generate_structured()` is re-exported from `custom_components.smartchain` as a public helper.

---

## 12. Sidebar panel — camera analysis

Click **SmartChain AI** in the HA sidebar to open the panel. Pick any camera entity, type a question, and the LLM returns a description. The result is mirrored to `sensor.smartchain_last_analysis` (proper SensorEntity since v4.0.2) and the `smartchain_image_analyzed` event for automation use.

The panel calls `smartchain.analyze_image` under the hood — same behaviour as the service.

---

## 13. Skills system

Drop YAML files into `/config/smartchain/skills/`. Each skill file:

```yaml
name: locks_safety
description: Rules for door/lock control
prompt: |
  Never unlock the front door without confirmation from the home owner.
  Garage door auto-closes after 5 minutes if left open.
```

Skills are appended to the LLM's system prompt at conversation start (executor-offloaded for cold reads). They're a lightweight alternative to long system prompts when you want shared rules across all agents.

To reload skills, restart HA or reload the config entry.

---

## 14. Troubleshooting

### "No SmartChain agent available."
The `smartchain.ask` service couldn't find any agent. Check **Settings > Devices & Services > SmartChain** — does it have at least one conversation sub-entry with `runtime_data` set?

### Custom tools aren't showing up
1. Check `/config/smartchain/tools.yaml` syntax: `python -c "import yaml; yaml.safe_load(open('/config/smartchain/tools.yaml'))"`.
2. Call `smartchain.reload_tools` — it raises `HomeAssistantError` on validation failures with a clear message.
3. Check HA log for `Tool <name> uses a reserved built-in name; skipping` or `Duplicate tool name`.

### MCP server unavailable
- `stdio`: confirm the `command` binary (`npx`, `python`, etc.) is on the HA container's PATH; check log for the subprocess startup error.
- `sse` / `http`: confirm URL reachable from HA; for self-signed certs use `verify_ssl: false`.
- Failures are isolated per server — other MCP servers and YAML tools keep working.

### Memory: "Memory is not configured for this installation."
The `search_memory` tool was called but no store came up. Either `tools.yaml` has no `memory.stores[]` entry, or every store failed to start — check the log for the per-store reason (see §9.9).

### Memory: a store references an embeddings sub-entry that doesn't exist
The log names the missing title and lists the available ones. The `embeddings:` field matches the sub-entry **title**, exactly — check for a typo or a renamed sub-entry. A title claimed by two sub-entries is refused too; rename one.

### Memory: "the flat memory: block was replaced in v4.5.0"
You are carrying a v4.3.x / v4.4.x `memory:` block with `provider` / `model` / `api_key`. Follow the three migration steps in §9.8.

### Memory: dimension mismatch on startup
The store's embeddings sub-entry now points at a model of a different width than the one already stored. `smartchain.clear_memory` cannot fix this — the store never came up, so the service does not know it. Remove the stored artefact the error message names (the `.db` file, the pgvector table or the Qdrant collection), then call `smartchain.reload_tools` — see §9.4.

### Embeddings provider unreachable
- The embeddings sub-entry is offered only by providers that have an embeddings API — not DeepSeek, not Anthropic (§9.1).
- Ollama: check it's running and reachable at the config entry's base URL; pull the model (`ollama pull nomic-embed-text`).
- Cloud providers: verify the config entry's credentials and that the model name matches the provider's spelling.
- Failures log at WARNING; conversation continues without ingest.

### LLM error: provider exception text not visible
By design. v4.0.2 added a security boundary — provider errors (which may embed API keys) are logged at ERROR via `LOGGER.exception` but the user-facing service response is a generic `"LLM request failed; see Home Assistant logs for details."` Check HA logs for the real error.

### Logs

All SmartChain log lines come from the `custom_components.smartchain.*` logger. Add to `/config/configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.smartchain: debug
```
