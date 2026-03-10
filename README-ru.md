[![en](https://img.shields.io/badge/lang-en-red.svg)](https://github.com/dzerik/ha-smartchain/blob/main/README.md)
[![ru](https://img.shields.io/badge/lang-ru-green.svg)](https://github.com/dzerik/ha-smartchain/blob/main/README-ru.md)

<div align="center">
  <h1 align="center">SmartChain</h1>
  <p>Мультипровайдерный LLM-ассистент для Home Assistant</p>
</div>

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub release](https://img.shields.io/github/v/release/dzerik/ha-smartchain)](https://github.com/dzerik/ha-smartchain/releases)

## Обзор

SmartChain — кастомная интеграция Home Assistant, предоставляющая голосового/текстового ассистента на базе нескольких LLM-провайдеров через LangChain:

- **GigaChat** (Сбер) — русскоязычная LLM
- **YandexGPT** — LLM от Яндекса
- **OpenAI** — GPT-4.1, GPT-4o, o3, o4-mini
- **Ollama** — локальные модели (Llama, Qwen, Gemma, T-Pro, DeepSeek, Home-3B)
- **DeepSeek** — самый доступный облачный провайдер (V3, R1)
- **Anthropic** — Claude (Sonnet, Haiku, Opus)

### Возможности

- **6 LLM-провайдеров** — облачные и локальные, переключение без потери конфигурации
- **Sub-entries** — несколько агентов с разными моделями/промптами на одном провайдере
- **Потоковые ответы** — ответы приходят токен за токеном в реальном времени
- **Assist API (tool calling)** — управление устройствами HA через LLM (свет, розетки, замки и т.д.)
- **AI Task entity** — использование LLM в автоматизациях через `ai_task.generate_data`
- **История диалогов** — многоходовые разговоры с контекстом
- **Встроенный процессор команд HA** — фоллбек на нативные команды HA
- **Настраиваемый системный промпт** — Jinja2 шаблоны с контекстом устройств и зон

## Установка

### Требования
- Home Assistant 2025.3+ (для AI Task, иначе 2024.12+)
- [HACS](https://hacs.xyz/)

### Установка через HACS
1. Добавьте репозиторий как [пользовательский HACS репозиторий](https://hacs.xyz/docs/faq/custom_repositories)
2. Найдите "SmartChain" в HACS
3. Установите и перезапустите Home Assistant

## Настройка

### 1. Добавление интеграции
**Настройки > Устройства и службы > Добавить интеграцию > SmartChain**

### 2. Выбор LLM-провайдера

| Провайдер | Что нужно |
|-----------|----------|
| GigaChat | Авторизационные данные с [developers.sber.ru](https://developers.sber.ru/studio) |
| YandexGPT | API-ключ + Folder ID из [Yandex Cloud](https://cloud.yandex.com) |
| OpenAI | API-ключ с [platform.openai.com](https://platform.openai.com/account/api-keys) |
| Ollama | Адрес сервера (по умолчанию: `http://localhost:11434`) |
| DeepSeek | API-ключ с [platform.deepseek.com](https://platform.deepseek.com) |
| Anthropic | API-ключ с [console.anthropic.com](https://console.anthropic.com) |

### 3. Параметры
- **Модель** — выбор из списка или ввод своего имени модели
- **Assist API** — управление устройствами через tool calling
- **Системный промпт** — настройка поведения ассистента (Jinja2)
- **Температура** — креативность ответов (0.0-1.0)
- **Макс. токенов** — ограничение длины ответа
- **История** — включение/отключение памяти диалога
- **Встроенные команды** — использование нативного процессора команд HA

## Использование

Создайте голосовой ассистент в настройках HA и выберите SmartChain как conversation agent.

## Лицензия

MIT
