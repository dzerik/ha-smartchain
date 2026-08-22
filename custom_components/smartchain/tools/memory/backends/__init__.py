"""Pluggable vector storage backends for the SmartChain memory subsystem."""

import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from ....const import (
    MEMORY_DEFAULT_PG_TABLE,
    MEMORY_DEFAULT_QDRANT_COLLECTION,
)
from .base import BackendInitError, Filter, VectorBackend, VectorHit, VectorRecord

LOGGER = logging.getLogger(__name__)

__all__ = [
    "BackendInitError",
    "Filter",
    "VectorBackend",
    "VectorHit",
    "VectorRecord",
    "create_backend",
]


def create_backend(
    hass: HomeAssistant,
    config: Any,
    store_name: str,
    storage_dir: Path,
) -> VectorBackend:
    """Build the backend named by `config.type`.

    `storage_dir` is where file-based backends put their database; the file is
    named after the store so several stores can coexist.

    Raises BackendInitError for an unknown type — a value the schema should
    have rejected, so reaching this is a bug rather than user error.
    """
    backend_type = getattr(config, "type", None) or "sqlite_numpy"

    if backend_type == "sqlite_numpy":
        from .sqlite_numpy import SqliteNumpyBackend  # noqa: PLC0415

        return SqliteNumpyBackend(hass, _db_path(config, storage_dir, store_name))

    if backend_type == "sqlite_vec":
        from .sqlite_vec import SqliteVecBackend  # noqa: PLC0415

        return SqliteVecBackend(hass, _db_path(config, storage_dir, store_name))

    if backend_type == "pgvector":
        from .pgvector import PgVectorBackend  # noqa: PLC0415

        return PgVectorBackend(
            hass,
            dsn=getattr(config, "dsn", "") or "",
            table=getattr(config, "table", None) or MEMORY_DEFAULT_PG_TABLE,
        )

    if backend_type == "qdrant":
        from .qdrant import QdrantBackend  # noqa: PLC0415

        return QdrantBackend(
            hass,
            url=getattr(config, "url", "") or "",
            collection=(getattr(config, "collection", None) or MEMORY_DEFAULT_QDRANT_COLLECTION),
            api_key=getattr(config, "api_key", None),
            verify_ssl=bool(getattr(config, "verify_ssl", True)),
        )

    raise BackendInitError(f"unknown backend type {backend_type!r}")


def _db_path(config: Any, storage_dir: Path, store_name: str) -> Path:
    """Resolve the on-disk path for a file-based backend."""
    configured = getattr(config, "path", None)
    if configured:
        return Path(configured)
    return storage_dir / f"{store_name}.db"
