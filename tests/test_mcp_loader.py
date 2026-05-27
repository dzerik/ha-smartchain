"""Tests for loader handling of mcp_servers blocks."""

from pathlib import Path

from custom_components.smartchain.tools.loader import LoaderResult, load_tools_file
from custom_components.smartchain.tools.mcp.config import SSEConfig, StdioConfig

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_loader_returns_result_with_servers(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text((FIXTURE_DIR / "mcp_basic.yaml").read_text())

    result = load_tools_file(target)

    assert isinstance(result, LoaderResult)
    assert result.yaml_tools == []
    assert len(result.mcp_servers) == 2
    assert isinstance(result.mcp_servers[0], StdioConfig)
    assert result.mcp_servers[0].name == "fs"
    assert result.mcp_servers[0].command == "npx"
    assert isinstance(result.mcp_servers[1], SSEConfig)
    assert result.mcp_servers[1].url == "https://example.com/mcp/brave"


def test_loader_returns_empty_servers_when_absent(tmp_path: Path) -> None:
    target = tmp_path / "tools.yaml"
    target.write_text(
        "tools:\n"
        "  - name: ping\n"
        "    description: x\n"
        "    parameters: { type: object, properties: {} }\n"
        "    action: { type: template, value_template: pong }\n"
    )
    result = load_tools_file(target)
    assert len(result.yaml_tools) == 1
    assert result.mcp_servers == []


def test_loader_missing_file_returns_empty_result(tmp_path: Path) -> None:
    result = load_tools_file(tmp_path / "does_not_exist.yaml")
    assert isinstance(result, LoaderResult)
    assert result.yaml_tools == []
    assert result.mcp_servers == []
