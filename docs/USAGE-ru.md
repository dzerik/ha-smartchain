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
  kind: conversation    # any | conversation | logbook (default: any)
  agent_id: conversation.smartchain_main   # необязательно — только этот агент
```

Стреляет `smartchain_memory_cleared` с `{"deleted": <int>}`. Бросает `HomeAssistantError` если память не сконфигурирована.

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
| `search_memory` *(v4.3.0+)* | блок `memory:` в YAML | Семантический поиск по embeddings диалогов + logbook (см. §9) |
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
    url: "https://api.openweathermap.org/data/2.5/forecast?q={{ city }}&appid=!secret openweather_key"
    timeout: 10
    response_format: json   # или "text"
```

`!secret` резолвится HA-loader'ом. Не-2xx-ответы → `"Error: HTTP <статус>"`. Network-ошибки и таймауты тоже → чистые error-строки, без leak текста исключения в LLM.

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
      Authorization: "Bearer !secret brave_api_key"
    timeout: 30
    verify_ssl: true

  - name: github
    transport: http
    url: https://api.example.com/mcp/github
    headers:
      Authorization: "Bearer !secret github_token"
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

Сохранять диалоги и (опционально) HA logbook как embeddings в локальной Chroma векторной БД. LLM может вспоминать их через встроенный tool `search_memory`.

### 9.1. Включение в `tools.yaml`

```yaml
memory:
  enabled: true
  provider: ollama                    # ollama | openai | gigachat | yandex
  model: nomic-embed-text
  base_url: http://localhost:11434    # для ollama; для облака игнорируется
  api_key: "!secret openai_embed_key" # обязателен для openai / gigachat / yandex
  retention_days: 90                  # 0 отключает ежедневную чистку
  ingest_conversation: true
  ingest_logbook:
    enabled: false
    domains: [light, climate, lock, alarm_control_panel]
    poll_interval_minutes: 60
```

Рекомендуемая стартовая точка: `provider: ollama` с `nomic-embed-text` — локально, бесплатно, privacy-friendly. Облачные провайдеры отправляют embedded-текст на их серверы.

### 9.2. Как это видит LLM

После включения каждый ход диалога планирует background task, который embedд'ит и сохраняет `User: <q>\n\nAssistant: <a>` с метаданными `{kind: conversation, timestamp, agent_id, subentry_id, conversation_id}`. Tool `search_memory` добавляется в список tools LLM.

> Пользователь: *«Напомни, что я говорил вчера вечером про посудомойку.»*
>
> Ассистент вызывает `search_memory(query="посудомойка", kind="conversation")`, получает релевантные прошлые ходы и отвечает на их основе.

Tool также фильтрует по текущему `subentry_id` — агенты по умолчанию видят только свои memories (privacy-гарантия).

### 9.3. Ингест logbook (opt-in)

Установите `ingest_logbook.enabled: true` — SmartChain будет периодически импортировать записи HA logbook (с фильтром по доменам) как memories `kind: logbook`. LLM может запрашивать `search_memory(query="…", kind="logbook")` или `kind="any"` для объединения.

> **Заметка:** Ингест logbook зависит от внутренностей HA logbook (`logbook.humanify` / `_get_events`) — на некоторых версиях HA этих имён нет и ингест тихо no-op'ит. Ингест диалогов работает независимо.

### 9.4. Чистка памяти

Используйте сервис `smartchain.clear_memory` (§5.4) для удаления memories. Фильтр по `kind` и/или `agent_id`. Полная Chroma БД живёт в `<config>/.storage/smartchain_memory/`.

### 9.5. Персистентность и устойчивость

- Embeddings считаются через `hass.async_add_executor_job` (не блокирует event-loop) с timeout 30 с per call.
- Падающий embeddings-провайдер не крашит диалог — лог WARNING, ход не ингестится.
- Daily retention task удаляет записи старше `retention_days` (timezone-normalised в UTC).

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
Tool `search_memory` был вызван, но блока `memory:` нет в `tools.yaml`. Либо добавьте его, либо перестаньте просить LLM использовать tool.

### Embeddings-провайдер недоступен
- `ollama`: убедитесь что он запущен и достижим по `base_url`; скачайте модель (`ollama pull nomic-embed-text`).
- Облачные провайдеры: проверьте `api_key` и что имя модели совпадает с написанием провайдера.
- Фейлы логируются WARNING; диалог продолжается без ингеста.

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
