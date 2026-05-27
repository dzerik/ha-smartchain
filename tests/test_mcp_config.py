"""Tests for MCPServerConfig dataclasses."""

from custom_components.smartchain.tools.mcp.config import (
    HTTPConfig,
    MCPServerConfig,
    SSEConfig,
    StdioConfig,
)


def test_stdio_config_defaults() -> None:
    cfg = StdioConfig(name="fs", command="npx")
    assert cfg.transport == "stdio"
    assert cfg.command == "npx"
    assert cfg.args == []
    assert cfg.env == {}


def test_sse_config_defaults() -> None:
    cfg = SSEConfig(name="brave", url="https://example.com/mcp")
    assert cfg.transport == "sse"
    assert cfg.headers == {}
    assert cfg.timeout == 30
    assert cfg.verify_ssl is True


def test_http_config_defaults() -> None:
    cfg = HTTPConfig(name="gh", url="https://example.com/mcp")
    assert cfg.transport == "http"


def test_server_config_shared_fields() -> None:
    cfg = StdioConfig(
        name="x",
        command="npx",
        prefix="my_fs",
        include_tools=["a", "b"],
        exclude_tools=["c"],
        enabled=False,
    )
    assert cfg.prefix == "my_fs"
    assert cfg.include_tools == ["a", "b"]
    assert cfg.exclude_tools == ["c"]
    assert cfg.enabled is False


def test_mcp_server_config_alias_is_union() -> None:
    """`MCPServerConfig` is the union of the three transport variants."""
    a: MCPServerConfig = StdioConfig(name="x", command="npx")
    b: MCPServerConfig = SSEConfig(name="y", url="https://example.com")
    c: MCPServerConfig = HTTPConfig(name="z", url="https://example.com")
    assert a.transport == "stdio"
    assert b.transport == "sse"
    assert c.transport == "http"
