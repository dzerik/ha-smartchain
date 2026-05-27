"""Second-opinion tool — ask a sibling agent to critique a draft answer."""

import asyncio
import logging
from typing import Any

from langchain_core.messages import HumanMessage

from ..const import CRITIQUE_TOOL_NAME, MULTI_AGENT_PER_CALL_TIMEOUT_SECONDS

LOGGER = logging.getLogger(__name__)

CRITIQUE_PROMPT = (
    "You are reviewing another agent's draft answer.\n\n"
    "The user asked:\n{question}\n\n"
    "The candidate answer is:\n{answer}\n\n"
    "Briefly assess: is it correct, complete and safe? "
    "Reply in 3-5 sentences. If there is a problem, name it specifically."
)


def get_critique_tool_definition(
    available_agents: list[dict[str, str]],
) -> dict[str, Any]:
    """Build the critique_response tool spec from the current sibling list."""
    agent_names = [a["name"] for a in available_agents]
    agents_desc = ", ".join(f"'{a['name']}'" for a in available_agents)
    return {
        "name": CRITIQUE_TOOL_NAME,
        "description": (
            "Ask another sibling agent to review and critique a candidate "
            "response before you send it to the user. Use for safety-critical "
            "actions or when uncertain. The reviewer's verdict is for your "
            f"consideration. Available reviewers: {agents_desc}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reviewer": {
                    "type": "string",
                    "enum": agent_names,
                    "description": "Name of the agent to act as reviewer.",
                },
                "original_question": {
                    "type": "string",
                    "description": "What the user originally asked.",
                },
                "candidate_answer": {
                    "type": "string",
                    "description": "The draft answer you are about to send.",
                },
            },
            "required": ["reviewer", "original_question", "candidate_answer"],
        },
    }


async def execute_critique_tool(
    clients: dict[str, Any],
    agent_map: dict[str, str],
    reviewer_name: str,
    original_question: str,
    candidate_answer: str,
) -> str:
    """Ask the named reviewer to critique the candidate answer."""
    sub_id = agent_map.get(reviewer_name)
    client = clients.get(sub_id) if sub_id else None
    if client is None:
        return f"Error: reviewer agent '{reviewer_name}' unavailable"

    prompt = CRITIQUE_PROMPT.format(question=original_question, answer=candidate_answer)
    try:
        async with asyncio.timeout(MULTI_AGENT_PER_CALL_TIMEOUT_SECONDS):
            result = await client.ainvoke([HumanMessage(content=prompt)])
            return str(result.content)
    except TimeoutError:
        LOGGER.warning("critique: %s timed out", reviewer_name)
        return "Error: critique timeout"
    except Exception:  # noqa: BLE001 — boundary
        LOGGER.exception("critique: %s failed", reviewer_name)
        return "Error: critique failed"
