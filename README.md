[![en](https://img.shields.io/badge/lang-en-green.svg)](https://github.com/dzerik/ha-smartchain/blob/main/README.md)
[![ru](https://img.shields.io/badge/lang-ru-red.svg)](https://github.com/dzerik/ha-smartchain/blob/main/README-ru.md)

<div align="center">
  <h1 align="center">SmartChain</h1>
  <p>Multi-provider LLM conversation agent for Home Assistant</p>
</div>

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub release](https://img.shields.io/github/v/release/dzerik/ha-smartchain)](https://github.com/dzerik/ha-smartchain/releases)

## Overview

SmartChain is a Home Assistant custom integration that provides an intelligent voice/conversation assistant powered by multiple LLM providers through LangChain. Beyond conversation, it includes a built-in AI panel for generating, editing, and deploying automations directly from natural language.

Supported providers:

- **GigaChat** (Sber) — Russian-focused LLM with vision support
- **YandexGPT** — Yandex Cloud LLM
- **OpenAI** — GPT-4.1, GPT-4o, o3, o4-mini
- **Ollama** — local models (Llama, Qwen, Gemma, T-Pro, DeepSeek, Home-3B)
- **DeepSeek** — cheapest cloud provider (V3, R1)
- **Anthropic** — Claude (Sonnet, Haiku, Opus)

![SmartChain AI Panel](img.png)

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
- **`smartchain.generate_automation`** — natural language → HA automation/script/scene/blueprint YAML
- **`smartchain.deploy_automation`** — deploy generated YAML to HA configuration files
- **`smartchain.list_yaml`** — list existing automations, scripts, scenes, or blueprints
- **`smartchain.get_yaml`** — retrieve the YAML source of any existing HA item
- **AI Task entity** — structured data generation for automations

**SmartChain AI Panel**
- Sidebar panel with Generate and Analyze tabs
- Generate automations, scripts, scenes, and blueprints from text descriptions
- Edit and improve existing YAML with AI assistance
- Entity picker and agent selector built in
- YAML validation (structure, entity IDs, services) before deploy
- Browse and load existing HA items into the editor

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
Click **SmartChain AI** in the Home Assistant sidebar to access the automation generation panel.

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
- SmartChain AI Panel (automation generation, camera analysis)
- `smartchain.ask` service (Telegram, Slack)
- `smartchain.analyze_image` service
- `smartchain.generate_automation` service
- Deploy and validate generated YAML
- Edit and improve existing automations
- AI Task for automations
- System prompt customization
- Parameter and model reference

## License

MIT
