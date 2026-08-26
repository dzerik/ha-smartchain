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


async def test_a_retrieving_turn_two_keeps_the_instruction_from_turn_one(
    hass: HomeAssistant,
) -> None:
    """The other half of the same field, and the one the first fix broke.

    The test above only ever runs a turn 2 that retrieves *nothing*: the
    composer returns `None`, HA reads `None` as "keep what you have", and the
    instruction survives no matter what we do. The lossy path is the opposite
    one — a turn that *does* retrieve passes a real string, and HA's
    ``user_extra_system_prompt or self.extra_system_prompt`` then takes it
    instead of the kept instruction, not on top of it. So whatever we hand
    over on a retrieving turn has to carry the instruction itself.

    Turn 2 supplies no `extra_system_prompt` of its own — as callers on the
    second and later turns of a session normally do not — and retrieves. "Будь
    краток." must still be in force.
    """
    ent = _entity(hass)
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock(side_effect=[BLOCK_ONE, BLOCK_TWO])):
        await _run(ent, log_one, "включи свет на кухне", extra="Будь краток.")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "что с телевизором")

    prompt = log_two.content[0].content
    assert "Будь краток." in prompt, (
        "turn 2 retrieved, so the block replaced the session instruction instead"
        f" of joining it:\n{prompt}"
    )
    assert log_two.extra_system_prompt == "Будь краток."


async def test_a_retrieving_turn_two_does_not_carry_turn_ones_block(
    hass: HomeAssistant,
) -> None:
    """Carrying the instruction forward must not carry the block with it.

    The instruction is re-sent every retrieving turn, so the field it is read
    back from has to hold the instruction *alone*. If the composed value were
    stored instead, turn 2 would re-send turn 1's entity ids and their turn-1
    states underneath its own — the exact staleness this module exists to stop,
    only now hidden behind a turn that does produce a fresh block.
    """
    ent = _entity(hass)
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock(side_effect=[BLOCK_ONE, BLOCK_TWO])):
        await _run(ent, log_one, "включи свет на кухне", extra="Будь краток.")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "что с телевизором")

    prompt = log_two.content[0].content
    assert "light.kitchen" not in prompt, f"turn 1's block rode along:\n{prompt}"
    assert prompt.count(_RETRIEVED_HEADING) == 1
    assert _RETRIEVED_HEADING not in (log_two.extra_system_prompt or "")


async def test_a_retrieving_turn_two_shows_its_own_block(hass: HomeAssistant) -> None:
    """Carrying the instruction must not cost turn 2 its own retrieval."""
    ent = _entity(hass)
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock(side_effect=[BLOCK_ONE, BLOCK_TWO])):
        await _run(ent, log_one, "включи свет на кухне", extra="Будь краток.")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "что с телевизором")

    prompt = log_two.content[0].content
    assert "media_player.tv" in prompt, f"turn 2 lost its own block:\n{prompt}"
    assert prompt.index("Будь краток.") < prompt.index("media_player.tv")


async def test_two_retrieving_turns_with_no_instruction_at_all(hass: HomeAssistant) -> None:
    """The common case: nobody ever set an `extra_system_prompt`.

    Nothing of the user's exists to carry, so the field must come back empty —
    not holding the composed block, which is what would let turn 3 inherit
    turn 2's entities.
    """
    ent = _entity(hass)
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock(side_effect=[BLOCK_ONE, BLOCK_TWO])):
        await _run(ent, log_one, "включи свет на кухне")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "что с телевизором")

    prompt = log_two.content[0].content
    assert "media_player.tv" in prompt
    assert "light.kitchen" not in prompt, f"turn 1's block rode along:\n{prompt}"
    assert log_two.extra_system_prompt is None, (
        "nothing of the user's was ever set, so the field must be empty rather"
        f" than holding ours: {log_two.extra_system_prompt!r}"
    )


async def test_a_new_extra_prompt_on_a_non_retrieving_turn_two_replaces_the_old_one(
    hass: HomeAssistant,
) -> None:
    """Still HA's rule, and this pins the line that puts the field back.

    Turn 2 retrieves nothing, so the composer returns
    `user_input.extra_system_prompt` untouched from its early exit and never
    reaches the line that joins an instruction to a block. What is on trial
    here is the *restore*: ``user_input.extra_system_prompt or
    sticky_extra_system_prompt``. Read the other way round it would write the
    turn-1 instruction back over the turn-2 one, and turn 3 would inherit an
    order the caller had already replaced.

    The composer's own copy of that priority is a separate decision on a
    separate line, reached only on a turn that does retrieve; it is guarded by
    the test below.
    """
    ent = _entity(hass)
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock(side_effect=[BLOCK_ONE, ""])):
        await _run(ent, log_one, "включи свет на кухне", extra="Будь краток.")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "расскажи анекдот", extra="Отвечай подробно.")

    assert log_two.extra_system_prompt == "Отвечай подробно."
    assert "Будь краток." not in log_two.content[0].content


async def test_a_new_instruction_on_a_retrieving_turn_two_wins_over_the_kept_one(
    hass: HomeAssistant,
) -> None:
    """The kept instruction is a fallback, not a floor.

    Carrying turn 1's instruction into a retrieving turn is only correct while
    the caller has not spoken again. When turn 2 supplies its own
    `extra_system_prompt`, that is the user changing their standing order, and
    it has to be the one that goes to the model — the composer's
    ``user_input.extra_system_prompt or sticky_user_prompt`` in that order.

    Swap the two and the failure is silent in the worst way: the caller sets a
    new instruction, sees no error, and the model keeps obeying the old one for
    the rest of the session. Nothing in the stored field would show it — the
    restore line writes "Отвечай подробно." there either way — so the evidence
    is only in the prompt turn 2 was actually sent.
    """
    ent = _entity(hass)
    log_one = _fresh_log(hass)

    with patch(_BUILD_RETRIEVED, new=AsyncMock(side_effect=[BLOCK_ONE, BLOCK_TWO])):
        await _run(ent, log_one, "включи свет на кухне", extra="Будь краток.")
        log_two = _next_turn(log_one)
        await _run(ent, log_two, "что с телевизором", extra="Отвечай подробно.")

    prompt = log_two.content[0].content
    assert "Отвечай подробно." in prompt, (
        "turn 2's own instruction never reached the model:\n" + prompt
    )
    assert "Будь краток." not in prompt, (
        f"turn 2 replaced the instruction, but the superseded one is still in force:\n{prompt}"
    )
    assert "media_player.tv" in prompt, "turn 2 lost its own block"
    assert log_two.extra_system_prompt == "Отвечай подробно."


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
