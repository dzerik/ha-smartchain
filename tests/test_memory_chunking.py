"""Tests for memory text chunking."""

from custom_components.smartchain.const import (
    MEMORY_CHUNK_OVERLAP,
    MEMORY_CHUNK_SIZE,
    MEMORY_MAX_TEXT_LEN,
)
from custom_components.smartchain.tools.memory.store import chunk_text


def test_chunk_short_text_returns_single_chunk() -> None:
    chunks = chunk_text("hello world")
    assert chunks == ["hello world"]


def test_chunk_text_at_threshold_returns_single_chunk() -> None:
    text = "a" * MEMORY_MAX_TEXT_LEN
    chunks = chunk_text(text)
    assert chunks == [text]


def test_chunk_long_text_uses_chunk_size_with_overlap() -> None:
    text = "a" * (MEMORY_MAX_TEXT_LEN + 500)
    chunks = chunk_text(text)
    assert len(chunks) >= 2
    assert all(len(c) <= MEMORY_CHUNK_SIZE for c in chunks)
    # consecutive chunks must overlap by MEMORY_CHUNK_OVERLAP characters
    for i in range(1, len(chunks)):
        prev_tail = chunks[i - 1][-MEMORY_CHUNK_OVERLAP:]
        next_head = chunks[i][:MEMORY_CHUNK_OVERLAP]
        assert prev_tail == next_head


def test_chunk_empty_text_returns_empty_list() -> None:
    assert chunk_text("") == []
