# SmartChain — Руководство пользователя

[![en](https://img.shields.io/badge/lang-en-red.svg)](USAGE.md) [![ru](https://img.shields.io/badge/lang-ru-green.svg)](USAGE-ru.md)

Документ описывает каждую возможность SmartChain с работающим примером. Обзор и список фич — в [README-ru.md](../README-ru.md).

## Оглавление

1. [Установка](#1-установка)
2. [Провайдеры и креды](#2-провайдеры-и-креды)
3. [Sub-entries — несколько агентов на провайдер](#3-sub-entries--несколько-агентов-на-провайдер)
4. [Опции conversation entity](#4-опции-conversation-entity)
5. [Справочник сервисов](#5-справочник-сервисов)
6. [Встроенные tools для диалога](#6-встроенные-tools-для-диалога)
7. [Свои tools в YAML](#7-свои-tools-в-yaml)
8. [MCP-клиент — внешние tool-серверы](#8-mcp-клиент--внешние-tool-серверы)
9. [Долговременная память / RAG](#9-долговременная-память--rag)
10. [Multi-agent оркестрация](#10-multi-agent-оркестрация)
11. [AI Task](#11-ai-task)
12. [Боковая панель — анализ камер](#12-боковая-панель--анализ-камер)
13. [Система навыков](#13-система-навыков)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. Установка

**Требования:**
- Home Assistant 2024.12.0 или новее
- [HACS](https://hacs.xyz/)

**Через HACS:**
1. Добавьте репозиторий как [пользовательский HACS репозиторий](https://hacs.xyz/docs/faq/custom_repositories): `https://github.com/dzerik/ha-smartchain`
2. Найдите "SmartChain" в HACS и установите
3. Перезапустите Home Assistant
4. **Настройки > Устройства и службы > Добавить интеграцию > SmartChain**

Или нажмите [![Открыть в HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=dzerik&repository=ha-smartchain&category=integration).

---

## 2. Провайдеры и креды

| Провайдер | Требуемые поля | Где получить |
|---|---|---|
| GigaChat | `api_key` (Authorization Data) | [developers.sber.ru/studio](https://developers.sber.ru/studio) |
| YandexGPT | `api_key` + `folder_id` | [Yandex Cloud Console](https://cloud.yandex.com) |
| OpenAI | `api_key` | [platform.openai.com](https://platform.openai.com/account/api-keys) |
| Ollama | `base_url` (например `http://localhost:11434`) | локальная установка |
| DeepSeek | `api_key` | [platform.deepseek.com](https://platform.deepseek.com) |
| Anthropic | `api_key` | [console.anthropic.com](https://console.anthropic.com) |

При создании entry SmartChain автоматически валидирует креды миниатюрным тестовым запросом. Если фейл — config flow покажет ошибку до создания entry.

---

## 3. Sub-entries — несколько агентов на провайдер

Один SmartChain config entry может содержать **несколько conversation-агентов** в виде «sub-entries». Разные sub-entries могут использовать разные модели, системные промпты и опции, разделяя одни и те же креды.

**Создание sub-entry:**

**Настройки > Устройства и службы > SmartChain > меню (три точки) > Добавить sub-entry** — заполните форму.

Каждый sub-entry становится отдельной сущностью `conversation.smartchain_*`. Разные sub-entries можно назначать в разные комнаты / пользователям / Voice pipeline.

---

## 4. Опции conversation entity

Опции живут на **каждом sub-entry**:

| Опция | По умолчанию | Действие |
|---|---|---|
| `model` | модель провайдера | Переопределение модели |
| `temperature` | 0.1 | Sampling temperature |
| `max_tokens` | по провайдеру | Ограничение ответа |
| `prompt` | шаблон системного промпта | Jinja2-системный промпт — см. §4.1 |
| `llm_hass_api` | не задано | Включить HA Assist API (управление устройствами через tool calling) |
| `process_builtin_sentences` | true | Сперва пробовать встроенный intent parser HA; на промах — LLM |
| `chat_history` | true | Передавать историю диалога (vs. только текущее сообщение) |
| `enable_history_tool` | false | Дать LLM tool `get_state_history` |
| `allowed_tools` *(v4.1.0+)* | все | Ограничить набор tools (YAML / MCP), которые видит этот агент |
| `enable_multi_agent_tools` *(v4.4.0+)* | false | Включить tools `ask_agents` + `critique_response` (только при ≥2 sub-entries) |
| `verify_ssl` (только GigaChat) | false | TLS verify для self-signed сертификатов Сбера |
| `profanity` (только GigaChat) | false | Включить фильтр ненормативной лексики GigaChat |

### 4.1. Свой системный промпт

Промпт по умолчанию объявляет роль ассистента и перечисляет комнаты / устройства дома через Jinja-хелперы `{{ states }}` и `{{ areas() }}`. Переопределить свободно:

```jinja2
Ты — {{ ha_name }}, домашний ассистент в {{ states('zone.home') }}.
Будь краток. Время: {{ now().strftime('%H:%M') }}.
{% if states('binary_sensor.someone_home') == 'on' %}
Хозяева дома — общайся по-домашнему.
{% else %}
В доме никого нет — отвечай кратко.
{% endif %}
```

`{{ ha_name }}` пробрасывается автоматически. Доступны все шаблонные функции HA (`states`, `state_attr`, `area_devices`, `area_name`, `now` и др.).

---

## 5. Справочник сервисов

### 5.1. `smartchain.ask`

Отправить текст агенту SmartChain из автоматизации, Telegram-бота, REST-вызова и т.п.

```yaml
service: smartchain.ask
data:
  message: "Какая температура на кухне?"
  entity_id: conversation.smartchain_main   # необязательно — выбор конкретного агента
```

Возвращает `{"response": "<текст>"}`. Без `entity_id` берётся первый доступный агент. Ошибки авторизации провайдера возвращаются как дженерик-сообщение (полный текст — в логе HA) — ваши API-ключи не утекают в ответ.

### 5.2. `smartchain.analyze_image`

Сделать снимок камеры и отдать мультимодальному LLM (GigaChat, OpenAI gpt-4o, Anthropic Claude и др.).

```yaml
service: smartchain.analyze_image
data:
  camera_entity_id: camera.front_door
  message: "Кто у двери? Опиши в 1-2 предложениях."
  entity_id: conversation.smartchain_vision   # необязательно — какой агент
  notify_entity: notify.mobile_app_phone      # необязательно — отправить уведомление
```

Побочные эффекты:
- Возвращает `{"response": "<анализ>"}`
- Стреляет шинное событие `smartchain_image_analyzed` с ответом, камерой, запросом и timestamp
- Обновляет `sensor.smartchain_last_analysis` через dispatcher signal — state — первые 255 символов, атрибут `full_response` ограничен 4 КиБ

**Автоматизация — анализ по движению на крыльце:**

```yaml
automation:
  - alias: "Движение на крыльце — описать сцену"
    trigger:
      - platform: state
        entity_id: binary_sensor.porch_motion
        to: "on"
    action:
      - service: smartchain.analyze_image
        data:
          camera_entity_id: camera.porch
          message: "Кратко опиши что происходит на крыльце."
          notify_entity: notify.mobile_app_phone
```

### 5.3. `smartchain.reload_tools` *(v4.1.0+)*

Перечитывает `/config/smartchain/tools.yaml`, перезапускает MCP-соединения, пересобирает память — атомарно. При фейле валидации YAML предыдущее состояние сохраняется.

```yaml
service: smartchain.reload_tools
```

Стреляет `smartchain_tools_reloaded` с количеством tools при успехе. Использовать после редактирования `tools.yaml` или блока `memory:`.

### 5.4. `smartchain.clear_memory` *(v4.3.0+)*

Удалить сохранённые memories с опциональными фильтрами.

```yaml
service: smartchain.clear_memory
data:
  store: conversations  # необязательно (v5.0.0+) — опустите, чтобы очистить все хранилища
  kind: conversation    # any | conversation | logbook (default: any)
  agent_id: conversation.smartchain_main   # необязательно — только этот агент
```

Стреляет `smartchain_memory_cleared` с `{"deleted": <int>, "stores": [<names>]}`. Бросает `HomeAssistantError`, если память не сконфигурирована или если `store` называет несуществующее хранилище.

> **Очистка индекса сущностей его пересобирает** *(v5.0.0+)*. Если у очищаемого хранилища есть блок `source:` (§9.10), сразу после удаления в фоне планируется сверяющий обход, и индекс возвращается из живых реестров. Удаление не окончательно, а пересборка эмбеддит всё заново. См. §9.10.

### 5.5. `smartchain.reindex_entities` *(v5.0.0+)*

Принудительно обойти индекс сущностей (§9.10), не дожидаясь изменения в реестрах или перезапуска.

```yaml
service: smartchain.reindex_entities
data:
  store: entities   # optional — omit to sweep every entity index
  full: false       # optional — true re-embeds everything
```

Заново эмбеддятся только те сущности, у которых изменился каталожный текст, поэтому обычный вызов дёшев. `full: true` игнорирует отпечатки и эмбеддит всё заново — это нужно только тогда, когда сменилась модель эмбеддингов, а сущности остались прежними.

Стреляет `smartchain_entities_reindexed` с `{"stores": [<names>], "new": <int>, "changed": <int>, "removed": <int>, "unchanged": <int>}`. Бросает `HomeAssistantError`, если индекс сущностей не настроен или если `store` называет несуществующий.

---

## 6. Встроенные tools для диалога

При каждом ходе диалога с LLM могут вызываться нижеперечисленные tools. Каждый включается опцией или состоянием репозитория.

| Tool | Включается когда | Что делает |
|---|---|---|
| HA Assist API (свет, розетки, климат…) | `llm_hass_api` задан на sub-entry | Управляет устройствами через tool calls |
| `get_state_history` | `enable_history_tool: true` | Читает прошлые состояния устройств из recorder |
| `ask_agent` | ≥ 2 sub-entries | Делегировать вопрос конкретному siblings |
| `ask_agents` *(v4.4.0+)* | `enable_multi_agent_tools: true` + ≥ 2 sub-entries | Параллельный fan-out нескольким siblings (см. §10) |
| `critique_response` *(v4.4.0+)* | то же | Попросить siblings отревьюить черновик ответа (см. §10) |
| `search_memory` *(v4.3.0+)* | поднялось хотя бы одно хранилище блока `memory:` | Семантический поиск по эмбеддингам диалогов + logbook (см. §9) |
| `search_entities` *(v5.0.0+)* | есть хотя бы одно хранилище с блоком `source:` | Найти сущность по её описанию, когда `entity_id` неизвестен (см. §9.10) |
| Свои YAML tools | блок `tools:` в YAML | Декларативные tools пользователя (см. §7) |
| MCP tools | блок `mcp_servers:` в YAML | Автоматически обнаруживаются на каждом сервере (см. §8) |

LLM решает сам когда вызывать каждый tool — вы не диспатчите их напрямую. Результат tool возвращается модели, та может выдать следующий tool call или финальный текстовый ответ.

### 6.1. Пример `get_state_history`

Включите в sub-entry. Тогда:

> Пользователь: *«Открывалась ли входная дверь за последние 2 часа?»*
>
> Ассистент вызывает `get_state_history(entity_id="binary_sensor.front_door", hours=2)`, получает список изменений и отвечает:
> *«Да — открыта в 17:43 и закрыта в 17:45.»*

---

## 7. Свои tools в YAML

Объявите свои LLM-tools в `/config/smartchain/tools.yaml`. У каждого tool есть имя, описание, блок параметров (JSON-Schema) и `action` — что делать при вызове.

Четыре типа action: `service`, `template`, `rest`, `script`. Аргументы валидируются по JSON-Schema перед выполнением; шаблонные строки внутри action рендерятся Jinja с подставленными LLM-аргументами.

### 7.1. Минимальный пример — action `service`

```yaml
tools:
  - name: turn_on_light
    description: Включить свет в комнате.
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

После сохранения — `smartchain.reload_tools` (или рестарт). Теперь LLM может выбрать этот tool на запрос вроде *«Включи свет на кухне на 30%»*.

### 7.2. `template` action — вернуть рендеренную Jinja-строку

```yaml
- name: list_recent_motion
  description: Получить список комнат с движением за последний час.
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

### 7.3. `rest` action — HTTP-запрос к внешнему сервису

```yaml
- name: get_weather_forecast
  description: Получить прогноз погоды для города.
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
    response_format: json   # или "text"
```

`!secret` резолвится загрузчиком HA из `secrets.yaml` (§9.2). Это тег **целого значения**: он подставляется вместо одного скаляра YAML целиком, его нельзя вставить в середину строки и нельзя брать в кавычки — `"Bearer !secret my_key"` это обычная строка, которая уйдёт на сервер буквально. Кладите в `secrets.yaml` готовое значение целиком, вместе с префиксом `Bearer `:

```yaml
# <config>/secrets.yaml
weather_api_authorization: "Bearer 0123456789abcdef"
```

Не-2xx-ответы → `"Error: HTTP <статус>"`. Сетевые ошибки и таймауты тоже → чистые error-строки, без утечки текста исключения в LLM.

### 7.4. `script` action — вызов HA-скрипта

```yaml
- name: morning_routine
  description: Запустить утренний скрипт.
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

### 7.5. Per-agent видимость

По умолчанию каждый sub-entry видит все YAML-tools. Для ограничения задайте `allowed_tools` на sub-entry:

```yaml
# В UI опций sub-entry SmartChain:
allowed_tools:
  - turn_on_light
  - list_recent_motion
```

Семантика: отсутствие/`None` = все доступны; пустой список `[]` = никаких custom tools; явный список = только эти имена.

### 7.6. Зарезервированные имена

`get_state_history` и `ask_agent` — зарезервированные имена встроенных tools. Использование их в YAML приводит к пропуску записи с error-логом при старте.

---

## 8. MCP-клиент — внешние tool-серверы

SmartChain может подключаться к удалённым MCP (Model Context Protocol) серверам и выставлять их tools рядом с YAML и встроенными. Три транспорта: `stdio` (subprocess), `sse` (Server-Sent Events) и `http` (streamable HTTP).

### 8.1. Конфигурация в `tools.yaml`

```yaml
mcp_servers:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/config/notes"]
    env:
      NODE_ENV: production
    prefix: filesystem            # default = name; "" отключает префикс
    include_tools: ["list_directory", "read_file"]
    exclude_tools: []
    enabled: true

  - name: brave_search
    transport: sse
    url: https://example.com/mcp/brave
    headers:
      # Тег целого значения, без кавычек; в secrets.yaml лежит "Bearer <токен>".
      Authorization: !secret brave_authorization
    timeout: 30
    verify_ssl: true

  - name: github
    transport: http
    url: https://api.example.com/mcp/github
    headers:
      Authorization: !secret github_authorization
```

После сохранения — `smartchain.reload_tools`.

### 8.2. Именование tools

Каждый tool MCP-сервера регистрируется как `<prefix>__<sanitised_name>` — чтобы избежать коллизий. Например: tool `list-directory` на сервере `filesystem` → `filesystem__list_directory`. `prefix: ""` отключает префикс (для продвинутых сценариев).

### 8.3. Устойчивость

- Один медленный или упавший сервер не влияет на остальные.
- Автореконнект с exponential backoff (1 с → 30 с).
- Per-call timeout (по умолчанию 30 с).
- `verify_ssl: false` корректно работает для SSE/HTTP через кастомный httpx client factory.

### 8.4. Per-agent видимость

Тот же фильтр `allowed_tools` из §7.5 применяется — указывайте MCP-tools по их **зарегистрированному имени** (`<prefix>__<tool>`).

---

## 9. Долговременная память / RAG

Сохраняет ходы диалога и (опционально) записи HA logbook как эмбеддинги в векторном хранилище. LLM вспоминает их через встроенный tool `search_memory`.

**В v5.0.0 эта подсистема переработана.** Эмбеддинги теперь — **возможность провайдера**, настраиваемая как sub-entry: креды больше не появляются в `tools.yaml` вообще. Векторное хранилище стало **подключаемым**, и бэкенд по умолчанию не требует установки ничего сверх того, что уже входит в Home Assistant. Если вы обновляетесь с v4.3.x / v4.4.x, сначала прочитайте §9.8: старый плоский блок `memory:` намеренно отвергается.

Настройка состоит из двух шагов: создать sub-entry эмбеддингов (§9.1), затем объявить одно или несколько хранилищ, которые на него ссылаются (§9.2).

**Хранилище может индексировать и сам дом**, а не диалог. Добавьте ему блок `source:` — и оно станет семантическим индексом ваших сущностей, по которому LLM ищет через `search_entities`; см. §9.10.

### 9.1. Шаг 1 — создать sub-entry эмбеддингов

**Настройки > Устройства и службы > SmartChain > меню из трёх точек > Добавить связку embeddings.**

Форма спрашивает три поля, из которых заполнять нужно два:

- **Название** — заголовок sub-entry. Именно на него ссылается `tools.yaml`, поэтому выберите что-то устойчивое и уникальное среди *всех* config entries SmartChain. Если два sub-entry носят одинаковый заголовок, SmartChain откажется привязывать любой из них вместо того, чтобы гадать, и запишет ошибку в лог с указанием конфликта.
- **Модель эмбеддингов** — выпадающий список моделей эмбеддингов провайдера.
- **Своё имя модели** — поле свободного ввода для модели, которую API провайдера не анонсирует (например, локально скачанной в Ollama). Оставьте пустым, чтобы взять модель из списка.

**Модель обязательна.** Заполните ровно одно из двух полей модели: если оба пусты, форма отвергается с ошибкой «Выберите модель из списка либо задайте свою» и показывается заново. Если заполнены оба, непустое своё имя побеждает выбор из списка.

Креды наследуются от config entry. Больше заполнять нечего — у связки embeddings нет ни промпта, ни tools, ни температуры.

> **Оговорка о возможностях.** Пункт **Добавить связку embeddings** предлагается только у провайдеров, которые действительно предоставляют API эмбеддингов. **DeepSeek и Anthropic — нет**, поэтому у их config entries этого пункта в меню не будет. Если это ваши единственные провайдеры, добавьте второй config entry для провайдера, у которого API есть: локальный Ollama ничего не стоит и может обслуживать только эмбеддинги.

| Провайдер | Модели эмбеддингов |
|---|---|
| GigaChat | `Embeddings`, `EmbeddingsGigaR` |
| YandexGPT | `text-search-doc`, `text-search-query` |
| OpenAI | `text-embedding-3-small`, `text-embedding-3-large` |
| Ollama | `nomic-embed-text`, `mxbai-embed-large`, `bge-m3` |
| DeepSeek, Anthropic | — нет API эмбеддингов |

Списки моделей по возможности запрашиваются у провайдера вживую и фильтруются по назначению, поэтому формы чата больше не предлагают модели эмбеддингов и наоборот. Таблица выше — встроенный запасной вариант на случай, когда API провайдера недоступен.

Рекомендуемая стартовая точка: **Ollama + `nomic-embed-text`** — локально, бесплатно, privacy-friendly. Облачные провайдеры получают полный текст всего, что вы эмбеддите.

### 9.2. Шаг 2 — объявить хранилища в `tools.yaml`

**Хранилище** связывает один sub-entry эмбеддингов с одним векторным бэкендом и несёт собственные настройки хранения и ингеста. Минимальная рабочая конфигурация — две строки:

```yaml
memory:
  stores:
    - name: conversations
      embeddings: "Ollama nomic"
```

Это даёт бэкенд `sqlite_numpy`, хранение 90 дней, ингест диалогов включён, ингест logbook выключен.

Более полный пример с двумя хранилищами:

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

| Поле | Обязательно | По умолчанию | Смысл |
|---|---|---|---|
| `name` | да | — | Идентификатор хранилища, должен соответствовать `^[a-z_][a-z0-9_]*$` и быть уникальным в списке. Он же даёт имя файлу SQLite у файловых бэкендов. |
| `embeddings` | да | — | Заголовок sub-entry эмбеддингов, к которому привязываемся (§9.1). |
| `description` | нет | `""` | Показывается LLM в схеме `search_memory` — пишите так, чтобы модель могла выбрать нужное хранилище. |
| `backend` | нет | `{type: sqlite_numpy}` | Выбор векторного бэкенда, см. §9.3. |
| `retention_days` | нет | `90` | Горизонт ежедневной чистки, 0–3650. `0` отключает чистку для этого хранилища. |
| `ingest_conversation` | нет | `true` | Писать ли ходы диалога в это хранилище. |
| `ingest_logbook` | нет | выключен | `enabled` (bool), `domains` (список), `poll_interval_minutes` (5–1440, по умолчанию 60). |
| `source` | нет | отсутствует | Превращает хранилище в индекс сущностей вместо хранилища диалогов, см. §9.10. Если блок есть, три ключа выше отвергаются. |

После правки вызовите `smartchain.reload_tools`. Ошибки валидации поднимаются оттуда с сообщением, называющим проблемный ключ, а предыдущая конфигурация продолжает работать.

> **`!secret` в `tools.yaml` работает.** SmartChain читает файл загрузчиком YAML из Home Assistant с хранилищем секретов, привязанным к каталогу конфигурации, поэтому тег `!secret` резолвится из `<config>/smartchain/secrets.yaml`, если такой файл есть, и иначе из `<config>/secrets.yaml` — тот же порядок поиска, что HA использует для `configuration.yaml`. Строке подключения pgvector (`dsn`) и ключу Qdrant (`api_key`) место именно там, а не в `tools.yaml`:
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
> Два правила: тег подставляется вместо **одного целого скаляра**, поэтому его нельзя вставить в середину строки, и его нельзя брать в кавычки — `"!secret x"` это обычная строка, а не тег. Имя, которого нет в `secrets.yaml`, роняет перезагрузку с сообщением *«Secret \<имя\> not defined»*; в сообщение попадает только имя ключа, но никогда не значение.

### 9.3. Векторные бэкенды

Каждое хранилище выбирает бэкенд самостоятельно. Все четыре реализуют один и тот же контракт, поэтому можно начать с бэкенда по умолчанию и позже перевести хранилище на другой, ничего больше не меняя.

| Бэкенд | Доп. установка | Когда использовать |
|---|---|---|
| `sqlite_numpy` | ничего | По умолчанию. Любая инсталляция. До ~50 000 записей на хранилище. |
| `sqlite_vec` | `pip install sqlite-vec` | Та же раскладка файлов, нативный KNN. Нужна сборка Python с загрузкой расширений. |
| `pgvector` | `pip install asyncpg` + PostgreSQL | Большие хранилища; естественный выбор, если recorder HA уже работает на PostgreSQL. |
| `qdrant` | сервер Qdrant | Большие хранилища без PostgreSQL. Без Python-зависимостей. |

**`sqlite_numpy` (по умолчанию) — вообще без шага установки.** Хранение — на стандартном `sqlite3`, близость — косинус на numpy по отобранным строкам, и то и другое поставляется вместе с Home Assistant. Поэтому долговременная память работает «из коробки» на любой инсталляции.

```yaml
      backend:
        type: sqlite_numpy
        path: /config/smartchain/conversations.db   # optional
```

Без `path` база кладётся в `<config>/.storage/smartchain_memory/<имя хранилища>.db`, так что несколько хранилищ сосуществуют без коллизий. После ~50 000 записей бэкенд один раз пишет в лог предупреждение с советом перейти на `pgvector` или `qdrant`; работать он продолжает, просто медленнее.

**`sqlite_vec`** — та же раскладка файлов и та же опция `path`, но поиск идёт в виртуальной таблице `vec0`, а не в numpy. Нужен `pip install sqlite-vec` **и** сборка Python с `enable_load_extension`, что верно не везде. Если чего-то из этого нет, хранилище отключается с записью в лог, называющей `sqlite_numpy` как замену без изменений.

**`pgvector`** — нужен `pip install asyncpg` в Python-окружении Home Assistant и база PostgreSQL, пользователю которой разрешено выполнять `CREATE EXTENSION`: при старте SmartChain выполняет `CREATE EXTENSION IF NOT EXISTS vector`. Если ваш пользователь не суперпользователь, попросите администратора выполнить этот оператор один раз для базы заранее — тогда вызов при старте станет пустой операцией. Индекс HNSW по косинусу создаётся, если сервер это поддерживает.

```yaml
      backend:
        type: pgvector
        dsn: "postgresql://smartchain:CHANGE_ME@db.example.local:5432/smartchain"
        table: smartchain_memory
```

`table` по умолчанию `smartchain_memory`; давайте каждому хранилищу свою таблицу, если они делят одну базу. Ошибки подключения логируются полностью, но наружу отдаются без DSN, поэтому креды не попадают ни к LLM, ни в ответ сервиса.

**`qdrant`** — без Python-зависимостей: SmartChain говорит с REST API Qdrant через общую сессию aiohttp Home Assistant. Нужен только доступный сервер Qdrant. Коллекция создаётся при первом старте с косинусной метрикой.

```yaml
      backend:
        type: qdrant
        url: "https://qdrant.example.local:6333"
        api_key: "CHANGE_ME"
        collection: smartchain_memory
        verify_ssl: true
```

`collection` по умолчанию `smartchain_memory`; `api_key` не обязателен для сервера без аутентификации; для самоподписанного сертификата поставьте `verify_ssl: false`.

Любая операция бэкенда ограничена таймаутом 30 с, а бэкенд, который не смог подняться, отключает только своё хранилище.

### 9.4. Размерность эмбеддингов закрепляется за хранилищем

При старте SmartChain эмбеддит короткую пробную строку, измеряет длину вектора и передаёт эту ширину бэкенду, а тот её запоминает. Если позже sub-entry эмбеддингов этого хранилища начнёт указывать на модель другой ширины, расхождение обнаруживается *до* того, как что-либо будет записано:

> `stored embedding dimension is 768 but the configured model produces 1536. Delete the database file /config/.storage/smartchain_memory/conversations.db, then call smartchain.reload_tools.`

Это хранилище отключается, остальные продолжают работать. Векторы разной ширины никогда не смешиваются, поэтому индекс не может тихо испортиться.

**`smartchain.clear_memory` не чинит расхождение размерности.** Хранилище, которое не смогло подняться, не попадает в реестр, поэтому сервис отвечает *«unknown memory store»*, — да и удаление строк не помогло бы: записанная размерность (тип колонки `vector(N)`, таблица `vec0`, размер вектора коллекции Qdrant) переживает удаление строк. Сохранённый артефакт нужно удалить руками. Сообщение об ошибке каждого бэкенда называет, какой именно:

| Бэкенд | Что просит удалить сообщение |
|---|---|
| `sqlite_numpy` | *Delete the database file `<путь>`* — файл `.db` по пути из `path:` либо `<config>/.storage/smartchain_memory/<имя хранилища>.db`. |
| `sqlite_vec` | *Delete the database file `<путь>`* — тот же файл и то же расположение по умолчанию. |
| `pgvector` | *Drop the table `<таблица>` in the configured database* — например `DROP TABLE smartchain_memory;`. |
| `qdrant` | *Delete the collection `<коллекция>` on the Qdrant server* — например `DELETE /collections/smartchain_memory`. |

После этого вызовите `smartchain.reload_tools`, и хранилище пересоберётся с новой шириной.

Чтобы осознанно сменить модель эмбеддингов у хранилища — автоматического переэмбеддинга нет, поэтому старые векторы придётся удалить:

1. Удалите артефакт хранилища по таблице выше (файл, таблицу или коллекцию).
2. Наведите связку на новую модель (**меню из трёх точек > Изменить связку embeddings**).
3. `smartchain.reload_tools`.

`smartchain.clear_memory` нужен, чтобы опустошить **работающее** хранилище (см. §9.7), а не для смены ширины вектора.

### 9.5. Как это видит LLM

Каждый ход диалога планирует фоновую задачу для каждого хранилища с `ingest_conversation: true`. Задача эмбеддит и сохраняет `User: <q>\n\nAssistant: <a>` с метаданными `{kind: conversation, timestamp, agent_id, subentry_id, conversation_id}`. Один медленный провайдер не может задержать другое хранилище.

Tool `search_memory` добавляется в список tools LLM, если поднялось хотя бы одно хранилище. Его схема перечисляет имена хранилищ и их описания, чтобы модель могла выбрать:

> Пользователь: *«Напомни, что я говорил вчера вечером про посудомойку.»*
>
> Ассистент вызывает `search_memory(query="посудомойка", kind="conversation", store="conversations")`, получает релевантные прошлые ходы и отвечает на их основе.

- `store` **обязателен, когда настроено два или больше хранилищ**, и не обязателен ровно при одном — при единственном хранилище нечего уточнять.
- Tool также фильтрует по `subentry_id` вызывающего агента, поэтому агенты достают только свои воспоминания (гарантия приватности).
- `kind` — `conversation`, `logbook` или `any` (по умолчанию); `top_k` по умолчанию 5 и ограничен сверху значением 20.

### 9.6. Ингест logbook (opt-in)

Поставьте у хранилища `ingest_logbook.enabled: true` — и SmartChain будет периодически импортировать записи HA logbook, отфильтрованные по указанным `domains`, как воспоминания `kind: logbook`. После этого LLM может запросить `search_memory(query="…", kind="logbook")` или оставить `kind` равным `any`, чтобы искать по обоим видам.

Опрос выполняется отдельно для каждого хранилища, поэтому одно может следить за logbook, пока другое остаётся чисто диалоговым.

> **Заметка:** ингест logbook зависит от внутренностей HA logbook (`logbook.humanify` / `_get_events`). На версиях HA, где этих имён нет, поллер молча ничего не импортирует. Ингест диалогов от этого не страдает.

### 9.7. Чистка памяти

Используйте сервис `smartchain.clear_memory` (§5.4). Он фильтрует по `kind` и/или `agent_id` и принимает необязательный `store`:

```yaml
service: smartchain.clear_memory
data:
  store: conversations   # optional — omit to clear every store
  kind: conversation     # any | conversation | logbook (default: any)
```

Если `store` опущен, чистятся все настроенные хранилища. Событие `smartchain_memory_cleared` несёт `{"deleted": <int>, "stores": [<names>]}`.

> **Индекс сущностей не остаётся очищенным.** Хранилище с блоком `source:` (§9.10) сразу после удаления обходится заново в фоне, поэтому оно пересобирает себя из живых реестров, и пересборка эмбеддит всё заново. Событие по-прежнему сообщает только количество удалённого и об этом не намекнёт. Чтобы действительно выключить индекс сущностей, уберите блок `source:` — или само хранилище — и вызовите `smartchain.reload_tools`.

Файловые хранилища живут в `<config>/.storage/smartchain_memory/<имя хранилища>.db`, если хранилище не задало `backend.path`.

### 9.8. Миграция с v4.4.x

Блок из v4.3.0 / v4.4.x выглядел так и **больше не принимается**:

```yaml
memory:
  enabled: true
  provider: ollama
  model: nomic-embed-text
  api_key: "…"
```

Поскольку креды уехали из YAML, мигрировать его *куда-то* невозможно, пока не существует sub-entry эмбеддингов, — поэтому SmartChain громко отвергает старую форму вместо того, чтобы гадать. `smartchain.reload_tools` падает с сообщением, называющим проблемные ключи и три шага:

1. Создайте sub-entry эмбеддингов на config entry провайдера (§9.1), задав имя и модель эмбеддингов.
2. Замените блок `memory:` списком `stores:`, в поле `embeddings:` которого стоит это имя (§9.2).
3. Вызовите `smartchain.reload_tools`.

**Chroma удалён.** `chromadb` и `langchain-chroma` убраны из манифеста и из кода — шаг `pip install chromadb`, который описывали прежние версии этого руководства, больше не нужен, и именно эту проблему приходилось обходить в v4.4.1. Если в `<config>/.storage/smartchain_memory/` осталась директория Chroma от прежней версии, она теперь бесхозная и её можно удалить; данные не конвертируются. На большинстве инсталляций она всё равно пуста, потому что pip-шаг HA не мог установить `chromadb`.

### 9.9. Персистентность и устойчивость

- Эмбеддинги считаются через `hass.async_add_executor_job` (не блокирует event-loop) с таймаутом 30 с на вызов; операции бэкенда ограничены собственными 30 с.
- Сбой изолирован одним хранилищем: отсутствующий заголовок sub-entry, дублирующийся заголовок, недоступный бэкенд или расхождение размерности отключают это хранилище, записывают причину в лог и дают подняться всем остальным.
- Падающий провайдер эмбеддингов не роняет диалог — сбой пишется в лог на уровне WARNING, а ход не ингестится.
- Ежедневная задача чистки на каждое хранилище удаляет записи старше `retention_days` (метки времени нормализуются в UTC). `retention_days: 0` её отключает.
- `smartchain.reload_tools` перестраивает реестр атомарно: новый собирается первым и подменяет старый только при успехе, поэтому неудачная правка не трогает работающие хранилища.

### 9.10. Индекс сущностей *(v5.0.0+)* — найти устройство по описанию

Хранилище памяти можно нацелить на сам дом, а не на диалоги. Дайте ему блок `source:` — и оно станет **семантическим индексом ваших сущностей**, по которому LLM ищет через встроенный tool `search_entities`.

Он существует ради запросов, на которые не отвечает поиск по имени. У «что варит кофе» нет ни одного общего слова с `switch.kitchen_socket_3`, а у «чем посушить волосы» — с розеткой, в которую воткнут фен. Зато у этих запросов есть общий смысл с названием сущности, её областью и — самое ценное — с псевдонимами, которые вы задали ей своими словами; векторный поиск по этому тексту их и находит.

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

`source:` не обязателен, и всё остальное в хранилище остаётся прежним, поэтому хранилище без него так и остаётся обычным хранилищем диалогов. Оба вида спокойно уживаются в одном списке `stores:` — индексу сущностей и памяти диалогов всё равно обычно нужны разные бэкенды.

После добавления блока вызовите `smartchain.reload_tools`.

#### Пресеты

Пресет решает, какие сущности индексируются. Их четыре, и они **монотонны** — каждый следующий является надмножеством предыдущего, поэтому расширение охвата никогда ничего не выбрасывает.

| Пресет | Что попадает |
|---|---|
| `minimal` | Только то, чем человек управляет: `light`, `switch`, `cover`, `climate`, `lock`, `fan`, `media_player`, `scene`, `script`, `vacuum`, `water_heater`, `humidifier`, `valve`. Сущности с категорией `config` или `diagnostic` не берутся. |
| `optimal` **(по умолчанию)** | `minimal` плюс целиком `button`, `input_boolean`, `input_select`, `input_number`, `select`, `number`, `alarm_control_panel`, `person` и `weather`; плюс те `sensor` и `binary_sensor`, у которых device class — один из `temperature`, `humidity`, `illuminance`, `pressure`, `motion`, `occupancy`, `presence`, `door`, `window`, `opening`, `garage_door`, `smoke`, `gas`, `moisture`, `carbon_monoxide`, `carbon_dioxide`, `power`, `energy`, `sound`, `vibration`, `problem`. Категории `config` и `diagnostic` здесь тоже не берутся. |
| `maximal` | Каждая сущность, которая не скрыта и не отключена, независимо от домена, device class и категории. Диагностика, `update.*` и `device_tracker.*` — все внутри. |
| `paranoid` | `maximal` плюс скрытые и отключённые сущности. |

Уровни заряда батарей, уровни сигнала и прочая служебная мелочь намеренно отсутствуют в `optimal`: в настоящем доме они подавляют всё остальное по количеству, а искать их никто никогда не станет. Если вы не согласны, верните их через `include:`.

Две вещи, которые обычно удивляют:

- **`maximal` и `paranoid` индексируют и собственные внутренние сущности Home Assistant** — `conversation.home_assistant`, `zone.home`, `sun.sun` и подобные. Это правильно, а не утечка: множество кандидатов — это объединение реестра сущностей *и* машины состояний, потому что шаблонные сенсоры, группы и сущности старых YAML-платформ в реестр не попадают вообще. Ограничение обхода одним реестром молча выпотрошило бы ровно то, что обещает `maximal`. И всё-таки в первый раз это выглядит в индексе как шум.
- **У отключённой сущности состояния нет вообще.** Поэтому под `paranoid` она даёт только каталожную запись и больше ничего; `search_entities` покажет её состояние как `unavailable`, потому что показывать нечего.

#### `include` и `exclude`

Оба принимают список, элементы которого — либо голый домен, либо полный `entity_id`. `include` добавляет поверх пресета; `exclude` применяется последним и **побеждает и пресет, и `include`**. Всё, что не является ни корректным доменом, ни корректным `entity_id`, — ошибка схемы, ловится при перезагрузке.

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

Это индексирует управляемые домены, добавляет все `media_player` и один конкретный сенсор мощности, а затем выбрасывает все `scene` и один конкретный выключатель.

#### Ключи, которые у индекса сущностей отвергаются

Три ключа, которые хранилище диалогов принимает, при наличии `source.type: entities` **отвергаются наотрез** — не игнорируются, — и перезагрузка падает с их перечислением:

| Ключ | Почему |
|---|---|
| `retention_days` | Чистка удаляет документы по возрасту. Сущность не устаревает оттого, что она старая, и проход чистки тихо съел бы индекс. |
| `ingest_conversation` | Ходы диалога не должны попадать в индекс сущностей. |
| `ingest_logbook` | Записи logbook — тоже. |

Проверка идёт по сырому YAML, до применения значений по умолчанию, поэтому срабатывает только на ключ, который вы действительно написали: хранилище, которое просто не упоминает `ingest_conversation`, проходит, хотя по умолчанию этот ключ равен `true`.

#### `index_states`

Выключен по умолчанию, и для большинства инсталляций выключенным его и стоит оставить.

**Когда выключен**, слушатель состояний не регистрируется вообще, а в сохранённых метаданных нет поля `state`.

**Когда включён**, индексатор подписывается на изменения состояний *только проиндексированных сущностей*, склеивает их и раз в 30 секунд записывает в метаданные каждого документа. Вызовов эмбеддинга при этом **не происходит вовсе** — состояние никогда не входит в эмбеддимый текст, ровно поэтому перезапуск и обходится даром.

Что это даёт — поле `state` в метаданных каждого документа, для всего, что читает хранилище напрямую. Чего это **не** меняет — результата `search_entities`: аргумент `state=` всегда сверяется с живым состоянием, а не с сохранёнными метаданными. Фильтрация внутри хранилища отсекала бы векторные попадания по значению возрастом до 30 секунд — а для сущности, не менявшейся с прошлого прохода, и сколь угодно более старому, — то есть выбрасывала бы ровно те совпадения, ради которых поиск и затевался. Лучшего поиска это тоже не даёт: косинусная близость по `"on"`, `"off"` и `"23.5"` слаба, и режим существует не ради неё.

**Оставить выключенным ничего не стоит в смысле свежести.** Состояние, которое показывает `search_entities`, в обоих режимах читается вживую из `hass.states` в момент ответа, поэтому оно никогда не устаревает. Передать `state=` хранилищу с `index_states: false` тоже не ошибка — фильтр в обоих режимах применяется после живого чтения, и вызывающий получит тот же ответ.

#### `search_entities`

Tool добавляется в список tools LLM, как только хотя бы у одного хранилища появляется источник сущностей.

| Параметр | Обязателен | По умолчанию | Смысл |
|---|---|---|---|
| `query` | да | — | Описание устройства: что это или что оно делает. |
| `top_k` | нет | `10` | Сколько результатов вернуть, 1–50. |
| `domain` | нет | — | Ограничить одним доменом, например `light`. |
| `area` | нет | — | Ограничить одной областью, по названию. |
| `state` | нет | — | Ограничить текущим состоянием, например `on`. |
| `store` | при 2+ индексах сущностей | — | В каком индексе искать. При единственном не обязателен. |

> Пользователь: *«Выключи то, что варит кофе.»*
>
> Ассистент вызывает `search_entities(query="кофеварка")` и получает:
>
> ```
> Found 2 entities:
> 1. switch.kitchen_socket_3 — Кофеварка [switch, Кухня] = on
> 2. sensor.kitchen_socket_3_power — Кофеварка потребление [sensor, Кухня] = 812
> ```
>
> …после чего вызывает Assist API и выключает `switch.kitchen_socket_3`. Tool возвращает `entity_id`, поэтому их можно сразу подставлять в вызов сервиса.

Работают и сливаются два прохода. **Лексический** сопоставляет текст, приведённый к нижнему регистру и лишённый диакритики, с дружественным именем, псевдонимами, областью и `entity_id` — точно, по префиксу и по подстроке. **Векторный** ищет по хранилищу, а `domain` и `area` превращаются в фильтр по метаданным — `state` не превращается, потому что сохранённое состояние отстаёт от живого: он применяется потом, уже по `hass.states`. Точные лексические совпадения ранжируются первыми, за ними префиксные, за ними векторные по убыванию оценки; результаты дедуплицируются по `entity_id` и обрезаются до `top_k`.

Лексический поиск здесь не утешительный приз: на «свет на кухне» совпадение по имени и быстрее, и точнее косинусной близости. К тому же он читает реестры напрямую, а не индекс, и именно это делает запасной путь настоящим — **`search_entities` продолжает работать, когда хранилище недоступно**. Упавший провайдер эмбеддингов деградирует его до поиска по именам, а не заставляет замолчать.

Если ничего не нашлось, возвращается фраза об этом с перечислением применённых фильтров, чтобы модель могла повторить попытку с меньшим их числом.

#### `smartchain.reindex_entities`

Заставляет обход выполниться сейчас, а не дожидаться изменения в реестрах или перезапуска.

```yaml
service: smartchain.reindex_entities
data:
  store: entities   # optional — omit to sweep every entity index
  full: false       # optional — true re-embeds everything
```

Стреляет `smartchain_entities_reindexed` с `{"stores": [<names>], "new": <int>, "changed": <int>, "removed": <int>, "unchanged": <int>}`. Несуществующее имя в `store` — или существующее, но у хранилища нет источника сущностей — поднимает `HomeAssistantError` с перечислением тех индексов сущностей, которые есть: молча обойти ничего было бы неотличимо от успеха.

**`full: true` отвечает ровно на одну ситуацию: сменилась модель эмбеддингов, а сущности остались прежними.** Обычный обход сравнивает отпечатки каталожного *текста*, поэтому он справедливо доложил бы, что не изменилось ничего, — при том что каждый сохранённый вектор всё ещё получен старой моделью. `full: true` игнорирует отпечатки и эмбеддит всё заново. Учтите, что смена *размерности* эмбеддингов — другая проблема с другим решением, см. §9.4.

#### Во что это обходится

Обходы инкрементальны. У каждого документа хранится отпечаток его каталожного текста. Обход забирает все сохранённые отпечатки **одним** вызовом, затем эмбеддит только те сущности, которые новые или у которых текст изменился, удаляет документы тех сущностей, что выпали из охвата, и всё остальное пропускает целиком.

- **Первый** обход эмбеддит каждую выбранную сущность один раз.
- Каждый следующий — включая тот, что происходит после каждого перезапуска Home Assistant, — эмбеддит только то, что действительно изменилось. **Перезапуск с неизменившимся домом стоит ноль вызовов эмбеддинга.**
- Переименование сущности, перенос её в другую область, смена имени устройства или добавление псевдонима заново эмбеддят одну эту сущность. Переименование *области* заново эмбеддит всё, что в ней есть.
- Сужение пресета убирает выпавшее из охвата на следующем обходе; ручная чистка не нужна.

Если вы платите за токены, оценивать имеет смысл только первый обход. Грубые порядки величин для дома, в машине состояний которого около 1 500 сущностей: несколько десятков документов при `minimal`, примерно 200–400 при `optimal` и все ~1 500 при `maximal` или `paranoid`. Каждый документ — одна короткая каталожная запись, ограниченная 900 символами, чтобы она никогда не разбивалась на несколько чанков.

Обходы выполняются при старте Home Assistant фоновой задачей — никогда не встроенно, потому что тысяча эмбеддингов не должна задерживать старт, — после изменений в реестрах с задержкой в 5 секунд и по `smartchain.reindex_entities`.

#### Очистка индекса сущностей его пересобирает

`smartchain.clear_memory` на хранилище с источником сущностей удаляет его документы, а затем **планирует в фоне сверяющий обход**, поэтому индекс за считаные мгновения возвращается из живых реестров. Это сделано намеренно: очищенный индекс сущностей, который никто не пересобрал, снаружи выглядел бы как *«`search_entities` не находит ничего, и так навсегда»* — до тех пор, пока какое-нибудь постороннее событие реестра случайно не запустило бы обход.

Два следствия, которые стоит учитывать. Пересборка **эмбеддит всё заново**, потому что сохранённых отпечатков для сравнения больше не осталось, — поэтому на платном провайдере очистка индекса сущностей стоит столько же, сколько стоил первый обход. И очистка — **не** способ выключить индекс: для этого уберите у хранилища блок `source:` либо само хранилище и вызовите `smartchain.reload_tools`.

Событие `smartchain_memory_cleared` сообщает только количество удалённых документов и о состоявшемся обходе вам не скажет; об этом скажет строка-итог самого обхода в логе.

#### Приватность — прочтите до выбора пресета

Индексация отправляет провайдеру эмбеддингов каталожный текст каждой выбранной сущности: дружественное имя, название области, имя устройства и **псевдонимы, которые вы написали сами**. Если этот провайдер — облачный API, то из дома уезжают его планировка и ваша схема именования. Так феатура устроена по своей сути, это не её дефект, но пусть это будет решением, а не сюрпризом.

Что стоит знать до выбора:

- **`optimal`, который стоит по умолчанию, включает сущности `person`** — имена людей в вашем доме.
- **`maximal` и `paranoid` добавляют `device_tracker`** — кто дома и где, по устройствам.
- **`paranoid` отправляет дом целиком**, вместе с диагностикой, а также скрытые и отключённые сущности, которые UI намеренно держит с глаз долой.

Чтобы держать это в узде, сделайте одно из двух или оба сразу:

- Возьмите **локального провайдера эмбеддингов**. Ollama с `nomic-embed-text` работает на вашем железе, и наружу не уходит ничего.
- Возьмите **`preset: minimal` плюс `include:`**, перечислив только те сущности, которые действительно должны находиться. `exclude:` выбрасывает конкретные сущности или целые домены из любого пресета и всегда побеждает, поэтому поверх более широкого пресета он работает и как список вымарывания.

Больше о сущности не отправляется ничего: **состояния не эмбеддятся никогда**, ни в каком режиме, и ни один кред не попадает ни в каталожную запись, ни в строку лога индексатора, ни в результат tool, ни в полезную нагрузку `smartchain_entities_reindexed`. `entity_id` и названия областей в логах появляются — они не креды.

---

## 10. Multi-agent оркестрация

Когда у вас **два или больше conversation sub-entries** в одном SmartChain config entry, они могут общаться между собой через три tools.

### 10.1. Включение

На каждом sub-entry, которому разрешено *инициировать* multi-agent вызовы:

- Откройте опции sub-entry.
- Переключите **Enable multi-agent tools** *(v4.4.0+, скрыто если sub-entry один)*.

Это добавит `ask_agents` и `critique_response` в список tools агента. Однонаправленный `ask_agent` доступен всегда при наличии siblings (без opt-in).

### 10.2. `ask_agent` — одиночное делегирование

> Агент A: У меня нет в контексте сенсора кухни. Спрошу "Kitchen Specialist".
>
> `ask_agent(agent_name="Kitchen Specialist", message="Какая температура духовки?")` → вернёт ответ.

### 10.3. `ask_agents` *(v4.4.0+)* — параллельный fan-out

> Пользователь: *«Спланируй завтра — погода, что купить, календарь?»*
>
> Агент: `ask_agents(agents=["weather", "shopping", "calendar"], query="Что у меня завтра?")`
>
> Все 3 siblings выполняются параллельно через `asyncio.gather`. Результат:
> ```
> Responses from 3 agents:
>
> [weather] Солнечно, 18°C.
> [shopping] Нужно молоко, хлеб и яйца.
> [calendar] 14:00 стоматолог.
> ```
> Агент затем суммирует для пользователя.

Ограничения: `MULTI_AGENT_MAX_PARALLEL = 5`, per-agent timeout 60 с, дубликаты дедуплицируются, фейлы становятся `"[<agent>] Error: …"`.

### 10.4. `critique_response` *(v4.4.0+)* — ревью второго мнения

> Главный агент имеет черновик ответа. Перед отправкой при safety-critical действии:
>
> `critique_response(reviewer="security", original_question="…", candidate_answer="…")`
>
> Reviewer отвечает оценкой в 3-5 предложений. Главный агент читает её и решает — переписать ответ или продолжать.

### 10.5. Recursion guard

Когда делегируешь sibling через `ask_agent` / `ask_agents` / `critique_response`, sibling вызывается с plain text-промптом и **без tools** — он не может рекурсивно делегировать дальше. Глубина гарантированно 1.

---

## 11. AI Task

Когда в HA установлена интеграция `ai_task`, SmartChain регистрирует AI Task entity на каждый sub-entry. Это рекомендуемый способ получать **структурированные данные** из LLM в автоматизациях.

```yaml
automation:
  - alias: "Ежедневная инвентаризация холодильника"
    trigger:
      - platform: time
        at: "20:00:00"
    action:
      - service: ai_task.generate_data
        data:
          entity_id: ai_task.smartchain_main
          task_name: "fridge_inventory"
          instructions: "Перечисли продукты в холодильнике на основе снимка камеры."
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
          message: "Продукты: {{ result.items | join(', ') }}"
```

Ответ валидируется по `structure` и возвращается как dict.

Для downstream-интеграций `smartchain.async_generate_structured()` экспортирован из `custom_components.smartchain` как публичный helper.

---

## 12. Боковая панель — анализ камер

Нажмите **SmartChain AI** в боковой панели HA — откроется панель. Выберите камеру, введите вопрос — LLM вернёт описание. Результат отражается в `sensor.smartchain_last_analysis` (правильный SensorEntity с v4.0.2) и шинном событии `smartchain_image_analyzed`.

Под капотом панель вызывает `smartchain.analyze_image` — то же поведение что и у сервиса.

---

## 13. Система навыков

Кидайте YAML-файлы в `/config/smartchain/skills/`. Каждый skill-файл:

```yaml
name: locks_safety
description: Правила управления замками/дверями
prompt: |
  Никогда не открывай входную дверь без подтверждения хозяина.
  Гаражные ворота автоматически закрываются через 5 минут.
```

Skills добавляются к системному промпту LLM при старте диалога (executor-offload для холодного чтения). Это легковесная альтернатива длинному системному промпту когда нужны общие правила для всех агентов.

Перезагрузка skills — рестартом HA или перезагрузкой config entry.

---

## 14. Troubleshooting

### "No SmartChain agent available."
Сервис `smartchain.ask` не нашёл агента. Проверьте **Настройки > Устройства и службы > SmartChain** — есть ли хотя бы один conversation sub-entry с заполненным `runtime_data`?

### Свои tools не появляются
1. Проверьте синтаксис `/config/smartchain/tools.yaml`: `python -c "import yaml; yaml.safe_load(open('/config/smartchain/tools.yaml'))"`.
2. Вызовите `smartchain.reload_tools` — он бросает `HomeAssistantError` с понятным сообщением при фейле валидации.
3. Проверьте лог HA на `Tool <name> uses a reserved built-in name; skipping` или `Duplicate tool name`.

### MCP-сервер недоступен
- `stdio`: убедитесь что бинарник `command` (`npx`, `python`, etc.) в PATH контейнера HA; проверьте лог на ошибку запуска subprocess.
- `sse` / `http`: убедитесь что URL доступен из HA; для self-signed-сертов используйте `verify_ssl: false`.
- Фейлы изолированы per server — остальные MCP-серверы и YAML-tools продолжают работать.

### Memory: "Memory is not configured for this installation."
Tool `search_memory` был вызван, но ни одно хранилище не поднялось. Либо в `tools.yaml` нет ни одной записи `memory.stores[]`, либо все хранилища упали при старте — ищите в логе причину по каждому (см. §9.9).

### Memory: хранилище ссылается на несуществующий sub-entry эмбеддингов
В логе указан отсутствующий заголовок и перечислены доступные. Поле `embeddings:` совпадает с **заголовком** sub-entry в точности — проверьте опечатку или переименование. Заголовок, занятый двумя sub-entry, тоже отвергается; переименуйте один из них.

### Memory: «the flat memory: block was replaced in v5.0.0»
У вас остался блок `memory:` из v4.3.x / v4.4.x с `provider` / `model` / `api_key`. Выполните три шага миграции из §9.8.

### Memory: расхождение размерности при старте
Sub-entry эмбеддингов этого хранилища теперь указывает на модель другой ширины, чем уже сохранённая. `smartchain.clear_memory` тут не поможет: хранилище не поднялось, поэтому сервис о нём не знает. Удалите артефакт, названный в сообщении об ошибке (файл `.db`, таблицу pgvector или коллекцию Qdrant), и вызовите `smartchain.reload_tools` — см. §9.4.

### Провайдер эмбеддингов недоступен
- Sub-entry эмбеддингов предлагают только провайдеры с API эмбеддингов — не DeepSeek и не Anthropic (§9.1).
- Ollama: убедитесь, что он запущен и достижим по базовому URL из config entry; скачайте модель (`ollama pull nomic-embed-text`).
- Облачные провайдеры: проверьте креды config entry и что имя модели совпадает с написанием провайдера.
- Сбои логируются на уровне WARNING; диалог продолжается без ингеста.

### LLM ошибка: текст provider exception не виден
Так задумано. v4.0.2 добавила security-границу — ошибки провайдера (которые могут содержать API-ключи) логируются как ERROR через `LOGGER.exception`, но пользовательский ответ сервиса — дженерик `"LLM request failed; see Home Assistant logs for details."` Реальная ошибка — в логе HA.

### Логи

Все строки SmartChain идут из логгера `custom_components.smartchain.*`. Добавьте в `/config/configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.smartchain: debug
```
