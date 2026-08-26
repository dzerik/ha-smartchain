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
7. [Custom tools](#7-custom-tools)
8. [MCP client — external tool servers](#8-mcp-client--external-tool-servers)
9. [Long-term memory / RAG](#9-long-term-memory--rag)
10. [Multi-agent orchestration](#10-multi-agent-orchestration)
11. [AI Task entity](#11-ai-task-entity)
12. [Sidebar panel](#12-sidebar-panel)
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
| OpenRouter *(v5.0.0+)* | `api_key` | [openrouter.ai](https://openrouter.ai) |
| Groq *(v5.0.0+)* | `api_key` | [console.groq.com](https://console.groq.com) |
| Together *(v5.0.0+)* | `api_key` | [api.together.xyz](https://api.together.xyz) |
| LM Studio *(v5.0.0+)* | `base_url` (default: `http://localhost:1234/v1`) — no API key needed | local install |
| llama.cpp *(v5.0.0+)* | `base_url` (default: `http://localhost:8080/v1`) — no API key needed | local install |

After choosing a provider during setup, SmartChain auto-validates the credentials by making a tiny test call. If it fails the config flow reports the error before creating the entry.

Every provider except GigaChat, YandexGPT, Ollama and Anthropic speaks the OpenAI API, and its `base_url` is editable in the config flow — point OpenRouter, Groq, Together, OpenAI or DeepSeek at a mirror, a proxy or a self-hosted gateway. Defaults are unchanged, so an existing OpenAI or DeepSeek entry that never touched the field behaves exactly as before.

**Local OpenAI-compatible servers.** LM Studio and llama.cpp need no API key — leave that field empty. Load a model and start the server, then create the SmartChain entry against its `base_url`:
- **LM Studio** — load a model in the app, start its local server (default `http://localhost:1234/v1`).
- **llama.cpp** — run `llama-server -m <model.gguf>` (default `http://localhost:8080/v1`).

Either one plugs into every SmartChain feature that consumes a chat model, and both can also serve embeddings if the loaded model supports them.

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
| `dynamic_entity_context` *(v5.0.0+)* | **true** | Send a compact map of the home plus the entities the message is about, instead of every entity — see §9.11 |
| `dynamic_context_preset` *(v5.0.0+)* | `optimal` | Which entities that map covers — see §9.11 |
| `dynamic_context_on_assist` *(v5.0.0+)* | false | Also add the matched entities when the Assist API is on — see §9.11 |
| `allowed_tools` *(v4.1.0+, reshaped in v5.4.0)* | all | The one list of everything this agent may call — built-in tools and your own — see §7.5 |
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
  store: conversations  # optional (v5.0.0+) — omit to clear every store
  kind: conversation    # any | conversation | logbook (default: any)
  agent_id: conversation.smartchain_main   # optional — limit to one agent
```

Fires `smartchain_memory_cleared` with `{"deleted": <int>, "stores": [<names>]}`. Raises `HomeAssistantError` if the memory subsystem isn't configured, or if `store` names a store that isn't.

> **Clearing an entity index rebuilds it** *(v5.0.0+)*. If the cleared store has a `source:` block (§9.10), a reconciling sweep is scheduled in the background straight after the delete, so the index comes back from the live registries. The deletion is not permanent, and the rebuild re-embeds everything. See §9.10.

### 5.5. `smartchain.reindex_entities` *(v5.0.0+)*

Force a sweep of an entity index (§9.10) instead of waiting for a registry change or a restart.

```yaml
service: smartchain.reindex_entities
data:
  store: entities   # optional — omit to sweep every entity index
  full: false       # optional — true re-embeds everything
```

Only entities whose catalogue text changed are re-embedded, so an ordinary call is cheap. `full: true` ignores the fingerprints and re-embeds everything — needed only when the embedding model changed but the entities did not.

Fires `smartchain_entities_reindexed` with `{"stores": [<names>], "new": <int>, "changed": <int>, "removed": <int>, "unchanged": <int>}`. Raises `HomeAssistantError` if no entity index is configured, or if `store` names one that isn't.

---

## 6. Built-in conversation tools

Every conversation turn that involves the LLM may call these tools. Since v5.4.0 each is
gated by **one** thing — the agent's `allowed_tools` list — plus, for some, a structural
precondition it cannot work without. Expand an agent's tools cell in the panel's **Agents**
tab to see the whole list, including what is off and why.

| Tool | Enabled when | What it does |
|---|---|---|
| HA Assist API tools (lights, switches, climate…) | `llm_hass_api` set on subentry | Control devices via tool calls |
| `get_state_history` | listed in `allowed_tools` | Read past device states from the recorder |
| `ask_agent` | listed, **and** ≥ 2 conversation sub-entries on this entry | Delegate the question to a specific sibling |
| `ask_agents` *(v4.4.0+)* | same | Parallel fan-out to several siblings (see §10) |
| `critique_response` *(v4.4.0+)* | same | Ask a sibling to review a draft answer (see §10) |
| `search_memory` *(v4.3.0+)* | listed, **and** at least one store configured | Semantic search over conversation + logbook embeddings (see §9) |
| `search_entities` *(v5.0.0+)* | listed, **and** at least one store with a `source:` block | Find an entity by describing it, when the `entity_id` is unknown (see §9.10) |
| Custom tools | listed, or covered by `"*"` | Your own tools, from the Tools tab or `tools.yaml` (see §7) |
| MCP tools | listed, or covered by `"*"` | Discovered automatically per server (see §8) |

The LLM decides on its own when to call each tool — you don't dispatch them directly. The tool result is returned to the model, which may produce a follow-up tool call or a final text answer.

### 6.1. `get_state_history` example

Turn it on per sub-entry. Then:

> User: *"Was the front door opened in the last 2 hours?"*
>
> Assistant calls `get_state_history(entity_id="binary_sensor.front_door", hours=2)`, gets back the state-change list, and answers:
> *"Yes — it opened at 17:43 and closed at 17:45."*

---

## 7. Custom tools

A custom tool is an LLM-callable action you define: a name, a description, a
JSON-Schema `parameters` block describing its arguments, and an `action` saying
what to do when the model calls it. Four action types: `service`, `template`,
`rest`, `script`. Arguments are validated against the JSON Schema before
execution; templated strings inside the action are Jinja-rendered with the
LLM-supplied arguments as the variable scope.

**There are two ways to write one, and they produce the same tool** — plus a
catalogue of ready-made ones you do not have to write at all.

### 7.0. Ready-made tools *(v5.4.6+)* — a set you switch on

The **Tools** tab opens with a **Ready-made tools** block above your own tools.
Each row is a real tool with a switch; flip it and the tool exists.

| Tool | What it gives the model |
|---|---|
| `weather_forecast` | The forecast for the coming days or hours — Assist only reports the weather *now* |
| `sun_times` | Sunrise, sunset, dawn and dusk |
| `calendar_events` | Events from a calendar over a date range |
| `todo_list_items` | Reads a to-do or shopping list back — Assist can only add to one |
| `area_summary` | What is on in one room, in a single call |
| `who_is_home` | Presence, without assembling it from entity names |
| `look_at_camera` | Looks at a camera mid-conversation and describes what it sees |
| `notify_device` | Sends a notification, so the agent can reach you rather than only answer |

Each takes the entity as an *argument*, so one `weather_forecast` serves every
weather entity in the house.

Nothing about an installed preset stays special: it is a tool sub-entry, it
appears in the list below with source **built here**, and Edit, disable and
Delete all work on it. The switch goes on and stays on — removing it is Delete
in the list below, where the button says what it does.

The catalogue deliberately does **not** duplicate Home Assistant's own Assist
API (turning things on and off, setting lights and climate, adding to lists) or
our built-in tools (§6). Energy over a period, a sensor's min/max/mean and
recent logbook events are absent for a different reason: they live in the
recorder's statistics and the logbook, which are reachable only over the
websocket API, and doing them properly means a built-in tool rather than a
preset.

A preset whose name is already taken — by one of your tools or by a connected
MCP server — is refused with the reason, exactly as the form refuses it. A
`tools.yaml` tool of the same name is *not* a conflict: installing shadows it,
and the panel says so (§7.7).

### 7.0.1. The Tools tab *(v5.3.0+)* — build one without YAML

Open the SmartChain panel and pick **Tools**, or add a **Tool** sub-entry from
Settings → Devices & Services. Either way you get a form:

- **Name**, **what it does** and **enabled** are plain fields.
- **What happens when the model calls it** is a picker, and the rest of the form
  changes to match it. A `service` tool asks for an action and a target — both
  pickers, not text boxes; a `script` tool asks for a script entity; a `rest`
  tool asks for a method, URL, headers, body and timeout.
- **Arguments** is a row per argument — name, type, description, required. This
  is the JSON Schema, built for you.
- For a schema rows cannot express (`anyOf`, nested objects, arrays), switch
  **How the arguments are described** to `advanced` and write the JSON Schema
  directly. It is validated before it is saved, and again against every call.

A tool built here is stored by Home Assistant, not in a file. `tools.yaml` keeps
working — see §7.7 for how the two sources combine.

> **REST header values are write-only.** A header is where an `Authorization`
> token goes, so once saved its value never travels back to the browser: the
> form shows the header's name with an empty value, and leaving it empty keeps
> what is stored. Type a new value to replace it; delete the row to remove it.

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

`allowed_tools` is the single control over what one agent may call. It offers the six
built-in tools (labelled as built-in) alongside every custom and MCP tool, and it renders
whether or not you have any custom tools:

```yaml
# In the SmartChain sub-entry options UI:
allowed_tools:
  - "*"                # every custom tool
  - search_memory      # a built-in needs its own name
  - get_state_history
```

Semantics: missing/`None` = no restriction; `"*"` = every *custom* tool (not built-ins);
an explicit name = that tool, built-in or custom; empty list `[]` = nothing.

A tool added *after* an agent was given an explicit list is not granted to it — that is
deliberate, and since v5.4.0 it applies to built-ins as well.

> **Upgrading from 5.3 or earlier:** `enable_history_tool` and `enable_multi_agent_tools`
> were separate switches, and `allowed_tools` filtered custom tools only. Config entries
> migrate automatically: each agent's built-ins are written into its list and the switches
> are removed, so no agent gains or loses a tool.

### 7.6. Reserved names

All six built-in tool names are reserved: `get_state_history`, `ask_agent`, `ask_agents`, `critique_response`, `search_memory` and `search_entities`. Using one in `tools.yaml` drops the entry with an error logged at startup; using one in the Tools tab is refused while you are still looking at the name.

> **Three of these were only reserved from v5.3.0.** Before that, a custom tool named `search_memory`, `ask_agents` or `critique_response` was registered alongside the built-in and appended last, so the model read the built-in's description while the call resolved to the custom tool. If you have such a tool, rename it — after upgrading it is skipped rather than silently winning.

### 7.7. Two sources, one registry *(v5.3.0+)*

Tools come from three places and land in one registry: the Tools tab (config sub-entries), `tools.yaml`, and connected MCP servers. The Tools tab lists all three and says which is which, because it can only edit the first.

- **A name defined both in a sub-entry and in `tools.yaml` resolves in favour of the sub-entry**, for the same reason a memory store does: the sub-entry is the one the UI can edit. The shadowing is never silent — logged as a warning, reported by `smartchain/tool/list`, and shown on the tab.
- **Import** turns the tools in `tools.yaml` into editable sub-entries. It leaves the file alone, so every imported tool then shadows its copy; delete the copies when you are satisfied. A file using `!secret` **anywhere** is refused outright: importing would have to resolve the secret and write the resolved value into `.storage` as plain text, quietly moving a credential out of `secrets.yaml`.
- **Export** writes the sub-entry tools back out as YAML. REST header values are exported blank and the affected tools are named, for the same reason the form never shows them.
- `mcp_servers:` and `memory:` are not importable and have no constructor here — MCP servers are configured in `tools.yaml`, memory stores on the Stores tab.

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

**v5.0.0 reshaped this feature.** Embeddings are now a **provider capability** configured as a sub-entry — credentials never appear in `tools.yaml`. The vector store is **pluggable**, and the default backend needs nothing installed beyond what Home Assistant already ships. If you are upgrading from v4.3.x / v4.4.x, read §9.8 first: the old flat `memory:` block is rejected on purpose.

Setting it up is two steps: create an embeddings sub-entry (§9.1), then declare one or more stores that reference it (§9.2).

**A store can also index the home itself** rather than the conversation. Give it a `source:` block and it becomes a semantic index of your entities, searchable by the LLM through `search_entities` — see §9.10.

### 9.1. Step 1 — create an embeddings sub-entry

**Settings > Devices & Services > SmartChain > 3-dot menu > Add embeddings binding.**

The form asks for three fields, of which you fill in two:

- **Name** — the sub-entry title. This is the handle `tools.yaml` refers to, so pick something stable and unique across *all* SmartChain config entries. If two sub-entries share a title, SmartChain refuses to bind either rather than guessing, and logs an error naming the clash.
- **Embedding model** — a dropdown of the provider's embedding models.
- **Custom model name** — a free-text field for a model the provider's API doesn't advertise (a local Ollama pull, for example). Leave it empty to use the dropdown.

**A model is mandatory.** Fill in exactly one of the two model fields: leaving both empty is rejected with *"Either Model or Custom Model required"* and the form is redisplayed. When both are filled the non-empty custom name wins over the dropdown selection.

Credentials are inherited from the config entry. There is nothing else to fill in — an embeddings binding has no prompt, no tools and no temperature.

> **Capability caveat.** The **Add embeddings binding** option is only offered by providers that actually expose an embeddings API. **DeepSeek, Anthropic, OpenRouter and Groq do not**, so the menu entry is absent on their config entries. If those are your only providers, add a second config entry for a provider that does — a local Ollama entry costs nothing and can serve embeddings only.

| Provider | Embedding models offered |
|---|---|
| GigaChat | `Embeddings`, `EmbeddingsGigaR` |
| YandexGPT | `text-search-doc`, `text-search-query` |
| OpenAI | `text-embedding-3-small`, `text-embedding-3-large` |
| Ollama | `nomic-embed-text`, `mxbai-embed-large`, `bge-m3` |
| Together, LM Studio, llama.cpp *(v5.0.0+)* | discovered live from the provider's model list by name pattern (`embed`, `bge-`, `gte-`, `e5-`, `minilm`) — no static fallback list |
| DeepSeek, Anthropic, OpenRouter, Groq | — no embeddings API |

Model lists are fetched live from the provider where possible and filtered by purpose, so chat forms no longer offer embedding models and vice versa. The table above is the built-in fallback used when the provider's API is unreachable — except for Together, LM Studio and llama.cpp, which have none: if their API is unreachable while creating the sub-entry, only the **Custom model name** field works.

Recommended starting point: **Ollama + `nomic-embed-text`** — local, free, privacy-friendly. Cloud providers receive the full text of everything you embed.

### 9.2. Step 2 — declare stores

A **store** binds one embeddings sub-entry to one vector backend and carries its own retention and ingest settings. There are two ways to create one, and they build the same thing.

**In the UI *(v5.2.0+)*, which is the recommended way.** **Settings > Devices & Services > SmartChain > Add memory store**, or the **Stores** tab of the SmartChain panel. Every option below is a field on that form, and the Stores tab additionally shows whether each configured store actually came up.

> **Step 1 first.** A store must name an embeddings binding, and the field is a dropdown over the bindings that exist — with none, there is nothing to pick. The Stores tab says so above the form and holds **Save** until you have made one on the **Embeddings** tab *(v5.4.7+)*.

Prefer the UI when the backend needs a credential. `backend.dsn` embeds a PostgreSQL password and `backend.api_key` is a qdrant token; written in `tools.yaml` they are handed to your browser whenever the panel's Tools tab opens that file. A store sub-entry keeps them in `.storage` and never serves them back — the form shows an empty field and "leave empty to keep the stored one".

**In `tools.yaml`**, which keeps working unchanged. The smallest working configuration is two lines:

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
| `source` | no | absent | Turns the store into an entity index instead of a conversation store, see §9.10. Present means the three keys above are rejected. |

Call `smartchain.reload_tools` after editing. Validation errors are raised there with a message naming the offending key, and the previous configuration stays live. A store created in the UI needs no reload — the command that writes it rebuilds the registry itself.

> **A store defined in both places resolves in favour of the sub-entry** *(v5.2.0+)*, because the sub-entry is the one the UI can edit; losing to a file the panel cannot safely rewrite would make the UI a read-only display of something it appears to control. The shadowing is never silent: it is logged as a warning, reported by `smartchain/store/status`, and shown on the Stores tab. Delete the block from `tools.yaml` once you have moved a store.

> **A store form has no logbook-ingest switch.** `ingest_logbook` above still parses, but the poller reaches for `logbook._get_events` / `logbook.humanify`, which the installed Home Assistant no longer exposes — it is a runtime no-op today. Shipping a live toggle over that would advertise something the code cannot do, so the field exists in YAML only, and starts working again the day the fetcher does.

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

> **An entity index does not stay cleared.** A store with a `source:` block (§9.10) is swept again in the background immediately after the delete, so it rebuilds itself from the live registries and the rebuild re-embeds everything. The event still reports only the number deleted, so it will not hint at this. To actually switch an entity index off, remove its `source:` block — or the store — and call `smartchain.reload_tools`.

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

### 9.10. Entity index *(v5.0.0+)* — find a device by describing it

A memory store can be pointed at the home itself instead of at conversations. Give it a `source:` block and it becomes a **semantic index of your entities**, which the LLM searches through the built-in `search_entities` tool.

It exists for the queries that name matching cannot answer. *"What makes the coffee"* shares no word with `switch.kitchen_socket_3`, and *"what can I dry my hair with"* shares none with the socket the hair dryer is plugged into. What those queries do share is meaning with the entity's name, its area and — most valuable of all — the aliases you gave it yourself, and a vector search over that text finds them.

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

`source:` is optional and everything else about the store is unchanged, so a store without it stays an ordinary conversation store. Both kinds can coexist in the same `stores:` list — the entity index and the conversation memory usually want different backends anyway.

Call `smartchain.reload_tools` after adding the block.

#### Presets

The preset decides which entities are indexed. Four are available, and they are **monotonic** — each is a superset of the one above it, so widening the scope never drops anything.

| Preset | What it selects |
|---|---|
| `minimal` | Only what a person controls: `light`, `switch`, `cover`, `climate`, `lock`, `fan`, `media_player`, `scene`, `script`, `vacuum`, `water_heater`, `humidifier`, `valve`. Entities in the `config` or `diagnostic` entity category are left out. |
| `optimal` **(default)** | `minimal` plus the whole of `button`, `input_boolean`, `input_select`, `input_number`, `select`, `number`, `alarm_control_panel`, `person` and `weather`; plus `sensor` and `binary_sensor` whose device class is one of `temperature`, `humidity`, `illuminance`, `pressure`, `motion`, `occupancy`, `presence`, `door`, `window`, `opening`, `garage_door`, `smoke`, `gas`, `moisture`, `carbon_monoxide`, `carbon_dioxide`, `power`, `energy`, `sound`, `vibration`, `problem`. `config` and `diagnostic` are left out here too. |
| `maximal` | Every entity that is neither hidden nor disabled, whatever its domain, device class or entity category. Diagnostics, `update.*` and `device_tracker.*` are all in. |
| `paranoid` | `maximal` plus hidden and disabled entities. |

Battery levels, signal strengths and the rest of the housekeeping device classes are deliberately absent from `optimal`: they dominate a real home by count and nobody ever searches for them. Add them back with `include:` if you disagree.

Two things that surprise people:

- **`maximal` and `paranoid` index Home Assistant's own internal entities** — `conversation.home_assistant`, `zone.home`, `sun.sun` and the like. This is correct rather than a leak: the candidate set is the union of the entity registry *and* the state machine, because template sensors, groups and legacy YAML platform entities never reach the registry at all. Restricting the sweep to the registry would silently gut exactly what `maximal` promises. It still reads as noise the first time you look at the index.
- **A disabled entity has no state at all.** Under `paranoid` it therefore contributes a catalogue entry and nothing else; `search_entities` reports its state as `unavailable`, because there is no state to report.

#### `include` and `exclude`

Both take a list whose entries are either a bare domain or a full `entity_id`. `include` is additive on top of the preset; `exclude` is applied last and **wins over both the preset and `include`**. Anything that is neither a valid domain nor a valid `entity_id` is a schema error, caught at reload.

```yaml
      source:
        type: entities
        preset: minimal
        include:
          - media_player
          - sensor.washing_machine_power
        exclude:
          - scene
          - switch.boiler_relay
```

That indexes the controllable domains, adds every `media_player` and one specific power sensor, then drops every `scene` and one specific switch.

#### Keys that are rejected on an entity store

Three keys that a conversation store accepts are **rejected outright** — not ignored — when `source.type: entities` is present, and the reload fails naming them:

| Key | Why |
|---|---|
| `retention_days` | Retention deletes documents by age. An entity is not stale because it is old, and a retention pass would quietly eat the index. |
| `ingest_conversation` | Conversation turns must not be written into an entity index. |
| `ingest_logbook` | Nor logbook entries. |

The check runs against the raw YAML before defaults are applied, so it only fires on a key you actually wrote — a store that simply omits `ingest_conversation` is fine even though the key defaults to `true`.

#### `index_states`

Off by default, and off is the right choice for most installations.

**When off** no state listener is registered at all, and the stored metadata carries no `state` field.

**When on** the indexer subscribes to state changes *for the indexed entities only*, coalesces them, and writes them into each document's metadata every 30 seconds. It issues **no embedding calls** — the state is never part of the embedded text, which is precisely why a restart is free.

What it buys is a `state` field in each document's metadata, for anything that reads the store directly. What it does **not** change is what `search_entities` returns: the `state=` argument is always matched against the live state, never against stored metadata. Filtering inside the store would prune vector hits against a value up to 30 seconds old — and arbitrarily older for an entity that has not changed since its last sweep — throwing away exactly the matches the search was for. What it does not buy either is better search: cosine similarity over `"on"`, `"off"` and `"23.5"` is weak, and that is not what the mode is for.

**Leaving it off costs nothing in freshness.** The state that `search_entities` reports is read live from `hass.states` at answer time in either mode, so it is never stale. Passing `state=` to a store with `index_states: false` is not an error either — the filter is applied after the live read in both modes, and the caller gets the same answer.

#### `search_entities`

The tool is added to the LLM's tool list as soon as at least one store has an entity source.

| Parameter | Required | Default | Meaning |
|---|---|---|---|
| `query` | yes | — | A description of the device — what it is, or what it does. |
| `top_k` | no | `10` | How many results to return, 1–50. |
| `domain` | no | — | Restrict to one domain, e.g. `light`. |
| `area` | no | — | Restrict to one area, by name. |
| `state` | no | — | Restrict to a current state, e.g. `on`. |
| `store` | with 2+ entity indexes | — | Which index to search. Optional with exactly one. |

> User: *"Turn off whatever makes the coffee."*
>
> Assistant calls `search_entities(query="coffee machine")` and gets:
>
> ```
> Found 2 entities:
> 1. switch.kitchen_socket_3 — Кофеварка [switch, Кухня] = on
> 2. sensor.kitchen_socket_3_power — Кофеварка потребление [sensor, Кухня] = 812
> ```
>
> …then calls the Assist API to turn `switch.kitchen_socket_3` off. The tool returns entity ids, so they can be used directly in a service call.

Two passes run and merge. The **lexical** pass matches case- and accent-folded text against the friendly name, the aliases, the area and the `entity_id`, exactly and by prefix or substring. The **vector** pass searches the store, with `domain` and `area` translated into a metadata filter — `state` is not, because stored state lags the live one; it is applied afterwards against `hass.states`. Exact lexical hits rank first, then prefix hits, then vector hits by score, deduplicated by `entity_id` and truncated to `top_k`.

Lexical matching is not a consolation prize: on *"свет на кухне"* a name match is both faster and more accurate than cosine similarity. It also reads the registries directly rather than the index, which is what makes the fallback real — **`search_entities` keeps working when the store is unavailable.** A down embeddings provider degrades it to name matching instead of silencing it.

No match returns a sentence saying so and naming the filters that were applied, so the model can retry with fewer.

#### `smartchain.reindex_entities`

Forces a sweep now, rather than waiting for a registry change or a restart.

```yaml
service: smartchain.reindex_entities
data:
  store: entities   # optional — omit to sweep every entity index
  full: false       # optional — true re-embeds everything
```

Fires `smartchain_entities_reindexed` with `{"stores": [<names>], "new": <int>, "changed": <int>, "removed": <int>, "unchanged": <int>}`. A `store` that does not exist, or that exists but has no entity source, raises `HomeAssistantError` naming the entity indexes that do — sweeping nothing silently would be indistinguishable from success.

**`full: true` answers exactly one situation: the embedding model changed but the entities did not.** A normal sweep compares fingerprints of the catalogue *text*, so it would correctly report everything unchanged while every stored vector still came from the old model. `full: true` ignores the fingerprints and re-embeds the lot. Note that a change of embedding *dimension* is a different problem with a different fix — see §9.4.

#### What it costs

Sweeps are incremental. Every document stores a fingerprint of its catalogue text. A sweep fetches all stored fingerprints in **one** call, then embeds only the entities that are new or whose text changed, deletes the documents whose entity dropped out of scope, and skips everything else entirely.

- The **first** sweep embeds every selected entity once.
- Every later sweep — including the one after each Home Assistant restart — embeds only what actually changed. **A restart with an unchanged home costs zero embedding calls.**
- Renaming an entity, moving it to another area, changing its device name or adding an alias re-embeds that one entity. Renaming an *area* re-embeds everything in it.
- Narrowing the preset removes what dropped out of scope on the next sweep; no manual purge is needed.

If you are paying per token, the first sweep is the only bill worth estimating. As rough magnitudes for a home whose state machine holds around 1 500 entities: a few dozen documents under `minimal`, roughly 200–400 under `optimal`, and all ~1 500 under `maximal` or `paranoid`. Each document is one short catalogue entry, capped at 900 characters so it never splits into several chunks.

Sweeps run at Home Assistant startup as a background task — never inline, because a thousand embeddings must not delay startup — after registry changes with a 5-second debounce, and on `smartchain.reindex_entities`.

#### Clearing an entity index rebuilds it

`smartchain.clear_memory` on a store with an entity source deletes its documents and then **schedules a reconciling sweep in the background**, so the index comes back from the live registries within moments. That is deliberate: a cleared entity index that nothing rebuilt would read, from the outside, as *"`search_entities` finds nothing, permanently"*, until some unrelated registry event happened to trigger a sweep.

Two consequences worth planning for. The rebuild **re-embeds everything**, because there are no stored fingerprints left to compare against — so on a paid provider, clearing an entity index costs as much as the first sweep did. And clearing is **not** a way to switch the index off: to do that, remove the store's `source:` block, or the store itself, and call `smartchain.reload_tools`.

The `smartchain_memory_cleared` event reports only the number of documents deleted and will not tell you that the sweep happened; the sweep's own summary line in the log will.

#### Privacy — read this before choosing a preset

Indexing sends the catalogue text of every selected entity to your embeddings provider: the friendly name, the area name, the device name and **the aliases you wrote yourself**. If that provider is a cloud API, that is your home's layout and naming scheme leaving the house. This is inherent to how the feature works, not a defect in it, but it should be a decision rather than a surprise.

Specifics worth knowing before you pick:

- **`optimal`, the default, includes `person` entities** — the names of the people in your household.
- **`maximal` and `paranoid` add `device_tracker`** — who is home and where, by device.
- **`paranoid` sends the entire home**, diagnostics included, plus the hidden and disabled entities the UI deliberately keeps out of sight.

To keep it tight, do one or both of these:

- Use a **local embeddings provider**. Ollama with `nomic-embed-text` runs on your own hardware and nothing leaves the network.
- Use **`preset: minimal` plus `include:`**, naming only the entities you actually want findable. `exclude:` drops specific entities or whole domains from any preset and always wins, so it works as a redaction list on top of a wider preset too.

Nothing else about an entity is sent: **states are never embedded**, in any mode, and no credential ever enters a catalogue entry, an index log line, a tool result or the `smartchain_entities_reindexed` payload. Entity ids and area names do appear in log lines — they are not credentials.

### 9.11. Dynamic entity context *(v5.0.0+)* — the prompt stops carrying the whole home

**This one is on by default**, so an existing agent changes behaviour the moment you upgrade.

Until v5.0.0 the system prompt rendered every area, every device and every entity with its current state, on every single turn. In a home with a thousand entities that is most of the prompt, paid for on every message, and it buries the two or three entities the user actually asked about.

Now the prompt carries two much smaller blocks instead:

- a **skeleton** — one line per area, entity names grouped by domain, no ids and no states. It is always complete for the configured scope, so the model can always see the shape of the home.
- a **retrieved block** — only the entities this particular message is about, with their entity ids, areas and live states.

The split is the whole idea. Retrieval on its own answers *"what state is X in"* well and *"what exists"* badly: *"включи свет"* matches a dozen lamps, *"выключи всё"* matches nothing in particular, and an entity the user happened to describe with unlucky words does not surface at all — whereupon the model, seeing no such entity in its context, answers that the device does not exist. Keeping the skeleton always present and always complete is what makes that failure impossible.

**One checkbox restores the old behaviour.** Turn `dynamic_entity_context` off on the sub-entry and the agent renders the full device dump again, byte for byte, through the same cache it always used. Nothing else about the turn changes. It is the master switch for the whole feature, the Assist extension below included: with it off, `dynamic_context_on_assist` does nothing whatever its own checkbox says.

| Option | Default | Effect |
|---|---|---|
| `dynamic_entity_context` | **`true`** | Send the skeleton plus the retrieved block instead of the full device dump |
| `dynamic_context_preset` | `optimal` | Which entities the skeleton covers — one of `minimal` / `optimal` / `maximal` / `paranoid` |
| `dynamic_context_on_assist` | `false` | Also add the retrieved block when `llm_hass_api` is set |

How many entities the retrieval may add is **not** an option: it is the constant `ENTITY_CONTEXT_MAX_ENTITIES`, currently 12. Every extra option is a support surface, and if 12 turns out to be wrong it should change in one place for everybody.

#### What the skeleton looks like

```
Кухня — light: Потолочный, Подсветка; sensor: Влажность, Температура; switch: Кофеварка, Чайник
Спальня — climate: Кондиционер; light: Люстра, Бра
No area — binary_sensor: Входная дверь; vacuum: Пылесос
```

One line per area; inside it, the entity names grouped by domain.

- **Domain labels are the Home Assistant domain itself** — `light`, `switch`, `sensor` — left in English, exactly as the entity index's catalogue entries already are.
- **Names are friendly names**, resolved `name → original_name → entity_id`, the same way the entity index resolves them.
- **Areas come alphabetically and the unassigned entities come last**, under a `No area` line, rather than being dropped. An entity nobody put in a room is exactly the kind a user forgets exists.
- Within an area the domains are alphabetical and the names follow `entity_id` order, so an unchanged home renders an identical map every turn.
- **No entity ids, no device classes, no states, no device grouping.**

That last point surprises people, so it is worth saying why. **Without the Assist API the model has no Home Assistant control tools at all.** The conversation entity builds its tool list from `chat_log.llm_api.tools`, and Home Assistant fills that in only when `llm_hass_api` is configured. On the path this feature targets the device context is therefore purely informational — the model answers questions about the home rather than acting on it, except through whatever custom YAML or MCP tools you defined, which take their own arguments. An `entity_id` in the skeleton would buy the model nothing. Ids live in the retrieved block, where there are at most twelve of them and where the Assist opt-in below makes them actionable.

Per entity the skeleton costs roughly 12–20 characters against 60–90 in the dump it replaces. Note that the two are built from different candidate sets: the old dump only ever listed entities that belong to a *device* that sits in an *area*, so it silently skipped helpers, template entities and anything unassigned, while the skeleton uses the same candidate resolution the entity index does. Under `optimal` that is a much shorter prompt over a wider map; under `maximal` or `paranoid` the skeleton can name things the old prompt never did.

#### The skeleton is bounded, and says so when it truncates

A skeleton longer than `ENTITY_SKELETON_MAX_CHARS` — 6 000 characters, roughly 300–500 entities — would stop being a map and start being the dump it replaced. So areas are emitted until the budget is spent, and whatever did not fit is replaced by a final line naming what went missing:

```
… and 27 more area(s) holding 540 entities — use search_entities to look any of them up.
```

An area so large that it could not fit whole even on a fresh budget is rendered as far as it goes and carries its own note, in the same voice:

```
… 118 more entities in Гараж — use search_entities to look them up.
```

**Nothing is ever silently truncated.** A model that quietly lost half the home would be confidently wrong about it; a model that is told what it cannot see can go and look it up.

The rendered skeleton is cached per preset and shared by every agent. `entity_registry_updated`, `device_registry_updated` and `area_registry_updated` invalidate it — the same three events the entity indexer listens to — with a 300-second TTL as a backstop for a change that somehow raises none of them. It does not depend on states, so a light turning on does not rebuild it.

#### Scope — `dynamic_context_preset`

The skeleton covers whatever `dynamic_context_preset` selects, and the four presets are exactly the ones the entity index uses: `minimal`, `optimal` (the default), `maximal` and `paranoid`, with the same monotonic membership. See the preset table in §9.10 for what each one selects.

**It is a separate setting from any entity store's `source.preset`, deliberately.** Someone running both sets both. Coupling them would make the prompt's scope change whenever somebody edited an unrelated index, which is a worse surprise than a second setting.

One difference from §9.10 worth holding in mind: this preset decides what reaches the **chat** provider, in the prompt, on every turn — not what reaches the embeddings provider. `paranoid` here means the names of the hidden and disabled entities go to your LLM on every message.

**It is also independent of Home Assistant's own "expose entities to Assist" setting.** Candidates come from `dynamic_context_preset` and nothing else, so with `dynamic_context_on_assist` on, the retrieved block can name entities you deliberately withheld from Assist — with their entity ids and their live states. Narrow `dynamic_context_preset` if that matters to you; SmartChain does not filter by exposure.

#### No entity index is required

This is the part most easily missed. **Dynamic entity context needs no memory store, no embeddings sub-entry and no vector backend.** The skeleton is built from the entity, device and area registries, and retrieval's lexical pass reads those same registries directly — case- and accent-folded matching against the friendly name, the aliases, the area and the `entity_id`. With nothing configured beyond the integration itself, the feature is fully operational.

Note that here the query is a whole user sentence, not a phrase a model composed for a search tool, so it is matched **both whole and word by word**: nothing in your home is called *"включи свет на кухне"*, but *"свет"* is a word of *"Потолочный свет"*. The word pass compares **whole words to whole words**, never substrings — *"turn off the light"* does not reach an entity called *"Office"* through *"off"*, and *"what is the temperature"* does not reach a *"Thermostat"* through *"the"*. Words shorter than three characters are ignored, and a whole-phrase hit still outranks a word hit, so a device whose name is the entire query comes first. `search_entities` (§9.10) keeps matching its `query` whole and by substring, because a model picks that one deliberately.

Two details keep the word pass from returning half the house:

- **Word hits are ranked by how many words matched.** An entity matching *"kitchen"* and *"light"* comes above one matching *"light"* alone. Without that they tie, and the entity you actually named finishes wherever it happens to sit in the list.
- **The domain part of the `entity_id` is not matched.** Only the object id is — `light.kitchen_ceiling` contributes *kitchen* and *ceiling*, never *light*. Every entity of a domain shares its domain word, so matching it would make any sentence containing *"light"* pull in every lamp you own at an identical score. Use the `domain` argument of `search_entities` when you want a whole domain.

**Word matching is literal — there is no stemming, and inflected forms do not match.** *"на кухне"* yields the word *кухне*, which does not match an area named *Кухня*; *"lights"* does not match *"Light"*. Retrieval finds the words the user actually typed, in the form they typed them. This is a real limit rather than a rare edge case in Russian, where almost every noun in a sentence is inflected — and it is precisely what the always-present skeleton covers for: the model still sees *Кухня* and everything in it by name, so an inflected miss costs the live states of that turn, not knowledge that the room exists. A configured entity index closes much of the remaining gap, since the vector pass is not literal.

A configured entity index (§9.10) adds a second pass on top: a vector search over the store, merged with the lexical hits by the same ranking `search_entities` uses — exact lexical first, then prefix, then vector by score, deduplicated by `entity_id`. Word hits sit inside that prefix group, below a whole-phrase prefix hit and ordered among themselves by how many words matched, so they still rank **ahead of every vector hit**. That is worth knowing on a broad query: a common word shared by dozens of entity names produces dozens of equally weak word hits, and since the merged list is cut to twelve, they can fill every slot and leave the semantic pass with none. The lexical pass also stops after 200 candidates in registry order rather than keeping the best ones, so on such a query the strongest word match may not be among the twelve at all. A narrower phrasing, or `search_entities` with a `domain` or `area` argument, gets the index back in play. The vector pass runs only when there is **exactly one** entity index; with two or more there is no non-arbitrary choice and no user to ask, so retrieval stays lexical rather than silently preferring one index over another.

#### The retrieved block

```
Mentioned in this request:
- light.kitchen_ceiling — Потолочный [Кухня] = on
- switch.kitchen_socket_3 — Кофеварка [Кухня] = off
```

States are read live from `hass.states` at render time, never from a store's stored metadata — the same rule `search_entities` follows. An entity with no state reads `unavailable`; an entity with no area shows `—`. An empty result renders nothing at all, not an empty heading.

An entity can appear twice on a turn: by name in the skeleton and in full in the retrieved block. That repetition is deliberate and cheap. The two blocks answer different questions, and suppressing the skeleton entry would make the map of the home change shape depending on what was asked — the exact instability the skeleton exists to prevent.

#### `search_entities` still covers the rest

Automatic retrieval sees one message and can miss. `search_entities` (§9.10) stays available to the model for precisely those cases, and the skeleton's truncation lines point at it by name. It does need an entity index to exist — the tool is registered only when at least one store has a `source:` block — whereas the automatic retrieval described here does not.

#### The Assist path — opt-in, and the retrieved block only

When `llm_hass_api` is set, Home Assistant injects its own list of exposed entities and its own control tools. That list is Home Assistant's and we have no way to shrink it, so **by default this feature does nothing at all on the Assist path**: no skeleton, no retrieved block, no change of any kind.

Turn `dynamic_context_on_assist` on and exactly one thing is added: the **retrieved block**, appended to `extra_system_prompt` after whatever it already held, which is preserved untouched. Never the skeleton — that would duplicate Home Assistant's list at full price.

What it buys is the semantic hits a name-based exposure list does not surface, in a form the model can act on, since the block carries entity ids and the Assist tools take them. What it costs is tokens on every turn, on top of a prompt that already carries HA's own list. Hence: off by default.

**Both switches must be on.** `dynamic_entity_context` gates this path too, so unticking the master switch silences the Assist extension whatever `dynamic_context_on_assist` says. And the block's candidates come from `dynamic_context_preset`, not from Home Assistant's exposed-entity list — see the scope note above for what that means for an entity you kept out of Assist on purpose.

#### What it does not do

**Retrieval runs on the latest message alone.** Not on the conversation history. A follow-up like *"а выключи его"* therefore retrieves on a pronoun, and the retrieved block for that turn comes back empty or beside the point.

That is deliberate rather than unfinished: folding older turns into the query retrieves the *previous* subject, which is at least as often wrong as right. It degrades gracefully precisely because the skeleton is always there — the model still sees the whole home by name, still has the earlier turns in its own chat history, and still has `search_entities` when an index is configured. That is the honest boundary of the feature.

#### If something fails

Layered, so a turn is never lost:

- **Retrieval fails** → the skeleton alone is used and the failure is logged.
- **The skeleton fails** → the full device dump is used and the failure is logged. A failure is never cached, so a transient registry error cannot blind the agent for the whole TTL.
- Neither can raise into the message handler.

An empty home is not a failure and does not trigger the fallback: it renders an empty context, and the prompt is your system prompt alone.

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

## 12. Sidebar panel

Click **SmartChain AI** in the HA sidebar. Administrators see five tabs; everyone else sees **Camera** only.

| Tab | What it is for |
|---|---|
| **Agents** | Create, edit, duplicate and delete conversation agents across every provider. |
| **Embeddings** | Embeddings bindings (§9.1). Hidden entirely when no configured provider can embed. Warns before a rename or delete that would unbind a store. |
| **Stores** *(v5.2.0+)* | Memory and vector stores (§9.2), plus a health line per configured store — including the ones that still live in `tools.yaml` and cannot be edited here. |
| **Settings** | The entry's connection settings. Most providers have none and the tab says so. |
| **Tools** *(rebuilt in v5.3.0)* | A form-driven constructor for custom tools (§7.0), and a list of every registered tool with its source. The `tools.yaml` editor — with server-side validation, a backup and a rollback — is still there, demoted into an Import / Export block. |
| **Camera** | Pick any camera entity, type a question, get a description. |

The **Camera** tab calls `smartchain.analyze_image` under the hood — same behaviour as the service. Its result is mirrored to `sensor.smartchain_last_analysis` (a proper SensorEntity since v4.0.2) and to the `smartchain_image_analyzed` event for automation use.

Every form in the panel is rendered from a schema the backend serialises, so the panel itself declares no field names and a field added to a config flow appears there with no frontend change.

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

### Memory: "the flat memory: block was replaced in v5.0.0"
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
