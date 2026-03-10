[![en](https://img.shields.io/badge/lang-en-green.svg)](https://github.com/gritaro/ha-smartchain/blob/main/README.md)
[![ru](https://img.shields.io/badge/lang-ru-red.svg)](https://github.com/gritaro/ha-smartchain/blob/main/README-ru.md)

<div align="center">
  <h1 align="center">SmartChain</h1>
  <p>Multi-provider LLM conversation agent for Home Assistant</p>
</div>

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub release](https://img.shields.io/github/v/release/gritaro/ha-smartchain)](https://github.com/gritaro/ha-smartchain/releases)

## Overview

SmartChain is a Home Assistant custom integration that provides a voice/conversation assistant powered by multiple LLM providers through LangChain:

- **GigaChat** (Sber) — Russian-focused LLM
- **YandexGPT** — Yandex Cloud LLM
- **OpenAI** — GPT-4.1, GPT-4o, o3, o4-mini

### Key Features

- **Streaming responses** — real-time token-by-token output
- **Assist API (tool calling)** — control HA devices via LLM (lights, switches, locks, etc.)
- **Chat history** — multi-turn conversations with context
- **Builtin HA sentence processing** — fallback to native HA commands
- **Customizable system prompt** — Jinja2 templates with device/area context
- **Multiple LLM providers** — switch providers without losing configuration

## Installation

### Requirements
- Home Assistant with [HACS](https://hacs.xyz/) installed

### Install via HACS
1. Add this repository as a [custom HACS repository](https://hacs.xyz/docs/faq/custom_repositories)
2. Search for "SmartChain" in HACS
3. Install and restart Home Assistant

## Configuration

### 1. Add Integration
Go to **Settings → Devices & Services → Add Integration → SmartChain**

### 2. Select LLM Provider
Choose GigaChat, YandexGPT, or OpenAI and provide API credentials.

### 3. Configure Options
- **Model** — select or type custom model name
- **Assist API** — enable device control via LLM tool calling
- **System Prompt** — customize the assistant's behavior (Jinja2 template)
- **Temperature** — control response creativity (0.0–1.0)
- **Max Tokens** — limit response length
- **Chat History** — enable/disable multi-turn memory
- **Builtin Sentences** — use HA's native command processor as fallback

### Provider Setup

#### GigaChat
Register at [developers.sber.ru](https://developers.sber.ru/studio) and get authorization credentials.

#### YandexGPT
Create a [service account](https://cloud.yandex.com/en/docs/iam/operations/sa/create) with `ai.languageModels.user` role and generate an [API key](https://cloud.yandex.com/en/docs/iam/operations/api-key/create).

#### OpenAI
Get an API key at [platform.openai.com](https://platform.openai.com/account/api-keys)

## Usage

Create a Voice Assistant in HA settings and select your SmartChain entity as the conversation agent.

## License

MIT
