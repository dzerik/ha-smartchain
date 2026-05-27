"""Configuration dataclasses for the long-term memory subsystem."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LogbookConfig:
    """Settings for periodic HA logbook ingestion."""

    enabled: bool = False
    domains: list[str] = field(default_factory=list)
    poll_interval_minutes: int = 60


@dataclass(frozen=True)
class MemoryConfig:
    """Top-level memory configuration parsed from tools.yaml."""

    provider: str = "ollama"
    model: str = ""
    enabled: bool = True
    base_url: str | None = None
    api_key: str | None = None
    retention_days: int = 90
    ingest_conversation: bool = True
    logbook: LogbookConfig = field(default_factory=LogbookConfig)
