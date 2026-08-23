"""Built-in `search_memory` LLM tool, routed across named stores."""

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ...const import DOMAIN, MEMORY_TOOL_NAME

LOGGER = logging.getLogger(__name__)


def get_memory_tool_definition(registry: Any) -> dict[str, Any]:
    """Build the tool schema from the live registry.

    Store names and their descriptions go into the schema so the model can
    choose the right one instead of guessing.
    """
    described = registry.describe()
    names = [name for name, _desc in described]

    catalogue = "; ".join(f"{name}: {desc}" if desc else name for name, desc in described)
    description = (
        "Search long-term memory for past conversations and home events. Use "
        "this when the user asks about something said earlier or events from "
        "the past."
    )
    if catalogue:
        description += f" Available stores — {catalogue}."

    properties: dict[str, Any] = {
        "query": {"type": "string", "description": "Natural-language query."},
        "top_k": {"type": "integer", "default": 5, "minimum": 1, "maximum": 20},
        "kind": {
            "type": "string",
            "enum": ["conversation", "logbook", "any"],
            "default": "any",
        },
    }
    required = ["query"]

    if names:
        properties["store"] = {
            "type": "string",
            "enum": names,
            "description": f"Which memory store to search. {catalogue}",
        }
        # With one store the parameter is inferable, so leave it optional.
        if len(names) > 1:
            required.append("store")

    return {
        "name": MEMORY_TOOL_NAME,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


async def execute_memory_search(
    hass: HomeAssistant,
    query: str,
    top_k: int = 5,
    kind: str = "any",
    subentry_id: str | None = None,
    store: str | None = None,
) -> str:
    domain_data = hass.data.get(DOMAIN) or {}
    registry = domain_data.get("memory")
    if registry is None or not len(registry):
        return "Memory is not configured for this installation."

    configured = ", ".join(registry.names())
    if store is not None and store not in registry.names():
        return f"Unknown memory store {store!r}. Configured stores: {configured}."

    target = registry.get(store)
    if target is None:
        return (
            "Several memory stores are configured — pass the `store` parameter. "
            f"Available: {configured}."
        )

    where: dict[str, Any] = {}
    if kind != "any":
        where["kind"] = kind
    if subentry_id:
        where["subentry_id"] = subentry_id

    try:
        snippets = await target.search(query, top_k=top_k, where=where or None)
    except Exception:  # noqa: BLE001
        LOGGER.exception("memory search failed")
        return "Memory lookup failed; see logs."

    if not snippets:
        return "No memories matched the query."

    lines = [f"Found {len(snippets)} memories:"]
    for index, snip in enumerate(snippets, start=1):
        ts = (snip.metadata or {}).get("timestamp", "?")
        kind_label = (snip.metadata or {}).get("kind", "?")
        first_line = snip.text.replace("\n", " ").strip()
        if len(first_line) > 400:
            first_line = first_line[:400] + "…"
        lines.append(f"{index}. [{ts}, {kind_label}] {first_line}")
    return "\n".join(lines)
