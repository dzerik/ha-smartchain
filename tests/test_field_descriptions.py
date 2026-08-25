"""Every configurable field must carry `data_description` helper text, in both
locales, for exactly the form(s) it renders on.

Schema-driven, not a hand-written field list: the same trap documented on
`test_every_renderable_subentry_field_has_a_label` in test_subentries.py
applies here too — a field added without a translation renders silently, no
error, no log line. Two fields (`allowed_tools`, `enable_multi_agent_tools`)
already slipped through the *label* version of this gap for two releases
because they sit behind an `if` and only a schema walk, not a fixed field
list, catches a conditional branch.
"""

import ast
import json
from pathlib import Path

import pytest

from custom_components.smartchain import const as const_mod
from custom_components.smartchain.config_flow import (
    ENGINE_SCHEMA,
    STEP_USER_SCHEMA,
    embeddings_subentry_schema,
)

BASE = Path(__file__).parent.parent / "custom_components" / "smartchain"

TRANSLATION_FILES = {
    "translations/en.json": BASE / "translations" / "en.json",
    "translations/ru.json": BASE / "translations" / "ru.json",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _subentry_schema_conf_keys() -> set[str]:
    """`CONF_*` field names `subentry_schema` can render, found by AST walk.

    Mirrors `test_every_renderable_subentry_field_has_a_label`: `subentry_schema`
    needs a live `hass` for some of its branches (registered LLM APIs, the
    tools registry, multi-entry lookups), so calling it here would need a
    fixture just to prove a translation file is complete. Walking the source
    instead finds every `vol.Optional(CONF_..., ...)` / `vol.Required(...)`
    call regardless of which `if` branch it sits under.
    """
    tree = ast.parse((BASE / "config_flow.py").read_text())
    schema_fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "subentry_schema"
    )
    keys: set[str] = set()
    for node in ast.walk(schema_fn):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in ("Optional", "Required") or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Name) and first.id.startswith("CONF_"):
            keys.add(getattr(const_mod, first.id))
    assert keys, "found no schema fields — the AST walk is broken, not the translations"
    return keys


def _schema_field_names(schema) -> set[str]:
    return {str(key.schema) for key in schema.schema}


def test_every_subentry_field_has_a_description_in_both_locales():
    """options.step.settings and config_subentries.conversation.step.{user,
    reconfigure} all render the same field set (`subentry_schema`) and must
    each carry its own `data_description` block — a description present only
    under `options` would leave the two config-subentry forms undocumented."""
    keys = _subentry_schema_conf_keys()

    missing: list[str] = []
    for name, path in TRANSLATION_FILES.items():
        data = _load(path)
        conversation = data["config_subentries"]["conversation"]["step"]
        blocks = {
            "config_subentries.conversation.step.user": conversation["user"].get(
                "data_description", {}
            ),
            "config_subentries.conversation.step.reconfigure": conversation["reconfigure"].get(
                "data_description", {}
            ),
            "options.step.settings": data["options"]["step"]["settings"].get(
                "data_description", {}
            ),
        }
        for block_name, block in blocks.items():
            for key in sorted(keys - set(block)):
                missing.append(f"{name} -> {block_name} -> {key}")
            for key, value in block.items():
                if key in keys and not value.strip():
                    missing.append(f"{name} -> {block_name} -> {key} (empty)")

    assert not missing, "fields rendered without a description:\n" + "\n".join(missing)


def test_every_embeddings_field_has_a_description_in_both_locales():
    """`embeddings_subentry_schema` needs no `hass`, so it is called directly
    rather than AST-walked."""
    schema = embeddings_subentry_schema(["m1", "m2"], {})
    keys = _schema_field_names(schema)
    assert keys == {"name", "model", "model_user"}

    missing: list[str] = []
    for name, path in TRANSLATION_FILES.items():
        data = _load(path)
        embeddings = data["config_subentries"]["embeddings"]["step"]
        blocks = {
            "config_subentries.embeddings.step.user": embeddings["user"].get(
                "data_description", {}
            ),
            "config_subentries.embeddings.step.reconfigure": embeddings["reconfigure"].get(
                "data_description", {}
            ),
        }
        for block_name, block in blocks.items():
            for key in sorted(keys - set(block)):
                missing.append(f"{name} -> {block_name} -> {key}")
            for key, value in block.items():
                if key in keys and not value.strip():
                    missing.append(f"{name} -> {block_name} -> {key} (empty)")

    assert not missing, "fields rendered without a description:\n" + "\n".join(missing)


@pytest.mark.parametrize(
    "engine,schema",
    [
        ("gigachat", ENGINE_SCHEMA[const_mod.ID_GIGACHAT]),
        ("yandexgpt", ENGINE_SCHEMA[const_mod.ID_YANDEX_GPT]),
        ("openai", ENGINE_SCHEMA[const_mod.ID_OPENAI]),
        ("ollama", ENGINE_SCHEMA[const_mod.ID_OLLAMA]),
        ("deepseek", ENGINE_SCHEMA[const_mod.ID_DEEPSEEK]),
        ("anthropic", ENGINE_SCHEMA[const_mod.ID_ANTHROPIC]),
        ("openrouter", ENGINE_SCHEMA[const_mod.ID_OPENROUTER]),
        ("groq", ENGINE_SCHEMA[const_mod.ID_GROQ]),
        ("together", ENGINE_SCHEMA[const_mod.ID_TOGETHER]),
        ("lmstudio", ENGINE_SCHEMA[const_mod.ID_LMSTUDIO]),
        ("llamacpp", ENGINE_SCHEMA[const_mod.ID_LLAMACPP]),
    ],
)
def test_every_provider_step_field_has_a_description_in_both_locales(engine, schema):
    """`ENGINE_SCHEMA` (imported via `const` re-export below) is a plain
    module-level dict — no `hass` needed, so its fields are read straight off
    the live `vol.Schema` object rather than duplicated as a literal list."""
    keys = _schema_field_names(schema)
    assert keys, f"found no fields for {engine} — the schema import is broken, not translations"

    missing: list[str] = []
    for name, path in TRANSLATION_FILES.items():
        data = _load(path)
        block = data["config"]["step"][engine].get("data_description", {})
        for key in sorted(keys - set(block)):
            missing.append(f"{name} -> config.step.{engine} -> {key}")
        for key, value in block.items():
            if key in keys and not value.strip():
                missing.append(f"{name} -> config.step.{engine} -> {key} (empty)")

    assert not missing, "fields rendered without a description:\n" + "\n".join(missing)


def test_the_engine_picker_has_a_description_in_both_locales():
    keys = _schema_field_names(STEP_USER_SCHEMA)
    assert keys == {"engine"}

    missing: list[str] = []
    for name, path in TRANSLATION_FILES.items():
        data = _load(path)
        block = data["config"]["step"]["user"].get("data_description", {})
        for key in sorted(keys - set(block)):
            missing.append(f"{name} -> config.step.user -> {key}")

    assert not missing, "fields rendered without a description:\n" + "\n".join(missing)
