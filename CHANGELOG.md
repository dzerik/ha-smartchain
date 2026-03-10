# Changelog

Все заметные изменения в проекте документируются в этом файле.

Формат основан на [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/),
проект придерживается [Semantic Versioning](https://semver.org/lang/ru/).

## [0.5.0] - 2026-03-10

### Added
- **Streaming ответов** — `_attr_supports_streaming = True`, ответы LLM передаются потоково через `ChatLog.async_add_delta_content_stream()`
- Async генератор `_async_langchain_stream()` для конвертации `AIMessageChunk` → HA delta dicts
- Тесты streaming: `test_supports_streaming`, `test_async_langchain_stream`, `test_async_langchain_stream_skips_empty_chunks`
- Итого: 29 тестов (11 config flow + 14 conversation + 4 setup)

### Changed
- `client.invoke()` через `async_add_executor_job` заменён на `client.astream()` (async, без executor)
- `async_add_assistant_content_without_tools` заменён на `async_add_delta_content_stream` для потоковой передачи

## [0.4.0] - 2026-03-10

### Changed
- **ChatLog для истории** — удалён собственный `OrderedDict` для хранения истории, используется нативный `ChatLog` HA. История автоматически управляется через `chat_session`
- **Миграция на langchain-gigachat/langchain-openai** — `GigaChat` импортируется из `langchain_gigachat`, `ChatOpenAI` из `langchain_openai` (вместо deprecated `langchain_community.chat_models`)
- Зависимости в `manifest.json`: `gigachain` fork заменён на `langchain-gigachat>=0.3.0`, `langchain-openai>=0.3.0`, `langchain-community>=0.4.0`
- CI: добавлен шаг `pytest` в `push.yml` и `pull.yml`
- Конвертация ChatLog ↔ LangChain messages через `_chatlog_to_langchain()`

### Added
- Тесты setup/unload (`test_setup.py`): 4 теста
- Тесты `_chatlog_to_langchain`: 2 теста
- Итого: 26 тестов (11 config flow + 11 conversation + 4 setup)

### Removed
- `MAX_HISTORY_CONVERSATIONS` константа (больше не нужна, ChatLog управляет историей)
- `OrderedDict` история из `GigaChainConversationEntity`

## [0.3.0] - 2026-03-10

### Added
- **Миграция на ConversationEntity** — `GigaChatAI(AbstractConversationAgent)` заменён на `GigaChainConversationEntity(ConversationEntity)` с поддержкой `_async_handle_message(user_input, chat_log)` и `ChatLog`/`AssistantContent` API
- Новый файл `conversation.py` с entity-based conversation agent
- Платформа `Platform.CONVERSATION` с `async_forward_entry_setups`
- Тесты: 20 тестов (11 config flow + 9 conversation entity) с `pytest-homeassistant-custom-component`
- `CHANGELOG.md` на основе git истории
- `pytest.ini` для конфигурации тестов

### Changed
- `__init__.py` упрощён — setup/unload через `async_forward_entry_setups`/`async_unload_platforms`
- Версия обновлена до 0.3.0

## [0.2.1] - 2026-03-10

### Added
- Опция `verify_ssl` в Options Flow для GigaChat (по умолчанию `False`)
- Декоратор `@callback` на `async_get_options_flow` по best practices HA
- MIT лицензия (`LICENSE`)
- Строка `verify_ssl` в переводах en/ru

### Changed
- GitHub Actions: `actions/checkout` v3 -> v4, `actions/setup-python` v4 -> v5, Python 3.10 -> 3.12
- CI lint: `black` заменён на `ruff check` + `ruff format --check`

### Removed
- Дублирующие workflows `hacs.yaml` и `hassfest.yaml` (уже покрыты в `push.yml`)
- Файл `test-model.py` (мёртвый Anyscale код)

## [0.2.0] - 2026-03-10

### Fixed
- **Блокирующий вызов LLM** — `_client(messages)` заменён на `await hass.async_add_executor_job(client.invoke, messages)`, event loop HA больше не блокируется
- **Deprecated LangChain API** — `client(messages)` (`__call__`) заменён на `client.invoke(messages)`
- **Утечка памяти** — `dict` заменён на `OrderedDict` с лимитом `MAX_HISTORY_CONVERSATIONS = 50`
- **Баг модели OpenAI** — `DEFAULT_MODEL[ID_ANYSCALE]` исправлен на `DEFAULT_MODEL[ID_OPENAI]` (`gpt-4o-mini`)
- **Пробел-sentinel** — `" "` заменён на `""`, проверки `== " "` заменены на `not model or not model.strip()`
- Логика OptionsFlow: убрана безусловная ошибка `"unsupported"`

### Changed
- Импорты: `from langchain.schema import ...` -> `from langchain_core.messages import ...`
- Хранение клиента: `hass.data[DOMAIN]` -> `entry.runtime_data` (HA best practices)
- Config Flow: `FlowResult` -> `ConfigFlowResult`, добавлены type hints
- Метод `common_model_async_step` переименован в `_common_model_async_step` (приватный)
- Валидация: `validate_client` теперь использует `hass.async_add_executor_job`
- Pre-commit: ruff v0.9.7 с ruff-format (заменяет black + isort + ruff)
- Модели GigaChat: добавлен GigaChat-Max
- Модели OpenAI: gpt-4o, gpt-4o-mini, gpt-4-turbo, o1, o1-mini, o3-mini (удалены устаревшие text-davinci, code-davinci и др.)
- Модель OpenAI по умолчанию: `gpt-3.5-turbo` -> `gpt-4o-mini`
- Переводы: русская локализация дополнена (ошибки, skip_validation)

### Removed
- **Anyscale полностью удалён** — все константы, модели, импорт `ChatAnyscale`, класс `LocalChatAnyscale`, шаги config flow, записи в translations

## [0.1.8] - 2024-12-01

### Fixed
- Совместимость с Home Assistant 2024.12.1+ (#12)

### Removed
- Anyscale (начало удаления, rc-0.1.8)

## [0.1.7] - 2024-10-01

### Fixed
- Совместимость с Home Assistant (#9)

## [0.1.6] - 2024-08-01

### Added
- Поддержка Anyscale LLM (#8)
- Поддержка встроенного обработчика команд HA (`process_builtin_sentences`) (#6)

## [0.1.5] - 2024-07-01

### Changed
- Улучшены GitHub Actions workflows

## [0.1.4] - 2024-06-01

### Added
- Выбор моделей из списка в Options Flow

## [0.1.3] - 2024-05-01

### Added
- Поддержка настройки параметров моделей (температура, макс. токенов)
- Откат с community на официальную библиотеку gigachain

### Changed
- Bump version

## [0.1.2] - 2024-04-01

### Changed
- Bump version для совместимости с manifest

## [0.1.1] - 2024-03-01

### Added
- Первоначальный релиз
- Поддержка GigaChat и YandexGPT
- Config Flow для настройки через UI
- Options Flow для изменения параметров
- История диалогов
- Системный промпт с Jinja2 шаблонами
