"""A provider's exception text is for the operator, never for the person.

`v4.0.2` decided this for the service path: an exception raised by a provider
client may embed the credential that was rejected, the internal base URL it was
sent to, or a request id, and none of that belongs in something a caller reads.
The service path answered with one fixed sentence and put the detail in the log.

The conversation path did not. `_async_handle_message` interpolated the
exception straight into `async_set_error`, which becomes `async_set_speech` —
so the fragment was written into the conversation history and *spoken aloud* by
whatever satellite asked the question. `_async_generate_data` did the same into
the `HomeAssistantError` an automation trace records.

These tests pin the whole rule at once:

* every path answers with the *same* constant, so there is one text and no
  third copy of it to drift;
* a plausible secret inside the exception reaches none of those surfaces;
* it does reach the log, next to which provider and which operation failed —
  the only reason replacing a specific message with a general one is allowed
  here at all. A generic sentence with nothing in the log would be this
  project's favourite bug: a failure made quieter and harder to diagnose.
"""

import logging
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components import ai_task
from homeassistant.components.conversation import ConversationInput
from homeassistant.components.conversation.chat_log import (
    ChatLog,
    SystemContent,
    UserContent,
)
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from custom_components.smartchain import EVENT_IMAGE_ANALYZED, async_setup
from custom_components.smartchain.ai_task import SmartChainAITaskEntity
from custom_components.smartchain.const import (
    CONF_CHAT_HISTORY,
    CONF_ENGINE,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    DOMAIN,
    GENERIC_LLM_ERROR,
    ID_GIGACHAT,
)
from custom_components.smartchain.conversation import SmartChainConversationEntity

from .conftest import MOCK_GIGACHAT_DATA

# A key-shaped string, an internal host and a request id — the three things a
# provider client puts in an exception message and the three things that must
# not be read out by a speaker.
SECRET = "sk-live-7f3a9b2c1d4e"
PROVIDER_ERROR = (
    f"401 Unauthorized: api key {SECRET} rejected by "
    "https://api.provider.internal/v1/chat (request id req_9f2c)"
)


def _leaked(text: str) -> list[str]:
    """Every part of the provider's message that `text` gives away."""
    return [
        fragment
        for fragment in (SECRET, "api.provider.internal", "req_9f2c", "401 Unauthorized")
        if fragment in text
    ]


def _exploding_client():
    """A client whose stream and single-shot call both fail like a provider."""
    client = MagicMock()

    async def _astream(_messages):
        raise RuntimeError(PROVIDER_ERROR)
        yield  # pragma: no cover - makes the function an async generator

    client.astream = _astream
    client.bind_tools = MagicMock(return_value=client)
    return client


def _conversation_entity(hass: HomeAssistant) -> SmartChainConversationEntity:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "You are a test assistant.",
        CONF_CHAT_HISTORY: True,
        CONF_PROCESS_BUILTIN_SENTENCES: False,
    }
    entry.subentries = {}
    entry.runtime_data = _exploding_client()
    ent = SmartChainConversationEntity(entry)
    ent.hass = hass
    return ent


def _conversation_input() -> ConversationInput:
    return ConversationInput(
        text="Какая температура на кухне?",
        context=Context(),
        conversation_id="conv-secret",
        device_id=None,
        satellite_id=None,
        language="ru",
        agent_id="conversation.smartchain_test",
    )


def _chat_log(hass: HomeAssistant, text: str) -> ChatLog:
    chat_log = ChatLog(hass, "conv-secret")
    chat_log.content = [SystemContent(content=""), UserContent(content=text)]
    chat_log.llm_api = None
    return chat_log


def _ai_task_entity(hass: HomeAssistant) -> SmartChainAITaskEntity:
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {}
    entry.subentries = {}
    entry.runtime_data = _exploding_client()
    ent = SmartChainAITaskEntity(entry)
    ent.hass = hass
    ent._attr_entity_id = "ai_task.smartchain_test"
    return ent


async def test_conversation_speech_never_carries_the_provider_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """What the assistant says back is our sentence, not the provider's."""
    entity = _conversation_entity(hass)

    with caplog.at_level(logging.ERROR, logger="custom_components.smartchain.conversation"):
        result = await entity._async_handle_message(_conversation_input(), _chat_log(hass, "?"))

    assert result.response.error_code is not None, result.response
    speech = result.response.speech.get("plain", {}).get("speech", "")
    assert _leaked(speech) == [], f"the provider's message reached the speech: {speech!r}"
    assert speech == GENERIC_LLM_ERROR


async def test_conversation_logs_the_provider_error_with_provider_and_operation(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The detail the person no longer sees has to be in the log instead."""
    entity = _conversation_entity(hass)

    with caplog.at_level(logging.ERROR, logger="custom_components.smartchain.conversation"):
        await entity._async_handle_message(_conversation_input(), _chat_log(hass, "?"))

    # Asserted in `key=value` form on purpose. A bare `"chat_stream" in text`
    # would also be satisfied by the traceback — the frame is called
    # `_async_handle_message`, but the AI Task test's frame is
    # `_async_generate_data`, and a bare substring there passed a mutation that
    # renamed the operation. The name has to be in the message we wrote.
    assert SECRET in caplog.text, "the detail vanished: quieter *and* undiagnosable"
    assert f"provider={ID_GIGACHAT}" in caplog.text, "the log does not say which provider failed"
    assert "operation=chat_stream" in caplog.text, "the log does not say which operation failed"


async def test_conversation_history_never_carries_the_provider_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing written into the chat log carries it either.

    The chat log is replayed to the model on the next turn and rendered in the
    Assist dialog, so a leak parked there outlives the turn that made it.
    """
    entity = _conversation_entity(hass)
    chat_log = _chat_log(hass, "?")

    with caplog.at_level(logging.ERROR, logger="custom_components.smartchain.conversation"):
        await entity._async_handle_message(_conversation_input(), chat_log)

    for content in chat_log.content:
        text = getattr(content, "content", None)
        if isinstance(text, str):
            assert _leaked(text) == [], f"the provider's message reached the chat log: {text!r}"


async def test_ai_task_error_never_carries_the_provider_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """An AI Task failure is recorded in a trace an automation author reads."""
    entity = _ai_task_entity(hass)
    task = ai_task.GenDataTask(name="test_task", instructions="Сводка", structure=None)

    with (
        caplog.at_level(logging.ERROR, logger="custom_components.smartchain.ai_task"),
        pytest.raises(HomeAssistantError) as excinfo,
    ):
        await entity._async_generate_data(task, _chat_log(hass, "Сводка"))

    message = str(excinfo.value)
    assert _leaked(message) == [], f"the provider's message reached the task error: {message!r}"
    assert message == GENERIC_LLM_ERROR
    assert SECRET in caplog.text, "the detail vanished: quieter *and* undiagnosable"
    assert f"provider={ID_GIGACHAT}" in caplog.text, "the log does not say which provider failed"
    assert "operation=generate_data" in caplog.text, "the log does not say which operation failed"


def _register_failing_entry(hass: HomeAssistant) -> MagicMock:
    """A hub whose single-shot client fails the way a provider does."""
    client = AsyncMock()
    client.ainvoke.side_effect = RuntimeError(PROVIDER_ERROR)

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.domain = DOMAIN
    entry.data = dict(MOCK_GIGACHAT_DATA)
    entry.options = {}
    entry.unique_id = "GigaChat"
    entry.subentries = {}
    entry.runtime_data = client
    hass.config_entries._entries[entry.entry_id] = entry
    return entry


async def test_ask_service_response_never_carries_the_provider_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The path that already behaved answers with the same one constant."""
    await async_setup(hass, {})
    _register_failing_entry(hass)

    with caplog.at_level(logging.ERROR, logger="custom_components.smartchain"):
        result = await hass.services.async_call(
            DOMAIN,
            "ask",
            {"message": "Какая температура на кухне?"},
            blocking=True,
            return_response=True,
        )

    assert _leaked(result["response"]) == []
    assert result["response"] == GENERIC_LLM_ERROR
    assert SECRET in caplog.text


async def test_analyze_image_response_never_carries_the_provider_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The fourth path, and the one whose answer is also fired as an event.

    `analyze_image` writes its result into `smartchain_image_analyzed` and into
    the Last Analysis sensor's state, so a leak here would be readable from any
    template long after the call — it never gets that far, because the failure
    returns before the event is fired.
    """
    await async_setup(hass, {})
    _register_failing_entry(hass)

    image = MagicMock()
    image.content = b"\xff\xd8\xff\xe0fake_jpeg_data"
    image.content_type = "image/jpeg"

    events: list[Any] = []
    # The name comes from the module, not from a literal: a listener attached
    # to a misspelled event would collect nothing and the assertion below would
    # pass without ever having been able to fail.
    hass.bus.async_listen(EVENT_IMAGE_ANALYZED, events.append)

    with (
        caplog.at_level(logging.ERROR, logger="custom_components.smartchain"),
        patch("custom_components.smartchain.async_get_image", return_value=image),
    ):
        result = await hass.services.async_call(
            DOMAIN,
            "analyze_image",
            {"message": "Кто у двери?", "camera_entity_id": "camera.front_door"},
            blocking=True,
            return_response=True,
        )
    await hass.async_block_till_done()

    assert _leaked(result["response"]) == []
    assert result["response"] == GENERIC_LLM_ERROR
    assert events == [], "a failed analysis must not be published as a result"
    assert SECRET in caplog.text


def test_the_generic_sentence_is_written_down_exactly_once() -> None:
    """One constant, one text — a second copy is how the two paths drift apart."""
    package = Path(__file__).resolve().parent.parent / "custom_components" / "smartchain"
    holders = [
        path.relative_to(package).as_posix()
        for path in sorted(package.rglob("*.py"))
        if GENERIC_LLM_ERROR in path.read_text(encoding="utf-8")
    ]
    assert holders == ["const.py"], f"the sentence is spelled out in more than one place: {holders}"
