"""Tests for loader handling of the `memory:` block."""

from pathlib import Path

import pytest

from custom_components.smartchain.tools.loader import LoaderError, load_tools_file

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_loader_parses_stores(tmp_path: Path) -> None:
    from custom_components.smartchain.tools.memory.config import MemorySettings

    target = tmp_path / "tools.yaml"
    target.write_text((FIXTURE_DIR / "memory_basic.yaml").read_text())
    result = load_tools_file(target)

    assert isinstance(result.memory_settings, MemorySettings)
    assert result.memory_settings.names() == ["conversations", "entities"]

    conv = result.memory_settings.stores[0]
    assert conv.embeddings == "GigaChat Embeddings"
    assert conv.description == "Past conversations"
    assert conv.backend.type == "sqlite_numpy"
    assert conv.retention_days == 30
    assert conv.ingest_conversation is True
    assert conv.logbook.enabled is True
    assert conv.logbook.domains == ["light", "lock"]

    ent = result.memory_settings.stores[1]
    assert ent.backend.type == "pgvector"
    assert ent.backend.table == "smartchain_entities"
    assert ent.retention_days == 0
    assert ent.ingest_conversation is False


def test_loader_without_memory_block_yields_no_stores(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text("tools: []\n")
    result = load_tools_file(target)
    assert result.memory_settings.stores == []


def test_loader_rejects_legacy_flat_block_with_guidance(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text("memory:\n  provider: ollama\n  model: nomic-embed-text\n  api_key: k\n")
    with pytest.raises(LoaderError) as exc:
        load_tools_file(target)

    message = str(exc.value)
    assert "embeddings subentry" in message
    assert "stores:" in message
    assert "reload_tools" in message
