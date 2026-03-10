[![en](https://img.shields.io/badge/lang-en-green.svg)](https://github.com/dzerik/ha-smartchain/blob/main/README.md)
[![ru](https://img.shields.io/badge/lang-ru-red.svg)](https://github.com/dzerik/ha-smartchain/blob/main/README-ru.md)

<div align="center">
  <h1 align="center">SmartChain</h1>
  <p>Multi-provider LLM conversation agent for Home Assistant</p>
</div>

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub release](https://img.shields.io/github/v/release/dzerik/ha-smartchain)](https://github.com/dzerik/ha-smartchain/releases)

## Overview

SmartChain is a Home Assistant custom integration that provides a voice/conversation assistant powered by multiple LLM providers through LangChain:

- **GigaChat** (Sber) — Russian-focused LLM
- **YandexGPT** — Yandex Cloud LLM
- **OpenAI** — GPT-4.1, GPT-4o, o3, o4-mini
- **Ollama** — local models (Llama, Qwen, Gemma, T-Pro, DeepSeek, Home-3B)
- **DeepSeek** — cheapest cloud provider (V3, R1)
- **Anthropic** — Claude (Sonnet, Haiku, Opus)

### Key Features

- **6 LLM providers** — cloud and local, switch without losing configuration
- **Streaming responses** — real-time token-by-token output
- **Assist API (tool calling)** — control HA devices via LLM (lights, switches, locks, etc.)
- **AI Task entity** — use LLM in automations via `ai_task.generate_data`
- **Chat history** — multi-turn conversations with context
- **Builtin HA sentence processing** — fallback to native HA commands
- **Customizable system prompt** — Jinja2 templates with device/area context

## Installation

### Requirements
- Home Assistant 2025.3+ (for AI Task support, otherwise 2024.12+)
- [HACS](https://hacs.xyz/) installed

### Install via HACS
1. Add this repository as a [custom HACS repository](https://hacs.xyz/docs/faq/custom_repositories)
2. Search for "SmartChain" in HACS
3. Install and restart Home Assistant

## Configuration

### 1. Add Integration
Go to **Settings > Devices & Services > Add Integration > SmartChain**

### 2. Select LLM Provider
Choose your provider and provide credentials:

| Provider | What you need |
|----------|--------------|
| GigaChat | Auth credentials from [developers.sber.ru](https://developers.sber.ru/studio) |
| YandexGPT | API Key + Folder ID from [Yandex Cloud](https://cloud.yandex.com) |
| OpenAI | API key from [platform.openai.com](https://platform.openai.com/account/api-keys) |
| Ollama | Base URL (default: `http://localhost:11434`) |
| DeepSeek | API key from [platform.deepseek.com](https://platform.deepseek.com) |
| Anthropic | API key from [console.anthropic.com](https://console.anthropic.com) |

### 3. Configure Options
- **Model** — select or type custom model name
- **Assist API** — enable device control via LLM tool calling
- **System Prompt** — customize the assistant's behavior (Jinja2 template)
- **Temperature** — control response creativity (0.0-1.0)
- **Max Tokens** — limit response length
- **Chat History** — enable/disable multi-turn memory
- **Builtin Sentences** — use HA's native command processor as fallback

## Usage

Create a Voice Assistant in HA settings and select your SmartChain entity as the conversation agent.

## License

MIT
