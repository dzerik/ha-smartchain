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
[![tests](https://img.shields.io/badge/tests-656+-brightgreen)](tests/)
[![CI](https://img.shields.io/github/actions/workflow/status/dzerik/ha-smartchain/ci.yml?label=CI&branch=main)](https://github.com/dzerik/ha-smartchain/actions/workflows/ci.yml)
[![HACS validation](https://img.shields.io/github/actions/workflow/status/dzerik/ha-smartchain/hacs.yml?label=HACS&branch=main)](https://github.com/dzerik/ha-smartchain/actions/workflows/hacs.yml)
[![Hassfest](https://img.shields.io/github/actions/workflow/status/dzerik/ha-smartchain/hassfest.yml?label=Hassfest&branch=main)](https://github.com/dzerik/ha-smartchain/actions/workflows/hassfest.yml)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-blue)](https://www.home-assistant.io)

[![Open via HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dzerik&repository=ha-smartchain&category=integration)

## Overview

SmartChain is a Home Assistant custom integration that provides an intelligent voice/conversation assistant powered by multiple LLM providers through LangChain. It also ships a sidebar panel for camera image analysis.

Supported providers:

- **GigaChat** (Sber) — Russian-focused LLM with vision support
- **YandexGPT** — Yandex Cloud LLM
- **OpenAI** — GPT-4.1, GPT-4o, o3, o4-mini
- **Ollama** — local models (Llama, Qwen, Gemma, T-Pro, DeepSeek, Home-3B)
- **DeepSeek** — cheapest cloud provider (V3, R1)
- **Anthropic** — Claude (Sonnet, Haiku, Opus)

### Key Features

**Conversation**
- **6 LLM providers** — cloud and local, switch without losing configuration
- **Multiple agents** — different models and prompts per provider (sub-entries)
- **Streaming responses** — real-time token-by-token output
- **Device control** — Assist API (tool calling): lights, switches, locks, climate
- **Multi-agent orchestration** *(v4.4.0+)* — `ask_agents` parallel fan-out across up to 5 siblings, `critique_response` second-opinion review, `ask_agent` single delegation
- **Custom tools from YAML** *(v4.1.0+)* — declarative LLM-callable tools with four action types (`service`, `template`, `rest`, `script`); per-subentry `allowed_tools` filter
- **MCP client** *(v4.2.0+)* — connect to remote MCP servers (`stdio` / `sse` / `http`) — filesystem, GitHub, brave-search, etc.; per-server auto-reconnect
- **Long-term memory / RAG** *(v4.3.0+, reworked in v5.0.0)* — named memory stores over four pluggable vector backends (`sqlite_numpy` — the default, no extra install — plus `sqlite_vec`, `pgvector`, `qdrant`); embeddings configured as a provider sub-entry (GigaChat / YandexGPT / OpenAI / Ollama) so credentials stay out of YAML; `search_memory` LLM tool; conversation + (opt-in) HA logbook ingest
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
- Sidebar panel with a camera analysis tab
- Pick any HA camera, ask the LLM a natural-language question about the snapshot
- Result is mirrored to the `smartchain_image_analyzed` event and `sensor.smartchain_last_analysis`

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

### 3. Configure Options
- **Model** — select from list or type custom model name
- **Assist API** — enable device control via LLM tool calling
- **System Prompt** — customize the assistant's behavior
- **State History Tool** — enable past event analysis

### 4. Activate Assistant
**Settings > Voice Assistants > Add** — select your SmartChain entity as the conversation agent.

### 5. Open SmartChain AI Panel
Click **SmartChain AI** in the Home Assistant sidebar to open the camera analysis panel.

![SmartChain AI Panel - Analyze Camera](img_1.png)

## Documentation

Full user guide with all features and running examples:
- **English:** [docs/USAGE.md](docs/USAGE.md)
- **Русский:** [docs/USAGE-ru.md](docs/USAGE-ru.md)

Covers: providers and credentials · subentry options · all services with examples · built-in conversation tools (Assist API, history, delegate, multi-agent, search_memory, search_entities) · custom tools from YAML (service / template / rest / script) · MCP client (stdio / SSE / HTTP) · long-term memory (4 vector backends + embeddings sub-entries) · entity indexing (presets, `include` / `exclude`, privacy) · dynamic entity context (skeleton + per-turn retrieval) · AI Task entity · sidebar panel · skills system · troubleshooting.

## What's new

| Version | Highlights |
|---|---|
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
