"""Built-in `search_memory` LLM tool."""

import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ...const import DOMAIN, MEMORY_TOOL_NAME
from .store import MemoryStore

LOGGER = logging.getLogger(__name__)


def get_memory_tool_definition() -> dict[str, Any]:
    return {
        "name": MEMORY_TOOL_NAME,
        "description": (
            "Search long-term memory for past conversations and home events. "
            "Use this when the user asks about something said earlier or events "
            "from the past."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural-language query.",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "minimum": 1,
                    "maximum": 20,
                },
                "kind": {
                    "type": "string",
                    "enum": ["conversation", "logbook", "any"],
                    "default": "any",
                },
            },
            "required": ["query"],
        },
    }


async def execute_memory_search(
    hass: HomeAssistant,
    query: str,
    top_k: int = 5,
    kind: str = "any",
) -> str:
    domain_data = hass.data.get(DOMAIN) or {}
    store: MemoryStore | None = domain_data.get("memory")
    if store is None or not getattr(store, "is_available", False):
        return "Memory is not configured for this installation."

    where: dict[str, Any] | None = None
    if kind != "any":
        where = {"kind": kind}

    try:
        snippets = await store.search(query, top_k=top_k, where=where)
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
