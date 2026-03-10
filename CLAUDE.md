# SmartChain — Project Rules

## Project Overview
SmartChain is a Home Assistant custom integration providing a multi-provider LLM conversation agent via LangChain.

- **Domain**: `smartchain`
- **HA Platform**: `Platform.CONVERSATION` (+ `Platform.AI_TASK` planned)
- **Supported LLM providers**: GigaChat, YandexGPT, OpenAI
- **Planned providers**: Ollama, DeepSeek, Anthropic
- **GitHub**: https://github.com/dzerik/ha-smartchain

## Architecture

### Core Files
- `custom_components/smartchain/__init__.py` — entry setup, client creation
- `custom_components/smartchain/conversation.py` — `SmartChainConversationEntity` (streaming, tool calling)
- `custom_components/smartchain/ai_task.py` — `SmartChainAITaskEntity` (data generation)
- `custom_components/smartchain/config_flow.py` — Config Flow + Options Flow
- `custom_components/smartchain/client_util.py` — LLM client factory (`get_client`, `validate_client`)
- `custom_components/smartchain/const.py` — all constants, prompts, model lists

### Key Patterns
- **Streaming**: `client.astream()` -> `_async_langchain_stream()` -> `chat_log.async_add_delta_content_stream()`
- **Tool calling**: HA `llm.Tool` -> `_ha_tool_to_dict()` -> `client.bind_tools()` -> loop until no `unresponded_tool_results`
- **ChatLog conversion**: `_chatlog_to_langchain()` converts HA ChatLog content to LangChain message list
- **System prompt**: With Assist API — `async_provide_llm_data()`, without — manual Jinja2 template + `DEFAULT_DEVICES_PROMPT`

### Tests
- `tests/test_config_flow.py` — 11 config flow tests
- `tests/test_init.py` — 19 conversation entity tests
- `tests/test_setup.py` — 4 setup/unload tests
- Run: `python3 -m pytest tests/ -v`

## Development Rules

### Naming
- Entity classes: `SmartChain*Entity` (e.g., `SmartChainConversationEntity`)
- Imports: `from custom_components.smartchain.X import Y`
- Domain constant: `DOMAIN = "smartchain"`

### Testing
- Always run tests before committing: `python3 -m pytest tests/ -v`
- All tests must pass
- Mock LLM clients with `MagicMock` + `astream` side_effect
- Use `_make_chat_log()` helper for mock ChatLog with streaming support

### Dependencies
- `langchain-gigachat>=0.3.0` — GigaChat provider
- `langchain-openai>=0.3.0` — OpenAI provider
- `langchain-community>=0.4.0` — YandexGPT and others
- `home-assistant-intents` — language support
- `yandexcloud==0.295.0` — Yandex Cloud SDK

### Version Policy
- Manifest version in `custom_components/smartchain/manifest.json`
- Follow semver: PATCH for fixes, MINOR for features, MAJOR for breaking changes
- Current: 0.7.0
