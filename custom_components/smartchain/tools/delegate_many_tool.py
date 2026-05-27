"""Parallel fan-out tool — ask N sibling agents the same question."""

import asyncio
import logging
from typing import Any

from langchain_core.messages import HumanMessage

from ..const import (
    DELEGATE_MANY_TOOL_NAME,
    MULTI_AGENT_MAX_PARALLEL,
    MULTI_AGENT_PER_CALL_TIMEOUT_SECONDS,
)

LOGGER = logging.getLogger(__name__)


def get_delegate_many_tool_definition(
    available_agents: list[dict[str, str]],
) -> dict[str, Any]:
    """Build the ask_agents tool spec from the current sibling list."""
    agent_names = [a["name"] for a in available_agents]
    agents_desc = ", ".join(f"'{a['name']}'" for a in available_agents)
    return {
        "name": DELEGATE_MANY_TOOL_NAME,
        "description": (
            "Ask multiple sibling agents the same question in parallel and "
            "get all their responses combined. Use when the user's request "
            "needs input from several specialised agents. Available agents: "
            f"{agents_desc}. You then summarise their answers for the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agents": {
                    "type": "array",
                    "items": {"type": "string", "enum": agent_names},
                    "minItems": 1,
                    "maxItems": MULTI_AGENT_MAX_PARALLEL,
                    "description": (
                        f"Names of the agents to ask (max {MULTI_AGENT_MAX_PARALLEL})."
                    ),
                },
                "query": {
                    "type": "string",
                    "description": "The question to send to each agent.",
                },
            },
            "required": ["agents", "query"],
        },
    }


async def _invoke_with_timeout(client: Any, name: str, query: str) -> tuple[str, str]:
    """Invoke one sibling, converting timeouts and exceptions to error strings."""
    try:
        async with asyncio.timeout(MULTI_AGENT_PER_CALL_TIMEOUT_SECONDS):
            result = await client.ainvoke([HumanMessage(content=query)])
            return name, str(result.content)
    except TimeoutError:
        LOGGER.warning("delegate_many: %s timed out", name)
        return name, "Error: timeout"
    except Exception:  # noqa: BLE001 — boundary, no leak to LLM
        LOGGER.exception("delegate_many: %s failed", name)
        return name, "Error: agent failed"


async def execute_delegate_many_tool(
    clients: dict[str, Any],
    agent_map: dict[str, str],
    agent_names: list[str],
    query: str,
) -> str:
    """Ask multiple siblings the same question in parallel."""
    # Dedup preserving order; truncate at MAX_PARALLEL.
    seen: set[str] = set()
    deduped: list[str] = []
    for name in agent_names:
        if name not in seen:
            seen.add(name)
            deduped.append(name)
        if len(deduped) >= MULTI_AGENT_MAX_PARALLEL:
            break

    unavailable: list[tuple[str, str]] = []
    tasks: list = []
    for name in deduped:
        sub_id = agent_map.get(name)
        client = clients.get(sub_id) if sub_id else None
        if client is None:
            unavailable.append((name, "Error: agent unavailable"))
            continue
        tasks.append(_invoke_with_timeout(client, name, query))

    if not tasks and not unavailable:
        return "No matching sibling agents available."

    # If every requested agent resolved to unavailable and nothing was invoked,
    # surface the generic message so the LLM knows there's nothing to fan-out to.
    if not tasks:
        return "No matching sibling agents available."

    results: list[tuple[str, str]] = []
    results = list(await asyncio.gather(*tasks))
    results.extend(unavailable)

    # Preserve original order
    order = {name: i for i, name in enumerate(deduped)}
    results.sort(key=lambda r: order.get(r[0], len(order)))

    if not results:
        return "No matching sibling agents available."

    lines = [f"Responses from {len(results)} agents:", ""]
    for name, text in results:
        lines.append(f"[{name}] {text}")
    return "\n".join(lines)
