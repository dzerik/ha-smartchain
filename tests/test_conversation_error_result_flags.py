"""What the two error exits of a turn are allowed to carry back.

`async_get_result_from_chat_log` builds its result with
`continue_conversation=chat_log.continue_conversation`; the two error exits of
`_async_handle_message` build theirs without it. That reads like a lost flag,
so both exits are pinned here — one because the flag provably cannot be set
where it exits, the other because leaving it unset is a decision.

`ChatLog.continue_conversation` is true only when the last entry is an
assistant message whose text ends in a question mark.

* The exit that answers a `HomeAssistantError` from
  `async_get_result_from_chat_log` is reached *only* when the last entry is not
  an assistant message — that is the single condition HA raises on. The two
  conditions exclude each other, so there is nothing to carry.
* The exit that answers an exception from the stream is reachable with the flag
  set: HA appends the assistant message before it awaits the tool tasks, so a
  tool raising anything other than `HomeAssistantError`/`vol.Invalid` leaves a
  question as the last entry. It still returns false, on purpose — see the test.
"""

from unittest.mock import MagicMock

import voluptuous as vol
from homeassistant.components.conversation import ConversationInput
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    ChatLog,
    SystemContent,
    ToolResultContent,
    UserContent,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import llm
from langchain_core.messages import AIMessageChunk

from custom_components.smartchain.const import (
    CONF_CHAT_HISTORY,
    CONF_ENGINE,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    ID_GIGACHAT,
)
from custom_components.smartchain.conversation import SmartChainConversationEntity

TOOL_NAME = "HassTurnOn"


def _input() -> ConversationInput:
    return ConversationInput(
        text="Включи лампу",
        context=Context(),
        conversation_id="conv-error-flags",
        device_id=None,
        satellite_id=None,
        language="ru",
        agent_id="test_agent",
    )


def _entity(hass: HomeAssistant, client) -> SmartChainConversationEntity:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "You are a test assistant.",
        CONF_CHAT_HISTORY: True,
        CONF_PROCESS_BUILTIN_SENTENCES: False,
    }
    entry.runtime_data = client
    ent = SmartChainConversationEntity(entry)
    ent.hass = hass
    return ent


class _Tool(llm.Tool):
    """A tool that either records the call or blows up in a way HA won't catch."""

    name = TOOL_NAME
    description = "Turn on a device"
    parameters = vol.Schema({vol.Required("entity_id"): str})

    def __init__(self, *, explode: bool = False) -> None:
        """Start with an empty execution log."""
        self.calls: list[dict] = []
        self._explode = explode

    async def async_call(self, hass, tool_input, llm_context):
        """Record the call, then fail if this tool was built to fail."""
        self.calls.append(dict(tool_input.tool_args))
        if self._explode:
            raise RuntimeError("the integration behind this tool is broken")
        return {"success": True}


def _llm_api(tool: _Tool) -> MagicMock:
    api = MagicMock()
    api.tools = [tool]

    async def _call_tool(tool_input):
        return await tool.async_call(None, tool_input, None)

    api.async_call_tool = _call_tool
    return api


def _chat_log(hass: HomeAssistant, tool: _Tool) -> ChatLog:
    chat_log = ChatLog(hass, "conv-error-flags")
    chat_log.content = [SystemContent(content=""), UserContent(content="Включи лампу")]
    chat_log.llm_api = _llm_api(tool)
    return chat_log


def _client(*, text: str, ask_forever: bool):
    """A model that answers with `text` and a tool call, every time it is asked."""
    client = MagicMock()
    calls = {"n": 0}

    async def _astream(_messages):
        calls["n"] += 1
        yield AIMessageChunk(content=text)
        if ask_forever or calls["n"] == 1:
            yield AIMessageChunk(
                content="",
                tool_calls=[
                    {
                        "id": f"call_{calls['n']}",
                        "name": TOOL_NAME,
                        "args": {"entity_id": "light.bedroom"},
                    }
                ],
            )

    client.astream = MagicMock(side_effect=_astream)
    client.bind_tools = MagicMock(return_value=client)
    return client


async def test_the_exhausted_tool_loop_never_had_a_flag_to_lose(hass: HomeAssistant) -> None:
    """The two conditions exclude each other, and this is where that is checked.

    A model asking for a tool forever ends the loop on a tool result. HA raises
    there, and its own flag reads false there, for the same reason: the last
    entry is not an assistant message. Carrying the flag into this exit would
    be code that can only ever copy `False`.
    """
    tool = _Tool()
    ent = _entity(hass, _client(text="Сейчас, ", ask_forever=True))
    chat_log = _chat_log(hass, tool)

    result = await ent._async_handle_message(_input(), chat_log)

    assert result.response.error_code is not None, result.response
    assert isinstance(chat_log.content[-1], ToolResultContent)
    assert chat_log.continue_conversation is False, (
        "HA's own flag is set on an exit that HA refuses to build a result for"
    )
    assert result.continue_conversation is False


async def test_a_turn_broken_by_a_tool_does_not_keep_the_conversation_open(
    hass: HomeAssistant,
) -> None:
    """Here the flag *is* set, and the error exit still refuses to pass it on.

    HA appends the assistant message before awaiting the tool tasks, so a tool
    raising `RuntimeError` leaves "Какую именно лампу?" as the last entry and
    `continue_conversation` true. Passing it on would be wrong twice over: the
    person hears the error text rather than the question, so they would be
    answering something nobody asked; and the log now ends with a tool call
    that has no result, which is exactly the shape providers reject on the next
    request. The turn failed — it does not get to open another one.
    """
    tool = _Tool(explode=True)
    ent = _entity(hass, _client(text="Включаю. Какую именно лампу?", ask_forever=False))
    chat_log = _chat_log(hass, tool)

    result = await ent._async_handle_message(_input(), chat_log)

    last = chat_log.content[-1]
    assert isinstance(last, AssistantContent) and last.content.endswith("?")
    assert chat_log.continue_conversation is True, "precondition: the flag is live here"
    assert not any(isinstance(c, ToolResultContent) for c in chat_log.content), (
        "precondition: the failed tool left its call unanswered"
    )

    assert result.response.error_code is not None, result.response
    assert result.continue_conversation is False
