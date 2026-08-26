"""Streaming chunks must be accumulated before HA sees a tool call.

Providers on the OpenAI wire protocol (and Anthropic) split a single tool call
across several chunks: the first carries the name and id, the rest carry slices
of the JSON arguments. Converting each chunk on its own hands HA a call with
empty arguments plus a phantom call with no name at all, because langchain
re-derives ``tool_calls`` from the ``tool_call_chunks`` of that chunk alone.
"""

from typing import Any
from unittest.mock import MagicMock

from homeassistant.helpers import llm
from langchain_core.messages import AIMessageChunk

from custom_components.smartchain.conversation import _async_langchain_stream


def _client(*chunks: AIMessageChunk) -> MagicMock:
    """Return a client whose astream replays the given chunks."""

    async def _astream(_messages):
        for chunk in chunks:
            yield chunk

    client = MagicMock()
    client.astream = _astream
    return client


def _split_tool_call_chunks() -> tuple[AIMessageChunk, ...]:
    """One tool call cut into three chunks, the way OpenAI streams it."""
    return (
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "id": "call_1",
                    "name": "HassTurnOn",
                    "args": '{"name": ',
                    "index": 0,
                    "type": "tool_call_chunk",
                }
            ],
        ),
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "id": None,
                    "name": None,
                    "args": '"kitchen light"',
                    "index": 0,
                    "type": "tool_call_chunk",
                }
            ],
        ),
        AIMessageChunk(
            content="",
            tool_call_chunks=[
                {
                    "id": None,
                    "name": None,
                    "args": "}",
                    "index": 0,
                    "type": "tool_call_chunk",
                }
            ],
        ),
    )


async def _collect(client: MagicMock, **kwargs: Any) -> list[dict[str, Any]]:
    return [delta async for delta in _async_langchain_stream(client, [], **kwargs)]


async def test_split_tool_call_args_arrive_complete() -> None:
    """A tool call split across chunks reaches HA as one call with full args."""
    deltas = await _collect(_client(*_split_tool_call_chunks()))

    tool_inputs = [tc for d in deltas for tc in d.get("tool_calls", [])]
    assert len(tool_inputs) == 1, f"expected one tool call, got {tool_inputs}"
    call = tool_inputs[0]
    assert isinstance(call, llm.ToolInput)
    assert call.tool_name == "HassTurnOn"
    assert call.id == "call_1"
    assert call.tool_args == {"name": "kitchen light"}


async def test_no_phantom_tool_call_without_name() -> None:
    """A continuation chunk carrying no name must not become a second call.

    OpenAI-compatible endpoints close a tool call with a chunk whose name, id
    and argument slice are all empty; on its own langchain reads that as a
    complete call named "" with no arguments.
    """
    tail = AIMessageChunk(
        content="",
        tool_call_chunks=[
            {"id": "", "name": "", "args": "", "index": 0, "type": "tool_call_chunk"}
        ],
    )
    deltas = await _collect(_client(*_split_tool_call_chunks(), tail))

    tool_inputs = [tc for d in deltas for tc in d.get("tool_calls", [])]
    assert [tc.tool_name for tc in tool_inputs] == ["HassTurnOn"]
    assert tool_inputs[0].tool_args == {"name": "kitchen light"}


async def test_list_content_is_yielded_as_text() -> None:
    """Anthropic streams content blocks; HA concatenates str, so send str."""
    deltas = await _collect(
        _client(
            AIMessageChunk(content=[{"type": "text", "text": "Hello", "index": 0}]),
            AIMessageChunk(content=[{"type": "text", "text": " world", "index": 0}]),
            AIMessageChunk(content=["!"]),
        )
    )

    contents = [d["content"] for d in deltas if "content" in d]
    assert all(isinstance(c, str) for c in contents), f"non-str content: {contents}"
    assert "".join(contents) == "Hello world!"


async def test_non_text_blocks_are_not_streamed_as_content() -> None:
    """Tool-use blocks travel in tool_calls, never in the text delta."""
    deltas = await _collect(
        _client(
            AIMessageChunk(
                content=[
                    {"type": "text", "text": "Sure", "index": 0},
                    {"type": "tool_use", "id": "call_1", "name": "HassTurnOn", "index": 1},
                ]
            ),
        )
    )

    contents = [d["content"] for d in deltas if "content" in d]
    assert contents == ["Sure"]


async def test_tool_calls_delta_is_emitted_once_after_content() -> None:
    """HA fires a tool call the moment it sees it: emit it only when complete."""
    head, *rest = _split_tool_call_chunks()
    # The chunk that opens the tool call also carries text, as providers do.
    head = AIMessageChunk(content="Turning it on. ", tool_call_chunks=head.tool_call_chunks)
    deltas = await _collect(_client(head, *rest))

    with_tools = [i for i, d in enumerate(deltas) if "tool_calls" in d]
    assert len(with_tools) == 1, f"tool_calls appeared in {len(with_tools)} deltas"
    last_content = max(i for i, d in enumerate(deltas) if "content" in d)
    assert with_tools[0] > last_content, f"tool call emitted before the text: {deltas}"
    assert with_tools[0] == len(deltas) - 1


async def test_role_only_in_first_delta() -> None:
    """The role key opens a new assistant message and must not repeat."""
    deltas = await _collect(_client(AIMessageChunk(content="Hi"), *_split_tool_call_chunks()))

    assert deltas[0].get("role") == "assistant"
    assert not any("role" in d for d in deltas[1:]), deltas


async def test_external_flag_survives_accumulation() -> None:
    """Custom tools stay external once the call is assembled at the end."""
    deltas = await _collect(
        _client(*_split_tool_call_chunks()), external_tool_names=frozenset({"HassTurnOn"})
    )

    tool_inputs = [tc for d in deltas for tc in d.get("tool_calls", [])]
    assert len(tool_inputs) == 1
    assert tool_inputs[0].external is True
