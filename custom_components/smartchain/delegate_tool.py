"""Agent delegation tool for SmartChain — allows one agent to delegate tasks to another."""

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from .const import DELEGATE_TOOL_NAME


def get_delegate_tool_definition(
    available_agents: list[dict[str, str]],
) -> dict[str, Any]:
    """Return the LangChain-compatible tool definition for agent delegation.

    available_agents is a list of dicts with 'name' and 'description' keys.
    """
    agent_names = [a["name"] for a in available_agents]
    agents_desc = ", ".join(f"'{a['name']}'" for a in available_agents)
    return {
        "name": DELEGATE_TOOL_NAME,
        "description": (
            "Delegate a question or task to a specialized agent. "
            f"Available agents: {agents_desc}. "
            "Use this when the question is better handled by a specialist."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": (f"Name of the agent to delegate to. One of: {agents_desc}"),
                    "enum": agent_names,
                },
                "message": {
                    "type": "string",
                    "description": "The question or task to send to the agent",
                },
            },
            "required": ["agent_name", "message"],
        },
    }


async def execute_delegate_tool(
    clients: dict[str, object],
    agent_map: dict[str, str],
    agent_name: str,
    message: str,
) -> str:
    """Execute delegation to another agent.

    agent_map maps agent_name -> subentry_id.
    clients maps subentry_id -> LLM client.
    """
    sub_id = agent_map.get(agent_name)
    if not sub_id:
        return f"Agent '{agent_name}' not found."

    client = clients.get(sub_id)
    if not client:
        return f"Agent '{agent_name}' client not available."

    messages = [
        SystemMessage(content="Answer the user's question concisely."),
        HumanMessage(content=message),
    ]
    result = await client.ainvoke(messages)
    return result.content
