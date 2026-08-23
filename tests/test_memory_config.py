"""Tests for LogbookConfig, StoreConfig, BackendConfig, and MemorySettings dataclasses."""

from custom_components.smartchain.tools.memory.config import LogbookConfig


def test_logbook_config_defaults() -> None:
    lb = LogbookConfig()
    assert lb.enabled is False
    assert lb.domains == []
    assert lb.poll_interval_minutes == 60


def test_store_config_defaults() -> None:
    from custom_components.smartchain.tools.memory.config import (
        BackendConfig,
        LogbookConfig,
        StoreConfig,
    )

    cfg = StoreConfig(name="conversations", embeddings="GigaChat Embeddings")
    assert cfg.description == ""
    assert cfg.retention_days == 90
    assert cfg.ingest_conversation is True
    assert cfg.backend == BackendConfig()
    assert cfg.logbook == LogbookConfig()


def test_store_config_full() -> None:
    from custom_components.smartchain.tools.memory.config import (
        BackendConfig,
        StoreConfig,
    )

    cfg = StoreConfig(
        name="entities",
        description="Devices and sensors",
        embeddings="Ollama nomic",
        backend=BackendConfig(type="pgvector", dsn="postgresql://x/y"),
        retention_days=0,
        ingest_conversation=False,
    )
    assert cfg.backend.type == "pgvector"
    assert cfg.retention_days == 0
    assert cfg.ingest_conversation is False


def test_memory_settings_defaults_to_no_stores() -> None:
    from custom_components.smartchain.tools.memory.config import MemorySettings

    assert MemorySettings().stores == []


def test_memory_settings_names() -> None:
    from custom_components.smartchain.tools.memory.config import (
        MemorySettings,
        StoreConfig,
    )

    settings = MemorySettings(
        stores=[
            StoreConfig(name="a", embeddings="E1"),
            StoreConfig(name="b", embeddings="E2"),
        ]
    )
    assert settings.names() == ["a", "b"]


def test_entity_source_defaults() -> None:
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    cfg = EntitySourceConfig()
    assert cfg.type == "entities"
    assert cfg.preset == "optimal"
    assert cfg.index_states is False
    assert cfg.include == []
    assert cfg.exclude == []


def test_store_config_source_defaults_to_none() -> None:
    from custom_components.smartchain.tools.memory.config import StoreConfig

    assert StoreConfig(name="a", embeddings="E").source is None


def test_store_config_carries_a_source() -> None:
    from custom_components.smartchain.tools.memory.config import (
        EntitySourceConfig,
        StoreConfig,
    )

    cfg = StoreConfig(
        name="entities",
        embeddings="E",
        source=EntitySourceConfig(preset="paranoid", index_states=True),
    )
    assert cfg.source is not None
    assert cfg.source.preset == "paranoid"
    assert cfg.source.index_states is True
