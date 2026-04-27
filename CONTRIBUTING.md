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
