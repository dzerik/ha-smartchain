"""Tests for the sqlite-vec backend, including the extension-missing path."""

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.sqlite_vec import (
    SqliteVecBackend,
)

sqlite_vec = pytest.importorskip(
    "sqlite_vec", reason="sqlite-vec is optional and not installed in CI"
)


async def test_initialize_creates_virtual_table(hass: HomeAssistant, tmp_path) -> None:
    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    await be.initialize(3)
    assert be.is_available is True
    await be.close()


async def test_upsert_then_query(hass: HomeAssistant, tmp_path) -> None:
    from custom_components.smartchain.tools.memory.backends.base import VectorRecord

    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    await be.initialize(3)
    await be.upsert(
        [
            VectorRecord("a", [1.0, 0.0, 0.0], "text-a", {"kind": "conversation"}),
            VectorRecord("b", [0.0, 1.0, 0.0], "text-b", {"kind": "conversation"}),
        ]
    )
    hits = await be.query([1.0, 0.0, 0.0], top_k=1, where=None)
    assert [h.doc_id for h in hits] == ["a"]
    await be.close()
