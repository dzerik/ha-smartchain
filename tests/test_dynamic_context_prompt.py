"""Prompt composition from the entity-context skeleton and retrieval.

Off keeps today's prompt byte for byte, through the same cache. On swaps the
full devices dump for the skeleton plus whatever this turn's retrieval found.
`build_entity_context` returning None (option off, or the skeleton could not
be built) is the caller's signal to fall back to exactly today's behaviour;
`""` is a genuinely empty home and is not a fallback trigger.

Composition is driven directly through `_build_system_prompt`, the method
extracted out of `_async_handle_message` for exactly this purpose: exercising
it does not require a real ChatLog, a mocked client or the tool-calling loop.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.conversation import ConversationInput
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    SystemContent,
    UserContent,
)
from homeassistant.core import Context, HomeAssistant

from custom_components.smartchain.const import (
    CONF_CHAT_HISTORY,
    CONF_DYNAMIC_ENTITY_CONTEXT,
    CONF_ENGINE,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    DEFAULT_DEVICES_PROMPT,
    DEFAULT_PROMPT,
    ID_GIGACHAT,
)
from custom_components.smartchain.conversation import SmartChainConversationEntity

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

_BUILD_CONTEXT = "custom_components.smartchain.conversation.build_entity_context"

# Unique to DEFAULT_DEVICES_PROMPT's static text; never appears in the
# skeleton/retrieval path.
_DEVICES_DUMP_MARKER = "rooms, devices and sensors are available in the home"


def _make_entity(hass: HomeAssistant) -> SmartChainConversationEntity:
    """Create a test entity with hass attached (matches test_prompt_cache.py)."""
    entry = MagicMock()
    entry.entry_id = "test"
    entry.data = {CONF_ENGINE: ID_GIGACHAT}
    entry.options = {}
    entry.runtime_data = MagicMock()
    entry.subentries = {}

    ent = SmartChainConversationEntity(entry)
    ent.hass = hass
    return ent


def _make_input(text: str = "Hello, assistant!") -> ConversationInput:
    return ConversationInput(
        text=text,
        context=Context(),
        conversation_id=None,
        device_id=None,
        satellite_id=None,
        language="ru",
        agent_id="test_agent",
    )


def _todays_prompt(entity: SmartChainConversationEntity, user_prompt: str) -> str:
    """Reproduce the pre-existing composition, independent of the code under test."""
    return entity._render_prompt_cached(user_prompt + DEFAULT_DEVICES_PROMPT)


async def test_off_reproduces_todays_prompt_exactly(hass: HomeAssistant) -> None:
    """The single most important test in this task."""
    entity = _make_entity(hass)
    options = {CONF_PROMPT: DEFAULT_PROMPT, CONF_DYNAMIC_ENTITY_CONTEXT: False}
    user_input = _make_input()
    expected = _todays_prompt(entity, DEFAULT_PROMPT)

    with patch(_BUILD_CONTEXT, new=AsyncMock()) as mock_build:
        result = await entity._build_system_prompt(options, user_input)

    assert result == expected
    mock_build.assert_not_called()


async def test_on_uses_the_skeleton_and_not_the_dump(hass: HomeAssistant) -> None:
    entity = _make_entity(hass)
    options = {CONF_PROMPT: DEFAULT_PROMPT, CONF_DYNAMIC_ENTITY_CONTEXT: True}
    user_input = _make_input()

    with patch(_BUILD_CONTEXT, new=AsyncMock(return_value="Kitchen — light: Ceiling")):
        result = await entity._build_system_prompt(options, user_input)

    assert "Kitchen — light: Ceiling" in result
    assert _DEVICES_DUMP_MARKER not in result


async def test_on_appends_the_retrieved_block(hass: HomeAssistant) -> None:
    entity = _make_entity(hass)
    options = {CONF_PROMPT: DEFAULT_PROMPT, CONF_DYNAMIC_ENTITY_CONTEXT: True}
    user_input = _make_input(text="is the kitchen light on")
    context = (
        "Kitchen — light: Ceiling\n\n"
        "Mentioned in this request:\n"
        "- light.kitchen — Ceiling [Kitchen] = on"
    )

    with patch(_BUILD_CONTEXT, new=AsyncMock(return_value=context)):
        result = await entity._build_system_prompt(options, user_input)

    assert "light.kitchen" in result
    assert "= on" in result


async def test_a_none_context_falls_back_to_the_dump(hass: HomeAssistant) -> None:
    """Layer two of the failure ladder, at the call site."""
    entity = _make_entity(hass)
    options = {CONF_PROMPT: DEFAULT_PROMPT, CONF_DYNAMIC_ENTITY_CONTEXT: True}
    user_input = _make_input()
    expected = _todays_prompt(entity, DEFAULT_PROMPT)

    with patch(_BUILD_CONTEXT, new=AsyncMock(return_value=None)):
        result = await entity._build_system_prompt(options, user_input)

    assert result == expected


async def test_the_user_prompt_is_still_rendered_through_jinja(hass: HomeAssistant) -> None:
    entity = _make_entity(hass)
    user_prompt = "Hi {{ ha_name }}"
    options = {CONF_PROMPT: user_prompt, CONF_DYNAMIC_ENTITY_CONTEXT: True}
    user_input = _make_input()

    with patch(_BUILD_CONTEXT, new=AsyncMock(return_value="some context")):
        result = await entity._build_system_prompt(options, user_input)

    assert "{{ ha_name }}" not in result
    assert f"Hi {hass.config.location_name}" in result


async def test_the_skills_prompt_is_still_appended_after(hass: HomeAssistant) -> None:
    """Ordering is unchanged: user prompt, context, then skills.

    Skills concatenation happens in `_async_handle_message`, not in the
    extracted method, so this is the one test in the file that must drive
    the full turn to prove the call site still appends after.
    """
    entry = MagicMock()
    entry.entry_id = "test"
    entry.data = {CONF_ENGINE: ID_GIGACHAT}
    entry.options = {
        CONF_PROMPT: "USERMARK {{ ha_name }}",
        CONF_DYNAMIC_ENTITY_CONTEXT: True,
        CONF_CHAT_HISTORY: True,
        CONF_PROCESS_BUILTIN_SENTENCES: False,
    }
    llm_client = MagicMock()

    async def _astream(_messages):
        return
        yield  # pragma: no cover - makes this an async generator

    llm_client.astream = _astream
    entry.runtime_data = llm_client
    entry.subentries = {}

    entity = SmartChainConversationEntity(entry)
    entity.hass = hass

    chat_log = MagicMock()
    chat_log.conversation_id = "test-conv-id"
    chat_log.content = [
        SystemContent(content=""),
        UserContent(content="Hello, assistant!"),
    ]
    chat_log.llm_api = None
    chat_log.unresponded_tool_results = False

    async def _mock_add_delta_stream(agent_id, stream):
        collected = ""
        async for delta in stream:
            if "content" in delta:
                collected += delta["content"]
        content = AssistantContent(agent_id=agent_id, content=collected)
        chat_log.content.append(content)
        yield content

    chat_log.async_add_delta_content_stream = _mock_add_delta_stream

    with (
        patch(_BUILD_CONTEXT, new=AsyncMock(return_value="CONTEXTMARK")),
        patch.object(
            SmartChainConversationEntity,
            "_async_get_skills_prompt",
            new=AsyncMock(return_value="\n\nSKILLSMARK"),
        ),
    ):
        await entity._async_handle_message(_make_input(), chat_log)

    system_text = chat_log.content[0].content
    assert "USERMARK" in system_text
    assert system_text.index("USERMARK") < system_text.index("CONTEXTMARK")
    assert system_text.index("CONTEXTMARK") < system_text.index("SKILLSMARK")


async def test_the_query_is_the_users_message(hass: HomeAssistant) -> None:
    entity = _make_entity(hass)
    options = {CONF_PROMPT: DEFAULT_PROMPT, CONF_DYNAMIC_ENTITY_CONTEXT: True}
    user_input = _make_input(text="turn off the kitchen light")

    with patch(_BUILD_CONTEXT, new=AsyncMock(return_value="context")) as mock_build:
        await entity._build_system_prompt(options, user_input)

    assert mock_build.call_args.kwargs["query"] == "turn off the kitchen light"
