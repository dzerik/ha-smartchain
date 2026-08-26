"""The retrieved block belongs to one turn and must not outlive it.

On the Assist path the block is handed to Home Assistant through
`async_provide_llm_data`'s `user_extra_system_prompt`. That argument is not a
per-call value: `chat_log.py:751-761` reads it as
``user_extra_system_prompt or self.extra_system_prompt`` and then *stores* the
result on the `ChatLog`, and `async_get_chat_log` carries the field forward
into every later turn of the same conversation (`chat_log.py:106` copies it
with `dataclasses.replace`). A turn that produces no block passes `None`, HA
falls back to what it kept, and the previous turn's entity ids and live states
are re-sent — frozen — for the rest of the session.

So these run **two** turns over one `ChatLog`. On a single turn the defect does
not exist; it is entirely a question of what the second turn inherits.

The reset has to be narrow. HA's stickiness is a real feature for the *user's*
own `extra_system_prompt`, and a fix that simply cleared the field every turn
would silently drop that instead — trading a stale block for lost instructions.
Both halves are pinned below.
"""

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.conversation import ConversationInput
from homeassistant.components.conversation.chat_log import (
    ChatLog,
    SystemContent,
    UserContent,
)
from homeassistant.core import Context, HomeAssistant
from langchain_core.messages import AIMessageChunk

from custom_components.smartchain.const import (
    CONF_ALLOWED_TOOLS,
    CONF_CHAT_HISTORY,
    CONF_DYNAMIC_CONTEXT_ON_ASSIST,
    CONF_DYNAMIC_ENTITY_CONTEXT,
    CONF_ENGINE,
    CONF_LLM_HASS_API,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    ID_GIGACHAT,
)
from custom_components.smartchain.conversation import SmartChainConversationEntity
from custom_components.smartchain.tools.memory.entity_context import _RETRIEVED_HEADING

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

_BUILD_RETRIEVED = "custom_components.smartchain.conversation.build_retrieved_context"

BLOCK_ONE = f"{_RETRIEVED_HEADING}\n- light.kitchen — Свет на кухне [Кухня] = on"
BLOCK_TWO = f"{_RETRIEVED_HEADING}\n- media_player.tv — Телевизор [Зал] = off"


def _entity(hass: HomeAssistant, **options) -> SmartChainConversationEntity:
    """An agent on the Assist path whose model always answers with one word."""

    async def _astream(_messages):
        yield AIMessageChunk(content="Готово")

    client = MagicMock()
    client.astream = _astream
    client.bind_tools = MagicMock(return_value=client)

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "You are a test assistant.",
        CONF_CHAT_HISTORY: True,
        CONF_PROCESS_BUILTIN_SENTENCES: False,
        CONF_LLM_HASS_API: "assist",
        CONF_ALLOWED_TOOLS: [],
        CONF_DYNAMIC_ENTITY_CONTEXT: True,
        CONF_DYNAMIC_CONTEXT_ON_ASSIST: True,
        **options,
    }
    entry.runtime_data = client
    entry.subentries = {}
    ent = SmartChainConversationEntity(entry)
    ent.hass = hass
    return ent


def _input(text: str, extra: str | None = None) -> ConversationInput:
    return ConversationInput(
        text=text,
        context=Context(),
        conversation_id="conv-scope",
        device_id=None,
        satellite_id=None,
        language="ru",
        agent_id="test_agent",
        extra_system_prompt=extra,
    )


def _fresh_log(hass: HomeAssistant) -> ChatLog:
    return ChatLog(hass, "conv-scope", content=[SystemContent(content="")])


def _next_turn(chat_log: ChatLog) -> ChatLog:
    """What `async_get_chat_log` hands the next turn of the same conversation.

    `chat_log.py:106` — the content list is copied, every other field, and so
    `extra_system_prompt`, comes along untouched.
    """
    return replace(chat_log, content=chat_log.content.copy())


async def _run(ent, chat_log: ChatLog, text: str, extra: str | None = None):
    chat_log.content.append(UserContent(content=text))
    return await ent._async_handle_message(_input(text, extra), chat_log)


async def test_the_block_from_turn_one_does_not_reach_turn_two(hass: HomeAssistant) -> None:
    """Turn 2 asks about nothing in the house and must be told about nothing."""
    ent = _entity(hass)
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock(side_effect=[BLOCK_ONE, ""])):
        await _run(ent, log_one, "включи свет на кухне")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "расскажи анекдот")

    prompt = log_two.content[0].content
    assert _RETRIEVED_HEADING not in prompt, (
        "turn 2 retrieved nothing, so it is being shown turn 1's entities and"
        f" their turn-1 states:\n{prompt}"
    )
    assert "light.kitchen" not in prompt


async def test_the_stale_block_is_gone_from_the_chat_log_field_itself(
    hass: HomeAssistant,
) -> None:
    """Not just absent from this prompt — gone from what HA would re-use.

    Scrubbing only the rendered prompt would leave the field loaded and the
    third turn would inherit the same block.
    """
    ent = _entity(hass)
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock(side_effect=[BLOCK_ONE, ""])):
        await _run(ent, log_one, "включи свет на кухне")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "расскажи анекдот")

    assert _RETRIEVED_HEADING not in (log_two.extra_system_prompt or "")


async def test_turn_two_gets_its_own_block_not_turn_ones(hass: HomeAssistant) -> None:
    """The block still arrives — the reset must not disable the feature."""
    ent = _entity(hass)
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock(side_effect=[BLOCK_ONE, BLOCK_TWO])):
        await _run(ent, log_one, "включи свет на кухне")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "что с телевизором")

    prompt = log_two.content[0].content
    assert "media_player.tv" in prompt
    assert "light.kitchen" not in prompt, "turn 1's entity is still in turn 2's prompt"


async def test_the_users_own_extra_prompt_keeps_home_assistants_stickiness(
    hass: HomeAssistant,
) -> None:
    """The narrow half of the fix.

    HA deliberately remembers `extra_system_prompt` so a caller can set it once
    for a session (`chat_log.py:753`). Clearing the field wholesale to evict
    our block would take the user's instruction with it — a stale block traded
    for a lost one. Turn 2 supplies no extra prompt of its own and must still
    be under "Будь краток."
    """
    ent = _entity(hass)
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock(side_effect=[BLOCK_ONE, ""])):
        await _run(ent, log_one, "включи свет на кухне", extra="Будь краток.")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "расскажи анекдот")

    assert "Будь краток." in log_two.content[0].content
    assert log_two.extra_system_prompt == "Будь краток."


async def test_a_new_extra_prompt_on_turn_two_replaces_the_old_one(
    hass: HomeAssistant,
) -> None:
    """Still HA's rule: a caller that supplies one this turn overrides the kept one."""
    ent = _entity(hass)
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock(side_effect=[BLOCK_ONE, ""])):
        await _run(ent, log_one, "включи свет на кухне", extra="Будь краток.")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "расскажи анекдот", extra="Отвечай подробно.")

    assert log_two.extra_system_prompt == "Отвечай подробно."
    assert "Будь краток." not in log_two.content[0].content


async def test_with_the_feature_off_the_field_is_left_exactly_as_ha_left_it(
    hass: HomeAssistant,
) -> None:
    """Nothing of ours goes in, so nothing of ours may come out either."""
    ent = _entity(hass, **{CONF_DYNAMIC_CONTEXT_ON_ASSIST: False})
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock()) as build:
        await _run(ent, log_one, "включи свет на кухне", extra="Будь краток.")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "расскажи анекдот")

    build.assert_not_called()
    assert log_two.extra_system_prompt == "Будь краток."
    assert "Будь краток." in log_two.content[0].content
