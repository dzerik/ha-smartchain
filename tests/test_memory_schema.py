"""Tests for the `memory:` voluptuous schema."""

import pytest
import voluptuous as vol

from custom_components.smartchain.tools.schema import (
    MEMORY_SCHEMA,
    TOOLS_FILE_SCHEMA,
)


def test_stores_block_validates() -> None:
    TOOLS_FILE_SCHEMA(
        {"memory": {"stores": [{"name": "conversations", "embeddings": "GigaChat Embeddings"}]}}
    )


def test_store_requires_name_and_embeddings() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"stores": [{"name": "a"}]})
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"stores": [{"embeddings": "E"}]})


def test_store_name_pattern_is_enforced() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"stores": [{"name": "Bad Name", "embeddings": "E"}]})


def test_store_name_rejects_trailing_newline() -> None:
    """The name becomes a filename component, so `$` alone would be too lax."""
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"stores": [{"name": "ok\n", "embeddings": "E"}]})


def test_duplicate_store_names_rejected() -> None:
    with pytest.raises(vol.Invalid, match="duplicate"):
        MEMORY_SCHEMA(
            {
                "stores": [
                    {"name": "a", "embeddings": "E1"},
                    {"name": "a", "embeddings": "E2"},
                ]
            }
        )


def test_store_backend_defaults_to_sqlite_numpy() -> None:
    result = MEMORY_SCHEMA({"stores": [{"name": "a", "embeddings": "E"}]})
    assert result["stores"][0]["backend"]["type"] == "sqlite_numpy"


def test_store_rejects_unknown_backend_type() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"stores": [{"name": "a", "embeddings": "E", "backend": {"type": "milvus"}}]})


def test_legacy_flat_block_is_rejected() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"provider": "ollama", "model": "nomic-embed-text"})


def test_backend_table_and_collection_accept_plain_identifiers() -> None:
    result = MEMORY_SCHEMA(
        {
            "stores": [
                {
                    "name": "a",
                    "embeddings": "E",
                    "backend": {"type": "pgvector", "table": "smartchain_memory2"},
                },
                {
                    "name": "b",
                    "embeddings": "E",
                    "backend": {"type": "qdrant", "collection": "_mem"},
                },
            ]
        }
    )
    assert result["stores"][0]["backend"]["table"] == "smartchain_memory2"
    assert result["stores"][1]["backend"]["collection"] == "_mem"


@pytest.mark.parametrize(
    "table",
    [
        'mem"; DROP TABLE users; --',
        "mem memory",
        "Memory",
        "1mem",
        "mem\n",
    ],
)
def test_backend_table_rejects_non_identifiers(table: str) -> None:
    """`table` is interpolated into pgvector DDL/DML and cannot be parameterised."""
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"stores": [{"name": "a", "embeddings": "E", "backend": {"table": table}}]})


@pytest.mark.parametrize(
    "collection",
    [
        "../../collections/other",
        "mem col",
        "Mem",
        "9mem",
        "mem\n",
    ],
)
def test_backend_collection_rejects_non_identifiers(collection: str) -> None:
    """`collection` becomes a segment of the Qdrant REST URL path."""
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA(
            {"stores": [{"name": "a", "embeddings": "E", "backend": {"collection": collection}}]}
        )


def test_source_block_validates() -> None:
    result = MEMORY_SCHEMA(
        {"stores": [{"name": "e", "embeddings": "E", "source": {"type": "entities"}}]}
    )
    source = result["stores"][0]["source"]
    assert source["preset"] == "optimal"
    assert source["index_states"] is False
    assert source["include"] == []


def test_source_rejects_an_unknown_type() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA(
            {"stores": [{"name": "e", "embeddings": "E", "source": {"type": "automations"}}]}
        )


def test_source_rejects_an_unknown_preset() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA(
            {
                "stores": [
                    {
                        "name": "e",
                        "embeddings": "E",
                        "source": {"type": "entities", "preset": "aggressive"},
                    }
                ]
            }
        )


@pytest.mark.parametrize(
    "key,value",
    [
        ("retention_days", 30),
        ("ingest_conversation", True),
        ("ingest_conversation", False),
        ("ingest_logbook", {"enabled": True}),
    ],
)
def test_entity_store_rejects_incompatible_keys(key: str, value: object) -> None:
    """Retention would delete the index by age; ingest would pollute it."""
    with pytest.raises(vol.Invalid, match="do not apply"):
        MEMORY_SCHEMA(
            {
                "stores": [
                    {"name": "e", "embeddings": "E", "source": {"type": "entities"}, key: value}
                ]
            }
        )


def test_entity_store_tolerates_defaulted_ingest_conversation() -> None:
    """The check must look at the raw keys, not at post-default values.

    `ingest_conversation` defaults to True, so a validator running after
    defaults were applied would reject every entity store ever written.
    """
    MEMORY_SCHEMA({"stores": [{"name": "e", "embeddings": "E", "source": {"type": "entities"}}]})


def test_conversation_store_keeps_its_keys() -> None:
    result = MEMORY_SCHEMA({"stores": [{"name": "c", "embeddings": "E", "retention_days": 7}]})
    assert result["stores"][0]["retention_days"] == 7
    assert result["stores"][0].get("source") is None


@pytest.mark.parametrize("bad", ["Sensor", "sensor.", ".x", "sensor x", "a.b.c"])
def test_source_include_rejects_malformed_entries(bad: str) -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA(
            {
                "stores": [
                    {
                        "name": "e",
                        "embeddings": "E",
                        "source": {"type": "entities", "include": [bad]},
                    }
                ]
            }
        )
