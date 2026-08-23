"""Configuration dataclasses for the long-term memory subsystem."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LogbookConfig:
    """Settings for periodic HA logbook ingestion."""

    enabled: bool = False
    domains: list[str] = field(default_factory=list)
    poll_interval_minutes: int = 60


@dataclass(frozen=True)
class BackendConfig:
    """Vector backend selection and its per-type settings.

    One dataclass carries every backend's options rather than a union: the
    schema already rejects irrelevant combinations, and a flat shape keeps the
    factory a simple attribute read.
    """

    type: str = "sqlite_numpy"
    # sqlite_numpy / sqlite_vec
    path: str | None = None
    # pgvector
    dsn: str | None = None
    table: str | None = None
    # qdrant
    url: str | None = None
    api_key: str | None = None
    collection: str | None = None
    verify_ssl: bool = True


@dataclass(frozen=True)
class EntitySourceConfig:
    """Turns a store into an index of Home Assistant entities.

    `include` and `exclude` accept either a bare domain (`sensor`) or a full
    entity_id (`sensor.kitchen_temperature`). `exclude` is applied last and
    wins over both the preset and `include`.
    """

    type: str = "entities"
    preset: str = "optimal"
    index_states: bool = False
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StoreConfig:
    """One named memory store: an embeddings binding plus a vector backend."""

    name: str
    embeddings: str = ""
    description: str = ""
    backend: BackendConfig = field(default_factory=BackendConfig)
    retention_days: int = 90
    ingest_conversation: bool = True
    logbook: LogbookConfig = field(default_factory=LogbookConfig)
    source: EntitySourceConfig | None = None


@dataclass(frozen=True)
class MemorySettings:
    """The parsed `memory:` block — a list of named stores."""

    stores: list[StoreConfig] = field(default_factory=list)

    def names(self) -> list[str]:
        return [s.name for s in self.stores]
