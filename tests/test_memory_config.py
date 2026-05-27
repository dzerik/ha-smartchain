"""Tests for MemoryConfig / LogbookConfig dataclasses."""

from custom_components.smartchain.tools.memory.config import (
    LogbookConfig,
    MemoryConfig,
)


def test_memory_config_defaults() -> None:
    cfg = MemoryConfig(provider="ollama", model="nomic-embed-text")
    assert cfg.enabled is True
    assert cfg.base_url is None
    assert cfg.api_key is None
    assert cfg.retention_days == 90
    assert cfg.ingest_conversation is True
    assert cfg.logbook == LogbookConfig()


def test_logbook_config_defaults() -> None:
    lb = LogbookConfig()
    assert lb.enabled is False
    assert lb.domains == []
    assert lb.poll_interval_minutes == 60


def test_memory_config_with_logbook() -> None:
    cfg = MemoryConfig(
        provider="openai",
        model="text-embedding-3-small",
        api_key="sk-xxx",
        retention_days=30,
        logbook=LogbookConfig(enabled=True, domains=["light", "lock"], poll_interval_minutes=15),
    )
    assert cfg.api_key == "sk-xxx"
    assert cfg.retention_days == 30
    assert cfg.logbook.enabled is True
    assert cfg.logbook.poll_interval_minutes == 15
