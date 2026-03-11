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


# --- generate_automation tests ---


async def test_generate_automation_service_registered(hass: HomeAssistant):
    """Test that smartchain.generate_automation service is registered after setup."""
    assert await async_setup(hass, {})
    assert hass.services.has_service(DOMAIN, "generate_automation")


async def test_generate_automation_no_agent(hass: HomeAssistant):
    """Test generate_automation service when no agent is available."""
    await async_setup(hass, {})

    result = await hass.services.async_call(
        DOMAIN,
        "generate_automation",
        {"description": "Turn on lights at sunset"},
        blocking=True,
        return_response=True,
    )

    assert result["automation_yaml"] == ""
    assert "No SmartChain agent" in result["error"]


async def test_generate_automation_returns_yaml(hass: HomeAssistant):
    """Test generate_automation returns LLM-generated YAML."""
    await async_setup(hass, {})

    yaml_output = """alias: Lights at sunset
description: Turn on living room lights at sunset
trigger:
  - platform: sun
    event: sunset
action:
  - service: light.turn_on
    target:
      entity_id: light.living_room"""

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content=yaml_output)
    _setup_entry_with_client(hass, mock_client)

    result = await hass.services.async_call(
        DOMAIN,
        "generate_automation",
        {"description": "Turn on living room lights at sunset"},
        blocking=True,
        return_response=True,
    )

    assert "alias: Lights at sunset" in result["automation_yaml"]
    assert "light.turn_on" in result["automation_yaml"]
    mock_client.ainvoke.assert_called_once()


async def test_generate_automation_strips_code_fences(hass: HomeAssistant):
    """Test generate_automation strips markdown code fences from LLM output."""
    await async_setup(hass, {})

    yaml_with_fences = """```yaml
alias: Coffee at 7AM
trigger:
  - platform: time
    at: "07:00:00"
action:
  - service: switch.turn_on
    target:
      entity_id: switch.coffee_machine
```"""

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content=yaml_with_fences)
    _setup_entry_with_client(hass, mock_client)

    result = await hass.services.async_call(
        DOMAIN,
        "generate_automation",
        {"description": "Make coffee at 7 AM"},
        blocking=True,
        return_response=True,
    )

    assert "```" not in result["automation_yaml"]
    assert "alias: Coffee at 7AM" in result["automation_yaml"]
    assert "switch.coffee_machine" in result["automation_yaml"]


async def test_generate_automation_llm_error(hass: HomeAssistant):
    """Test generate_automation handles LLM error gracefully."""
    await async_setup(hass, {})

    mock_client = AsyncMock()
    mock_client.ainvoke.side_effect = Exception("LLM timeout")
    _setup_entry_with_client(hass, mock_client)

    result = await hass.services.async_call(
        DOMAIN,
        "generate_automation",
        {"description": "Something"},
        blocking=True,
        return_response=True,
    )

    assert result["automation_yaml"] == ""
    assert "LLM timeout" in result["error"]


async def test_generate_automation_deploy(hass: HomeAssistant):
    """Test generate_automation with deploy=true creates automation in HA."""
    await async_setup(hass, {})

    yaml_output = """alias: Morning coffee
description: Turn on coffee machine at 7 AM
trigger:
  - platform: time
    at: "07:00:00"
action:
  - service: switch.turn_on
    target:
      entity_id: switch.coffee_machine"""

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content=yaml_output)
    _setup_entry_with_client(hass, mock_client)

    # Mock automation.reload service
    hass.services.async_register("automation", "reload", AsyncMock())

    result = await hass.services.async_call(
        DOMAIN,
        "generate_automation",
        {"description": "Coffee at 7AM", "deploy": True},
        blocking=True,
        return_response=True,
    )

    assert "alias: Morning coffee" in result["automation_yaml"]
    assert result["deployed"] is True
    assert result["alias"] == "Morning coffee"
    assert "automation_id" in result


async def test_generate_automation_deploy_false(hass: HomeAssistant):
    """Test generate_automation with deploy=false does not create automation."""
    await async_setup(hass, {})

    yaml_output = "alias: Test\ntrigger: []\naction: []"

    mock_client = AsyncMock()
    mock_client.ainvoke.return_value = AIMessage(content=yaml_output)
    _setup_entry_with_client(hass, mock_client)

    result = await hass.services.async_call(
        DOMAIN,
        "generate_automation",
        {"description": "Test", "deploy": False},
        blocking=True,
        return_response=True,
    )

    assert result["automation_yaml"] != ""
    assert "deployed" not in result
