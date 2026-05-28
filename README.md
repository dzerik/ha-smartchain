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
[![tests](https://img.shields.io/badge/tests-289+-brightgreen)](tests/)
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
- **Multi-agent** — task delegation between agents
- **State history** — LLM analyzes past events and trends
- **MCP servers** — connect external tools via Model Context Protocol
- **Vision** — camera image analysis via multimodal models
- **Skill system** — loadable YAML files with additional knowledge
- **Prompt caching** — token savings on repeated requests
- **Chat history** — multi-turn conversations with context
- **Jinja2 templates** — customizable system prompt with device context

**Services**
- **`smartchain.ask`** — send a message to LLM from automations (Telegram, Slack, etc.)
- **`smartchain.analyze_image`** — camera snapshot → multimodal LLM → response
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

Full user guide with all features:
**[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**

Topics:
- Multiple agents and multi-agent delegation
- Device control (Assist API)
- State history tool
- MCP servers
- Vision (camera image analysis)
- Skill system (YAML)
- SmartChain AI Panel (camera analysis)
- `smartchain.ask` service (Telegram, Slack)
- `smartchain.analyze_image` service
- AI Task for automations
- System prompt customization
- Parameter and model reference

## Long-term Memory (v4.3.0+)

SmartChain can persist conversation turns and (opt-in) HA logbook events into a
local Chroma vector database and let the LLM recall them through a built-in
`search_memory` tool. Enable it by adding a `memory:` block to
`/config/smartchain/tools.yaml`:

```yaml
memory:
  provider: ollama                # ollama | openai | gigachat | yandex
  model: nomic-embed-text
  base_url: http://localhost:11434
  retention_days: 90
  ingest_conversation: true
  ingest_logbook:
    enabled: false
    domains: [light, climate, lock]
    poll_interval_minutes: 60
```

- `provider`: where embeddings come from. `ollama` is local and free (default).
  Cloud providers (`openai`, `gigachat`, `yandex`) require `api_key`.
- `retention_days: 0` disables the daily cleanup task.
- The `smartchain.clear_memory` service deletes stored memories filtered by
  `kind` and/or `agent_id`.

When the `memory:` block is absent, the feature stays disabled and the
integration behaves exactly as in 4.2.0.

## License

MIT
