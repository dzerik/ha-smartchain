[![en](https://img.shields.io/badge/lang-en-red.svg)](https://github.com/gritaro/ha-smartchain/blob/main/README.md)
[![ru](https://img.shields.io/badge/lang-ru-green.svg)](https://github.com/gritaro/ha-smartchain/blob/main/README-ru.md)

<div align="center">
  <h1 align="center">SmartChain</h1>
  <p>Мультипровайдерный LLM-ассистент для Home Assistant</p>
</div>

[![HACS](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![GitHub release](https://img.shields.io/github/v/release/gritaro/ha-smartchain)](https://github.com/gritaro/ha-smartchain/releases)

## Обзор

SmartChain — кастомная интеграция Home Assistant, предоставляющая голосового/текстового ассистента на базе нескольких LLM-провайдеров через LangChain:

- **GigaChat** (Сбер) — русскоязычная LLM
- **YandexGPT** — LLM от Яндекса
- **OpenAI** — GPT-4.1, GPT-4o, o3, o4-mini

### Возможности

- **Потоковые ответы** — ответы приходят токен за токеном в реальном времени
- **Assist API (tool calling)** — управление устройствами HA через LLM (свет, розетки, замки и т.д.)
- **История диалогов** — многоходовые разговоры с контекстом
- **Встроенный процессор команд HA** — фоллбек на нативные команды HA
- **Настраиваемый системный промпт** — Jinja2 шаблоны с контекстом устройств и зон
- **Несколько LLM-провайдеров** — переключение без потери конфигурации

## Установка

### Требования
- Home Assistant с установленным [HACS](https://hacs.xyz/)

### Установка через HACS
1. Добавьте репозиторий как [пользовательский HACS репозиторий](https://hacs.xyz/docs/faq/custom_repositories)
2. Найдите "SmartChain" в HACS
3. Установите и перезапустите Home Assistant

## Настройка

### 1. Добавление интеграции
**Настройки → Устройства и службы → Добавить интеграцию → SmartChain**

### 2. Выбор LLM-провайдера
Выберите GigaChat, YandexGPT или OpenAI и введите API-ключ.

### 3. Параметры
- **Модель** — выбор из списка или ввод своего имени модели
- **Assist API** — управление устройствами через tool calling
- **Системный промпт** — настройка поведения ассистента (Jinja2)
- **Температура** — креативность ответов (0.0–1.0)
- **Макс. токенов** — ограничение длины ответа
- **История** — включение/отключение памяти диалога
- **Встроенные команды** — использование нативного процессора команд HA

### Настройка провайдеров

#### GigaChat
Зарегистрируйтесь на [developers.sber.ru](https://developers.sber.ru/studio) и получите авторизационные данные.

#### YandexGPT
Создайте [сервисный аккаунт](https://cloud.yandex.com/ru/docs/iam/operations/sa/create) с ролью `ai.languageModels.user` и [API-ключ](https://cloud.yandex.com/ru/docs/iam/operations/api-key/create).

#### OpenAI
Получите API-ключ на [platform.openai.com](https://platform.openai.com/account/api-keys)

## Использование

Создайте голосовой ассистент в настройках HA и выберите SmartChain как conversation agent.

## Лицензия

MIT
