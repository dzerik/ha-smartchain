"""AI Task entity for SmartChain integration."""

import json
import logging
import re
from collections.abc import Callable
from typing import Any

import voluptuous as vol
import voluptuous_openapi
from homeassistant.components import ai_task, conversation
from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from langchain_core.messages import BaseMessage, SystemMessage

from .const import CONF_ENGINE, ID_OLLAMA, MAX_TOOL_ITERATIONS, SUBENTRY_TYPE_CONVERSATION
from .conversation import (
    EMPTY_RESPONSE_NATIVE,
    _async_langchain_stream,
    _chatlog_to_langchain,
    _ha_tool_to_dict,
)

LOGGER = logging.getLogger(__name__)

# Header of the block appended to the system prompt when the provider has no
# way of taking a schema as a parameter. Named so tests and readers can find
# the one place the contract is worded.
STRUCTURE_PROMPT_HEADER = "--- RESPONSE FORMAT (DO NOT CHANGE) ---"

# Providers whose LangChain client accepts a JSON Schema as an ordinary
# request keyword *and keeps streaming message chunks*.
#
# `with_structured_output` is deliberately not used here, even though
# `helpers.async_generate_structured` uses it for its own pydantic callers.
# It returns a parsing pipeline: `astream` on it yields partially-parsed
# objects, not `AIMessageChunk`s, and the chat log we feed
# (`_async_langchain_stream` -> `ChatLog.async_add_delta_content_stream`)
# needs message chunks — that is where tool calls, the empty-response marker
# and the assistant content all come from. Swapping in a parsing pipeline
# would cost an AI Task its tools and its "the model said nothing" guard.
#
# Ollama is the only provider in the table because its keyword is safe for
# every model the server can run. OpenAI's `response_format={"type":
# "json_schema", ...}` is model-dependent — pairing it with an older engine is
# a hard 400 where the prompt path simply works — and GigaChat and Anthropic
# express structured output as a forced tool call, which collides with the
# tools an AI Task may already be given. Everything absent from the table gets
# the schema in the prompt, which works everywhere.
NATIVE_STRUCTURED_BINDING: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    ID_OLLAMA: lambda json_schema: {"format": json_schema},
}

# A fenced block anywhere in the answer, with or without a language tag.
_FENCE_RE = re.compile(r"```(?:[A-Za-z0-9_+-]*)?\s*\n?(.*?)```", re.DOTALL)
# The outermost brace-delimited run, for an answer with prose around the JSON.
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


async def async_setup_entry(
    hass,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up AI Task entities."""
    entities: list[SmartChainAITaskEntity] = []

    for sub_id, subentry in (config_entry.subentries or {}).items():
        if subentry.subentry_type != SUBENTRY_TYPE_CONVERSATION:
            continue
        entities.append(
            SmartChainAITaskEntity(
                config_entry,
                subentry_id=sub_id,
            )
        )

    if not entities and config_entry.minor_version < 2:
        # Mirrors conversation.py: only an entry whose migration refused stays
        # below minor version 2, and it must not lose its entity.
        entities.append(SmartChainAITaskEntity(config_entry))

    async_add_entities(entities)


def _structure_to_json_schema(
    structure: vol.Schema, llm_api: llm.APIInstance | None
) -> dict[str, Any]:
    """Render a task's `structure` as JSON Schema the model can be shown.

    The values of `task.structure` are Home Assistant *selectors* — that is
    what `ai_task._validate_structure_fields` builds out of the service call —
    and `voluptuous_openapi.convert` cannot key a dict by one. Leaving the
    serializer out does not produce a poorer schema, it raises `TypeError`,
    which is why the serializer is not an optional refinement here.
    """
    serializer = llm_api.custom_serializer if llm_api else llm.selector_serializer
    return voluptuous_openapi.convert(structure, custom_serializer=serializer)


def _structure_prompt_block(json_schema: dict[str, Any]) -> str:
    """The response-format contract, for a provider that takes no schema."""
    return (
        f"{STRUCTURE_PROMPT_HEADER}\n"
        "Reply with ONLY a JSON object that matches this JSON Schema. "
        "No prose, no markdown fences, no commentary.\n\n"
        f"{json.dumps(json_schema, indent=2, ensure_ascii=False)}"
    )


def _bind_native_structure(client: Any, engine: str, json_schema: dict[str, Any]) -> Any:
    """Bind the schema to `client` the provider's own way, or return None.

    None means "this provider has no such keyword, put the schema in the
    prompt instead". A binding that the installed client version refuses is
    reported the same way — an older `langchain-ollama` that does not know
    `format` should cost the task its native mode, not the whole task.
    """
    factory = NATIVE_STRUCTURED_BINDING.get(engine)
    if factory is None:
        return None
    try:
        return client.bind(**factory(json_schema))
    except (AttributeError, TypeError, ValueError) as err:
        LOGGER.debug(
            "Native structured output unavailable on %s (%s), using the prompt instead",
            engine,
            err,
        )
        return None


def _with_structure_prompt(
    messages: list[BaseMessage], json_schema: dict[str, Any]
) -> list[BaseMessage]:
    """Return `messages` with the response-format contract in the system prompt.

    It goes into the system message rather than after the user's instructions
    because the tool loop re-sends the whole list on every iteration: a
    trailing instruction would land after a tool result, where several
    providers refuse a plain user message.
    """
    block = _structure_prompt_block(json_schema)
    if messages and isinstance(messages[0], SystemMessage):
        head = SystemMessage(content=f"{messages[0].content}\n\n{block}".strip())
        return [head, *messages[1:]]
    return [SystemMessage(content=block), *messages]


def _image_attachments(chat_log: conversation.ChatLog) -> list[Any]:
    """Every image attachment the request being built is meant to carry.

    Read off the chat log rather than off the task, because the log is what
    `_chatlog_to_langchain` converts — HA appends
    `UserContent(task.instructions, attachments=task.attachments)` — and the
    count is only meaningful next to what that conversion produced.
    """
    return [
        attachment
        for content in chat_log.content
        if isinstance(content, conversation.UserContent) and content.attachments
        for attachment in content.attachments
        if (attachment.mime_type or "").startswith("image/")
    ]


def _delivered_image_parts(messages: list[BaseMessage]) -> int:
    """How many images the built request actually carries."""
    delivered = 0
    for message in messages:
        content = getattr(message, "content", None)
        if not isinstance(content, list):
            continue
        delivered += sum(
            1 for part in content if isinstance(part, dict) and part.get("type") == "image_url"
        )
    return delivered


def _attachment_label(attachment: Any) -> str:
    """What to call an attachment in an error a person has to act on."""
    return getattr(attachment, "media_content_id", None) or str(
        getattr(attachment, "path", "unknown")
    )


def _extract_json_object(text: str) -> Any:
    """Pull the JSON the model meant to send out of the text it actually sent.

    Models fence their JSON and put a sentence in front of it often enough
    that a bare `json.loads` turns a usable answer into a failed task. The
    candidates are tried in order of how likely each is to be the whole
    answer; when none of them parses, the response is reported as
    unparseable — recovering more must never turn "no answer" into a
    recovered one.

    Raises:
        HomeAssistantError: when nothing in `text` parses as JSON.
    """
    stripped = (text or "").strip()

    candidates: list[str] = [fenced.strip() for fenced in _FENCE_RE.findall(stripped)]
    candidates.append(stripped)
    if match := _OBJECT_RE.search(stripped):
        candidates.append(match.group(0))

    last_error: ValueError | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except ValueError as err:
            last_error = err

    LOGGER.error("Failed to parse structured AI Task response: %s", text)
    raise HomeAssistantError("Failed to parse structured AI Task response") from last_error


class SmartChainAITaskEntity(ai_task.AITaskEntity):
    """SmartChain AI Task entity for data generation."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, subentry_id: str | None = None) -> None:
        """Initialize the entity."""
        self.entry = entry
        self._subentry_id = subentry_id

        if subentry_id:
            self._attr_unique_id = f"{entry.entry_id}_{subentry_id}_ai_task"
            self._attr_name = f"{entry.subentries[subentry_id].title} AI Task"
        else:
            self._attr_unique_id = f"{entry.entry_id}_ai_task"
            self._attr_name = None

        # Attachments are declared because the request really carries them:
        # `_chatlog_to_langchain` base64-encodes an image attachment into the
        # message it builds. Without the flag `ai_task.generate_data` refuses
        # every attachment before reaching us, which is what made the
        # documented camera example impossible to run.
        self._attr_supported_features = (
            ai_task.AITaskEntityFeature.GENERATE_DATA
            | ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS
        )

    @property
    def _client(self) -> Any:
        """Return the LLM client for this entity."""
        if self._subentry_id and isinstance(self.entry.runtime_data, dict):
            return self.entry.runtime_data[self._subentry_id]
        return self.entry.runtime_data

    @property
    def _engine(self) -> str:
        """The provider id behind this entity, or "" when it cannot be read."""
        data = getattr(self.entry, "data", None) or {}
        engine = data.get(CONF_ENGINE) if isinstance(data, dict) else None
        return engine or ""

    async def _async_generate_data(
        self,
        task: ai_task.GenDataTask,
        chat_log: conversation.ChatLog,
    ) -> ai_task.GenDataTaskResult:
        """Handle a generate data task."""
        # Only images survive `_chatlog_to_langchain`; anything else is
        # dropped there without a word. Declaring attachment support and then
        # silently answering without the file would be a wrong answer wearing
        # a success, so the unusable attachment is named and the task fails.
        unusable = sorted(
            {
                attachment.mime_type or "unknown"
                for attachment in (task.attachments or [])
                if not (attachment.mime_type or "").startswith("image/")
            }
        )
        if unusable:
            raise HomeAssistantError(
                "AI Task attachments must be images, cannot send: " + ", ".join(unusable)
            )

        client = self._client
        tools: list[dict[str, Any]] = (
            [_ha_tool_to_dict(tool) for tool in chat_log.llm_api.tools] if chat_log.llm_api else []
        )
        bound_client = client.bind_tools(tools) if tools else client

        json_schema: dict[str, Any] | None = None
        schema_in_prompt = False
        if task.structure is not None:
            json_schema = _structure_to_json_schema(task.structure, chat_log.llm_api)
            if (native := _bind_native_structure(bound_client, self._engine, json_schema)) is None:
                schema_in_prompt = True
            else:
                bound_client = native

        expected_images = _image_attachments(chat_log)
        has_attachments = any(
            isinstance(content, conversation.UserContent) and content.attachments
            for content in chat_log.content
        )

        for _iteration in range(MAX_TOOL_ITERATIONS):
            if has_attachments:
                # `_chatlog_to_langchain` reads the attachment files and may run
                # TurboJPEG on a large one — `Path.read_bytes` is in HA's
                # `block_async_io` table, so doing this inline is a reported
                # blocking call and a genuinely stalled loop. Offloading only
                # when there is a file to read keeps the ordinary turn on one
                # thread, the same trade conversation.py makes.
                messages = await self.hass.async_add_executor_job(_chatlog_to_langchain, chat_log)
            else:
                messages = _chatlog_to_langchain(chat_log)

            # An image that could not be read leaves no trace in the request:
            # `_attachment_to_base64` returns None and the part is simply not
            # added, so the model is asked the question with the picture
            # missing and answers it anyway. Counting what arrived against what
            # was attached is the only check that survives every reason a file
            # might be unreadable, and it has to happen before the request is
            # sent — an invented answer must not even be paid for.
            if expected_images:
                delivered = _delivered_image_parts(messages)
                if delivered < len(expected_images):
                    raise HomeAssistantError(
                        "AI Task could not read "
                        f"{len(expected_images) - delivered} of "
                        f"{len(expected_images)} image attachment(s); answering "
                        "without them would be a guess: "
                        + ", ".join(_attachment_label(a) for a in expected_images)
                    )

            if schema_in_prompt and json_schema is not None:
                messages = _with_structure_prompt(messages, json_schema)

            try:
                async for _content in chat_log.async_add_delta_content_stream(
                    self.entity_id,
                    _async_langchain_stream(bound_client, messages),
                ):
                    pass
            except Exception as err:
                LOGGER.exception("AI Task error: %s", type(err))
                raise HomeAssistantError(f"AI Task error: {err}") from err

            if not chat_log.unresponded_tool_results:
                break

        last = chat_log.content[-1]
        if not isinstance(last, conversation.AssistantContent):
            raise HomeAssistantError("Last content in chat log is not an AssistantContent")

        if last.native == EMPTY_RESPONSE_NATIVE:
            # The stream closes every turn with an assistant message, so the
            # check above no longer catches a model that answered with nothing;
            # the marker is what "nothing" looks like now. A conversation could
            # ask the person to try again, but the result of a task goes
            # straight into an automation that cannot ask anyone anything, so
            # an empty string here is a silent wrong answer.
            raise HomeAssistantError("AI Task got no usable response from the model")

        text = last.content or ""

        if task.structure is None:
            return ai_task.GenDataTaskResult(
                conversation_id=chat_log.conversation_id,
                data=text,
            )

        raw = _extract_json_object(text)

        # The schema is what the caller asked for, so it is also what decides
        # whether the answer is one. Validating here is not a formality: it
        # coerces the selectors' types (a "true" becomes a bool, a number
        # becomes a float) and it rejects invented, missing or wrongly typed
        # fields, all of which an automation would otherwise carry on with.
        try:
            data = task.structure(raw)
        except vol.Invalid as err:
            LOGGER.error(
                "AI Task response does not match the requested structure: %s. Response: %s",
                err,
                text,
            )
            raise HomeAssistantError(
                f"AI Task response does not match the requested structure: {err}"
            ) from err

        return ai_task.GenDataTaskResult(
            conversation_id=chat_log.conversation_id,
            data=data,
        )
