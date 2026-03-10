# SmartChain — Project Rules

## Project Overview
SmartChain is a Home Assistant custom integration providing a multi-provider LLM conversation agent via LangChain.

- **Domain**: `smartchain`
- **HA Platforms**: `Platform.CONVERSATION` + `Platform.AI_TASK` (optional, detected dynamically)
- **Supported LLM providers**: GigaChat, YandexGPT, OpenAI, Ollama, DeepSeek, Anthropic
- **GitHub**: https://github.com/dzerik/ha-smartchain

## Architecture

### Core Files
- `custom_components/smartchain/__init__.py` — entry setup, client creation, dynamic AI_TASK detection
- `custom_components/smartchain/conversation.py` — `SmartChainConversationEntity` (streaming, tool calling)
- `custom_components/smartchain/ai_task.py` — `SmartChainAITaskEntity` (data generation for automations)
- `custom_components/smartchain/config_flow.py` — Config Flow (6 providers) + Options Flow
- `custom_components/smartchain/client_util.py` — LLM client factory (`get_client`, `validate_client`)
- `custom_components/smartchain/const.py` — all constants, prompts, model lists

### Key Patterns
- **Streaming**: `client.astream()` -> `_async_langchain_stream()` -> `chat_log.async_add_delta_content_stream()`
- **Tool calling**: HA `llm.Tool` -> `_ha_tool_to_dict()` -> `client.bind_tools()` -> loop until no `unresponded_tool_results`
- **ChatLog conversion**: `_chatlog_to_langchain()` converts HA ChatLog content to LangChain message list
- **System prompt**: With Assist API — `async_provide_llm_data()`, without — manual Jinja2 template + `DEFAULT_DEVICES_PROMPT`
- **Provider client creation**: lazy imports for optional providers (Ollama, Anthropic)

### Provider Implementation
| Provider | LangChain Class | Auth | Package |
|----------|----------------|------|---------|
| GigaChat | `GigaChat` | credentials | `langchain-gigachat` |
| YandexGPT | `ChatYandexGPT` | api_key + folder_id | `langchain-community` |
| OpenAI | `ChatOpenAI` | api_key | `langchain-openai` |
| Ollama | `ChatOllama` | base_url (no key) | `langchain-ollama` |
| DeepSeek | `ChatOpenAI` | api_key + deepseek base_url | `langchain-openai` |
| Anthropic | `ChatAnthropic` | api_key | `langchain-anthropic` |

### Tests (51 total)
- `tests/test_config_flow.py` — 18 config flow tests (all 6 providers)
- `tests/test_init.py` — 19 conversation entity tests
- `tests/test_setup.py` — 7 setup/unload tests (all providers)
- `tests/test_ai_task.py` — 7 AI task tests
- Run: `uv run --prerelease=allow pytest tests/ -v`
- Lint: `uv run --prerelease=allow ruff check . && ruff format --check .`

## Development Rules

### Naming
- Entity classes: `SmartChain*Entity` (e.g., `SmartChainConversationEntity`)
- Imports: `from custom_components.smartchain.X import Y`
- Domain constant: `DOMAIN = "smartchain"`

### Testing
- Always run tests before committing
- All tests must pass, lint must be clean
- Mock LLM clients with `MagicMock` + `astream` side_effect
- `conftest.py` has mock data for all 6 providers

### Dependencies (CRITICAL constraint)
- `langchain-gigachat` requires `langchain-core<1`
- ALL langchain packages must be pinned to versions compatible with `langchain-core<1`
- `langchain-community<0.4` (0.4+ needs core>=1)
- `ai_task` NOT in manifest.json dependencies (detected at import time in __init__.py)
- `requires-python>=3.13`

### Version Policy
- Version in `pyproject.toml` AND `custom_components/smartchain/manifest.json`
- Follow semver: PATCH for fixes, MINOR for features, MAJOR for breaking changes
- Current: 0.8.0
