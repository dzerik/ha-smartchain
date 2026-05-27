"""Tests for the CustomTool data model and ToolRegistry."""

from custom_components.smartchain.tools.model import (
    CustomTool,
    ServiceAction,
    ToolRegistry,
)


def test_custom_tool_to_llm_schema_minimal() -> None:
    """A tool with empty parameters renders a valid LLM-tool schema."""
    tool = CustomTool(
        name="ping",
        description="Reply with pong",
        parameters={"type": "object", "properties": {}},
        action=ServiceAction(domain="homeassistant", service="check_config"),
    )

    schema = tool.to_llm_schema()

    assert schema == {
        "name": "ping",
        "description": "Reply with pong",
        "parameters": {"type": "object", "properties": {}},
    }


def test_registry_add_and_lookup() -> None:
    """ToolRegistry stores tools by name and retrieves them correctly."""
    reg = ToolRegistry()
    tool = CustomTool(
        name="ping",
        description="x",
        parameters={"type": "object", "properties": {}},
        action=ServiceAction(domain="homeassistant", service="check_config"),
    )
    reg.add(tool)

    assert reg.get("ping") is tool
    assert reg.get("missing") is None
    assert list(reg.all()) == [tool]


def test_registry_replace_swaps_contents_atomically() -> None:
    """`replace_all` swaps the entire tool map in one assignment."""
    reg = ToolRegistry()
    a = CustomTool(
        name="a",
        description="x",
        parameters={"type": "object", "properties": {}},
        action=ServiceAction(domain="d", service="s"),
    )
    b = CustomTool(
        name="b",
        description="x",
        parameters={"type": "object", "properties": {}},
        action=ServiceAction(domain="d", service="s"),
    )
    reg.add(a)
    reg.replace_all([b])

    assert reg.get("a") is None
    assert reg.get("b") is b


def test_mcp_action_is_a_tool_action() -> None:
    """MCPAction is a valid ToolAction variant carrying server + tool_name."""
    from custom_components.smartchain.tools.model import MCPAction

    action = MCPAction(server="filesystem", tool_name="list_directory")
    assert action.type == "mcp"
    assert action.server == "filesystem"
    assert action.tool_name == "list_directory"
    assert action.timeout == 30
