# SmartChain — Project Rules

## CRITICAL: Workflow Rules

### Never stop until the plan is complete
- When given a TODO list or plan — execute ALL items, do NOT stop after partial completion
- Track progress with TaskCreate/TaskUpdate, mark each item as completed
- If blocked on one item — skip it, continue with others, return to blocked items later
- Only stop when ALL tasks are done or user explicitly says stop

### Commit and push after every milestone
- Commit and push after each completed feature, fix, or logical unit of work
- Do NOT accumulate large uncommitted changes
- Each commit should be atomic: tests pass, lint clean, code works
- Always run `uv run --prerelease=allow pytest tests/ -v` and `ruff check . && ruff format .` before committing

### Act autonomously
- Make decisions independently — do not ask questions unless truly ambiguous
- Choose the simplest working solution
- Fix problems as they arise, do not leave broken state

## Design Principles

### SOLID
- **S**ingle Responsibility: each file/class has one purpose (conversation.py = conversation, ai_task.py = AI tasks, client_util.py = client creation)
- **O**pen/Closed: new providers added by extending `const.py` + `client_util.py` + `config_flow.py`, no modification of existing provider logic
- **L**iskov Substitution: all LangChain clients are interchangeable (same `astream()`, `bind_tools()` interface)
- **I**nterface Segregation: `ConversationEntity` and `AITaskEntity` are separate, not merged into one god-class
- **D**ependency Inversion: `conversation.py` depends on abstract LangChain `BaseChatModel`, not concrete `GigaChat`/`ChatOpenAI`

### DRY (Don't Repeat Yourself)
- Shared functions in `conversation.py`: `_chatlog_to_langchain()`, `_async_langchain_stream()`, `_ha_tool_to_dict()`
- `ai_task.py` imports and reuses these instead of duplicating
- `_common_model_async_step()` in config_flow handles all providers through one method
- `ENGINE_SCHEMA`, `ENGINE_MODELS`, `UNIQUE_ID`, `DEFAULT_MODEL` dicts in const.py — add provider = add to dicts

### KISS (Keep It Simple)
- No unnecessary abstractions — provider factory is just if/elif, not a complex plugin system
- No metaclasses, no registries, no dynamic imports beyond what's needed
- Lazy imports only where required (Ollama, Anthropic — to avoid mandatory dependency)

### YAGNI (You Aren't Gonna Need It)
- Don't add features not in the current TODO/ROADMAP phase
- Don't build plugin architectures "for the future"
- Don't add config options nobody asked for

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
- Test every new provider: config flow selection, full flow, setup entry

### Dependencies (CRITICAL constraint)
- `gigachat>=0.2.0` — required for Python 3.14 / pydantic v2 compatibility
- `langchain-gigachat` requires `langchain-core<1`
- ALL langchain packages must be pinned to versions compatible with `langchain-core<1`
- `langchain-community<0.4` (0.4+ needs core>=1)
- `ai_task` NOT in manifest.json dependencies (detected at import time in __init__.py)
- `requires-python>=3.13`

### Version Policy
- Version in `pyproject.toml` AND `custom_components/smartchain/manifest.json` — ALWAYS keep in sync
- Follow semver: PATCH for fixes, MINOR for features, MAJOR for breaking changes
- Current: 0.8.1
