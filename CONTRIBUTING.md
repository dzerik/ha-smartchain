# Contributing to SmartChain

Thank you for your interest in contributing to SmartChain! This guide will help you get started.

## Getting Started

1. **Fork** the repository
2. **Clone** your fork:
   ```bash
   git clone https://github.com/<your-username>/ha-smartchain.git
   cd ha-smartchain
   ```
3. **Install dependencies** (requires [uv](https://docs.astral.sh/uv/)):
   ```bash
   uv sync
   ```

## Development

### Running Tests

```bash
uv run --prerelease=allow pytest tests/ -v
```

### Running the Panel Tests

The panel (`custom_components/smartchain/panel/`) is plain ES modules loaded
straight from disk by the browser — no bundler, no build step, and no runtime
npm dependency. The tests run those exact files under
[jsdom](https://github.com/jsdom/jsdom) with
[Vitest](https://vitest.dev/), which is the only reason `package.json` exists.

```bash
npm ci        # once, and whenever package-lock.json changes
npm test      # runs custom_components/smartchain/panel/**/*.test.js
npm run test:watch
```

Tests live in `custom_components/smartchain/panel/__tests__/`, next to the code
they cover. `harness.js` there is shared scaffolding, not a test file: a fake
`hass` that records every websocket message and answers from a table of canned
results.

**A panel test must fail when the panel is broken.** Before adding one, break
the code it covers — substitute a wrong value, do not delete the line — and
confirm the new test goes red; then put the code back. A panel test that stays
green against broken code is worse than no test, because it makes the untested
path look covered. This repository has already paid for that lesson: a blank
config form shipped on `main` for a whole subsystem because nothing ever ran
the panel.

Constraints for anything added here:

- **Do not make the panel need a build step to run.** No `require`, no bundler
  imports, no syntax the browser cannot load directly. If a test needs a Vite
  plugin or an alias to load a panel file, the panel has stopped being
  browser-loadable and *that* is the bug.
- Keep the fake `hass` free of SmartChain command names; pass the commands a
  test cares about into `fakeHass({...})`.

### Linting & Formatting

We use [Ruff](https://docs.astral.sh/ruff/) for linting and formatting:

```bash
uv run ruff check .
uv run ruff format --check .
```

To auto-fix:

```bash
uv run ruff check --fix .
uv run ruff format .
```

### Code Style

- Python 3.13+
- Line length: 100 characters
- Follow existing patterns in the codebase
- Keep imports sorted (enforced by Ruff)

## Pull Request Process

1. Create a **feature branch** from `main`:
   ```bash
   git checkout -b feat/my-feature
   ```
2. Make your changes
3. Ensure **all tests pass** and **lint is clean**
4. Write a clear commit message:
   ```
   feat: add support for new provider
   ```
5. Open a Pull Request against `main`

### Commit Message Convention

| Prefix     | Usage                        |
|------------|------------------------------|
| `feat:`    | New feature                  |
| `fix:`     | Bug fix                      |
| `refactor:`| Code refactoring             |
| `docs:`    | Documentation changes        |
| `test:`    | Adding or updating tests     |
| `chore:`   | Maintenance, dependencies    |

### PR Checklist

- [ ] Tests pass (`pytest tests/ -v`)
- [ ] Panel tests pass, if any panel file changed (`npm test`)
- [ ] Lint is clean (`ruff check . && ruff format --check .`)
- [ ] New features have tests
- [ ] Breaking changes are documented

## Adding a New Provider

1. Add constants to `const.py` (engine schema, models, unique ID, default model)
2. Add client creation to `client_util.py`
3. Add config flow step to `config_flow.py`
4. Add setup logic to `__init__.py`
5. Add tests for config flow, setup, and conversation

## Reporting Bugs

Please use the [bug report template](https://github.com/dzerik/ha-smartchain/issues/new?template=bug_report.yml) and include:

- Home Assistant version
- SmartChain version
- Provider used
- Relevant logs

## Questions?

Open a [discussion](https://github.com/dzerik/ha-smartchain/issues) or issue.
