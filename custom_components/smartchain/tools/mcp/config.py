"""Configuration dataclasses for MCP servers."""

from dataclasses import dataclass, field
from typing import Literal

type MCPServerConfig = StdioConfig | SSEConfig | HTTPConfig


@dataclass(frozen=True)
class _BaseServerConfig:
    """Fields shared by every MCP server transport."""

    name: str
    prefix: str | None = None  # None -> use server name; "" -> no prefix
    include_tools: list[str] = field(default_factory=list)
    exclude_tools: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass(frozen=True)
class StdioConfig(_BaseServerConfig):
    """Stdio MCP server — launched as a subprocess."""

    transport: Literal["stdio"] = "stdio"
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SSEConfig(_BaseServerConfig):
    """SSE-transport MCP server — remote HTTPS endpoint."""

    transport: Literal["sse"] = "sse"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    verify_ssl: bool = True


@dataclass(frozen=True)
class HTTPConfig(_BaseServerConfig):
    """Streamable-HTTP-transport MCP server — remote HTTPS endpoint."""

    transport: Literal["http"] = "http"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    verify_ssl: bool = True
