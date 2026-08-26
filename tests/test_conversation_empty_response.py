"""A model that said nothing must reach the person as an error, not as silence.

Until v5.4.13 a stream carrying no text left the chat log ending in something
other than an assistant message, `async_get_result_from_chat_log` raised, and
`_async_handle_message` answered with an intent error. v5.4.13 taught the
stream to always close with a `native`-only delta so a thinking-only turn would
stop killing the generator — and in doing so turned "the model did not answer"
into "the model answered with an empty string": `error_code` `None`, `speech`
`""`, and not one line in the log.

The marker in `native` is the difference between the two. It is written by our
own stream and by nothing else, so keying on it lets a model that deliberately
answered with whitespace through while catching the turn that produced nothing
at all. The empty text alone cannot be that key — it also describes a perfectly
good answer that happens to be blank.

What the person is shown is our own sentence, not a stand-in for the answer:
the model never wrote one, and inventing one here would put words in its mouth.
The traceback that v5.4.13 removed does not come back either — the operator
gets an ERROR line, the person gets a sentence.

These run a real `ChatLog`, because the thing under test is what HA builds out
of our deltas.
"""

import logging
from unittest.mock import MagicMock

from homeassistant.components.conversation import ConversationInput
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    ChatLog,
    SystemContent,
    UserContent,
)
from homeassistant.core import Context, HomeAssistant
from langchain_core.messages import AIMessageChunk

from custom_components.smartchain.const import (
    CONF_ALLOWED_TOOLS,
    CONF_CHAT_HISTORY,
    CONF_ENGINE,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    DOMAIN,
    ID_GIGACHAT,
    MEMORY_TOOL_NAME,
)
from custom_components.smartchain.conversation import (
    EMPTY_RESPONSE_NATIVE,
    SmartChainConversationEntity,
)

THINKING_ONLY = AIMessageChunk(content=[{"type": "thinking", "thinking": "хм", "index": 0}])


def _input() -> ConversationInput:
    return ConversationInput(
        text="Какая завтра погода?",
        context=Context(),
        conversation_id="conv-empty",
        device_id=None,
        satellite_id=None,
        language="ru",
        agent_id="test_agent",
    )


def _entity(
    hass: HomeAssistant, *chunks: AIMessageChunk, options: dict | None = None
) -> SmartChainConversationEntity:
    """An agent whose model replays `chunks` and nothing else."""

    async def _astream(_messages):
        for chunk in chunks:
            yield chunk

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
        **(options or {}),
    }
    entry.runtime_data = client
    ent = SmartChainConversationEntity(entry)
    ent.hass = hass
    return ent


def _chat_log(hass: HomeAssistant) -> ChatLog:
    chat_log = ChatLog(hass, "conv-empty")
    chat_log.content = [SystemContent(content=""), UserContent(content="Какая завтра погода?")]
    chat_log.llm_api = None
    return chat_log


async def test_an_empty_stream_reaches_the_person_as_an_error(hass: HomeAssistant, caplog) -> None:
    """Nothing came back, so the turn fails — visibly, and in the log."""
    ent = _entity(hass, AIMessageChunk(content=""))
    chat_log = _chat_log(hass)

    with caplog.at_level(logging.ERROR, logger="custom_components.smartchain.conversation"):
        result = await ent._async_handle_message(_input(), chat_log)

    assert result.response.error_code is not None, result.response
    assert result.response.speech.get("plain", {}).get("speech"), (
        "the person is told something, not handed an empty bubble"
    )
    assert [r for r in caplog.records if r.levelno >= logging.ERROR], (
        "the operator gets a line to find this by"
    )


async def test_a_thinking_only_stream_reaches_the_person_as_an_error(
    hass: HomeAssistant,
) -> None:
    """Reasoning the person never sees is not an answer to the person."""
    ent = _entity(hass, THINKING_ONLY)
    chat_log = _chat_log(hass)

    result = await ent._async_handle_message(_input(), chat_log)

    assert result.response.error_code is not None, result.response
    last = chat_log.content[-1]
    assert isinstance(last, AssistantContent) and last.native == EMPTY_RESPONSE_NATIVE, (
        "precondition: the turn is the one our stream marked as carrying no response"
    )


async def test_the_error_neither_speaks_for_the_model_nor_shows_a_traceback(
    hass: HomeAssistant, caplog
) -> None:
    """Our sentence, not the model's; an ERROR line, not a stack trace."""
    ent = _entity(hass, AIMessageChunk(content=""))
    chat_log = _chat_log(hass)

    with caplog.at_level(logging.ERROR, logger="custom_components.smartchain.conversation"):
        result = await ent._async_handle_message(_input(), chat_log)

    speech = result.response.speech.get("plain", {}).get("speech", "")
    assert "Traceback" not in speech
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert errors and all(r.exc_info is None for r in errors), (
        "v5.4.13 removed the traceback from this path on purpose"
    )


async def test_a_model_that_answered_with_a_space_still_gets_through(
    hass: HomeAssistant,
) -> None:
    """The marker is the key, not the emptiness of the text.

    A blank-looking answer the model actually wrote carries no marker, and it
    stays a successful turn — the guard reads what our stream recorded, not how
    much the answer weighs.
    """
    ent = _entity(hass, AIMessageChunk(content=" "))
    chat_log = _chat_log(hass)

    result = await ent._async_handle_message(_input(), chat_log)

    assert result.response.error_code is None, result.response
    assert result.response.speech.get("plain", {}).get("speech") == " "


async def test_a_real_answer_is_untouched(hass: HomeAssistant) -> None:
    """The guard must not cost a turn that worked."""
    ent = _entity(hass, AIMessageChunk(content="Завтра +18 и ясно"))
    chat_log = _chat_log(hass)

    result = await ent._async_handle_message(_input(), chat_log)

    assert result.response.error_code is None, result.response
    assert result.response.speech.get("plain", {}).get("speech") == "Завтра +18 и ясно"


async def test_a_turn_with_no_answer_is_not_written_to_memory(hass: HomeAssistant) -> None:
    """Long-term memory does not get to keep a question paired with silence.

    The ingest picks the last assistant message that *has* text, so a turn that
    answered with nothing would be stored against the previous turn's answer —
    a memory of an exchange that never happened.
    """
    registry = MagicMock()
    registry.__len__.return_value = 1
    registry.describe.return_value = [("notes", "personal notes")]
    registry.entity_store_names.return_value = []
    registry.stores_for_conversation_ingest.return_value = [MagicMock()]
    hass.data.setdefault(DOMAIN, {})["memory"] = registry

    ent = _entity(
        hass,
        AIMessageChunk(content=""),
        options={CONF_ALLOWED_TOOLS: [MEMORY_TOOL_NAME]},
    )
    chat_log = _chat_log(hass)
    chat_log.content.insert(1, AssistantContent(agent_id="test_agent", content="Вчера было +10"))

    created: list[str] = []
    original = hass.async_create_background_task

    def _record(target, name, *args, **kwargs):
        created.append(name)
        target.close()
        return MagicMock()

    hass.async_create_background_task = _record
    try:
        result = await ent._async_handle_message(_input(), chat_log)
    finally:
        hass.async_create_background_task = original

    assert result.response.error_code is not None, result.response
    assert "smartchain_memory_ingest" not in created
