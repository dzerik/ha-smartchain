"""State history tool for SmartChain — allows LLM to query past device states."""

from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import HISTORY_TOOL_MAX_HOURS, HISTORY_TOOL_NAME


def get_history_tool_definition() -> dict[str, Any]:
    """Return the LangChain-compatible tool definition for state history."""
    return {
        "name": HISTORY_TOOL_NAME,
        "description": (
            "Get the state history of a Home Assistant entity over a time period. "
            "Use this to answer questions about past events, trends, and changes. "
            "Returns a list of state changes with timestamps."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_id": {
                    "type": "string",
                    "description": (
                        "The entity ID to get history for (e.g. sensor.temperature, light.kitchen)"
                    ),
                },
                "hours": {
                    "type": "number",
                    "description": (
                        "Number of hours of history to retrieve"
                        f" (max {HISTORY_TOOL_MAX_HOURS}, default 1)"
                    ),
                },
            },
            "required": ["entity_id"],
        },
    }


async def execute_history_tool(
    hass: HomeAssistant,
    entity_id: str,
    hours: float = 1.0,
) -> str:
    """Execute the history tool and return formatted state changes."""
    from homeassistant.components.recorder.history import get_significant_states

    hours = min(hours, HISTORY_TOOL_MAX_HOURS)
    end_time = dt_util.utcnow()
    start_time = end_time - timedelta(hours=hours)

    states_dict = await hass.async_add_executor_job(
        get_significant_states,
        hass,
        start_time,
        end_time,
        [entity_id],
    )

    states = states_dict.get(entity_id, [])
    if not states:
        return f"No history found for {entity_id} in the last {hours} hours."

    lines = [f"State history for {entity_id} (last {hours}h):"]
    for state in states[-20:]:  # Limit to last 20 changes to avoid token overflow
        ts = state.last_changed
        if isinstance(ts, datetime):
            ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        else:
            ts_str = str(ts)
        lines.append(f"  {ts_str}: {state.state}")

    if len(states) > 20:
        lines.append(f"  ... ({len(states) - 20} more entries omitted)")

    return "\n".join(lines)
