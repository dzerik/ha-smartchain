# Repository Guidelines

## Project Structure & Module Organization

SmartChain is a multi-provider LLM integration for Home Assistant. Python source lives in `custom_components/smartchain/`: configuration flows, conversation handling, websocket APIs, and services. `tools/` contains custom tools, MCP support, and memory backends. `panel/` contains browser-loaded JavaScript components; `translations/` contains localization files.

Python tests and YAML fixtures live in `tests/` and `tests/fixtures/`. Panel tests live in `custom_components/smartchain/panel/__tests__/`. `docs/` contains English and Russian guides; `static/` holds documentation images. Read `CONTRIBUTING.md` for detailed workflows.

## Build, Test, and Development Commands

Use Python 3.13+ and uv; panel CI uses Node.js 22.

- `uv sync --prerelease=allow`: install Python development dependencies as CI does.
- `uv run --prerelease=allow pytest tests/ -v`: run Python tests.
- `uv run --prerelease=allow ruff check .`: check lint and import ordering.
- `uv run --prerelease=allow ruff format --check .`: verify formatting; omit `--check` to format.
- `npm ci`: install locked panel test dependencies.
- `npm test`: run panel tests; `npm run test:watch` starts watch mode.

The panel has no build step or runtime npm dependencies. For manual testing, copy `custom_components/smartchain/` into a Home Assistant configuration's `custom_components/` directory, restart Home Assistant, and add SmartChain through Devices & Services.

## Coding Style & Naming Conventions

Use four-space Python indentation, type annotations, `snake_case` functions/modules, `PascalCase` classes, and `UPPER_SNAKE_CASE` constants. Ruff enforces a 100-character line length and sorted imports. Follow existing JavaScript style: two-space indentation, camelCase methods, and kebab-case component filenames. Keep panel modules browser-loadable without bundling or transpilation.

## Testing Guidelines

Python uses pytest, pytest-homeassistant-custom-component, and automatic asyncio handling. Name files `test_*.py`, reuse fixtures in `tests/conftest.py`, and mock provider calls. JavaScript uses Vitest with jsdom and `*.test.js` files. Add behavioral tests for new features. For new panel tests, substitute an incorrect value in covered code, confirm failure, then restore it. No numeric coverage threshold is configured.

## Commit & Pull Request Guidelines

Use the history's prefixes: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, and `chore:`; dependency updates use `chore(deps):`. Branch from `main`, e.g. `feat/my-feature`, and target PRs there. Describe behavior changes and validation, link relevant issues, and document breaking changes. Ensure Python tests and Ruff checks pass; run panel tests whenever panel files change.
