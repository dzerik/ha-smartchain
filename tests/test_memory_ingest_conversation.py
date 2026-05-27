"""Tests for ingest_conversation_turn."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.ingest import ingest_conversation_turn


async def test_ingest_writes_combined_turn(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.add = AsyncMock(return_value=["doc-1"])

    await ingest_conversation_turn(
        store,
        user_text="what time is it?",
        assistant_text="it is 6 pm",
        metadata={"kind": "conversation", "timestamp": "2026-05-27T18:00:00+00:00"},
    )

    store.add.assert_awaited_once()
    args, kwargs = store.add.call_args
    text_written = args[0] if args else kwargs.get("text")
    assert "what time is it?" in text_written
    assert "it is 6 pm" in text_written


async def test_ingest_noop_when_store_unavailable(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = False
    store.add = AsyncMock()
    await ingest_conversation_turn(
        store,
        user_text="x",
        assistant_text="y",
        metadata={"kind": "conversation", "timestamp": "t"},
    )
    store.add.assert_not_called()


async def test_ingest_skips_empty_assistant_text(hass: HomeAssistant) -> None:
    store = MagicMock()
    store.is_available = True
    store.add = AsyncMock()
    await ingest_conversation_turn(
        store,
        user_text="hi",
        assistant_text="",
        metadata={"kind": "conversation", "timestamp": "t"},
    )
    store.add.assert_not_called()


async def test_ingest_swallows_exceptions(hass: HomeAssistant, caplog) -> None:
    store = MagicMock()
    store.is_available = True
    store.add = AsyncMock(side_effect=RuntimeError("boom"))
    # Must not raise — must log at warning.
    await ingest_conversation_turn(
        store,
        user_text="hi",
        assistant_text="there",
        metadata={"kind": "conversation", "timestamp": "t"},
    )
    assert "boom" in caplog.text.lower() or "memory" in caplog.text.lower()
