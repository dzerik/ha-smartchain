"""Tests for the tools.yaml loader."""

from pathlib import Path

import pytest

from custom_components.smartchain.tools.loader import (
    LoaderError,
    load_tools_file,
)
from custom_components.smartchain.tools.model import (
    ACTION_DEFAULT_TIMEOUT,
    ServiceAction,
    TemplateAction,
)
from tests.conftest import BUILT_IN_TOOL_NAMES

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


def test_a_disabled_tool_does_not_reserve_its_name(tmp_path) -> None:
    """Switching a tool off and adding its replacement under the same name must
    keep the replacement.

    The duplicate check used to claim the name before the `enabled` check ran,
    so the disabled entry shadowed the live one and the replacement vanished
    with only a "duplicate tool name" line in the log to explain it.
    """
    path = tmp_path / "tools.yaml"
    path.write_text(
        "tools:\n"
        "  - name: weather\n"
        "    enabled: false\n"
        "    description: the old one, switched off\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: old }\n"
        "  - name: weather\n"
        "    description: the replacement\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: new }\n"
    )
    result = load_tools_file(path)
    names = [t.name for t in result.yaml_tools]
    assert names == ["weather"]
    assert result.yaml_tools[0].description == "the replacement"


@pytest.mark.parametrize("reserved", sorted(BUILT_IN_TOOL_NAMES))
def test_every_built_in_name_is_reserved_against_the_file(
    tmp_path: Path, caplog, reserved: str
) -> None:
    """All six built-ins, not three.

    `search_memory`, `ask_agents` and `critique_response` were shadowable until
    v5.3.0: a tools.yaml tool taking one of those names reached `bind_tools`
    alongside the built-in, appended last, so the model read the built-in's
    description while the dispatch lookup resolved to the custom tool.
    Parametrised over the whole frozenset so adding a built-in later cannot
    quietly reopen the gap.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        f"  - name: {reserved}\n"
        "    description: shadow\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: x }\n"
    )
    result = load_tools_file(target)
    assert result.yaml_tools == []
    assert "reserved" in caplog.text.lower()


def test_broken_parameters_schema_is_caught_at_load_and_names_tool_and_field(
    tmp_path: Path,
) -> None:
    """A `type: str` typo is a load error, not a first-call surprise.

    USAGE §7.0.1 promises the JSON Schema is validated before it is saved. It
    was not: only the outer shell was checked, so the file loaded clean and the
    tool detonated inside `jsonschema.validate` the first time a model reached
    for it. The message has to name the tool and the field, because the
    voluptuous path alone says `data['tools'][3]` and nobody counts list items.
    """
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: fine\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: pong }\n"
        "  - name: weather\n"
        "    description: broken\n"
        "    parameters:\n"
        "      type: object\n"
        "      properties:\n"
        "        city: { type: str }\n"
        "    action: { type: template, value_template: x }\n"
    )
    with pytest.raises(LoaderError) as err:
        load_tools_file(target)
    message = str(err.value)
    assert "weather" in message
    assert "parameters" in message


def test_action_without_timeout_key_still_loads_with_a_default(tmp_path: Path) -> None:
    """Files written before the key existed keep working, with a budget."""
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: morning\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: script, script: script.morning_routine }\n"
        "  - name: lights\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: service, domain: light, service: turn_on }\n"
    )
    result = load_tools_file(target)
    assert [t.action.timeout for t in result.yaml_tools] == [
        ACTION_DEFAULT_TIMEOUT,
        ACTION_DEFAULT_TIMEOUT,
    ]


def test_explicit_timeout_reaches_the_action(tmp_path: Path) -> None:
    """An explicit `timeout:` is what the executor gets, not the default."""
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: morning\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: script, script: script.morning_routine, timeout: 7 }\n"
        "  - name: lights\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: service, domain: light, service: turn_on, timeout: 9 }\n"
    )
    result = load_tools_file(target)
    assert [t.action.timeout for t in result.yaml_tools] == [7, 9]
