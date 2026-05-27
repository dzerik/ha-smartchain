"""Tests for the mcp_servers voluptuous schema."""

import pytest
import voluptuous as vol

from custom_components.smartchain.tools.schema import (
    MCP_SERVER_SCHEMA,
    TOOLS_FILE_SCHEMA,
)


def test_stdio_server_validates() -> None:
    MCP_SERVER_SCHEMA(
        {
            "name": "fs",
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        }
    )


def test_sse_server_validates() -> None:
    MCP_SERVER_SCHEMA(
        {
            "name": "brave",
            "transport": "sse",
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer x"},
            "timeout": 60,
        }
    )


def test_http_server_validates() -> None:
    MCP_SERVER_SCHEMA(
        {
            "name": "gh",
            "transport": "http",
            "url": "https://example.com/mcp",
        }
    )


def test_unknown_transport_rejected() -> None:
    with pytest.raises(vol.Invalid, match="unknown transport"):
        MCP_SERVER_SCHEMA({"name": "x", "transport": "websocket", "url": "https://example.com"})


def test_stdio_requires_command() -> None:
    with pytest.raises(vol.Invalid):
        MCP_SERVER_SCHEMA({"name": "fs", "transport": "stdio"})


def test_sse_requires_url() -> None:
    with pytest.raises(vol.Invalid):
        MCP_SERVER_SCHEMA({"name": "x", "transport": "sse"})


def test_bad_server_name_rejected() -> None:
    with pytest.raises(vol.Invalid):
        MCP_SERVER_SCHEMA({"name": "Bad Server!", "transport": "sse", "url": "https://example.com"})


def test_tools_file_schema_accepts_mcp_servers_block() -> None:
    TOOLS_FILE_SCHEMA(
        {
            "tools": [],
            "mcp_servers": [
                {"name": "fs", "transport": "stdio", "command": "npx"},
                {"name": "brave", "transport": "sse", "url": "https://example.com"},
            ],
        }
    )


def test_tools_file_schema_accepts_yaml_with_only_mcp_servers() -> None:
    TOOLS_FILE_SCHEMA(
        {
            "mcp_servers": [
                {"name": "fs", "transport": "stdio", "command": "npx"},
            ],
        }
    )


def test_mcp_server_rejects_bad_prefix() -> None:
    """`prefix` with invalid chars is rejected at schema time."""
    with pytest.raises(vol.Invalid):
        MCP_SERVER_SCHEMA(
            {
                "name": "fs",
                "transport": "stdio",
                "command": "npx",
                "prefix": "my-server",  # hyphen not allowed
            }
        )


def test_mcp_server_accepts_empty_prefix() -> None:
    """Empty `prefix` means no prefix; that must still validate."""
    MCP_SERVER_SCHEMA(
        {
            "name": "fs",
            "transport": "stdio",
            "command": "npx",
            "prefix": "",
        }
    )
