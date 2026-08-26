"""Custom tools that live in config subentries rather than in tools.yaml.

A tool used to exist only as an entry under `tools:` in
`/config/smartchain/tools.yaml`, which meant building one was an exercise in
remembering a schema: which keys an action type takes, that `parameters` is a
JSON Schema rather than a list of names, that `script` wants a full entity id.
A `tool` subentry is the same tool built by a form.

The two sources produce the *same* dataclass. `tool_from_subentry` reuses
`loader.action_from_dict`, so a `CustomTool` from a subentry and one from the
equivalent YAML compare equal — nothing downstream can tell them apart, which
is what lets the dispatcher, the registry and `allowed_tools` stay unchanged.

`merge_tool_sources` is the one place that decides what happens when both
sources name the same tool.
"""

import logging
from typing import Any

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant

from ..const import DOMAIN, SUBENTRY_TYPE_TOOL, TOOL_EMPTY_PARAMETERS
from .loader import action_from_dict
from .model import CustomTool

LOGGER = logging.getLogger(__name__)

# Where a merged tool came from. Reported by `smartchain/tool/list` so the
# Tools tab can say which ones it is able to edit.
SOURCE_SUBENTRY = "subentry"
SOURCE_YAML = "yaml"


def tool_from_subentry(subentry: ConfigSubentry) -> CustomTool:
    """Build a `CustomTool` from one `tool` subentry.

    The subentry title is the tool name — the same convention the embeddings
    and memory-store subentries use. `data` carries the three composed values
    the YAML schema also produces (`description`, `parameters`, `action`) plus
    `enabled`; `parameters` and `action` are stored already composed and
    already validated, precisely so this function has no reconstruction work to
    do and cannot reconstruct them differently from the way the save path did.
    """
    data: dict[str, Any] = dict(subentry.data)
    return CustomTool(
        name=subentry.title,
        description=data.get("description") or "",
        parameters=dict(data.get("parameters") or TOOL_EMPTY_PARAMETERS),
        action=action_from_dict(dict(data.get("action") or {})),
        enabled=bool(data.get("enabled", True)),
    )


def tool_subentries(hass: HomeAssistant) -> list[tuple[Any, ConfigSubentry]]:
    """Every `tool` subentry across every SmartChain entry."""
    return [
        (entry, subentry)
        for entry in hass.config_entries.async_entries(DOMAIN)
        for subentry in (entry.subentries or {}).values()
        if subentry.subentry_type == SUBENTRY_TYPE_TOOL
    ]


def tools_from_subentries(hass: HomeAssistant) -> list[CustomTool]:
    """Every enabled tool configured as a subentry, first claimant wins a clash.

    Disabled tools are skipped **before** the name is claimed, exactly as
    `load_tools_file` does: a disabled tool does not exist for this run, so it
    must not reserve its name against an enabled one — otherwise switching a
    tool off and adding its replacement under the same name would silently drop
    the replacement as a duplicate.

    Two subentries can hold the same title; nothing in Home Assistant stops it
    and the panel shows every entry at once, so it is reachable. The registry
    keys tools by name, so the second would silently replace the first.
    Dropping it with an error means the user is told and the tool that was
    already working keeps working. `ws_tool_save` refuses the clash up front;
    this is the backstop for one written any other way.

    A subentry whose stored action is unreadable is skipped rather than allowed
    to abort the whole rebuild — one broken tool must not cost every other tool
    and the entire memory subsystem behind it.
    """
    out: list[CustomTool] = []
    seen: set[str] = set()
    for _entry, subentry in tool_subentries(hass):
        if not subentry.data.get("enabled", True):
            continue
        if subentry.title in seen:
            LOGGER.error(
                "Two SmartChain tool subentries are both named %r. Only the first is used; "
                "rename one of them",
                subentry.title,
            )
            continue
        try:
            tool = tool_from_subentry(subentry)
        except Exception as err:  # noqa: BLE001 — one bad tool must not kill the rebuild
            LOGGER.error(
                "SmartChain tool subentry %r could not be loaded (%s); skipping it",
                subentry.title,
                type(err).__name__,
            )
            continue
        seen.add(subentry.title)
        out.append(tool)
    return out


def merge_tool_sources(
    yaml_tools: list[CustomTool], subentry_tools: list[CustomTool]
) -> tuple[list[CustomTool], dict[str, str], list[str]]:
    """Combine the two sources of tools. The subentry wins a name collision.

    Returns `(tools, sources, shadowed)`:

    - `tools` — what `ToolRegistry.replace_all` consumes.
    - `sources` — tool name to `SOURCE_YAML` / `SOURCE_SUBENTRY`, so the panel
      can say which tools it is able to edit and which live in the file.
    - `shadowed` — YAML tool names a subentry took over. Reported, never
      silent: a user whose YAML tool stopped taking effect otherwise has no way
      to find out except by noticing that edits to it do nothing.

    The subentry wins because it is the editable one, the same call
    `merge_store_sources` makes for stores. Losing to a file the panel cannot
    safely rewrite would make the UI a read-only display of something it
    appears to control.
    """
    subentry_names = {tool.name for tool in subentry_tools}
    shadowed = [tool.name for tool in yaml_tools if tool.name in subentry_names]
    if shadowed:
        LOGGER.warning(
            "Tool(s) %s are defined both in tools.yaml and as a config subentry. The "
            "subentry wins; the tools.yaml definition is ignored. Delete it from tools.yaml "
            "to silence this",
            ", ".join(sorted(shadowed)),
        )

    kept_yaml = [tool for tool in yaml_tools if tool.name not in subentry_names]
    sources = {tool.name: SOURCE_YAML for tool in kept_yaml}
    sources.update({tool.name: SOURCE_SUBENTRY for tool in subentry_tools})
    return [*kept_yaml, *subentry_tools], sources, shadowed
