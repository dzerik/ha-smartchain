"""A stream that goes wrong must not hand Home Assistant a half-built action.

Accumulating chunks fixed the tool call that arrives sliced, but it left three
ways for a broken stream to reach HA intact:

* the model stops mid-JSON (``max_tokens``) and langchain's partial parser
  turns ``'{"name": '`` into ``{}`` — a real tool run with no arguments at all;
* the model emits only thinking blocks, so no delta ever carries substance and
  ``ChatLog`` builds no assistant message, which makes the caller raise;
* two chunks disagree about the type of one metadata key and ``__add__``
  raises ``TypeError`` in the middle of the turn.

The last test in this file is the only one that runs our generator through the
real ``ChatLog.async_add_delta_content_stream``: the guarantee being defended
("HA fires a tool call the moment it sees the delta") is HA's behaviour, not
ours, so it is worth asserting against HA itself.
"""

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    ChatLog,
    SystemContent,
    UserContent,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from langchain_core.messages import AIMessageChunk

from custom_components.smartchain.conversation import _async_langchain_stream

TOOL_NAME = "HassTurnOn"


def _client(*chunks: AIMessageChunk) -> MagicMock:
    """Return a client whose astream replays the given chunks."""

    async def _astream(_messages):
        for chunk in chunks:
            yield chunk

    client = MagicMock()
    client.astream = _astream
    return client


async def _collect(client: MagicMock, **kwargs: Any) -> list[dict[str, Any]]:
    return [delta async for delta in _async_langchain_stream(client, [], **kwargs)]


def _tool_inputs(deltas: list[dict[str, Any]]) -> list[llm.ToolInput]:
    return [tc for d in deltas for tc in d.get("tool_calls", [])]


def _chunk(args: str, *, name: str | None = TOOL_NAME, call_id: str | None = "call_1"):
    """One tool-call chunk carrying `args` as its raw JSON slice."""
    return AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "id": call_id,
                "name": name,
                "args": args,
                "index": 0,
                "type": "tool_call_chunk",
            }
        ],
    )


# --- A1: arguments that never finished arriving ---------------------------------


async def test_truncated_arguments_are_not_executed(caplog) -> None:
    """A model that stopped mid-JSON must not run the tool with empty args.

    langchain parses `'{"name": '` with a partial-JSON parser and reports
    `args={}` on the tool call, so the accumulated message alone cannot tell
    "no arguments" from "arguments lost".
    """
    with caplog.at_level(logging.WARNING):
        deltas = await _collect(_client(_chunk('{"name": ')))

    assert _tool_inputs(deltas) == [], (
        f"a tool call with unparsed arguments reached HA: {_tool_inputs(deltas)}"
    )
    assert TOOL_NAME in caplog.text
    assert "name" not in caplog.text.replace(TOOL_NAME, ""), (
        f"argument content leaked into the log: {caplog.text}"
    )


async def test_truncated_arguments_split_across_chunks_are_not_executed() -> None:
    """The cut can fall anywhere; the join of the slices is what must parse."""
    deltas = await _collect(
        _client(
            _chunk('{"entity_id": "light.'),
            _chunk("bedroom", name=None, call_id=None),
        )
    )

    assert _tool_inputs(deltas) == []


async def test_tool_call_with_no_arguments_is_executed() -> None:
    """A provider that sends `args=""` means "this tool takes nothing"."""
    deltas = await _collect(_client(_chunk("")))

    calls = _tool_inputs(deltas)
    assert [c.tool_name for c in calls] == [TOOL_NAME]
    assert calls[0].tool_args == {}


async def test_tool_call_with_empty_object_arguments_is_executed() -> None:
    """`args="{}"` is a finished call with an empty argument object."""
    deltas = await _collect(_client(_chunk("{}")))

    calls = _tool_inputs(deltas)
    assert [c.tool_name for c in calls] == [TOOL_NAME]
    assert calls[0].tool_args == {}


async def test_a_finished_call_survives_a_truncated_sibling() -> None:
    """Dropping the broken call must not drop the one that did arrive."""
    chunk = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {
                "id": "call_ok",
                "name": TOOL_NAME,
                "args": '{"entity_id": "light.kitchen"}',
                "index": 0,
                "type": "tool_call_chunk",
            },
            {
                "id": "call_cut",
                "name": "HassTurnOff",
                "args": '{"entity_id": "light.',
                "index": 1,
                "type": "tool_call_chunk",
            },
        ],
    )
    calls = _tool_inputs(await _collect(_client(chunk)))

    assert [c.tool_name for c in calls] == [TOOL_NAME]
    assert calls[0].tool_args == {"entity_id": "light.kitchen"}


async def test_tool_call_without_streamed_chunks_is_trusted() -> None:
    """Providers that deliver a whole call at once carry no raw slice to check."""
    chunk = AIMessageChunk(
        content="",
        tool_calls=[{"id": "call_1", "name": TOOL_NAME, "args": {"entity_id": "light.hall"}}],
    )
    calls = _tool_inputs(await _collect(_client(chunk)))

    assert [c.tool_args for c in calls] == [{"entity_id": "light.hall"}]


# --- A2: a stream with nothing but thinking in it -------------------------------


async def test_thinking_only_stream_still_opens_an_assistant_message() -> None:
    """Without substance in some delta, ChatLog builds no AssistantContent."""
    deltas = await _collect(
        _client(
            AIMessageChunk(content=[{"type": "thinking", "thinking": "hmm", "index": 0}]),
            AIMessageChunk(content=[{"type": "redacted_thinking", "data": "xx", "index": 0}]),
        )
    )

    assert _chat_log_would_build_a_message(deltas), (
        f"HA would add no assistant content for {deltas}"
    )


def _chat_log_would_build_a_message(deltas: list[dict[str, Any]]) -> bool:
    """Mirror the condition ChatLog uses before it creates AssistantContent."""
    return any(
        d.get("content") or d.get("thinking_content") or d.get("tool_calls") or d.get("native")
        for d in deltas
    )


# --- A3: chunks that refuse to be added together --------------------------------


async def test_unmergeable_chunk_does_not_break_the_turn(caplog) -> None:
    """`AIMessageChunk.__add__` raises TypeError on a key of two types.

    It happens mid-stream, after the user has already been shown some text, so
    the turn must continue rather than die.
    """
    chunks = (
        AIMessageChunk(content="Привет", response_metadata={"usage": {"in": 1}}),
        AIMessageChunk(content=", ", response_metadata={"usage": "none"}),
        AIMessageChunk(content="мир"),
    )
    with caplog.at_level(logging.WARNING):
        deltas = await _collect(_client(*chunks))

    assert "".join(d["content"] for d in deltas if "content" in d) == "Привет, мир"


async def test_tool_call_still_emitted_after_an_unmergeable_chunk() -> None:
    """What accumulated before the clash is still a usable message."""
    chunks = (
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "id": "call_1",
                    "name": TOOL_NAME,
                    "args": '{"entity_id": "light.kitchen"}',
                    "index": 0,
                    "type": "tool_call_chunk",
                }
            ],
            response_metadata={"usage": {"in": 1}},
        ),
        AIMessageChunk(content="ok", response_metadata={"usage": "none"}),
    )
    calls = _tool_inputs(await _collect(_client(*chunks)))

    assert [c.tool_args for c in calls] == [{"entity_id": "light.kitchen"}]


# --- A6: the generator against the real ChatLog ---------------------------------


class _RecordingTool(llm.Tool):
    """A tool that records exactly what HA passed it."""

    name = TOOL_NAME
    description = "Turn on a device"

    def __init__(self) -> None:
        """Start with an empty execution log."""
        self.calls: list[dict] = []

    async def async_call(self, hass, tool_input, llm_context):
        """Record the call and report success."""
        self.calls.append(dict(tool_input.tool_args))
        return {"success": True}


def _llm_api(tool: _RecordingTool) -> MagicMock:
    api = MagicMock()
    api.tools = [tool]

    async def _call_tool(tool_input):
        return await tool.async_call(None, tool_input, None)

    api.async_call_tool = _call_tool
    return api


def _real_chat_log(hass: HomeAssistant, tool: _RecordingTool) -> ChatLog:
    chat_log = ChatLog(hass, "conv-stream-real")
    chat_log.content = [SystemContent(content=""), UserContent(content="включи свет")]
    chat_log.llm_api = _llm_api(tool)
    return chat_log


async def _drive(chat_log: ChatLog, client: MagicMock) -> None:
    async for _ in chat_log.async_add_delta_content_stream(
        "test_agent", _async_langchain_stream(client, [])
    ):
        pass


def _assistant(chat_log: ChatLog) -> AssistantContent:
    found = [c for c in chat_log.content if isinstance(c, AssistantContent)]
    assert found, f"no assistant message in {chat_log.content}"
    return found[-1]


async def test_real_chat_log_runs_the_tool_with_the_assembled_args(
    hass: HomeAssistant,
) -> None:
    """End to end through HA: text kept, tool run once with the full args."""
    tool = _RecordingTool()
    chat_log = _real_chat_log(hass, tool)
    await _drive(
        chat_log,
        _client(
            AIMessageChunk(content="Включаю. "),
            _chunk('{"entity_id": '),
            _chunk('"light.bedroom"}', name=None, call_id=None),
        ),
    )

    assistant = _assistant(chat_log)
    assert assistant.content == "Включаю. "
    assert [c.tool_name for c in (assistant.tool_calls or [])] == [TOOL_NAME]
    assert tool.calls == [{"entity_id": "light.bedroom"}]


async def test_real_chat_log_does_not_run_a_truncated_tool_call(
    hass: HomeAssistant,
) -> None:
    """HA runs a call the instant it sees it, so a cut call must never arrive."""
    tool = _RecordingTool()
    chat_log = _real_chat_log(hass, tool)
    await _drive(
        chat_log,
        _client(AIMessageChunk(content="Включаю. "), _chunk('{"entity_id": ')),
    )

    assert tool.calls == []
    assistant = _assistant(chat_log)
    assert assistant.content == "Включаю. "
    assert not assistant.tool_calls


async def test_real_chat_log_gets_a_message_from_a_thinking_only_stream(
    hass: HomeAssistant,
) -> None:
    """A model that only thought still ends the turn with an assistant message."""
    tool = _RecordingTool()
    chat_log = _real_chat_log(hass, tool)
    await _drive(
        chat_log,
        _client(
            AIMessageChunk(content=[{"type": "thinking", "thinking": "hmm", "index": 0}]),
        ),
    )

    assert isinstance(chat_log.content[-1], AssistantContent)
    assert tool.calls == []


@pytest.mark.parametrize("raw", ['{"entity_id": ', "{", '{"entity_id": "light.a"'])
async def test_real_chat_log_never_runs_a_tool_for_unparsed_args(
    hass: HomeAssistant, raw: str
) -> None:
    """Every way the JSON can be cut short ends the same way: no execution."""
    tool = _RecordingTool()
    chat_log = _real_chat_log(hass, tool)
    await _drive(chat_log, _client(_chunk(raw)))

    assert tool.calls == []
