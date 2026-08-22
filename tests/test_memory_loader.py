"""Tests for loader handling of the `memory:` block."""

from pathlib import Path

from custom_components.smartchain.tools.loader import LoaderResult, load_tools_file
from custom_components.smartchain.tools.memory.config import MemoryConfig

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_loader_returns_memory_config(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text((FIXTURE_DIR / "memory_basic.yaml").read_text())

    result = load_tools_file(target)

    assert isinstance(result, LoaderResult)
    assert isinstance(result.memory_config, MemoryConfig)
    assert result.memory_config.provider == "ollama"
    assert result.memory_config.model == "nomic-embed-text"
    assert result.memory_config.retention_days == 30
    assert result.memory_config.logbook.enabled is True
    assert result.memory_config.logbook.domains == ["light", "lock"]
    assert result.memory_config.logbook.poll_interval_minutes == 30


def test_loader_without_memory_block_returns_none(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text("tools: []\n")
    result = load_tools_file(target)
    assert result.memory_config is None


def test_loader_missing_file_returns_none_memory(tmp_path: Path) -> None:
    result = load_tools_file(tmp_path / "missing.yaml")
    assert result.memory_config is None


def test_loader_parses_backend_block(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text(
        "memory:\n"
        "  provider: ollama\n"
        "  model: nomic-embed-text\n"
        "  backend:\n"
        "    type: qdrant\n"
        "    url: http://localhost:6333\n"
        "    collection: mem\n"
    )
    result = load_tools_file(target)
    assert result.memory_config.backend.type == "qdrant"
    assert result.memory_config.backend.url == "http://localhost:6333"
    assert result.memory_config.backend.collection == "mem"


def test_loader_backend_defaults_when_absent(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text("memory:\n  provider: ollama\n  model: nomic-embed-text\n")
    result = load_tools_file(target)
    assert result.memory_config.backend.type == "sqlite_numpy"
