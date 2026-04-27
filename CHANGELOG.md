# Changelog

All notable changes to this project are documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
project follows [Semantic Versioning](https://semver.org/).

## [4.0.1] - 2026-04-27

### Fixed
- **GigaChat subentry options silently ignored** — `verify_ssl` and `profanity` toggles set in a subentry's form are now actually applied to the GigaChat client. Previously these were always read from the parent entry's options, so per-subentry values were lost.
- **Event-loop blocking I/O on first message** — `load_skills()` (sync YAML reads from disk) is now awaited via the executor inside the conversation entity, preventing the loop from stalling on the first reply.
- **Event-loop blocking I/O on multimodal messages** — when a chat log carries image attachments, `_chatlog_to_langchain()` (which reads files and may run TurboJPEG) is now offloaded to the executor. Plain text conversations stay on the event loop with no extra hop.
- **`_safe_extract_json` mangling responses** — fence-stripping now drops only the opening ` ``` `/` ```json ` fence and a matching trailing ` ``` `, instead of removing every backtick at either end of the response.

### Refactored
- **Config-flow model validation** — three near-identical model-resolution blocks (`_validate_and_create`, `_validate_and_update`, `OptionsFlow.async_step_settings`) now share a single `_normalize_model_input()` helper.
- **`common_config_option_schema` alias removed** — the dead backwards-compat shim referenced no live consumers after the v4.0.0 cleanup.

## [4.0.0] - 2026-04-27

### ⚠ BREAKING CHANGES

The LLM-driven YAML generation feature has been removed. SmartChain is now focused on conversation, AI Task, and camera analysis only.

### Removed
- **Services** — `smartchain.generate_automation`, `smartchain.deploy_automation`, `smartchain.validate_automation`, `smartchain.list_yaml`, `smartchain.get_yaml`. Existing automations that call these will fail at runtime — remove or replace those calls before upgrading.
- **Options-flow steps** — `generate_automation` and `preview_automation`. The options menu is collapsed: opening the integration's options now goes straight to the model-settings form.
- **Panel components** — the YAML editor (sidebar explorer, code editor, AI bar, toolbar, entity picker). The sidebar panel is now camera-analysis only.
- **Const prompts** — `GENERATE_AUTOMATION_PROMPT`, `GENERATE_SCRIPT_PROMPT`, `GENERATE_SCENE_PROMPT`, `GENERATE_BLUEPRINT_PROMPT`, `GENERATE_PROMPTS`, `IMPROVE_YAML_PROMPT`.
- **`hass.data[DOMAIN]` keys** — `generate_yaml` and `deploy_automation` are no longer registered.
- **Translation keys** (`options.error.{description_required, no_agent, service_not_ready, generation_failed, deploy_failed, empty_yaml}`, `options.abort.{automation_deployed, automation_not_deployed}`, `options.step.{init, generate_automation, preview_automation}`).

### Kept
- Conversation entity, AI Task entity, all 6 LLM providers (GigaChat, YandexGPT, OpenAI, Ollama, DeepSeek, Anthropic).
- `smartchain.ask` and `smartchain.analyze_image` services.
- `helpers.async_generate_structured()` — generic structured-output helper for downstream integrations (not tied to YAML generation).
- Sidebar panel — pruned to the camera analysis tab only.

### Migration
1. Remove any HA automations or scripts that call the deleted services.
2. If you were generating automations through the SmartChain panel, generate them via the LLM directly (`smartchain.ask`) and paste into HA's native automation editor.
3. The integration's options form will appear as a single screen instead of a menu — no action required.

### Tests
- 118 passing (was 128). The 10 dropped tests covered only the removed services.

## [3.0.5] - 2026-03-12

### Fixed
- **Code displayed in fragments** — `_rebuildEditor()` now clears container DOM (`innerHTML = ""`) before creating new editor, preventing leftover elements from previous instance
- **Stale content during rebuild** — `forceNormalMode(newValue)` accepts value parameter to set content atomically with editor rebuild, avoiding flash of old content

## [3.0.4] - 2026-03-12

### Fixed
- **Diff view opens on file load** — `forceNormalMode()` always exits diff when loading/creating files, regardless of flag state
- **"No changes" in diff stats** — replaced unreliable `setTimeout` with Monaco `onDidUpdateDiff` event for accurate stats
- **Diff state desync** — `forceNormalMode()` disposes diff editor even if `_diffMode` flag was already false

## [3.0.3] - 2026-03-12

### Fixed
- **Duplicate automations removed** — removed HA state machine loading, only YAML files are listed (no more duplicates)
- **Blueprints now visible** — removed filter that skipped files without `blueprint` metadata key; all `*.yaml` files under `blueprints/` are now listed via `rglob('*.yaml')`
- **Unsaved changes prompt** — switching files or creating new shows confirm dialog when editor has unsaved changes
- **Cursor blinking at 1:1** — removed `editor.focus()` call after loading YAML to prevent cursor position reset

## [3.0.2] - 2026-03-12

### Changed
- **Diff view redesigned** — full diff toolbar with navigation (prev/next change), inline/side-by-side toggle, diff statistics (+N/-N), Accept/Revert buttons
- `goToDiff('next')` / `goToDiff('previous')` Monaco API for diff navigation
- `renderSideBySide` toggle for inline vs side-by-side diff modes
- Accept applies modified content as new baseline; Revert restores original
- **Agent selector visible** — moved agent and type selectors from hidden options into the main AI bar, always visible

### Fixed
- Agent/subagent selector was hidden inside collapsible options and not discoverable

## [3.0.1] - 2026-03-12

### Fixed
- **Sidebar scroll** — item list now scrollable with proper flex layout on `sc-sidebar-explorer`
- **Tooltips** — type filter buttons (Automations/Scripts/Scenes/Blueprints) now show tooltip labels on hover
- **Blueprints loading** — scan entire `blueprints/` tree (automation + script + custom domains), not just `blueprints/automation/`
- **Load all items** — automations, scripts, scenes now also discovered from HA state machine (UI-defined items in `.storage/`), not only from YAML files
- **Monaco Editor visibility** — fixed zero-height container by setting `display: flex; flex: 1` on host custom elements

## [3.0.0] - 2026-03-12

### Added
- **Monaco Editor** — replaced custom YAML editor with Microsoft Monaco Editor (VS Code engine) loaded from CDN
- Full YAML/JSON syntax highlighting, IntelliSense, bracket matching, folding, find & replace (Ctrl+F)
- **Built-in diff editor** — Monaco's native side-by-side diff view with change navigation, replaces custom LCS diff
- **Jinja2 language support** — custom Monarch tokenizer for HA Jinja2 templates (`{{ }}`, `{% %}`, `{# #}`)
- **Custom keyboard shortcuts**: Ctrl+Shift+V (validate), Ctrl+Shift+D (deploy), Ctrl+Shift+G (diff toggle), Ctrl+Enter (AI focus)
- **Context menu actions** — SmartChain validate/deploy/diff/copy available in editor right-click menu
- SmartChain dark theme (`smartchain-dark`) extending VS Dark with Jinja2 token colors
- Status bar shows keyboard shortcut hints

### Changed
- `code-editor.js` and `diff-viewer.js` replaced by single `monaco-wrapper.js`
- Editor container uses `automaticLayout: true` for responsive resizing
- AI bar result now switches to Monaco diff mode automatically (showing old vs new)
- **MAJOR**: Monaco loaded from CDN (~2MB cached), requires internet on first load

## [2.9.0] - 2026-03-12

### Added
- **IDE-like panel** — complete redesign of SmartChain AI panel into a two-column IDE layout
- Left sidebar: file-explorer with type filters (All/Automations/Scripts/Scenes/Blueprints), search, item list with blueprint badges
- Right panel: full-screen YAML code editor with line numbers, tab-key indent, always-edit mode
- **AI assistant bar** — bottom input for describing changes, Enter to submit, agent/type selectors, entity picker toggle
- **Diff viewer** — inline LCS-based diff with context lines, add/delete highlighting, stats (+N/-N)
- **Toolbar** — Validate, Deploy, Diff toggle, Copy buttons with inline validation status
- Mode tabs: Editor (IDE) and Camera (existing camera analysis)
- Status bar showing line count, type, and item ID

### Changed
- Panel completely rewritten from tab-based generate/camera to IDE layout with 7 ES module components
- New components: `sidebar-explorer.js`, `code-editor.js`, `diff-viewer.js`, `ai-bar.js`, `toolbar.js`
- Existing `generate-tab.js`, `yaml-editor.js`, `yaml-picker.js` replaced by new components
- Camera tab preserved as second mode
- Auto-diff display after AI generates/improves YAML
- Total: 128 tests passing

## [2.8.1] - 2026-03-12

### Security
- **Path traversal fix** — `get_yaml` service now validates resolved blueprint paths stay within the blueprints directory, blocking `../../` traversal attacks
- **Input validation** — `get_yaml` service `id` parameter now restricted to safe characters (`[a-zA-Z0-9_./\- ]`)

### Fixed
- **Race condition** — YAML file writes (deploy) now protected by asyncio Lock to prevent concurrent write corruption
- **Validation on deploy** — `generate_automation` with `deploy=True` now validates YAML before deploying (previously skipped validation)
- **HTTP error handling** — model fetch functions (`_fetch_ollama_models`, `_fetch_openai_compatible_models`, `_fetch_anthropic_models`) now call `raise_for_status()` to properly detect API errors
- Fixed test warnings for `raise_for_status` mock in `test_fetch_models.py`

## [2.8.0] - 2026-03-12

### Added
- **YAML picker** — `list_yaml` and `get_yaml` services to browse and load existing HA items (automations, scripts, scenes, blueprints) into the panel editor
- "Choose from HA" / "Paste YAML" source tabs in the panel editor for flexible input workflow
- Blueprint-based automation detection: panel shows a warning when loaded automation uses a blueprint and recommends editing the blueprint instead
- `get_yaml` service returns raw YAML text of any existing automation, script, scene, or blueprint by ID

### Changed
- Panel editor now has two source modes: browse existing HA items or paste YAML manually
- Total: 128 tests passing

## [2.7.0] - 2026-03-12

### Added
- **"Edit existing YAML" / improve mode** — panel sends `source_yaml` parameter to LLM for targeted improvements to existing automations/scripts/scenes
- `IMPROVE_YAML_PROMPT` dedicated prompt for improve mode, instructing LLM to modify only what is asked while preserving existing structure
- `source_yaml` parameter in `generate_automation` service — when provided, LLM improves the given YAML rather than generating from scratch

### Changed
- Replaced custom `_collect_ha_context()` helper with HA's built-in Jinja2 `DEFAULT_DEVICES_PROMPT` template rendering for richer and more accurate home context in automation generation
- Fixed yaml-editor line numbers display (`white-space: pre` CSS rule to prevent number wrapping)
- Panel YAML editor shows correct line numbers for long files

## [2.6.0] - 2026-03-12

### Added
- **Multi-type YAML generation** — panel and service support `yaml_type` parameter: `automation`, `script`, `scene`, `blueprint`
- Dedicated generation prompts per YAML type (`GENERATE_AUTOMATION_PROMPT`, `GENERATE_SCRIPT_PROMPT`, `GENERATE_SCENE_PROMPT`, `GENERATE_BLUEPRINT_PROMPT`)
- Type-aware YAML validation: structure checks adapted per type (triggers only for automations, etc.)
- Type-aware deploy routing: scripts deploy to `scripts.yaml`, scenes to `scenes.yaml`, blueprints to `blueprints/` directory

### Changed
- Panel JavaScript decomposed from monolithic 430-line file into 7 ES module components for maintainability
- `generate_automation` service now accepts optional `yaml_type` field (defaults to `automation`)
- Validation checks adapted to the target YAML type

## [2.5.0] - 2026-03-12

### Added
- **HA context enrichment** — LLM prompt for automation generation now includes real entity IDs, area names, and device list from the live Home Assistant instance
- **YAML validation** — generated automations are validated for: correct structure (triggers/actions present), entity ID existence in HA, and referenced service availability
- **Entity picker** in panel — browse and insert entity IDs from HA directly into the description field
- **Agent selector** in panel — choose which SmartChain agent handles generation requests
- Validation errors shown inline in the panel before deploying

### Changed
- Panel UI extended with entity picker dropdown and agent selector
- Total: 128 tests passing

## [2.4.1] - 2026-03-12

### Fixed
- `deploy_automation` service now writes to `automations.yaml` instead of `.storage/automations` (correct HA file-based storage path)
- Removed unused imports from `__init__.py`

## [2.4.0] - 2026-03-12

### Added
- **SmartChain AI sidebar panel** — custom web component registered as a Home Assistant sidebar panel at `/smartchain/panel.js`
- Panel has two tabs: **Generate Automation** (natural language → YAML → deploy) and **Analyze Camera** (select camera entity → analyze with LLM → show result)
- Panel uses `hass.connection.sendMessagePromise` for service calls with `return_response`
- Static file served via `async_register_static_paths([StaticPathConfig(...)])`
- Panel registration is graceful — HA without `frontend` platform still loads the integration

### Changed
- `async_setup()` registers panel at domain level alongside existing services
- Total: 128 tests passing

## [2.3.0] - 2026-03-12

### Added
- **Interactive automation wizard** in Options Flow — describe automation in natural language, preview generated YAML, then deploy in one flow
- `deploy_automation` service — accepts raw YAML and writes it to `automations.yaml`, then calls `automation.reload`
- Options Flow now shows a **menu** as init step: "settings" (existing model config) or "generate_automation" (wizard)

### Changed
- `OptionsFlow` init step changed from form to menu (`async_step_init` returns menu)
- Tests must now select menu item first: `{"next_step_id": "settings"}` or `{"next_step_id": "generate_automation"}`

## [2.2.0] - 2026-03-12

### Added
- **`generate_automation` service** — converts natural language description into a Home Assistant automation YAML. Accepts `description` (required) and `entity_id` (optional, selects which agent generates). Returns `yaml` field in response
- `GENERATE_AUTOMATION_PROMPT` — dedicated system prompt instructing LLM to output only valid HA YAML with triggers, conditions, and actions
- 8 new service tests covering `generate_automation` and `analyze_image`

### Changed
- Total: 128 tests passing

## [2.1.0] - 2026-03-12

### Added
- **Security Guard blueprint** (`docs/blueprints/security_guard.yaml`) — ready-to-use HA blueprint that uses `analyze_image` to monitor cameras and send alerts when suspicious activity is detected

### Fixed
- GigaChat vision: `auto_upload_images=True` now correctly passed in `GigaChat()` constructor, enabling image analysis with GigaChat multimodal models

## [2.0.0] - 2026-03-12

### Added
- **`analyze_image` service** — takes a camera entity snapshot, encodes it as base64, sends to a multimodal LLM, and returns the analysis. Supports optional custom prompt
- `_find_client()` in `__init__.py` — shared helper for service handlers to locate the correct LLM client by `entity_id` or use the first available
- Service returns structured response: `{"response": "...", "entity_id": "..."}`

### Changed
- `async_setup()` now registers both `smartchain.ask` and `smartchain.analyze_image`
- Total: 128 tests passing

---

## [1.9.0] - 2026-03-11

### Added
- **v1.9 Dynamic model lists** — model dropdowns in config/options flow are now populated dynamically from provider APIs (Ollama, OpenAI, DeepSeek, Anthropic, GigaChat). YandexGPT uses static list. Falls back to static lists on network errors
- `async_fetch_models()` in `client_util.py` — fetches available models via HTTP (aiohttp) or SDK
- 7 new tests for model fetching (all providers + fallback)

### Changed
- `_subentry_schema()` accepts optional `models` parameter
- `OptionsFlow`, `ConversationSubentryFlow` fetch models before building schema
- Total: 110 tests passing

## [1.8.0] - 2026-03-11

### Added
- **v1.8 Prompt caching** — TTL-based cache (30s) for Jinja2-rendered system prompts. Avoids repeated expensive template rendering for device lists
- **v1.7 Skill system** — load custom skills from YAML files (`config/smartchain/skills/*.yaml`). Skills define name, description, and prompt — appended to system prompt as additional context
- **v1.5 smartchain.ask service** — simple service for automations (Telegram, Slack, etc). Accepts message + optional entity_id, returns LLM response. With services.yaml definition
- **v1.4 Multi-agent delegation** — `ask_agent` tool allows agents to delegate tasks to sibling agents in the same config entry. Tool-based routing without LangGraph dependency
- **v1.3 State history tool** — `get_state_history` tool lets LLM query past device states via HA recorder. Configurable via `enable_history_tool` option. Capped at 24h, last 20 changes
- **v1.2 MCP support** — works through HA native MCP integration + Assist API multi-select. No custom code needed
- **v1.0 Vision** — camera image analysis via multimodal LLM messages. `_attachment_to_base64()` reads images, optional PyTurboJPEG compression for large images

### Changed
- Custom tool calls (history, delegate) marked as `external=True` in stream, handled after `async_add_delta_content_stream`
- `_async_langchain_stream` sets `external` flag for custom tool names
- `async_setup()` added to register `smartchain.ask` service at domain level
- Total: 103 tests passing

## [0.9.0] - 2026-03-10

### Added
- **Sub-entries** — multiple conversation agents per provider via `ConfigSubentryFlow`. Each sub-entry has its own model, prompt, temperature, LLM API, and creates independent ConversationEntity + AITaskEntity
- `ConversationSubentryFlow` with `async_step_user()` and `async_step_reconfigure()` for adding/editing agents
- `async_get_supported_subentry_types()` on ConfigFlow returns `{"conversation": ConversationSubentryFlow}`
- Backward compatible: entries without sub-entries continue working in legacy mode (single agent from `entry.options`)
- **Options Flow tests** — 7 new tests covering form display, model validation, GigaChat-specific fields, LLM API handling
- **E2E tool calling loop test** — full simulation: user request → tool_call → tool execution → final response
- **Sub-entries tests** — 8 tests covering subentry flow, setup with subentries, multiple agents, legacy fallback

### Changed
- `conversation.py` — `SmartChainConversationEntity` now accepts `subentry_id` and `options` params; uses `_agent_options` and `_client` properties
- `ai_task.py` — `SmartChainAITaskEntity` now accepts `subentry_id`; uses `_client` property
- `__init__.py` — `async_setup_entry` creates per-subentry clients dict or single legacy client
- `config_flow.py` — renamed `common_config_option_schema()` → `_subentry_schema()` (backward-compatible alias kept)
- `OptionsFlow` — removed `__init__` (config_entry is read-only property in modern HA)
- Total: 67 tests passing

### Fixed
- `OptionsFlow.__init__` — removed setter for `self.config_entry` (read-only property in HA 2025+)

## [0.8.0] - 2026-03-10

### Added
- **Ollama provider** — local models (Llama 3.3, Qwen3, Gemma 3, T-Pro 2, T-Lite, DeepSeek R1, Phi 4, Home-3B). Config: base_url only, no API key needed
- **DeepSeek provider** — cheapest cloud LLM (deepseek-chat, deepseek-reasoner). Uses ChatOpenAI with DeepSeek base URL
- **Anthropic provider** — Claude models (claude-sonnet-4-6, claude-haiku-4-5, claude-opus-4-6) via ChatAnthropic

### Changed
- **ai_task made optional** — no longer in manifest.json dependencies, detected dynamically. Fixes hang on HA versions without ai_task support
- Config Flow extended with `async_step_ollama`, `async_step_deepseek`, `async_step_anthropic`
- `client_util.py` — new client factories for Ollama (ChatOllama), DeepSeek (ChatOpenAI), Anthropic (ChatAnthropic)
- `manifest.json` — added `langchain-anthropic`, `langchain-ollama` to requirements
- `pyproject.toml` — migrated to `requires-python>=3.13`, added all langchain dev deps

### Fixed
- ResponseError test updated for new gigachat API signature
- Dependency resolution: pinned langchain packages to compatible ranges (core<1)

## [0.7.0] - 2026-03-10

### Changed
- **Project renamed: GigaChain -> SmartChain** — reflects multi-provider nature (not GigaChat-only)
- Domain: `gigachain` -> `smartchain`
- Entity classes: `GigaChainConversationEntity` -> `SmartChainConversationEntity`
- New GitHub repository: `ha-smartchain`
- HACS name: SmartChain
- Version bumped to 0.7.0

### Added
- **AI Task entity** — `SmartChainAITaskEntity` implements `ai_task.AITaskEntity` with `_async_generate_data()` for automation-driven text generation via `ai_task.generate_data` service
- Structured output support in AI Task (JSON parsing with `task.structure`)
- Tool calling support in AI Task (reuses conversation entity's LangChain integration)

## [0.6.0] - 2026-03-10

### Added
- **Assist API for device control** — integration with HA LLM API (`async_provide_llm_data`) allows LLM to call Home Assistant services (turn on/off lights, locks, etc.)
- `llm_hass_api` option in Options Flow — select HA API for LLM (Assist, custom APIs)
- HA `llm.Tool` (voluptuous schema) -> LangChain tools conversion via `voluptuous_openapi` + `client.bind_tools()`
- Tool calling loop with `MAX_TOOL_ITERATIONS = 10`
- `tool_calls` in `AIMessageChunk` -> HA `ToolInput` in stream deltas
- `ToolResultContent` <-> LangChain `ToolMessage` conversion in `_chatlog_to_langchain()`

### Changed
- `_async_handle_message` — uses `async_provide_llm_data` when LLM API configured, manual prompt otherwise
- Options Flow: `common_config_option_schema` takes `hass` to list available LLM APIs

## [0.5.0] - 2026-03-10

### Added
- **Streaming responses** — `_attr_supports_streaming = True`, responses streamed via `ChatLog.async_add_delta_content_stream()`
- Async generator `_async_langchain_stream()` for `AIMessageChunk` -> HA delta dicts

### Changed
- `client.invoke()` via `async_add_executor_job` replaced with `client.astream()` (async, no executor)

## [0.4.0] - 2026-03-10

### Changed
- **ChatLog for history** — removed custom `OrderedDict`, uses native HA `ChatLog`
- **Migration to langchain-gigachat/langchain-openai** — proper package imports

## [0.3.0] - 2026-03-10

### Added
- **Migration to ConversationEntity** — entity-based conversation agent with `_async_handle_message(user_input, chat_log)`

## [0.2.0] - 2026-03-10

### Fixed
- Blocking LLM calls, deprecated LangChain API, memory leaks, model defaults

### Removed
- Anyscale support completely removed

## [0.1.8] - 2024-12-01

### Fixed
- Compatibility with Home Assistant 2024.12.1+

## [0.1.1] - 2024-03-01

### Added
- Initial release with GigaChat, YandexGPT support
- Config Flow and Options Flow
- Chat history and Jinja2 system prompts
