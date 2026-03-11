"""Tests for SmartChain ask and analyze_image services."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from langchain_core.messages import AIMessage

from custom_components.smartchain import async_setup
from custom_components.smartchain.const import DOMAIN

from .conftest import MOCK_GIGACHAT_DATA


async def test_ask_service_registered(hass: HomeAssistant):
    """Test that smartchain.ask service is registered after setup."""
    assert await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, "ask")


async def test_ask_service_no_agent(hass: HomeAssistant):
    """Test ask service when no agent is available."""
    await async_setup(hass, {})

    result = await hass.services.async_call(
        DOMAIN,
        "ask",
        {"message": "Hello"},
        blocking=True,
        return_response=True,
    )

    assert "No SmartChain agent" in result["response"]


async def test_ask_service_with_client(hass: HomeAssistant):
    """Test ask service returns LLM response."""
    await async_setup(hass, {})

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content="The kitchen is 22°C")

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.domain = DOMAIN
    entry.data = dict(MOCK_GIGACHAT_DATA)
    entry.options = {}
    entry.unique_id = "GigaChat"
    entry.subentries = {}
    entry.runtime_data = mock_client

    hass.config_entries._entries[entry.entry_id] = entry

    result = await hass.services.async_call(
        DOMAIN,
        "ask",
        {"message": "What's the temperature?"},
        blocking=True,
        return_response=True,
    )

    assert result["response"] == "The kitchen is 22°C"
    mock_client.ainvoke.assert_called_once()


async def test_ask_service_with_subentry_client(hass: HomeAssistant):
    """Test ask service with subentry-based clients."""
    await async_setup(hass, {})

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content="Sunny weather")

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.domain = DOMAIN
    entry.data = dict(MOCK_GIGACHAT_DATA)
    entry.unique_id = "GigaChat"
    entry.runtime_data = {"sub1": mock_client}

    hass.config_entries._entries[entry.entry_id] = entry

    result = await hass.services.async_call(
        DOMAIN,
        "ask",
        {"message": "What's the weather?"},
        blocking=True,
        return_response=True,
    )

    assert result["response"] == "Sunny weather"


async def test_analyze_image_service_registered(hass: HomeAssistant):
    """Test that smartchain.analyze_image service is registered after setup."""
    assert await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, "analyze_image")


async def test_analyze_image_no_agent(hass: HomeAssistant):
    """Test analyze_image service when no agent is available."""
    await async_setup(hass, {})

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8\xff\xe0fake_jpeg_data"
    mock_image.content_type = "image/jpeg"

    with patch(
        "custom_components.smartchain.async_get_image",
        return_value=mock_image,
    ):
        result = await hass.services.async_call(
            DOMAIN,
            "analyze_image",
            {"message": "What do you see?", "camera_entity_id": "camera.front_door"},
            blocking=True,
            return_response=True,
        )

    assert "No SmartChain agent" in result["response"]


async def test_analyze_image_with_client(hass: HomeAssistant):
    """Test analyze_image returns LLM response with camera snapshot."""
    await async_setup(hass, {})

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content="I see a person at the door")

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.domain = DOMAIN
    entry.data = dict(MOCK_GIGACHAT_DATA)
    entry.options = {}
    entry.unique_id = "GigaChat"
    entry.subentries = {}
    entry.runtime_data = mock_client

    hass.config_entries._entries[entry.entry_id] = entry

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8\xff\xe0fake_jpeg_data"
    mock_image.content_type = "image/jpeg"

    with patch(
        "custom_components.smartchain.async_get_image",
        return_value=mock_image,
    ):
        result = await hass.services.async_call(
            DOMAIN,
            "analyze_image",
            {"message": "What do you see?", "camera_entity_id": "camera.front_door"},
            blocking=True,
            return_response=True,
        )

    assert result["response"] == "I see a person at the door"
    mock_client.ainvoke.assert_called_once()

    # Verify multimodal message was sent
    call_args = mock_client.ainvoke.call_args[0][0]
    assert len(call_args) == 1
    msg = call_args[0]
    assert isinstance(msg.content, list)
    assert msg.content[0]["type"] == "text"
    assert msg.content[0]["text"] == "What do you see?"
    assert msg.content[1]["type"] == "image_url"
    assert msg.content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


async def test_analyze_image_camera_error(hass: HomeAssistant):
    """Test analyze_image handles camera error gracefully."""
    await async_setup(hass, {})

    with patch(
        "custom_components.smartchain.async_get_image",
        side_effect=Exception("Camera unavailable"),
    ):
        result = await hass.services.async_call(
            DOMAIN,
            "analyze_image",
            {"message": "Check camera", "camera_entity_id": "camera.broken"},
            blocking=True,
            return_response=True,
        )

    assert "Error getting camera image" in result["response"]


def _setup_entry_with_client(hass, mock_client):
    """Helper to register a mock config entry with client."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.domain = DOMAIN
    entry.data = dict(MOCK_GIGACHAT_DATA)
    entry.options = {}
    entry.unique_id = "GigaChat"
    entry.subentries = {}
    entry.runtime_data = mock_client
    hass.config_entries._entries[entry.entry_id] = entry
    return entry


async def test_analyze_image_fires_event(hass: HomeAssistant):
    """Test analyze_image fires smartchain_image_analyzed event."""
    await async_setup(hass, {})

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content="A cat on the porch")
    _setup_entry_with_client(hass, mock_client)

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8fake"
    mock_image.content_type = "image/jpeg"

    events = []
    hass.bus.async_listen("smartchain_image_analyzed", lambda e: events.append(e))

    with patch("custom_components.smartchain.async_get_image", return_value=mock_image):
        await hass.services.async_call(
            DOMAIN,
            "analyze_image",
            {"message": "What's there?", "camera_entity_id": "camera.porch"},
            blocking=True,
            return_response=True,
        )

    await hass.async_block_till_done()
    assert len(events) == 1
    assert events[0].data["response"] == "A cat on the porch"
    assert events[0].data["camera_entity_id"] == "camera.porch"
    assert events[0].data["message"] == "What's there?"
    assert "timestamp" in events[0].data


async def test_analyze_image_updates_sensor(hass: HomeAssistant):
    """Test analyze_image updates sensor.smartchain_last_analysis."""
    await async_setup(hass, {})

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content="Garage door is open")
    _setup_entry_with_client(hass, mock_client)

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8fake"
    mock_image.content_type = "image/jpeg"

    with patch("custom_components.smartchain.async_get_image", return_value=mock_image):
        await hass.services.async_call(
            DOMAIN,
            "analyze_image",
            {"message": "Check garage", "camera_entity_id": "camera.garage"},
            blocking=True,
            return_response=True,
        )

    state = hass.states.get("sensor.smartchain_last_analysis")
    assert state is not None
    assert state.state == "Garage door is open"
    assert state.attributes["camera_entity_id"] == "camera.garage"
    assert state.attributes["message"] == "Check garage"
    assert state.attributes["full_response"] == "Garage door is open"
    assert "timestamp" in state.attributes


async def test_analyze_image_with_notify_returns_response(hass: HomeAssistant):
    """Test analyze_image returns response and updates sensor when notify_entity is provided."""
    await async_setup(hass, {})

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content="Stranger at door")
    _setup_entry_with_client(hass, mock_client)

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8fake"
    mock_image.content_type = "image/jpeg"

    with patch("custom_components.smartchain.async_get_image", return_value=mock_image):
        result = await hass.services.async_call(
            DOMAIN,
            "analyze_image",
            {
                "message": "Who is there?",
                "camera_entity_id": "camera.front",
                "notify_entity": "notify.mobile_app_phone",
            },
            blocking=True,
            return_response=True,
        )

    # Response is returned even though notify service may not exist
    assert result["response"] == "Stranger at door"
    # Sensor is still updated
    state = hass.states.get("sensor.smartchain_last_analysis")
    assert state is not None
    assert state.state == "Stranger at door"


async def test_analyze_image_notify_failure_does_not_break(hass: HomeAssistant):
    """Test analyze_image still returns response even if notification fails."""
    await async_setup(hass, {})

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content="All clear")
    _setup_entry_with_client(hass, mock_client)

    mock_image = MagicMock()
    mock_image.content = b"\xff\xd8fake"
    mock_image.content_type = "image/jpeg"

    with patch("custom_components.smartchain.async_get_image", return_value=mock_image):
        result = await hass.services.async_call(
            DOMAIN,
            "analyze_image",
            {
                "message": "Check",
                "camera_entity_id": "camera.yard",
                "notify_entity": "notify.nonexistent",
            },
            blocking=True,
            return_response=True,
        )

    # Response should still be returned even if notify fails
    assert result["response"] == "All clear"
    # Sensor should still be updated
    state = hass.states.get("sensor.smartchain_last_analysis")
    assert state is not None
