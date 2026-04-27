"""Public helpers for downstream integrations.

Currently exposes `async_generate_structured` so other custom components can
ask SmartChain for a structured (Pydantic-typed) LLM response without having
to know about LangChain or per-provider quirks. The contract:

    obj = await async_generate_structured(
        hass,
        schema=MyPydanticModel,
        prompt="…fully assembled instruction text…",
        agent_id="conversation.smartchain_xxx",  # optional
    )
    # obj is an instance of MyPydanticModel — already validated.

Routing:
- We resolve the LangChain chat-model client behind the requested agent
  (or pick the first available SmartChain client when agent_id is None).
- We call `client.with_structured_output(schema)` which uses each
  provider's native structured-output mode where supported (OpenAI
  Structured Outputs, Anthropic tool-use, Google Gemini responseSchema,
  Ollama 0.5+ format=schema, GigaChat function_call).
- If the underlying model rejects with_structured_output (older LangChain
  binding or a provider that doesn't expose it), we fall back to a plain
  `ainvoke` + `schema.model_validate_json()` so callers still get a
  pydantic instance — best effort, but at least typed.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, TypeVar

from homeassistant.core import HomeAssistant
from langchain_core.messages import HumanMessage

if TYPE_CHECKING:
    from pydantic import BaseModel

LOGGER = logging.getLogger(__name__)

T = TypeVar("T", bound="BaseModel")


def _find_smartchain_client(hass: HomeAssistant, agent_id: str | None):
    """Locate a LangChain chat client backing the given SmartChain agent.

    Delegates to the existing `_find_client(hass, entity_id)` helper that
    SmartChain registers in `hass.data[DOMAIN]["find_client"]` during
    `async_setup`. Falls back to the first available SmartChain client when
    no specific agent_id is provided or the lookup misses.
    """
    from .const import DOMAIN  # noqa: PLC0415

    domain_data = hass.data.get(DOMAIN) or {}
    finder = domain_data.get("find_client")
    if finder is None:
        # SmartChain hasn't finished async_setup yet — defensive bail-out.
        return None
    return finder(hass, agent_id)


async def async_generate_structured(  # noqa: UP047
    hass: HomeAssistant,
    *,
    schema: type[T],
    prompt: str,
    agent_id: str | None = None,
) -> T:
    """Run an LLM request that must return an instance of ``schema``.

    Args:
        hass: Home Assistant instance.
        schema: Pydantic v2 BaseModel subclass describing the desired
            response shape. Used both to drive the provider's structured
            mode and to validate the result.
        prompt: The fully-assembled human prompt. The schema enforcement is
            handled by LangChain on the client side, so callers should not
            re-paste the JSON schema into the prompt themselves.
        agent_id: Optional Home Assistant entity_id of the target SmartChain
            agent (e.g. "conversation.smartchain_my_agent"). When omitted,
            the first available SmartChain client is used.

    Returns:
        A validated instance of ``schema``.

    Raises:
        RuntimeError: when no SmartChain client can be resolved.
        pydantic.ValidationError: when the model returns data that doesn't
            match the schema and the fallback path can't recover.
    """
    client = _find_smartchain_client(hass, agent_id)
    if client is None:
        raise RuntimeError(
            f"No SmartChain client available (agent_id={agent_id!r}). "
            "Make sure the SmartChain integration is configured."
        )

    try:
        structured = client.with_structured_output(schema)
    except (NotImplementedError, AttributeError):
        # Provider/binding doesn't expose with_structured_output — fall
        # back to text + manual parse + validation.
        LOGGER.debug(
            "with_structured_output unavailable on %s, falling back to text path",
            type(client).__name__,
        )
        return await _fallback_text_to_schema(client, schema, prompt)

    try:
        result = await structured.ainvoke([HumanMessage(content=prompt)])
    except Exception as exc:  # noqa: BLE001
        # Some providers raise when the structured output mode disagrees
        # with the chosen model (e.g. older OpenAI engines without JSON
        # mode). Fall through to the text path so the caller still gets
        # a typed answer when possible.
        LOGGER.debug(
            "Structured invoke failed on %s: %s — falling back to text",
            type(client).__name__,
            exc,
        )
        return await _fallback_text_to_schema(client, schema, prompt)

    # LangChain occasionally returns a raw dict instead of the Pydantic
    # instance (depends on version + provider). Normalise.
    if isinstance(result, schema):
        return result
    if isinstance(result, dict):
        return schema.model_validate(result)
    return schema.model_validate(_safe_extract_json(str(result)))


async def _fallback_text_to_schema(client, schema: type[T], prompt: str) -> T:  # noqa: UP047
    """Last-resort path: plain text invocation + manual JSON extraction.

    Used when the underlying chat model can't run native structured output.
    The schema is appended to the prompt verbatim so the LLM at least sees
    the contract; we then strip markdown fences and validate.
    """
    schema_text = json.dumps(schema.model_json_schema(), indent=2, ensure_ascii=False)
    enriched = (
        f"{prompt}\n\n"
        "--- RESPONSE FORMAT (DO NOT CHANGE) ---\n"
        "Reply with ONLY a JSON object that matches this JSON Schema. "
        "No prose, no markdown fences, no commentary.\n\n"
        f"{schema_text}"
    )
    result = await client.ainvoke([HumanMessage(content=enriched)])
    raw = getattr(result, "content", str(result))
    return schema.model_validate(_safe_extract_json(raw))


def _safe_extract_json(text: str) -> dict:
    """Strip markdown fences and pull the first JSON object from text."""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].lstrip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        import re  # noqa: PLC0415

        match = re.search(r"\{[\s\S]*\}", cleaned)
        if match:
            return json.loads(match.group(0))
        raise
