[![en](https://img.shields.io/badge/lang-en-red.svg)](https://github.com/dzerik/ha-smartchain/blob/main/README.md)
[![ru](https://img.shields.io/badge/lang-ru-green.svg)](https://github.com/dzerik/ha-smartchain/blob/main/README-ru.md)

<div align="center">
  <h1 align="center">SmartChain</h1>
  <p>Мультипровайдерный LLM-ассистент для Home Assistant</p>
</div>

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub release](https://img.shields.io/github/v/release/dzerik/ha-smartchain)](https://github.com/dzerik/ha-smartchain/releases)

> **⚠️ Ранняя пре-альфа.** Проект находится на очень ранней стадии разработки. Практически гарантированно не рабочий или почти не рабочий. Используйте на свой страх и риск — ожидайте ломающие изменения, отсутствующий функционал и баги. Баг-репорты и контрибуции приветствуются!

## Обзор

SmartChain — кастомная интеграция Home Assistant, предоставляющая интеллектуального голосового/текстового ассистента на базе нескольких LLM-провайдеров через LangChain:

- **GigaChat** (Сбер) — русскоязычная LLM
- **YandexGPT** — LLM от Яндекса
- **OpenAI** — GPT-4.1, GPT-4o, o3, o4-mini
- **Ollama** — локальные модели (Llama, Qwen, Gemma, T-Pro, DeepSeek, Home-3B)
- **DeepSeek** — самый доступный облачный провайдер (V3, R1)
- **Anthropic** — Claude (Sonnet, Haiku, Opus)

### Возможности

- **6 LLM-провайдеров** — облачные и локальные, переключение без потери конфигурации
- **Несколько агентов** — разные модели и промпты на одном провайдере (sub-entries)
- **Потоковые ответы** — токен за токеном в реальном времени
- **Управление устройствами** — Assist API (tool calling): свет, розетки, замки, климат
- **Мульти-агент** — делегирование задач между агентами
- **История состояний** — LLM анализирует прошлые события и тренды
- **MCP-серверы** — подключение внешних инструментов через Model Context Protocol
- **Распознавание изображений** — анализ камер через мультимодальные модели
- **Система навыков** — загружаемые YAML-файлы с дополнительными знаниями
- **Сервис для автоматизаций** — `smartchain.ask` для Telegram, Slack и др.
- **AI Task** — генерация структурированных данных в автоматизациях
- **Кэширование промптов** — экономия токенов на повторных запросах
- **История диалогов** — многоходовые разговоры с контекстом
- **Jinja2-шаблоны** — настраиваемый системный промпт с контекстом устройств

## Установка

### Требования
- Home Assistant 2025.3+ (для AI Task, иначе 2024.12+)
- [HACS](https://hacs.xyz/)

### Установка через HACS
1. Добавьте репозиторий как [пользовательский HACS репозиторий](https://hacs.xyz/docs/faq/custom_repositories): `https://github.com/dzerik/ha-smartchain`
2. Найдите "SmartChain" в HACS
3. Установите и перезапустите Home Assistant

## Быстрый старт

### 1. Добавление интеграции
**Настройки > Устройства и службы > Добавить интеграцию > SmartChain**

### 2. Выбор провайдера и ввод ключа

| Провайдер | Что нужно |
|-----------|----------|
| GigaChat | Авторизационные данные с [developers.sber.ru](https://developers.sber.ru/studio) |
| YandexGPT | API-ключ + Folder ID из [Yandex Cloud](https://cloud.yandex.com) |
| OpenAI | API-ключ с [platform.openai.com](https://platform.openai.com/account/api-keys) |
| Ollama | Адрес сервера (по умолчанию: `http://localhost:11434`) |
| DeepSeek | API-ключ с [platform.deepseek.com](https://platform.deepseek.com) |
| Anthropic | API-ключ с [console.anthropic.com](https://console.anthropic.com) |

### 3. Настройка параметров
- **Модель** — выбор из списка или ввод произвольного имени
- **Assist API** — включите для управления устройствами через LLM
- **Системный промпт** — настройте поведение ассистента
- **История состояний** — включите для анализа прошлых событий

### 4. Активация ассистента
**Настройки > Голосовые ассистенты > Добавить** — выберите SmartChain как conversation agent.

## Документация

Подробное руководство по всем возможностям:
**[docs/USER_GUIDE.md](docs/USER_GUIDE.md)**

Темы:
- Несколько агентов и мульти-агент
- Управление устройствами (Assist API)
- История состояний
- MCP-серверы
- Распознавание изображений
- Система навыков (YAML)
- Сервис `smartchain.ask` (Telegram, Slack)
- AI Task для автоматизаций
- Настройка промптов
- Справочник параметров и моделей

## Лицензия

MIT
