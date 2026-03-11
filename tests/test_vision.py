"""Tests for SmartChain vision (image analysis) support."""

import base64
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from homeassistant.components.conversation.chat_log import (
    Attachment,
    SystemContent,
    UserContent,
)
from langchain_core.messages import HumanMessage, SystemMessage

from custom_components.smartchain.conversation import (
    _attachment_to_base64,
    _chatlog_to_langchain,
)


@pytest.fixture
def sample_image_path():
    """Create a temporary image file for testing."""
    # Minimal valid JPEG (2x2 red pixel)
    jpeg_bytes = base64.b64decode(
        "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkS"
        "Ew8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJ"
        "CQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
        "MjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFAABAAAAAAAAAAAAAAAA"
        "AAAAB//EABQQAQAAAAAAAAAAAAAAAAAAAAD/xAAUAQEAAAAAAAAAAAAAAAAAAAAA/8QA"
        "FBEBAAAAAAAAAAAAAAAAAAAAAP/aAAwDAQACEQMRAD8AAAH/2Q=="
    )
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(jpeg_bytes)
        path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


def test_attachment_to_base64(sample_image_path) -> None:
    """Test converting an attachment to base64 data URL."""
    att = Attachment(
        media_content_id="camera.front_door",
        mime_type="image/jpeg",
        path=sample_image_path,
    )
    result = _attachment_to_base64(att)
    assert result is not None
    assert result.startswith("data:image/jpeg;base64,")
    # Decode to verify it's valid base64
    b64_data = result.split(",", 1)[1]
    decoded = base64.b64decode(b64_data)
    assert len(decoded) > 0


def test_attachment_to_base64_missing_file() -> None:
    """Test that missing file returns None."""
    att = Attachment(
        media_content_id="camera.missing",
        mime_type="image/jpeg",
        path=Path("/nonexistent/image.jpg"),
    )
    result = _attachment_to_base64(att)
    assert result is None


def test_chatlog_with_image_attachment(sample_image_path) -> None:
    """Test _chatlog_to_langchain converts image attachments to multimodal messages."""
    att = Attachment(
        media_content_id="camera.front_door",
        mime_type="image/jpeg",
        path=sample_image_path,
    )
    chat_log = MagicMock()
    chat_log.content = [
        SystemContent(content="System prompt"),
        UserContent(content="What do you see?", attachments=[att]),
    ]

    messages = _chatlog_to_langchain(chat_log)

    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert isinstance(messages[1], HumanMessage)
    # Content should be a list (multimodal)
    assert isinstance(messages[1].content, list)
    assert len(messages[1].content) == 2
    assert messages[1].content[0] == {"type": "text", "text": "What do you see?"}
    assert messages[1].content[1]["type"] == "image_url"
    assert messages[1].content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_chatlog_with_text_only_no_attachments() -> None:
    """Test that text-only messages remain simple strings (not lists)."""
    chat_log = MagicMock()
    chat_log.content = [
        SystemContent(content="System prompt"),
        UserContent(content="Hello!"),
    ]

    messages = _chatlog_to_langchain(chat_log)

    assert len(messages) == 2
    assert isinstance(messages[1], HumanMessage)
    # Content should be a plain string
    assert isinstance(messages[1].content, str)
    assert messages[1].content == "Hello!"


def test_chatlog_with_non_image_attachment() -> None:
    """Test that non-image attachments are ignored."""
    att = Attachment(
        media_content_id="media.audio_file",
        mime_type="audio/wav",
        path=Path("/tmp/test.wav"),
    )
    chat_log = MagicMock()
    chat_log.content = [
        SystemContent(content="System prompt"),
        UserContent(content="Listen to this", attachments=[att]),
    ]

    messages = _chatlog_to_langchain(chat_log)

    assert len(messages) == 2
    assert isinstance(messages[1], HumanMessage)
    # Only text part, no image
    assert isinstance(messages[1].content, list)
    assert len(messages[1].content) == 1
    assert messages[1].content[0] == {"type": "text", "text": "Listen to this"}


def test_chatlog_multiple_images(sample_image_path) -> None:
    """Test multiple image attachments in one message."""
    att1 = Attachment(
        media_content_id="camera.front",
        mime_type="image/jpeg",
        path=sample_image_path,
    )
    att2 = Attachment(
        media_content_id="camera.back",
        mime_type="image/png",
        path=sample_image_path,
    )
    chat_log = MagicMock()
    chat_log.content = [
        SystemContent(content="System prompt"),
        UserContent(content="Compare these views", attachments=[att1, att2]),
    ]

    messages = _chatlog_to_langchain(chat_log)

    assert isinstance(messages[1].content, list)
    # text + 2 images
    assert len(messages[1].content) == 3
    assert messages[1].content[0]["type"] == "text"
    assert messages[1].content[1]["type"] == "image_url"
    assert messages[1].content[2]["type"] == "image_url"
