"""The sqlite_vec backend must fail loudly and name its replacement."""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.base import BackendInitError
from custom_components.smartchain.tools.memory.backends.sqlite_vec import (
    SqliteVecBackend,
)


async def test_missing_package_raises_with_guidance(hass: HomeAssistant, tmp_path) -> None:
    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    with patch(
        "custom_components.smartchain.tools.memory.backends.sqlite_vec._load_sqlite_vec",
        side_effect=ImportError("no module named sqlite_vec"),
    ):
        with pytest.raises(BackendInitError, match="sqlite_numpy"):
            await be.initialize(3)
    assert be.is_available is False


async def test_extension_loading_disabled_raises_with_guidance(
    hass: HomeAssistant, tmp_path
) -> None:
    be = SqliteVecBackend(hass, tmp_path / "memory.db")
    with patch(
        "custom_components.smartchain.tools.memory.backends.sqlite_vec._load_sqlite_vec",
        side_effect=AttributeError("enable_load_extension"),
    ):
        with pytest.raises(BackendInitError, match="sqlite_numpy"):
            await be.initialize(3)
    assert be.is_available is False
