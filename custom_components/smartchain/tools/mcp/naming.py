"""Tool-name rewriting for MCP-discovered tools.

The LLM-side name regex is `^[a-z_][a-z0-9_]*$`. MCP servers can emit
arbitrary names (`list-directory`, `search.web`, `3d_model`). We sanitise
and prefix to guarantee uniqueness across servers.
"""

import re

_NON_ID_CHARS = re.compile(r"[^a-z0-9_]")


def sanitize_tool_name(raw: str) -> str:
    """Convert an MCP-supplied name into an LLM-safe identifier."""
    s = raw.lower()
    s = _NON_ID_CHARS.sub("_", s)
    if s and s[0].isdigit():
        s = "_" + s
    return s


def resolve_tool_name(server_name: str, prefix: str | None, raw_tool_name: str) -> str:
    """Build the registry name for an MCP tool.

    - `prefix is None` → use `server_name` as prefix
    - `prefix == ""` → no prefix (just the sanitised name)
    - otherwise use the explicit prefix
    """
    sanitised = sanitize_tool_name(raw_tool_name)
    if prefix is None:
        effective = server_name
    elif prefix == "":
        return sanitised
    else:
        effective = prefix
    return f"{effective}__{sanitised}"


def filter_tools(
    tool_names: list[str],
    include: list[str],
    exclude: list[str],
) -> list[str]:
    """Apply include then exclude filters.

    Both lists operate on the *original* MCP tool names (pre-sanitisation),
    matching what the user typed in YAML.
    """
    if include:
        result = [t for t in tool_names if t in include]
    else:
        result = list(tool_names)
    if exclude:
        result = [t for t in result if t not in exclude]
    return result
