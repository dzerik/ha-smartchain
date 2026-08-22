"""Tests for the `memory:` voluptuous schema."""

import pytest
import voluptuous as vol

from custom_components.smartchain.tools.schema import (
    MEMORY_SCHEMA,
    TOOLS_FILE_SCHEMA,
)


def test_minimal_memory_block_validates() -> None:
    MEMORY_SCHEMA({"provider": "ollama", "model": "nomic-embed-text"})


def test_memory_with_logbook_validates() -> None:
    MEMORY_SCHEMA(
        {
            "provider": "ollama",
            "model": "nomic-embed-text",
            "retention_days": 30,
            "ingest_logbook": {
                "enabled": True,
                "domains": ["light", "lock"],
                "poll_interval_minutes": 15,
            },
        }
    )


def test_unknown_provider_rejected() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"provider": "bogus", "model": "x"})


def test_negative_retention_rejected() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"provider": "ollama", "model": "x", "retention_days": -1})


def test_too_fast_poll_interval_rejected() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA(
            {
                "provider": "ollama",
                "model": "x",
                "ingest_logbook": {"enabled": True, "poll_interval_minutes": 1},
            }
        )


def test_tools_file_schema_accepts_memory_block() -> None:
    TOOLS_FILE_SCHEMA(
        {
            "memory": {"provider": "ollama", "model": "nomic-embed-text"},
        }
    )


def test_tools_file_schema_without_memory_block_still_validates() -> None:
    TOOLS_FILE_SCHEMA({"tools": []})


def test_memory_accepts_backend_block() -> None:
    MEMORY_SCHEMA(
        {
            "provider": "ollama",
            "model": "nomic-embed-text",
            "backend": {"type": "pgvector", "dsn": "postgresql://x/y"},
        }
    )


def test_memory_rejects_unknown_backend_type() -> None:
    with pytest.raises(vol.Invalid):
        MEMORY_SCHEMA({"provider": "ollama", "model": "x", "backend": {"type": "milvus"}})


def test_memory_backend_defaults_to_sqlite_numpy() -> None:
    result = MEMORY_SCHEMA({"provider": "ollama", "model": "x"})
    assert result["backend"]["type"] == "sqlite_numpy"
