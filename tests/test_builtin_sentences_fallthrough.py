"""The built-in agent writes to our chat log even when it understands nothing.

`process_builtin_sentences` (on by default) hands the sentence to Home
Assistant's own agent first, so "turn on the kitchen light" is matched locally
and never costs a token. When that agent recognises nothing we fall through to
the model — and the assumption underneath was that a turn it did not handle
left no trace.

It does. `DefaultAgent._async_handle_message` appends an `AssistantContent`
unconditionally, after the intent match has already failed, carrying its "I did
not understand" line. And it appends it to *our* log: `async_get_chat_log`
returns the chat log already on the contextvar when the conversation id
matches, which ours does, because we are the caller it was opened by.

So the model is handed a conversation whose last message is from the assistant.
Most providers shrug. GigaChat 3 does not: it answers a payload that carries
`functions` and ends on an assistant turn with

    422 INVALID_PARAMS: functions or thinking_functions should only appeal in
    user, function messages or random role messages

and the person gets an error for a sentence the model never saw. The same
oversight has a mirror image on the branch above it, where the intent *did*
match and we add a second copy of a reply Home Assistant has already stored.
"""

from unittest.mock import MagicMock, patch

import voluptuous as vol
from homeassistant.components.conversation import ConversationResult
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    ChatLog,
    SystemContent,
    UserContent,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import intent, llm
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from custom_components.smartchain.const import (
    CONF_ENGINE,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    ID_GIGACHAT,
)
from custom_components.smartchain.conversation import SmartChainConversationEntity

CONVERSATION_ID = "conv-builtin"
UNDERSTOOD_NOTHING = "Извините, я не понимаю."


def _make_input(text: str):
    from homeassistant.components.conversation import ConversationInput

    return ConversationInput(
        text=text,
        context=Context(),
        conversation_id=CONVERSATION_ID,
        device_id=None,
        satellite_id=None,
        language="ru",
        agent_id="test_agent",
    )


def _make_entity(hass: HomeAssistant, client):
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "You are a test assistant.",
        CONF_PROCESS_BUILTIN_SENTENCES: True,
    }
    entry.runtime_data = client
    ent = SmartChainConversationEntity(entry)
    ent.hass = hass
    return ent


def _make_client(sent: list[list]):
    client = MagicMock()

    async def _astream(messages):
        sent.append(list(messages))
        yield AIMessageChunk(content="Ответ модели.")

    client.astream = MagicMock(side_effect=_astream)
    client.bind_tools = MagicMock(return_value=client)
    return client


def _fake_default_agent(chat_log: ChatLog, *, recognised: bool):
    """Stand in for `DefaultAgent`, copying the part that matters.

    Namely: it appends its reply to the chat log on *every* path, recognised or
    not. Mirrors `default_agent.py`, where the append sits after the branch.
    """
    agent = MagicMock()

    async def _process(user_input):
        response = intent.IntentResponse(language="ru")
        if recognised:
            response.async_set_speech("Включаю свет.")
            response.intent = intent.Intent(None, "test", "HassTurnOn", {}, "", Context(), "ru")
        else:
            response.async_set_speech(UNDERSTOOD_NOTHING)
        chat_log.async_add_assistant_content_without_tools(
            AssistantContent(
                agent_id="conversation.home_assistant",
                content=response.speech.get("plain", {}).get("speech", ""),
            )
        )
        return ConversationResult(response=response, conversation_id=CONVERSATION_ID)

    agent.async_process = _process
    return agent


def _make_chat_log(hass: HomeAssistant, *, with_api: bool) -> ChatLog:
    chat_log = ChatLog(hass, CONVERSATION_ID)
    chat_log.content = [
        SystemContent(content=""),
        UserContent(content="Расскажи анекдот"),
    ]
    if with_api:
        api = MagicMock()
        api.tools = [_AnyTool()]
        chat_log.llm_api = api
    return chat_log


class _AnyTool(llm.Tool):
    name = "HassTurnOn"
    description = "Turn on a device"
    parameters = vol.Schema({vol.Required("entity_id"): str})

    async def async_call(self, hass, tool_input, llm_context):
        return {"success": True}


async def test_the_model_is_never_handed_a_conversation_ending_in_a_reply(
    hass: HomeAssistant,
) -> None:
    """The 422, reproduced without GigaChat.

    Asserting the shape the provider rejects rather than the provider's message:
    a payload carrying tools whose last message is the assistant's. That shape
    is wrong on its own terms — the model is being asked to answer a question
    that already has an answer attached.
    """
    sent: list[list] = []
    ent = _make_entity(hass, _make_client(sent))
    chat_log = _make_chat_log(hass, with_api=False)

    with patch(
        "homeassistant.components.conversation.agent_manager.async_get_agent",
        return_value=_fake_default_agent(chat_log, recognised=False),
    ):
        await ent._async_handle_message(_make_input("Расскажи анекдот"), chat_log)

    assert sent, "the model was never called"
    assert not isinstance(sent[0][-1], AIMessage), (
        "the built-in agent's 'I did not understand' reply is still the last "
        f"message we send: {sent[0][-1]!r}"
    )
    assert isinstance(sent[0][-1], HumanMessage)
    assert sent[0][-1].content == "Расскажи анекдот"


async def test_what_the_builtin_agent_could_not_answer_is_not_left_in_the_log(
    hass: HomeAssistant,
) -> None:
    """The log is the conversation's memory, so a non-answer must not persist.

    Left in place it outlives the turn: every later turn shows the model a reply
    that was never given, and `search_memory` ingests it as one.
    """
    sent: list[list] = []
    ent = _make_entity(hass, _make_client(sent))
    chat_log = _make_chat_log(hass, with_api=False)

    with patch(
        "homeassistant.components.conversation.agent_manager.async_get_agent",
        return_value=_fake_default_agent(chat_log, recognised=False),
    ):
        await ent._async_handle_message(_make_input("Расскажи анекдот"), chat_log)

    assert UNDERSTOOD_NOTHING not in [
        c.content for c in chat_log.content if isinstance(c, AssistantContent)
    ]


async def test_a_sentence_the_builtin_agent_handled_is_stored_once(
    hass: HomeAssistant,
) -> None:
    """The mirror image: Home Assistant already stored it, so we must not again.

    Two identical assistant messages in the log become two identical
    `AIMessage`s in the next request, which reads to the model as the assistant
    having said the same thing twice.
    """
    sent: list[list] = []
    ent = _make_entity(hass, _make_client(sent))
    chat_log = _make_chat_log(hass, with_api=False)

    with patch(
        "homeassistant.components.conversation.agent_manager.async_get_agent",
        return_value=_fake_default_agent(chat_log, recognised=True),
    ):
        result = await ent._async_handle_message(_make_input("Включи свет"), chat_log)

    replies = [c.content for c in chat_log.content if isinstance(c, AssistantContent)]
    assert replies == ["Включаю свет."], f"stored {len(replies)} copies: {replies}"
    assert not sent, "the model was called for a sentence the built-in agent handled"
    assert result.response.speech["plain"]["speech"] == "Включаю свет."
