"""Tests for the tools.yaml loader."""

from pathlib import Path

import pytest

from custom_components.smartchain.tools.loader import (
    LoaderError,
    load_tools_file,
)
from custom_components.smartchain.tools.model import (
    ServiceAction,
    TemplateAction,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_load_basic_yaml(tmp_path: Path) -> None:
    """Two tools are parsed from the basic fixture."""
    target = tmp_path / "tools.yaml"
    target.write_text((FIXTURE_DIR / "tools_basic.yaml").read_text())

    result = load_tools_file(target)

    assert [t.name for t in result.yaml_tools] == ["ping", "turn_on_light"]
    assert isinstance(result.yaml_tools[0].action, TemplateAction)
    assert result.yaml_tools[0].action.value_template == "pong"
    assert isinstance(result.yaml_tools[1].action, ServiceAction)
    assert result.yaml_tools[1].action.domain == "light"
    assert result.yaml_tools[1].action.target == {"area_id": "{{ area }}"}


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    """A missing tools.yaml is not an error; it yields an empty LoaderResult."""
    target = tmp_path / "does_not_exist.yaml"
    assert load_tools_file(target).yaml_tools == []


def test_load_invalid_yaml_raises(tmp_path: Path) -> None:
    """A syntactically broken YAML raises LoaderError."""
    target = tmp_path / "tools.yaml"
    target.write_text("tools:\n  - not closed: [")
    with pytest.raises(LoaderError):
        load_tools_file(target)


def test_load_validation_error_raises(tmp_path: Path) -> None:
    """Schema-invalid YAML raises LoaderError."""
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: Bad-Name\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: x }\n"
    )
    with pytest.raises(LoaderError):
        load_tools_file(target)


def test_load_duplicate_names_drops_later(tmp_path: Path, caplog) -> None:
    """When two tools share a name, the second is skipped with a logged error."""
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: first\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: a }\n"
        "  - name: ping\n"
        "    description: second\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: b }\n"
    )
    result = load_tools_file(target)
    assert len(result.yaml_tools) == 1
    assert result.yaml_tools[0].description == "first"
    assert "duplicate" in caplog.text.lower()


def test_load_reserved_name_drops_it(tmp_path: Path, caplog) -> None:
    """A tool that uses a reserved built-in name is dropped with a logged error."""
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: get_state_history\n"
        "    description: shadow\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: x }\n"
    )
    result = load_tools_file(target)
    assert result.yaml_tools == []
    assert "reserved" in caplog.text.lower()


def test_load_skips_disabled_tools(tmp_path: Path, caplog) -> None:
    """A tool with `enabled: false` is not converted or registered, and the
    skip is logged at INFO."""
    import logging

    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: on by default\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: a }\n"
        "    enabled: true\n"
        "  - name: pong\n"
        "    description: key omitted, defaults to enabled\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: b }\n"
        "  - name: silent\n"
        "    description: turned off while debugging\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: c }\n"
        "    enabled: false\n"
    )
    with caplog.at_level(logging.INFO):
        result = load_tools_file(target)

    assert {t.name for t in result.yaml_tools} == {"ping", "pong"}
    assert all(t.enabled for t in result.yaml_tools)
    assert "1" in caplog.text and "disabled" in caplog.text.lower()


def test_secret_resolves_when_the_config_dir_is_supplied(tmp_path: Path) -> None:
    """`!secret` works once the loader is given a config dir to root Secrets at.

    A pgvector DSN is exactly the value that belongs in secrets.yaml, so this
    is what keeps credentials out of tools.yaml.
    """
    (tmp_path / "secrets.yaml").write_text("pg_dsn: postgresql://u:p@db.local/smartchain\n")
    conf = tmp_path / "smartchain"
    conf.mkdir()
    target = conf / "tools.yaml"
    target.write_text(
        "memory:\n"
        "  stores:\n"
        "    - name: conversations\n"
        "      embeddings: Embed\n"
        "      backend:\n"
        "        type: pgvector\n"
        "        dsn: !secret pg_dsn\n"
    )

    result = load_tools_file(target, tmp_path)

    assert result.memory_settings.stores[0].backend.dsn == "postgresql://u:p@db.local/smartchain"


def test_secret_without_a_config_dir_still_fails_the_file(tmp_path: Path) -> None:
    """Default behaviour is unchanged for callers that pass only a path."""
    (tmp_path / "secrets.yaml").write_text("pg_dsn: postgresql://u:p@db.local/smartchain\n")
    target = tmp_path / "tools.yaml"
    target.write_text("memory:\n  stores: []\n  note: !secret pg_dsn\n")

    with pytest.raises(LoaderError):
        load_tools_file(target)


def test_missing_secret_raises_without_leaking_any_secret_value(tmp_path: Path) -> None:
    """The error names the missing key; no value from secrets.yaml appears."""
    (tmp_path / "secrets.yaml").write_text("other_key: SUPERSECRETVALUE\n")
    conf = tmp_path / "smartchain"
    conf.mkdir()
    target = conf / "tools.yaml"
    target.write_text(
        "memory:\n"
        "  stores:\n"
        "    - name: conversations\n"
        "      embeddings: Embed\n"
        "      backend:\n"
        "        type: pgvector\n"
        "        dsn: !secret pg_dsn\n"
    )

    with pytest.raises(LoaderError) as exc:
        load_tools_file(target, tmp_path)

    message = str(exc.value)
    assert "pg_dsn" in message
    assert "SUPERSECRETVALUE" not in message
