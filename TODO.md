# SmartChain — TODO

## Phase 1 — Competitive parity

- [x] v0.6 Assist API — device control via tool calling
- [x] v0.7 Rename GigaChain -> SmartChain + AI Task entity
- [x] v0.8.1 Ollama — local models (Llama, Qwen, Gemma, T-Pro, Home-3B)
- [x] v0.8.2 DeepSeek — cheapest cloud provider (V3, R1)
- [x] v0.8.3 Anthropic — Claude via LangChain
- [x] v0.9 Sub-entries — multiple agents with different models/prompts

## Phase 2 — Differentiation

- [x] v1.0 Vision — camera image analysis (GigaChat 2.0, GPT-4o, Ollama)
- [x] v1.1 Image generation — Kandinsky (GigaChat) + YandexART
- [x] v1.2 MCP — connect external MCP servers as tools (via HA native MCP + Assist API)
- [x] v1.3 State history — LLM analyzes past events and trends

## Phase 3 — Leadership

- [x] v1.4 Multi-agent — Dispatcher + specialized agents (tool-based delegation)
- [x] v1.5 smartchain.ask service — for Telegram/Slack/automation use
- [ ] v1.6 STT/TTS — Yandex SpeechKit, full voice pipeline
- [x] v1.7 Skill system — loadable skills from YAML
- [ ] v1.8 Prompt caching — token savings on repeated requests

## Technical debt

- [x] Tests: Options Flow (config_flow)
- [ ] Test: integration with real ChatLog (not mock)
- [x] E2E test: tool calling loop
- [ ] HACS: verify compatibility and publish
