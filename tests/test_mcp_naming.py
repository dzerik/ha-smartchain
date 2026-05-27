"""Tests for MCP tool naming (prefix / sanitize / collision)."""

from custom_components.smartchain.tools.mcp.naming import (
    filter_tools,
    resolve_tool_name,
    sanitize_tool_name,
)


def test_sanitize_lowercases_and_replaces_special_chars() -> None:
    assert sanitize_tool_name("List-Directory") == "list_directory"
    assert sanitize_tool_name("search.web") == "search_web"
    assert sanitize_tool_name("read file") == "read_file"


def test_sanitize_prefixes_leading_digit_with_underscore() -> None:
    assert sanitize_tool_name("3d_model") == "_3d_model"


def test_sanitize_collapses_consecutive_underscores_is_not_required() -> None:
    """Doubles are allowed (we don't try to be pretty)."""
    assert sanitize_tool_name("a..b") == "a__b"


def test_resolve_with_default_prefix_uses_server_name() -> None:
    assert resolve_tool_name("filesystem", None, "read_file") == "filesystem__read_file"


def test_resolve_with_explicit_prefix() -> None:
    assert resolve_tool_name("filesystem", "fs", "read_file") == "fs__read_file"


def test_resolve_with_empty_prefix_uses_sanitised_name() -> None:
    assert resolve_tool_name("filesystem", "", "read-file") == "read_file"


def test_filter_tools_include_only() -> None:
    tools = ["a", "b", "c"]
    assert filter_tools(tools, include=["a", "c"], exclude=[]) == ["a", "c"]


def test_filter_tools_exclude_only() -> None:
    tools = ["a", "b", "c"]
    assert filter_tools(tools, include=[], exclude=["b"]) == ["a", "c"]


def test_filter_tools_include_then_exclude() -> None:
    """Include narrows the set, exclude removes from that."""
    tools = ["a", "b", "c", "d"]
    assert filter_tools(tools, include=["a", "b", "c"], exclude=["b"]) == ["a", "c"]


def test_filter_tools_no_filters_returns_all() -> None:
    assert filter_tools(["a", "b"], include=[], exclude=[]) == ["a", "b"]
