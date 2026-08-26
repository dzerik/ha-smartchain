"""The memory-store subentry type in Home Assistant's own dialog.

The panel is not the only way in: Devices & Services can add a subentry too,
and a store created there must be the same store, held to the same rules. That
is what `validate_store_input` and one schema builder are for — this file is
where the flow half of that claim is exercised.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigSubentry, ConfigSubentryData
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.config_flow import (
    ConfigFlow,
    memory_store_subentry_schema,
)
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_OPENAI,
    MEMORY_BACKEND_TYPES,
    MEMORY_SOURCE_TYPES,
    SUBENTRY_TYPE_MEMORY_STORE,
    UNIQUE_ID_OPENAI,
)
from custom_components.smartchain.tools.memory.subentry_source import (
    store_config_from_subentry,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

BASE = Path(__file__).parent.parent / "custom_components" / "smartchain"
TITLE = "OpenAI Embeddings"


def _entry(hass: HomeAssistant, *, engine=ID_OPENAI, titles=(TITLE,)) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: engine, CONF_API_KEY: "k"},
        options={},
        unique_id=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={"model": "text-embedding-3-small"},
                subentry_type="embeddings",
                title=title,
                unique_id=None,
            )
            for title in titles
        ],
    )
    entry.add_to_hass(hass)
    return entry


# --- the type is offered --------------------------------------------------


@pytest.mark.parametrize("engine", [ID_OPENAI, ID_DEEPSEEK, ID_ANTHROPIC])
async def test_every_provider_offers_the_store_type(hass: HomeAssistant, engine) -> None:
    """Unlike embeddings, this is not gated on a provider capability: a store
    binds to an embeddings *title*, which can live on a different config
    entry, so a provider that cannot embed can still host the store."""
    entry = _entry(hass, engine=engine)
    assert SUBENTRY_TYPE_MEMORY_STORE in ConfigFlow.async_get_supported_subentry_types(entry)


# --- the two-step flow ----------------------------------------------------


async def test_flow_creates_a_store(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_MEMORY_STORE), context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "conversations",
            "embeddings": TITLE,
            "description": "Dialogue history",
            "backend_type": "sqlite_numpy",
            "source_type": "none",
        },
    )
    assert result["type"] == "form"
    assert result["step_id"] == "details"

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"retention_days": 30, "ingest_conversation": True}
    )
    assert result["type"] == "create_entry"
    assert result["title"] == "conversations"
    assert result["data"]["embeddings"] == TITLE
    assert "name" not in result["data"]


async def test_the_second_step_follows_the_first_answer(hass: HomeAssistant) -> None:
    """A config-flow form cannot change shape while open, so the questions that
    decide the shape are asked first and the rest follow."""
    entry = _entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_MEMORY_STORE), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "vectors",
            "embeddings": TITLE,
            "description": "",
            "backend_type": "qdrant",
            "source_type": "none",
        },
    )
    fields = {str(key.schema) for key in result["data_schema"].schema}
    assert {"url", "api_key", "collection", "verify_ssl"} <= fields
    assert "dsn" not in fields
    assert "path" not in fields


async def test_the_flow_refuses_a_name_the_panel_would_refuse(hass: HomeAssistant) -> None:
    """One validator, two front doors."""
    entry = _entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_MEMORY_STORE), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "Not A Valid Name",
            "embeddings": TITLE,
            "description": "",
            "backend_type": "sqlite_numpy",
            "source_type": "none",
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"retention_days": 90, "ingest_conversation": True}
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "invalid_name"}


async def test_the_flow_refuses_a_pgvector_store_with_no_dsn(hass: HomeAssistant) -> None:
    entry = _entry(hass)
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_MEMORY_STORE), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "vectors",
            "embeddings": TITLE,
            "description": "",
            "backend_type": "pgvector",
            "source_type": "none",
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {"dsn": "", "table": "memories", "retention_days": 90, "ingest_conversation": True},
    )
    assert result["type"] == "form"
    assert result["errors"] == {"base": "dsn_required"}


async def test_reconfigure_keeps_the_stored_credential(hass: HomeAssistant) -> None:
    """The form does not receive the key back, so an untouched edit submits it
    empty — which must mean "keep", not "clear"."""
    entry = _entry(hass)
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data={
                "embeddings": TITLE,
                "backend_type": "qdrant",
                "url": "https://qdrant.example",
                "api_key": "keep-me",
                "collection": "memories",
                "verify_ssl": True,
                "retention_days": 90,
                "ingest_conversation": True,
                "source_type": "none",
            },
            subentry_type=SUBENTRY_TYPE_MEMORY_STORE,
            title="conversations",
            unique_id=None,
        ),
    )
    subentry_id = next(
        sub.subentry_id
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_TYPE_MEMORY_STORE
    )

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_MEMORY_STORE),
        context={"source": "reconfigure", "subentry_id": subentry_id},
    )
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "name": "conversations",
            "embeddings": TITLE,
            "description": "edited",
            "backend_type": "qdrant",
            "source_type": "none",
        },
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "url": "https://qdrant.example",
            "api_key": "",
            "collection": "memories",
            "verify_ssl": True,
            "retention_days": 90,
            "ingest_conversation": True,
        },
    )
    assert result["type"] == "abort"
    stored = entry.subentries[subentry_id].data
    assert stored["api_key"] == "keep-me"
    assert stored["description"] == "edited"


# --- the schema itself ----------------------------------------------------


def _fake_hass_with_titles(titles):
    hass = MagicMock()
    entry = MagicMock()
    entry.subentries = {
        str(index): MagicMock(subentry_type="embeddings", title=title)
        for index, title in enumerate(titles)
    }
    hass.config_entries.async_entries.return_value = [entry]
    return hass


def _all_store_fields() -> set[str]:
    """Every field the store form can render, across every branch.

    A conditional field is exactly the kind that slips through a hand-written
    list — the same trap `test_every_renderable_subentry_field_has_a_label`
    documents for `subentry_schema`.
    """
    hass = _fake_hass_with_titles([TITLE])
    fields: set[str] = set()
    for backend in MEMORY_BACKEND_TYPES:
        for source in MEMORY_SOURCE_TYPES:
            schema = memory_store_subentry_schema(
                hass, {"backend_type": backend, "source_type": source}
            )
            fields |= {str(key.schema) for key in schema.schema}
    return fields


def test_the_schema_covers_every_backend_and_source() -> None:
    fields = _all_store_fields()
    assert {"dsn", "table", "url", "api_key", "collection", "path"} <= fields
    assert {"preset", "index_states", "include", "exclude"} <= fields
    assert {"retention_days", "ingest_conversation"} <= fields


def test_an_entity_store_declares_no_retention_field() -> None:
    """The mutual exclusion tools/schema.py enforces in YAML, enforced here by
    simply not declaring the fields — so voluptuous's PREVENT_EXTRA rejects
    them without a second rule to keep in step."""
    hass = _fake_hass_with_titles([TITLE])
    schema = memory_store_subentry_schema(hass, {"source_type": "entities"})
    fields = {str(key.schema) for key in schema.schema}
    assert "retention_days" not in fields
    assert "ingest_conversation" not in fields
    assert "preset" in fields


def test_a_missing_binding_stays_selectable() -> None:
    """Editing a store whose embeddings binding was deleted must still be
    possible — otherwise the selector's own membership check makes the store
    permanently unsavable, including the edit that would fix it."""
    hass = _fake_hass_with_titles([TITLE])
    schema = memory_store_subentry_schema(hass, {"embeddings": "Deleted Binding"})
    key = next(k for k in schema.schema if str(k.schema) == "embeddings")
    values = [option["value"] for option in schema.schema[key].config["options"]]
    assert "Deleted Binding" in values


def test_a_duplicated_title_is_labelled_rather_than_hidden() -> None:
    """Hiding it would leave a user editing an already-bound store with no way
    to see why it stopped working."""
    hass = _fake_hass_with_titles([TITLE, TITLE])
    schema = memory_store_subentry_schema(hass, {})
    key = next(k for k in schema.schema if str(k.schema) == "embeddings")
    labels = {option["value"]: option["label"] for option in schema.schema[key].config["options"]}
    assert "duplicated" in labels[TITLE]


# --- translations ---------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        BASE / "translations" / "en.json",
        BASE / "translations" / "ru.json",
        BASE / "strings.json",
    ],
    ids=["en", "ru", "strings"],
)
def test_every_store_field_is_labelled_and_described(path: Path) -> None:
    fields = _all_store_fields()
    data = json.loads(path.read_text(encoding="utf-8"))
    steps = data["config_subentries"]["memory_store"]["step"]

    labels: set[str] = set()
    described: set[str] = set()
    for step in steps.values():
        labels |= set(step.get("data", {}))
        described |= {
            name for name, text in step.get("data_description", {}).items() if text.strip()
        }

    assert not fields - labels, f"{path.name}: unlabelled {sorted(fields - labels)}"
    assert not fields - described, f"{path.name}: undescribed {sorted(fields - described)}"


@pytest.mark.parametrize(
    "path",
    [
        BASE / "translations" / "en.json",
        BASE / "translations" / "ru.json",
        BASE / "strings.json",
    ],
    ids=["en", "ru", "strings"],
)
def test_every_refusal_the_flow_can_show_has_a_translation(path: Path) -> None:
    """`errors={"base": key}` renders the raw key when the translation is
    missing, with no error and no log line."""
    from custom_components.smartchain.config_flow import STORE_ERROR_TEXT

    data = json.loads(path.read_text(encoding="utf-8"))
    errors = data["config_subentries"]["memory_store"].get("error", {})
    assert not set(STORE_ERROR_TEXT) - set(errors)


def test_a_store_built_by_the_flow_reads_back_as_a_store_config(hass) -> None:
    """The dialog and the panel write the same shape, so the same reader
    understands both."""
    subentry = MagicMock()
    subentry.title = "conversations"
    subentry.data = {
        "embeddings": TITLE,
        "backend_type": "pgvector",
        "dsn": "postgresql://u:p@h/db",
        "table": "memories",
        "retention_days": 90,
        "ingest_conversation": True,
        "source_type": "none",
    }
    config = store_config_from_subentry(subentry)
    assert config.backend.type == "pgvector"
    assert config.backend.table == "memories"
    assert config.source is None
