"""`chat_history: false` trims past turns only — never the turn in flight.

The option is documented as "do not send the previous conversation". It was
implemented as "send exactly one system message and one human message", and
that list is rebuilt on every pass of the tool loop. A model that asks for a
tool therefore never sees its own tool call or the tool's result: the second
pass shows it the same question it already answered, so it asks for the same
tool again, and `unresponded_tool_results` (literally `content[-1].role ==
"tool_result"`) never lets the loop break. The light toggles ten times.

These tests drive a real `ChatLog` with a real tool executor and a model stub
that decides from the messages it is handed — not from a call counter — so the
count of executions is the count of times the model was actually shown a
conversation that still lacked the answer.
"""

from unittest.mock import MagicMock

import pytest
import voluptuous as vol
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    ChatLog,
    SystemContent,
    ToolResultContent,
    UserContent,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from custom_components.smartchain.const import (
    CONF_CHAT_HISTORY,
    CONF_ENGINE,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    ID_GIGACHAT,
)
from custom_components.smartchain.conversation import (
    SmartChainConversationEntity,
    _current_turn_content,
)

TOOL_NAME = "HassTurnOn"


def _make_input(text: str):
    """Build a ConversationInput for the turn under test."""
    from homeassistant.components.conversation import ConversationInput

    return ConversationInput(
        text=text,
        context=Context(),
        conversation_id="conv-current-turn",
        device_id=None,
        satellite_id=None,
        language="ru",
        agent_id="test_agent",
    )


def _make_entity(hass: HomeAssistant, client, *, chat_history: bool):
    """Build an entity backed by `client` with history on or off."""
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "You are a test assistant.",
        CONF_CHAT_HISTORY: chat_history,
        CONF_PROCESS_BUILTIN_SENTENCES: False,
    }
    entry.runtime_data = client
    ent = SmartChainConversationEntity(entry)
    ent.hass = hass
    return ent


class _TurnOnTool(llm.Tool):
    """A tool that records every execution, so the test counts real calls."""

    name = TOOL_NAME
    description = "Turn on a device"
    parameters = vol.Schema({vol.Required("entity_id"): str})

    def __init__(self) -> None:
        """Start with an empty execution log."""
        self.calls: list[dict] = []

    async def async_call(self, hass, tool_input, llm_context):
        """Record the call and report success."""
        self.calls.append(dict(tool_input.tool_args))
        return {"success": True}


def _make_llm_api(tool: _TurnOnTool):
    """Return an llm_api stub that really runs the tool it is asked for."""
    api = MagicMock()
    api.tools = [tool]

    async def _call_tool(tool_input):
        return await tool.async_call(None, tool_input, None)

    api.async_call_tool = _call_tool
    return api


def _make_client(sent: list[list]):
    """Return a client whose model answers from the messages it is given.

    It asks for the tool until it can see a `ToolMessage` — i.e. until the
    conversation it is handed actually contains the answer. That is what a real
    model does, and it is the only way a test can tell "the loop ended" from
    "the stub ran out of scripted turns".
    """
    client = MagicMock()

    async def _astream(messages):
        sent.append(list(messages))
        if any(isinstance(m, ToolMessage) for m in messages):
            yield AIMessageChunk(content="Готово, лампа включена.")
            return
        yield AIMessageChunk(
            content="",
            tool_calls=[
                {
                    "id": f"call_{len(sent)}",
                    "name": TOOL_NAME,
                    "args": {"entity_id": "light.bedroom"},
                }
            ],
        )

    client.astream = MagicMock(side_effect=_astream)
    client.bind_tools = MagicMock(return_value=client)
    return client


def _make_chat_log(hass: HomeAssistant, api, *, history: list) -> ChatLog:
    """Build a real ChatLog: past turns, then the user message of this turn."""
    chat_log = ChatLog(hass, "conv-current-turn")
    chat_log.content = [SystemContent(content=""), *history]
    chat_log.llm_api = api
    return chat_log


async def test_history_disabled_runs_the_tool_exactly_once(hass: HomeAssistant) -> None:
    """One request to toggle a light must toggle it once, not MAX_TOOL_ITERATIONS times."""
    tool = _TurnOnTool()
    sent: list[list] = []
    client = _make_client(sent)
    ent = _make_entity(hass, client, chat_history=False)
    chat_log = _make_chat_log(
        hass,
        _make_llm_api(tool),
        history=[UserContent(content="Включи лампу в спальне")],
    )

    try:
        result = await ent._async_handle_message(_make_input("Включи лампу в спальне"), chat_log)
    except HomeAssistantError as err:
        pytest.fail(f"turn ended in an error after {len(tool.calls)} tool executions: {err}")

    assert tool.calls == [{"entity_id": "light.bedroom"}]
    assert result.response.speech["plain"]["speech"] == "Готово, лампа включена."

    # The second pass must show the model its own call and the tool's result —
    # that is what ends the loop.
    assert len(sent) == 2
    second = sent[1]
    assert any(isinstance(m, AIMessage) and m.tool_calls for m in second)
    assert any(isinstance(m, ToolMessage) for m in second)


async def test_history_disabled_still_hides_previous_turns(hass: HomeAssistant) -> None:
    """Trimming the past is the point of the option and must survive the fix."""
    tool = _TurnOnTool()
    sent: list[list] = []
    client = _make_client(sent)
    ent = _make_entity(hass, client, chat_history=False)
    chat_log = _make_chat_log(
        hass,
        _make_llm_api(tool),
        history=[
            UserContent(content="Какая погода вчера?"),
            AssistantContent(agent_id="test", content="Вчера было солнечно."),
            UserContent(content="Включи лампу в спальне"),
        ],
    )

    await ent._async_handle_message(_make_input("Включи лампу в спальне"), chat_log)

    first = sent[0]
    assert [type(m) for m in first] == [SystemMessage, HumanMessage]
    assert first[1].content == "Включи лампу в спальне"
    texts = " ".join(str(m.content) for m in first)
    assert "погода" not in texts
    assert "солнечно" not in texts

    # And the past stays hidden once the tool result arrives.
    second = sent[1]
    texts = " ".join(str(m.content) for m in second)
    assert "погода" not in texts
    assert "солнечно" not in texts


async def test_history_enabled_sends_the_whole_log(hass: HomeAssistant) -> None:
    """Regression guard: the default still sends every past turn."""
    tool = _TurnOnTool()
    sent: list[list] = []
    client = _make_client(sent)
    ent = _make_entity(hass, client, chat_history=True)
    chat_log = _make_chat_log(
        hass,
        _make_llm_api(tool),
        history=[
            UserContent(content="Какая погода вчера?"),
            AssistantContent(agent_id="test", content="Вчера было солнечно."),
            UserContent(content="Включи лампу в спальне"),
        ],
    )

    await ent._async_handle_message(_make_input("Включи лампу в спальне"), chat_log)

    assert tool.calls == [{"entity_id": "light.bedroom"}]
    first = sent[0]
    assert [type(m) for m in first] == [
        SystemMessage,
        HumanMessage,
        AIMessage,
        HumanMessage,
    ]
    assert first[2].content == "Вчера было солнечно."


def test_turn_without_a_user_message_reveals_nothing(hass: HomeAssistant) -> None:
    """No user message means no turn to send — not "send everything".

    The boundary of the turn is the last `UserContent`. With none in the log
    there is nothing the option would be willing to disclose, and falling back
    to the whole log inverts the promise the option makes.
    """
    chat_log = ChatLog(hass, "conv-no-user")
    chat_log.content = [
        SystemContent(content="Ты ассистент."),
        AssistantContent(agent_id="test", content="Секрет из прошлого хода."),
        ToolResultContent(
            agent_id="test",
            tool_call_id="call_old",
            tool_name=TOOL_NAME,
            tool_result={"secret": True},
        ),
    ]

    turn = _current_turn_content(chat_log)

    assert turn == [chat_log.content[0]], f"history leaked: {turn}"


def _make_stubborn_client(sent: list[list]):
    """A model that asks for the tool on every pass, whatever it is shown."""
    client = MagicMock()

    async def _astream(messages):
        sent.append(list(messages))
        yield AIMessageChunk(
            content="",
            tool_calls=[
                {
                    "id": f"call_{len(sent)}",
                    "name": TOOL_NAME,
                    "args": {"entity_id": "light.bedroom"},
                }
            ],
        )

    client.astream = MagicMock(side_effect=_astream)
    client.bind_tools = MagicMock(return_value=client)
    return client


async def test_tool_loop_exhaustion_returns_an_intent_error(hass: HomeAssistant) -> None:
    """Running out of tool iterations must answer, not raise at the user.

    The loop ends with a tool result as the last entry, and HA's
    `async_get_result_from_chat_log` raises `HomeAssistantError` on that. It is
    called outside the try/except that guards the stream, so the exception
    escapes the agent as a traceback.
    """
    tool = _TurnOnTool()
    sent: list[list] = []
    ent = _make_entity(hass, _make_stubborn_client(sent), chat_history=True)
    chat_log = _make_chat_log(
        hass,
        _make_llm_api(tool),
        history=[UserContent(content="Включи лампу в спальне")],
    )

    result = await ent._async_handle_message(_make_input("Включи лампу в спальне"), chat_log)

    assert result.response.error_code is not None, result.response
    assert result.conversation_id == "conv-current-turn"
