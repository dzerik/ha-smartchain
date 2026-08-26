"""Data classes for SmartChain custom tools."""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, Literal

# Seconds a `service` or `script` action may block the conversation turn.
#
# These two are called with `blocking=True`, and Home Assistant core no longer
# enforces a `SERVICE_CALL_LIMIT`, so without a budget of their own a script
# holding a `delay` or a `wait_for_trigger` keeps the turn open indefinitely.
# The bounds mirror the REST executor's (`REST_MIN_TIMEOUT`/`REST_MAX_TIMEOUT`
# in const.py) so every timeout in tools.yaml behaves the same way; the default
# is larger than REST's because a service call legitimately drives hardware.
ACTION_DEFAULT_TIMEOUT = 30
ACTION_MIN_TIMEOUT = 1
ACTION_MAX_TIMEOUT = 300


@dataclass(frozen=True)
class ServiceAction:
    """Invoke a Home Assistant service."""

    type: Literal["service"] = "service"
    domain: str = ""
    service: str = ""
    target: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    response: bool = False
    timeout: int = ACTION_DEFAULT_TIMEOUT


@dataclass(frozen=True)
class TemplateAction:
    """Render a Jinja template."""

    type: Literal["template"] = "template"
    value_template: str = ""


@dataclass(frozen=True)
class RESTAction:
    """Make an HTTP request."""

    type: Literal["rest"] = "rest"
    method: str = "GET"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    payload: dict[str, Any] | None = None
    timeout: int = 10
    response_format: Literal["text", "json"] = "text"


@dataclass(frozen=True)
class ScriptAction:
    """Run a Home Assistant script."""

    type: Literal["script"] = "script"
    script: str = ""
    variables: dict[str, Any] = field(default_factory=dict)
    timeout: int = ACTION_DEFAULT_TIMEOUT


@dataclass(frozen=True)
class MCPAction:
    """Call a tool exposed by a connected MCP server."""

    type: Literal["mcp"] = "mcp"
    server: str = ""
    tool_name: str = ""
    timeout: int = 30


type ToolAction = ServiceAction | TemplateAction | RESTAction | ScriptAction | MCPAction


@dataclass(frozen=True)
class CustomTool:
    """A YAML-defined LLM-callable tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    action: ToolAction
    enabled: bool = True

    def to_llm_schema(self) -> dict[str, Any]:
        """Render this tool in the schema shape accepted by LangChain bind_tools."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    """In-memory map of name -> CustomTool, with atomic replacement."""

    def __init__(self) -> None:
        self._tools: dict[str, CustomTool] = {}

    def add(self, tool: CustomTool) -> None:
        """Insert a tool. Overwrites if same name already present."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> CustomTool | None:
        """Return the tool with the given name, or None."""
        return self._tools.get(name)

    def all(self) -> Iterator[CustomTool]:
        """Iterate over all registered tools (insertion order)."""
        return iter(self._tools.values())

    def names(self) -> list[str]:
        """Return the list of registered tool names."""
        return list(self._tools.keys())

    def replace_all(self, tools: Iterable[CustomTool]) -> None:
        """Replace the registry contents in a single assignment."""
        self._tools = {t.name: t for t in tools}

    def __len__(self) -> int:
        return len(self._tools)
