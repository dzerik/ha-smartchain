[![en](https://img.shields.io/badge/lang-en-green.svg)](https://github.com/dzerik/ha-smartchain/blob/main/README.md)
[![ru](https://img.shields.io/badge/lang-ru-red.svg)](https://github.com/dzerik/ha-smartchain/blob/main/README-ru.md)

<div align="center">
  <h1 align="center">SmartChain</h1>
  <p>Multi-provider LLM conversation agent for Home Assistant</p>
</div>

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub release](https://img.shields.io/github/v/release/dzerik/ha-smartchain)](https://github.com/dzerik/ha-smartchain/releases)
[![Downloads](https://img.shields.io/github/downloads/dzerik/ha-smartchain/total?color=41BDF5&label=downloads)](https://github.com/dzerik/ha-smartchain/releases)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![tests](https://img.shields.io/badge/tests-1186+-brightgreen)](tests/)
[![CI](https://img.shields.io/github/actions/workflow/status/dzerik/ha-smartchain/ci.yml?label=CI&branch=main)](https://github.com/dzerik/ha-smartchain/actions/workflows/ci.yml)
[![HACS validation](https://img.shields.io/github/actions/workflow/status/dzerik/ha-smartchain/hacs.yml?label=HACS&branch=main)](https://github.com/dzerik/ha-smartchain/actions/workflows/hacs.yml)
[![Hassfest](https://img.shields.io/github/actions/workflow/status/dzerik/ha-smartchain/hassfest.yml?label=Hassfest&branch=main)](https://github.com/dzerik/ha-smartchain/actions/workflows/hassfest.yml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-blue)](https://www.home-assistant.io)

[![Open via HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dzerik&repository=ha-smartchain&category=integration)

## Overview

SmartChain is a Home Assistant custom integration that provides an intelligent voice/conversation assistant powered by multiple LLM providers through LangChain. It also ships a sidebar panel where agents, embeddings bindings, memory stores and custom tools are all configured — and where any camera can be handed to a multimodal model with a question.

Supported providers:

**Hosted:**
- **GigaChat** (Sber) — Russian-focused LLM with vision support
- **YandexGPT** — Yandex Cloud LLM
- **OpenAI** — GPT-4.1, GPT-4o, o3, o4-mini
- **Anthropic** — Claude (Sonnet, Haiku, Opus)
- **DeepSeek** — cheapest cloud provider (V3, R1)
- **OpenRouter** *(v5.0.0+)* — routes to hundreds of hosted models behind one API
- **Groq** *(v5.0.0+)* — low-latency inference for open-weight models
- **Together** *(v5.0.0+)* — hosted open-weight models

**Local:**
- **Ollama** — local models (Llama, Qwen, Gemma, T-Pro, DeepSeek, Home-3B)
- **LM Studio** *(v5.0.0+)* — local OpenAI-compatible server, no API key required
- **llama.cpp** *(v5.0.0+)* — local OpenAI-compatible server, no API key required

Every provider except GigaChat, YandexGPT, Ollama and Anthropic speaks the OpenAI API, and every one of them has an editable base URL — including OpenAI and DeepSeek, which previously used a fixed endpoint — so you can point it at a mirror, a proxy, or a self-hosted gateway. Existing configurations are unaffected: the defaults haven't changed.

Embeddings for long-term memory and the entity index are available from GigaChat, YandexGPT, OpenAI, Ollama, Together, LM Studio and llama.cpp — OpenRouter and Groq don't offer an embeddings API.

### Key Features

**Conversation**
- **11 LLM providers** — cloud and local, switch without losing configuration
- **A hub is a connection, an agent is an agent** *(v5.1.0+)* — a config entry holds credentials and endpoint and nothing else; models, prompts, tools and entity context all live on sub-entries. Four kinds: conversation agent, embeddings binding, memory store *(v5.2.0+)*, tool *(v5.3.0+)*
- **Multiple agents** — different models and prompts per provider (sub-entries)
- **Streaming responses** — real-time token-by-token output
- **Device control** — Assist API (tool calling): lights, switches, locks, climate
- **Multi-agent orchestration** *(v4.4.0+)* — `ask_agents` parallel fan-out across up to 5 siblings, `critique_response` second-opinion review, `ask_agent` single delegation
- **Custom tools from YAML** *(v4.1.0+)* — declarative LLM-callable tools with four action types (`service`, `template`, `rest`, `script`), built in a form since v5.3.0
- **Ready-made tools** *(v5.4.6+)* — a catalogue of eight real tools above your own on the Tools tab, each a row with a switch: weather forecast, sun times, calendar events, to-do list items, area summary, who is home, look at a camera, notify a device. Switching one on writes an ordinary tool sub-entry — editable, disableable, deletable afterwards. Deliberately no second way to turn a light on
- **One tool list per agent** *(v5.4.0+)* — `allowed_tools` lists the six built-in tools alongside your own, always renders, and is the only thing that decides; the Agents tab expands it into what each agent can do, including what is off and why
- **MCP client** *(v4.2.0+)* — connect to remote MCP servers (`stdio` / `sse` / `http`) — filesystem, GitHub, brave-search, etc.; per-server auto-reconnect
- **Long-term memory / RAG** *(v4.3.0+, reworked in v5.0.0, moved into the UI in v5.2.0)* — named memory stores over four pluggable vector backends (`sqlite_numpy` — the default, no extra install — plus `sqlite_vec`, `pgvector`, `qdrant`); embeddings configured as a provider sub-entry (GigaChat / YandexGPT / OpenAI / Ollama) so credentials stay out of YAML; a store is a sub-entry too, so a pgvector DSN and a qdrant API key are write-only rather than sitting in a text file the panel hands to the browser; `search_memory` LLM tool; conversation + (opt-in) HA logbook ingest
- **Entity indexing** *(v5.0.0+)* — point a store at the home instead of the conversation and it becomes a semantic index of your entities, with four scope presets (`minimal` / `optimal` / `maximal` / `paranoid`) and `include` / `exclude` overrides; the `search_entities` tool finds a device from a description (*"what makes the coffee"*) by merging lexical and vector matching, so it keeps working when the embeddings provider is down; sweeps are incremental, so a restart re-embeds nothing
- **Dynamic entity context** *(v5.0.0+, **on by default**)* — the system prompt stops carrying every entity with its state on every turn. Instead it carries a compact skeleton of the home (one line per area, names grouped by domain) plus a per-turn block naming the entities the message is actually about, with their ids and live states. Scope is a preset of its own (`dynamic_context_preset`); **no entity index is needed** — lexical matching works from the registries alone, and a configured index adds semantic matching on top. Off by default on the Assist path, opt-in via `dynamic_context_on_assist`; one checkbox (`dynamic_entity_context`) restores the old full dump
- **State history** — `get_state_history` tool for past device states
- **Vision** — camera image analysis via multimodal models
- **Skill system** — loadable YAML files with additional knowledge
- **Prompt caching** — token savings on repeated requests
- **Chat history** — multi-turn conversations with context
- **Jinja2 templates** — customizable system prompt with device context

**Services**
- **`smartchain.ask`** — send a message to LLM from automations (Telegram, Slack, etc.)
- **`smartchain.analyze_image`** — camera snapshot → multimodal LLM → response
- **`smartchain.reload_tools`** *(v4.1.0+)* — re-read `tools.yaml`, restart MCP connections, rebuild memory subsystem atomically
- **`smartchain.clear_memory`** *(v4.3.0+)* — delete stored memories filtered by `kind` and/or `agent_id`
- **`smartchain.reindex_entities`** *(v5.0.0+)* — force a sweep of an entity index; `full: true` re-embeds everything
- **AI Task entity** — structured data generation for automations

**SmartChain AI Panel**
- Six admin tabs — **Agents**, **Embeddings**, **Stores**, **Settings**, **Tools**, **Camera**; non-admins see Camera only
- Everything the integration configures is reachable here: agents (create, edit, duplicate, delete, and expand any agent into its whole tool inventory), embeddings bindings, memory stores with a health line each, the entry's connection settings, and a form-driven constructor for custom tools with the ready-made catalogue above it
- `tools.yaml` is still editable — server-side validation, a backup and a rollback — but demoted into an Import / Export block
- Every form is rendered from a schema the backend serialises, so the panel declares no field names of its own and a field added to a config flow appears with no frontend change
- **Camera** — pick any HA camera, ask the LLM a natural-language question about the snapshot; the result is mirrored to the `smartchain_image_analyzed` event and `sensor.smartchain_last_analysis`

> **Note:** The YAML automation/script/scene/blueprint generation feature was removed in v4.0.0. See [CHANGELOG.md](CHANGELOG.md) for migration details.

## Installation

### Requirements
- Home Assistant 2024.12.0+
- [HACS](https://hacs.xyz/) installed

### Install via HACS
1. Add this repository as a [custom HACS repository](https://hacs.xyz/docs/faq/custom_repositories): `https://github.com/dzerik/ha-smartchain`
2. Search for "SmartChain" in HACS
3. Install and restart Home Assistant

## Quick Start

### 1. Add Integration
**Settings > Devices & Services > Add Integration > SmartChain**

### 2. Select Provider and Enter Credentials

| Provider | What you need |
|----------|--------------|
| GigaChat | Auth credentials from [developers.sber.ru](https://developers.sber.ru/studio) |
| YandexGPT | API Key + Folder ID from [Yandex Cloud](https://cloud.yandex.com) |
| OpenAI | API key from [platform.openai.com](https://platform.openai.com/account/api-keys) |
| Ollama | Base URL (default: `http://localhost:11434`) |
| DeepSeek | API key from [platform.deepseek.com](https://platform.deepseek.com) |
| Anthropic | API key from [console.anthropic.com](https://console.anthropic.com) |
| OpenRouter | API key from [openrouter.ai](https://openrouter.ai) |
| Groq | API key from [console.groq.com](https://console.groq.com) |
| Together | API key from [api.together.xyz](https://api.together.xyz) |
| LM Studio | Base URL (default: `http://localhost:1234/v1`) — no API key needed |
| llama.cpp | Base URL (default: `http://localhost:8080/v1`) — no API key needed |

### 3. Add an Agent
A config entry is a **connection** to a provider and nothing more. Everything about
a conversation agent lives on an agent sub-entry, which you add explicitly:
**Settings > Devices & Services > SmartChain > Add conversation agent** (or the
Agents tab of the SmartChain panel).

- **Completion Model** — select from list, or type a custom model name
- **Assist API** — enable device control via LLM tool calling
- **Prompt Template** — customize the assistant's behavior
- **Tools** — one list of everything this agent may call, the six built-in tools
  included *(v5.4.0+; it replaced the separate "State History Tool" and
  "Multi-Agent Tools" switches)*

The entry's own **Configure** dialog holds connection settings only — for GigaChat
`verify_ssl` and `profanity` *(v5.4.1+: they are no longer on the agent form)*;
every other provider has none and says so. A provider with no agents yet is a
connection nobody is using, which is a valid state: it simply provides no
conversation entity.

### 4. Activate Assistant
**Settings > Voice Assistants > Add** — select your SmartChain entity as the conversation agent.

### 5. Open SmartChain AI Panel
Click **SmartChain AI** in the Home Assistant sidebar. Administrators get six tabs:
**Agents**, **Embeddings**, **Stores** (memory and vector stores, with a health line
per store), **Settings** (the entry's connection settings), **Tools** (the ready-made
catalogue plus a form-driven constructor for your own, with tools.yaml demoted to
import/export) and **Camera**; everyone else sees Camera only. Embeddings is hidden
when no configured provider has an embeddings API.

![SmartChain AI Panel - Analyze Camera](img_1.png)

## Documentation

Full user guide with all features and running examples:
- **English:** [docs/USAGE.md](docs/USAGE.md)
- **Русский:** [docs/USAGE-ru.md](docs/USAGE-ru.md)

Covers: providers and credentials · hubs and agents · agent options · connection settings · all services with examples · built-in conversation tools (Assist API, history, delegate, multi-agent, search_memory, search_entities) · custom tools from YAML (service / template / rest / script) · MCP client (stdio / SSE / HTTP) · long-term memory (4 vector backends + embeddings sub-entries) · entity indexing (presets, `include` / `exclude`, privacy) · dynamic entity context (skeleton + per-turn retrieval) · AI Task entity · the six-tab sidebar panel · skills system · troubleshooting.

## What's new

| Version | Highlights |
|---|---|
| **v5.4.x** | Ready-made tool catalogue on the Tools tab; `allowed_tools` becomes the one control over an agent's whole tool inventory (the "State History Tool" and "Multi-Agent Tools" switches are gone, folded into the list by migration); `verify_ssl` / `profanity` move to the connection; a storage guard that stopped a templated tool target from corrupting `core.config_entries`; writing a tool, store or binding no longer reloads the hub |
| v5.3.0 | Custom tools are built in a form, not typed as YAML — a `tool` sub-entry, with import / export against `tools.yaml` |
| v5.2.0 | Memory and vector stores move into the UI — a `memory_store` sub-entry, so a pgvector DSN and a qdrant API key are write-only; a health line per store |
| v5.1.0 | A hub is a connection only — the entry's options stop pretending to configure an agent; every agent is a sub-entry |
| **v5.0.0** | Pluggable vector backends (sqlite_numpy / sqlite_vec / pgvector / qdrant), embeddings as a provider capability, named multi-stores, entity indexing with the `search_entities` tool, dynamic entity context in the system prompt (on by default, no index required) |
| v4.4.0 | Multi-agent orchestration — `ask_agents` parallel fan-out + `critique_response` second-opinion review |
| v4.3.0 | Long-term memory / RAG — Chroma vector store *(replaced in v5.0.0)*, `search_memory` tool, conversation + logbook ingest |
| v4.2.0 | MCP client — connect to remote MCP servers via stdio / SSE / HTTP with auto-reconnect |
| v4.1.0 | Custom tools from YAML — declarative LLM tools (service / template / rest / script) |
| v4.0.2 | Security fixes, proper `Last Analysis` SensorEntity, correct `integration_type` |
| v4.0.0 | Major refactor — focused on conversation, AI Task and vision |

Full release notes: [CHANGELOG.md](CHANGELOG.md).

## License

MIT
