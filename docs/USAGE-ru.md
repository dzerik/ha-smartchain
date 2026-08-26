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
7. [Пользовательские инструменты](#7-пользовательские-инструменты)
8. [MCP-клиент — внешние tool-серверы](#8-mcp-клиент--внешние-tool-серверы)
9. [Долговременная память / RAG](#9-долговременная-память--rag)
10. [Multi-agent оркестрация](#10-multi-agent-оркестрация)
11. [AI Task](#11-ai-task)
12. [Боковая панель](#12-боковая-панель)
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
| OpenRouter *(v5.0.0+)* | `api_key` | [openrouter.ai](https://openrouter.ai) |
| Groq *(v5.0.0+)* | `api_key` | [console.groq.com](https://console.groq.com) |
| Together *(v5.0.0+)* | `api_key` | [api.together.xyz](https://api.together.xyz) |
| LM Studio *(v5.0.0+)* | `base_url` (по умолчанию: `http://localhost:1234/v1`) — API-ключ не нужен | локальная установка |
| llama.cpp *(v5.0.0+)* | `base_url` (по умолчанию: `http://localhost:8080/v1`) — API-ключ не нужен | локальная установка |

При создании entry SmartChain автоматически валидирует креды миниатюрным тестовым запросом. Если фейл — config flow покажет ошибку до создания entry.

Все провайдеры, кроме GigaChat, YandexGPT, Ollama и Anthropic, работают через OpenAI-совместимый API, а их `base_url` меняется прямо в config flow: OpenRouter, Groq, Together, OpenAI и DeepSeek можно направить на зеркало, прокси или собственный шлюз. Значения по умолчанию не изменились, поэтому уже настроенный entry OpenAI или DeepSeek, в котором это поле не трогали, ведёт себя ровно как раньше.

**Локальные OpenAI-совместимые серверы.** LM Studio и llama.cpp не требуют API-ключа — оставьте это поле пустым. Загрузите модель и запустите сервер, затем создайте entry SmartChain с его `base_url`:
- **LM Studio** — загрузите модель в приложении, запустите локальный сервер (по умолчанию `http://localhost:1234/v1`).
- **llama.cpp** — запустите `llama-server -m <model.gguf>` (по умолчанию `http://localhost:8080/v1`).

Любой из них подключается ко всем возможностям SmartChain, использующим chat-модель, и оба могут обслуживать эмбеддинги, если загруженная модель их поддерживает.

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
| `dynamic_entity_context` *(v5.0.0+)* | **true** | Слать компактную карту дома и то, о чём спрашивают, вместо всех сущностей — см. §9.11 |
| `dynamic_context_preset` *(v5.0.0+)* | `optimal` | Какие сущности попадают в эту карту — см. §9.11 |
| `dynamic_context_on_assist` *(v5.0.0+)* | false | Добавлять найденные сущности и при включённом Assist API — см. §9.11 |
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

## 7. Пользовательские инструменты

У каждого инструмента есть имя, описание, блок параметров (JSON Schema) и `action` — что делать при вызове. Четыре типа action: `service`, `template`, `rest`, `script`. Аргументы валидируются по JSON Schema перед выполнением; шаблонные строки внутри action рендерятся Jinja с подставленными LLM-аргументами.

**Есть два способа создать инструмент, и оба дают один и тот же результат.**

### 7.0. Вкладка Tools *(v5.3.0+)* — без YAML

Откройте панель SmartChain и выберите **Tools** либо добавьте подзапись **Tool** через Настройки → Устройства и службы. В обоих случаях — форма:

- **Имя**, **что делает инструмент** и **включён** — обычные поля.
- **Что происходит при вызове** — выбор из списка, и остальная форма подстраивается под него. Для `service` спрашиваются действие и цель — это выбор, а не ввод текста; для `script` — сущность скрипта; для `rest` — метод, URL, заголовки, тело и тайм-аут.
- **Аргументы** — по строке на аргумент: имя, тип, описание, обязательность. Это и есть JSON Schema, собранная за вас.
- Для схемы, которую строками не выразить (`anyOf`, вложенные объекты, массивы), переключите **как описаны аргументы** в `advanced` и напишите JSON Schema прямо. Она проверяется при сохранении и затем на каждом вызове.

Созданный так инструмент хранится в Home Assistant, а не в файле. `tools.yaml` продолжает работать — как источники объединяются, см. §7.7.

> **Значения заголовков REST записываются, но не читаются.** В заголовке живёт токен `Authorization`, поэтому после сохранения значение больше не возвращается в браузер: форма показывает имя заголовка с пустым значением, и пустое поле означает «оставить как есть». Введите новое значение, чтобы заменить; удалите строку, чтобы убрать заголовок.

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

Зарезервированы все шесть имён встроенных инструментов: `get_state_history`, `ask_agent`, `ask_agents`, `critique_response`, `search_memory` и `search_entities`. Использование любого из них в `tools.yaml` приводит к пропуску записи с error-логом при старте; во вкладке Tools имя отклоняется сразу, пока вы на него смотрите.

> **Три из них зарезервированы только с v5.3.0.** До этого пользовательский инструмент с именем `search_memory`, `ask_agents` или `critique_response` регистрировался рядом со встроенным и добавлялся последним: модель читала описание встроенного, а вызов уходил в пользовательский. Если такой инструмент есть — переименуйте его; после обновления он пропускается, а не выигрывает молча.

### 7.7. Два источника, один реестр *(v5.3.0+)*

Инструменты приходят из трёх мест и попадают в один реестр: вкладка Tools (подзаписи конфигурации), `tools.yaml` и подключённые MCP-серверы. Вкладка Tools показывает все три и подписывает источник, потому что редактировать может только первый.

- **Имя, объявленное и в подзаписи, и в `tools.yaml`, разрешается в пользу подзаписи** — по той же причине, что и хранилище памяти: подзапись редактируется из UI. Затенение не бывает молчаливым: предупреждение в лог, отчёт в `smartchain/tool/list` и строка на вкладке.
- **Import** превращает инструменты из `tools.yaml` в редактируемые подзаписи. Файл при этом не меняется, поэтому каждый импортированный инструмент затеняет свою копию; удалите копии, когда убедитесь, что всё работает. Файл, где **где-либо** используется `!secret`, отклоняется целиком: импорт вынужден был бы раскрыть секрет и записать значение в `.storage` открытым текстом, тихо унеся учётные данные из `secrets.yaml`.
- **Export** выгружает инструменты-подзаписи обратно в YAML. Значения заголовков REST выгружаются пустыми, а затронутые инструменты перечисляются — по той же причине, по которой форма их не показывает.
- `mcp_servers:` и `memory:` не импортируются и не имеют здесь конструктора: MCP-серверы настраиваются в `tools.yaml`, хранилища памяти — на вкладке Stores.

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

> **Оговорка о возможностях.** Пункт **Добавить связку embeddings** предлагается только у провайдеров, которые действительно предоставляют API эмбеддингов. **DeepSeek, Anthropic, OpenRouter и Groq — нет**, поэтому у их config entries этого пункта в меню не будет. Если это ваши единственные провайдеры, добавьте второй config entry для провайдера, у которого API есть: локальный Ollama ничего не стоит и может обслуживать только эмбеддинги.

| Провайдер | Модели эмбеддингов |
|---|---|
| GigaChat | `Embeddings`, `EmbeddingsGigaR` |
| YandexGPT | `text-search-doc`, `text-search-query` |
| OpenAI | `text-embedding-3-small`, `text-embedding-3-large` |
| Ollama | `nomic-embed-text`, `mxbai-embed-large`, `bge-m3` |
| Together, LM Studio, llama.cpp *(v5.0.0+)* | определяются вживую по списку моделей провайдера через шаблон имени (`embed`, `bge-`, `gte-`, `e5-`, `minilm`) — без статичного запасного списка |
| DeepSeek, Anthropic, OpenRouter, Groq | — нет API эмбеддингов |

Списки моделей по возможности запрашиваются у провайдера вживую и фильтруются по назначению, поэтому формы чата больше не предлагают модели эмбеддингов и наоборот. Таблица выше — встроенный запасной вариант на случай, когда API провайдера недоступен — кроме Together, LM Studio и llama.cpp, у которых его нет: если их API недоступен при создании sub-entry, работает только поле **Своё имя модели**.

Рекомендуемая стартовая точка: **Ollama + `nomic-embed-text`** — локально, бесплатно, privacy-friendly. Облачные провайдеры получают полный текст всего, что вы эмбеддите.

### 9.2. Шаг 2 — объявить хранилища

**Хранилище** связывает один sub-entry эмбеддингов с одним векторным бэкендом и несёт собственные настройки хранения и ингеста. Создать его можно двумя способами, и оба дают одно и то же.

**В интерфейсе *(v5.2.0+)* — рекомендуемый путь.** **Настройки > Устройства и службы > SmartChain > Добавить хранилище памяти** либо вкладка **Stores** панели SmartChain. Каждая опция из таблицы ниже — поле этой формы, а вкладка Stores вдобавок показывает, поднялось ли каждое настроенное хранилище на самом деле.

Если бэкенду нужны учётные данные — используйте интерфейс. `backend.dsn` содержит пароль к PostgreSQL, `backend.api_key` — токен Qdrant; записанные в `tools.yaml`, они отдаются вашему браузеру при каждом открытии вкладки Tools. Sub-entry хранит их в `.storage` и никогда не отдаёт обратно: форма показывает пустое поле и подпись «оставьте пустым, чтобы сохранить прежнее».

**В `tools.yaml`** — по-прежнему работает без изменений. Минимальная рабочая конфигурация — две строки:

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

После правки вызовите `smartchain.reload_tools`. Ошибки валидации поднимаются оттуда с сообщением, называющим проблемный ключ, а предыдущая конфигурация продолжает работать. Хранилищу, созданному в интерфейсе, reload не нужен — команда, которая его пишет, сама пересобирает реестр.

> **Хранилище, объявленное в обоих местах, разрешается в пользу sub-entry** *(v5.2.0+)*: именно его умеет править интерфейс, а проигрыш файлу, который панель не может безопасно переписать, превратил бы UI в неизменяемое отображение того, чем он якобы управляет. Затенение никогда не молчаливое: оно пишется предупреждением в лог, возвращается командой `smartchain/store/status` и показывается на вкладке Stores. Перенеся хранилище, удалите блок из `tools.yaml`.

> **В форме хранилища нет переключателя ингеста logbook.** Ключ `ingest_logbook` выше по-прежнему разбирается, но поллер обращается к `logbook._get_events` / `logbook.humanify`, которых установленный Home Assistant больше не предоставляет — сегодня это no-op. Живой переключатель обещал бы то, чего код не умеет, поэтому поле осталось только в YAML и заработает в тот день, когда заработает fetcher.

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

### 9.11. Динамический контекст сущностей *(v5.0.0+)* — промпт перестаёт возить весь дом

**Эта возможность включена по умолчанию**, поэтому существующий агент меняет поведение сразу после обновления.

До v5.0.0 системный промпт отрисовывал каждую область, каждое устройство и каждую сущность с её текущим состоянием — на каждом ходу. В доме на тысячу сущностей это большая часть промпта, оплачиваемая на каждом сообщении, и она хоронит те две-три сущности, о которых пользователь на самом деле спросил.

Теперь промпт вместо этого несёт два куда меньших блока:

- **скелет** — по одной строке на область, имена сущностей сгруппированы по доменам, без идентификаторов и без состояний. Он всегда полон в пределах настроенного охвата, поэтому модель всегда видит форму дома.
- **блок найденного** — только те сущности, о которых именно это сообщение, с их `entity_id`, областями и живыми состояниями.

Всё дело в этом разделении. Поиск сам по себе хорошо отвечает на вопрос *«в каком состоянии X»* и плохо — на вопрос *«что вообще есть»*: *«включи свет»* попадает в десяток ламп, *«выключи всё»* не попадает ни во что конкретное, а сущность, которую пользователь описал неудачными словами, не всплывает вовсе — после чего модель, не видя такой сущности в контексте, отвечает, что устройства не существует. Именно то, что скелет присутствует всегда и всегда полон, делает такой провал невозможным.

**Один флажок возвращает старое поведение.** Выключите `dynamic_entity_context` у sub-entry — и агент снова отрисует полный дамп устройств, байт в байт, через тот же кэш, которым пользовался всегда. Больше в ходе не меняется ничего. Это главный выключатель всей возможности, включая расширение для Assist ниже: при выключенном `dynamic_entity_context` опция `dynamic_context_on_assist` не делает ничего, что бы ни стояло у её собственного флажка.

| Опция | По умолчанию | Действие |
|---|---|---|
| `dynamic_entity_context` | **`true`** | Слать скелет и блок найденного вместо полного дампа устройств |
| `dynamic_context_preset` | `optimal` | Какие сущности покрывает скелет — одно из `minimal` / `optimal` / `maximal` / `paranoid` |
| `dynamic_context_on_assist` | `false` | Добавлять блок найденного и тогда, когда задан `llm_hass_api` |

Сколько сущностей вправе добавить поиск — **не** опция: это константа `ENTITY_CONTEXT_MAX_ENTITIES`, сейчас 12. Каждая лишняя опция — это поверхность поддержки, а если 12 окажется неверным числом, менять его следует в одном месте и сразу для всех.

#### Как выглядит скелет

```
Кухня — light: Потолочный, Подсветка; sensor: Влажность, Температура; switch: Кофеварка, Чайник
Спальня — climate: Кондиционер; light: Люстра, Бра
No area — binary_sensor: Входная дверь; vacuum: Пылесос
```

По одной строке на область; внутри — имена сущностей, сгруппированные по доменам.

- **Метки доменов — это сами домены Home Assistant**: `light`, `switch`, `sensor` — оставлены по-английски, ровно так же, как уже устроены каталожные записи индекса сущностей.
- **Имена — дружественные**, разрешаются по цепочке `name → original_name → entity_id`, тем же способом, что и в индексе сущностей.
- **Области идут по алфавиту, а сущности без области — последними**, строкой `No area`, а не выбрасываются. Сущность, которую никто не положил в комнату, — как раз та, о существовании которой пользователь забывает.
- Внутри области домены идут по алфавиту, а имена — в порядке `entity_id`, поэтому дом без изменений отрисовывает одну и ту же карту на каждом ходу.
- **Ни идентификаторов сущностей, ни device class, ни состояний, ни группировки по устройствам.**

Последний пункт удивляет, поэтому стоит сказать почему. **Без Assist API у модели вообще нет tools управления Home Assistant.** Conversation entity собирает свой список tools из `chat_log.llm_api.tools`, а Home Assistant заполняет его только тогда, когда настроен `llm_hass_api`. На том пути, ради которого сделана эта возможность, контекст устройств поэтому чисто информационный — модель отвечает на вопросы о доме, а не действует в нём, если не считать ваших собственных tools из YAML или MCP, которые принимают свои аргументы. `entity_id` в скелете не дал бы модели ничего. Идентификаторы живут в блоке найденного, где их не больше двенадцати и где включение на пути Assist (ниже) делает их пригодными к действию.

На одну сущность скелет тратит примерно 12–20 символов против 60–90 в дампе, который он заменяет. При этом два набора кандидатов у них разные: старый дамп перечислял только сущности, принадлежащие *устройству*, которое стоит в *области*, поэтому он молча пропускал хелперы, шаблонные сущности и всё нераспределённое, — а скелет берёт кандидатов так же, как их берёт индекс сущностей. На `optimal` это заметно более короткий промпт по более широкой карте; на `maximal` или `paranoid` скелет может назвать то, чего старый промпт не называл никогда.

#### Скелет ограничен и сообщает об обрезке

Скелет длиннее `ENTITY_SKELETON_MAX_CHARS` — 6 000 символов, примерно 300–500 сущностей — перестал бы быть картой и стал бы тем самым дампом, который он заменил. Поэтому области выкладываются, пока не исчерпан бюджет, а то, что не поместилось, заменяется последней строкой, называющей пропавшее:

```
… and 27 more area(s) holding 540 entities — use search_entities to look any of them up.
```

Область, которая не поместилась бы целиком даже на свежем бюджете, отрисовывается настолько, насколько влезла, и несёт собственную пометку тем же голосом:

```
… 118 more entities in Гараж — use search_entities to look them up.
```

**Молча не обрезается никогда ничего.** Модель, которая тихо потеряла половину дома, была бы уверенно неправа о нём; модель, которой сказали, чего она не видит, может пойти и посмотреть.

Отрисованный скелет кэшируется по пресетам и общий для всех агентов. Его инвалидируют `entity_registry_updated`, `device_registry_updated` и `area_registry_updated` — те же три события, которые слушает индексатор сущностей, — плюс TTL в 300 секунд как подстраховка на случай изменения, которое почему-то не подняло ни одного из них. От состояний скелет не зависит, поэтому включившийся свет его не пересобирает.

#### Охват — `dynamic_context_preset`

Скелет покрывает то, что выбирает `dynamic_context_preset`, и четыре пресета здесь ровно те же, что у индекса сущностей: `minimal`, `optimal` (по умолчанию), `maximal` и `paranoid`, с тем же монотонным составом. Что именно выбирает каждый — см. таблицу пресетов в §9.10.

**Это намеренно отдельная настройка от `source.preset` любого хранилища сущностей.** Кто пользуется обеими вещами, задаёт обе. Связать их означало бы, что охват промпта меняется всякий раз, когда кто-то правит посторонний индекс, — а это сюрприз похуже второй настройки.

Одно отличие от §9.10 стоит держать в голове: этот пресет решает, что попадает **чат-**провайдеру, в промпт, на каждом ходу, — а не что попадает провайдеру эмбеддингов. `paranoid` здесь означает, что имена скрытых и отключённых сущностей уезжают в вашу LLM на каждом сообщении.

**И он никак не связан с собственной настройкой Home Assistant «выставить сущности в Assist».** Кандидаты берутся из `dynamic_context_preset` и больше ниоткуда, поэтому при включённом `dynamic_context_on_assist` блок найденного может назвать сущности, которые вы намеренно не выставляли в Assist, — вместе с их `entity_id` и текущими состояниями. Если это важно, сузьте `dynamic_context_preset`: по признаку «выставлено в Assist» SmartChain не фильтрует.

#### Индекс сущностей не нужен

Это то, что упускают чаще всего. **Динамическому контексту сущностей не нужны ни хранилище памяти, ни sub-entry эмбеддингов, ни векторный бэкенд.** Скелет строится из реестров сущностей, устройств и областей, а лексический проход поиска читает те же реестры напрямую — сопоставление с приведением регистра и диакритики по дружественному имени, псевдонимам, области и `entity_id`. Если не настроено ничего, кроме самой интеграции, возможность работает в полную силу.

Учтите: запрос здесь — целая фраза пользователя, а не поисковое выражение, составленное моделью, поэтому сопоставление идёт **и целиком, и по словам**: «включи свет на кухне» не называется у вас в доме ничем, зато «свет» — это слово имени «Потолочный свет». Пословный проход сравнивает **целые слова с целыми словами**, а не подстроки: «turn off the light» не достаёт сущность «Office» через «off», а «what is the temperature» не достаёт «Thermostat» через «the». Слова короче трёх символов отбрасываются, а попадание по всей фразе всё равно опережает попадание по слову, так что устройство, чьё имя совпало с запросом целиком, идёт первым. `search_entities` (§9.10) по-прежнему сопоставляет свой `query` целиком и по подстроке: его модель выбирает намеренно.

Две детали не дают пословному проходу вернуть пол-дома:

- **Пословные попадания ранжируются по числу совпавших слов.** Сущность, у которой совпали и «kitchen», и «light», идёт выше той, у которой совпало одно «light». Без этого они встают вровень, и та сущность, которую вы назвали, оказывается там, где придётся.
- **Доменная часть `entity_id` не сопоставляется.** Сопоставляется только object id: `light.kitchen_ceiling` даёт «kitchen» и «ceiling», но никогда «light». Доменное слово общее у всех сущностей домена, поэтому его сопоставление затягивало бы в ответ на любую фразу со словом «light» все ваши лампы разом и с одинаковым весом. Если нужен целый домен, у `search_entities` для этого есть аргумент `domain`.

**Сопоставление буквальное — стемминга нет, и словоформы не совпадают.** «На кухне» даёт слово «кухне», которое не совпадает с областью «Кухня»; «lights» не совпадает с «Light». Поиск находит ровно те слова, которые пользователь набрал, и ровно в той форме, в какой он их набрал. Для русского это настоящее ограничение, а не редкий частный случай: в живой фразе почти каждое существительное стоит в косвенном падеже. Именно на этот случай и рассчитан всегда присутствующий скелет: модель по-прежнему видит «Кухню» и всё, что в ней, по именам, поэтому промах по словоформе стоит вам живых состояний на этом ходу, а не знания о том, что комната существует. Настроенный индекс сущностей закрывает бо́льшую часть остатка — векторный проход не буквален.

Настроенный индекс сущностей (§9.10) добавляет сверху второй проход: векторный поиск по хранилищу, слитый с лексическими попаданиями тем же ранжированием, каким пользуется `search_entities`, — сперва точные лексические, затем префиксные, затем векторные по score, с дедупликацией по `entity_id`. Пословные попадания находятся внутри префиксной группы — ниже попадания по всей фразе и упорядоченные между собой по числу совпавших слов, — то есть всё равно **выше любого векторного попадания**. Об этом стоит знать на широком запросе: одно общее слово, встречающееся в десятках имён, даёт десятки одинаково слабых пословных попаданий, а поскольку итоговый список режется до двенадцати, они способны занять все места и не оставить семантическому проходу ни одного. Лексический проход к тому же останавливается после 200 кандидатов в порядке реестра, а не оставляет лучшие, поэтому на таком запросе сильнейшее пословное совпадение может вообще не попасть в эти двенадцать. Более узкая формулировка или `search_entities` с аргументом `domain` либо `area` возвращают индекс в игру. Векторный проход выполняется, только если индекс сущностей **ровно один**; при двух и более выбрать без произвола нельзя, а спросить некого, поэтому поиск остаётся лексическим, а не отдаёт молча предпочтение одному индексу перед другим.

#### Блок найденного

```
Mentioned in this request:
- light.kitchen_ceiling — Потолочный [Кухня] = on
- switch.kitchen_socket_3 — Кофеварка [Кухня] = off
```

Состояния читаются живыми из `hass.states` в момент отрисовки, а не из сохранённых метаданных хранилища, — то же правило, которому следует `search_entities`. Сущность без состояния читается как `unavailable`; сущность без области показывает `—`. Пустой результат не отрисовывает вообще ничего — не пустой заголовок.

Сущность может встретиться на ходу дважды: по имени в скелете и целиком в блоке найденного. Этот повтор намеренный и дешёвый. Два блока отвечают на разные вопросы, а подавление записи в скелете заставляло бы карту дома менять форму в зависимости от того, о чём спросили, — ровно та нестабильность, ради предотвращения которой скелет и существует.

#### `search_entities` закрывает остальное

Автоматический поиск видит одно сообщение и может промахнуться. `search_entities` (§9.10) остаётся у модели именно для таких случаев, и строки обрезки в скелете указывают на него по имени. Ему, правда, нужен существующий индекс сущностей — tool регистрируется, только если блок `source:` есть хотя бы у одного хранилища, — тогда как описанному здесь автоматическому поиску не нужен.

#### Путь Assist — по желанию и только блок найденного

Когда задан `llm_hass_api`, Home Assistant подставляет собственный список выставленных сущностей и собственные tools управления. Этот список — его, и уменьшить его мы никак не можем, поэтому **по умолчанию на пути Assist эта возможность не делает вообще ничего**: ни скелета, ни блока найденного, никаких изменений.

Включите `dynamic_context_on_assist` — и добавится ровно одно: **блок найденного**, дописанный в `extra_system_prompt` после всего, что там уже было и что сохраняется нетронутым. Скелета — никогда: он дублировал бы список Home Assistant в полную цену.

Взамен вы получаете семантические попадания, которых список выставленных по именам не показывает, причём в форме, пригодной к действию: блок несёт `entity_id`, а tools Assist их принимают. Стоит это токенов на каждом ходу — поверх промпта, который и так везёт список HA. Отсюда и «выключено по умолчанию».

**Включены должны быть оба переключателя.** `dynamic_entity_context` перекрывает и этот путь, поэтому снятый главный флажок глушит расширение для Assist, что бы ни стояло у `dynamic_context_on_assist`. А кандидаты блока берутся из `dynamic_context_preset`, а не из списка выставленных сущностей Home Assistant, — что это значит для сущности, которую вы намеренно держали вне Assist, см. в замечании о пресете выше.

#### Чего оно не делает

**Поиск работает только по последнему сообщению.** Не по истории диалога. Поэтому уточнение вида *«а выключи его»* ищет по местоимению, и блок найденного на таком ходу приходит пустым или мимо цели.

Так сделано намеренно, а не по недоделанности: подмешивание прошлых ходов в запрос находит *предыдущий* предмет разговора, что неверно как минимум не реже, чем верно. И деградирует это мягко именно потому, что скелет на месте всегда: модель по-прежнему видит весь дом по именам, по-прежнему держит прошлые ходы в собственной истории диалога и по-прежнему имеет `search_entities`, если индекс настроен. Такова честная граница этой возможности.

#### Если что-то сломалось

Слоями, чтобы ход не терялся никогда:

- **Поиск упал** → используется один скелет, отказ пишется в лог.
- **Скелет упал** → используется полный дамп устройств, отказ пишется в лог. Отказ никогда не кэшируется, поэтому кратковременная ошибка реестра не может ослепить агента на весь TTL.
- Наверх, в обработчик сообщения, ни то ни другое выброситься не может.

Пустой дом — не отказ и к откату не приводит: он отрисовывает пустой контекст, и промптом остаётся один ваш системный промпт.

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

## 12. Боковая панель

Нажмите **SmartChain AI** в боковой панели HA. Администратор видит пять вкладок, все остальные — только **Camera**.

| Вкладка | Для чего |
|---|---|
| **Agents** | Создание, правка, копирование и удаление агентов у всех провайдеров. |
| **Embeddings** | Привязки эмбеддингов (§9.1). Полностью скрыта, если ни один настроенный провайдер не умеет эмбеддинги. Предупреждает перед переименованием или удалением, которое отвяжет хранилище. |
| **Stores** *(v5.2.0+)* | Хранилища памяти и векторов (§9.2) плюс строка состояния по каждому настроенному хранилищу — включая те, что живут в `tools.yaml` и здесь не редактируются. |
| **Settings** | Настройки подключения записи. У большинства провайдеров их нет, и вкладка так и говорит. |
| **Tools** *(переработана в v5.3.0)* | Конструктор пользовательских инструментов на форме (§7.0) и список всех зарегистрированных инструментов с указанием источника. Редактор `tools.yaml` — с серверной валидацией, резервной копией и откатом — остался, но переехал в блок Import / Export. |
| **Camera** | Выберите камеру, введите вопрос — получите описание. |

Вкладка **Camera** под капотом вызывает `smartchain.analyze_image` — то же поведение, что и у сервиса. Результат отражается в `sensor.smartchain_last_analysis` (правильный SensorEntity с v4.0.2) и шинном событии `smartchain_image_analyzed`.

Каждая форма панели рисуется по схеме, которую сериализует бэкенд, поэтому сама панель не объявляет ни одного имени поля: поле, добавленное в config flow, появляется в ней без правок фронтенда.

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
