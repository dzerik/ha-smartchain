"""An AI Task that says it takes attachments has to actually send them.

`SUPPORT_ATTACHMENTS` is a promise made to `ai_task.generate_data`: hand us a
camera snapshot and the model will see it. Two ways that promise was being
broken, both of them only reachable once the flag was declared:

* an image whose file cannot be read is dropped by `_attachment_to_base64`
  (it returns `None` and logs a warning), the request goes out as text alone,
  and the model answers anyway — an invented answer returned as a success to
  an automation with nobody to re-ask;
* reading that file happens on the event loop. `Path.read_bytes` is one of the
  calls `homeassistant/block_async_io.py` intercepts, so in a real HA every AI
  Task carrying a snapshot printed a blocking-call report and held the loop for
  the duration of the read (and of TurboJPEG, when the image is large).

The tests below use a genuinely missing path and a genuinely present file
rather than a stubbed encoder, because the bug lives in what the file system
does, not in what a mock was told to return.
"""

import asyncio
import importlib
from typing import Any

import pytest
from homeassistant.components import ai_task
from homeassistant.components.conversation import Attachment
from homeassistant.components.conversation.chat_log import (
    ChatLog,
    SystemContent,
    UserContent,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from langchain_core.messages import AIMessageChunk

from custom_components.smartchain.ai_task import SmartChainAITaskEntity
from custom_components.smartchain.const import CONF_ENGINE, ID_GIGACHAT

# `custom_components.smartchain.__init__` imports Home Assistant's own
# `ai_task`, so the package attribute of that name is HA's module, not ours.
# Going through `import_module` gets the one we mean to patch.
ai_task_module = importlib.import_module("custom_components.smartchain.ai_task")


class _FakeClient:
    """A chat client that records the messages it was handed."""

    def __init__(self, *chunks: AIMessageChunk) -> None:
        self._chunks = chunks
        self.sent: list[list[Any]] = []

    def bind(self, **kwargs: Any) -> "_FakeClient":
        return self

    async def astream(self, messages):
        self.sent.append(list(messages))
        for chunk in self._chunks:
            yield chunk


def _entity(hass: HomeAssistant, client: _FakeClient) -> SmartChainAITaskEntity:
    class _Entry:
        entry_id = "test_entry"
        data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
        options: dict[str, Any] = {}
        subentries: dict[str, Any] = {}
        runtime_data = client

    entity = SmartChainAITaskEntity(_Entry())
    entity.hass = hass
    entity._attr_entity_id = "ai_task.smartchain_test"
    return entity


def _chat_log(hass: HomeAssistant, attachments: list[Attachment] | None = None) -> ChatLog:
    """The chat log HA builds for a task: the instructions carry the attachments.

    `ai_task/entity.py` appends `UserContent(task.instructions,
    attachments=task.attachments)`, so a test whose attachments live only on
    the task object is testing a request shape that never happens.
    """
    chat_log = ChatLog(hass, "conv-attachments")
    chat_log.content = [
        SystemContent(content="You are a Home Assistant expert."),
        UserContent(content="What is in the fridge?", attachments=attachments),
    ]
    chat_log.llm_api = None
    return chat_log


def _task(attachments: list[Attachment] | None = None) -> ai_task.GenDataTask:
    return ai_task.GenDataTask(
        name="fridge_inventory",
        instructions="What is in the fridge?",
        structure=None,
        attachments=attachments,
    )


def _snapshot(tmp_path) -> Attachment:
    """A camera snapshot that is really on disk."""
    path = tmp_path / "fridge.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0not-really-a-jpeg-but-really-a-file")
    return Attachment(
        media_content_id="media-source://camera/camera.fridge",
        mime_type="image/jpeg",
        path=str(path),
    )


def _missing_snapshot(tmp_path) -> Attachment:
    """A camera snapshot whose file the resolver never produced."""
    return Attachment(
        media_content_id="media-source://camera/camera.fridge",
        mime_type="image/jpeg",
        path=str(tmp_path / "never-written.jpg"),
    )


# --------------------------------------------------------------------------
# An image we could not read must not become a confident answer
# --------------------------------------------------------------------------


async def test_an_unreadable_image_fails_the_task(hass: HomeAssistant, tmp_path) -> None:
    """The model answers happily without the picture — that answer is a guess."""
    client = _FakeClient(AIMessageChunk(content="A fridge full of food."))
    entity = _entity(hass, client)
    attachment = _missing_snapshot(tmp_path)

    with pytest.raises(HomeAssistantError, match="could not read"):
        await entity._async_generate_data(_task([attachment]), _chat_log(hass, [attachment]))


async def test_the_unreadable_image_is_named_in_the_error(hass: HomeAssistant, tmp_path) -> None:
    """An automation's log needs to say *which* snapshot never arrived."""
    client = _FakeClient(AIMessageChunk(content="A fridge full of food."))
    entity = _entity(hass, client)
    attachment = _missing_snapshot(tmp_path)

    with pytest.raises(HomeAssistantError) as err:
        await entity._async_generate_data(_task([attachment]), _chat_log(hass, [attachment]))

    assert "media-source://camera/camera.fridge" in str(err.value)


async def test_the_unreadable_image_never_reaches_the_model(hass: HomeAssistant, tmp_path) -> None:
    """Failing after the answer arrived would still have spent the request.

    The guard has to sit between building the request and sending it, so the
    task that cannot be answered honestly is not billed for a guess.
    """
    client = _FakeClient(AIMessageChunk(content="A fridge full of food."))
    entity = _entity(hass, client)
    attachment = _missing_snapshot(tmp_path)

    with pytest.raises(HomeAssistantError):
        await entity._async_generate_data(_task([attachment]), _chat_log(hass, [attachment]))

    assert client.sent == [], "the model was asked despite the missing image"


async def test_one_missing_image_among_several_still_fails(hass: HomeAssistant, tmp_path) -> None:
    """A partial delivery is the same wrong answer, only harder to notice."""
    client = _FakeClient(AIMessageChunk(content="A fridge full of food."))
    entity = _entity(hass, client)
    attachments = [_snapshot(tmp_path), _missing_snapshot(tmp_path)]

    with pytest.raises(HomeAssistantError, match="could not read"):
        await entity._async_generate_data(_task(attachments), _chat_log(hass, attachments))


async def test_a_readable_image_is_sent_and_the_task_succeeds(
    hass: HomeAssistant, tmp_path
) -> None:
    """The guard must not cost the camera example it exists to protect."""
    client = _FakeClient(AIMessageChunk(content="Milk and eggs."))
    entity = _entity(hass, client)
    attachment = _snapshot(tmp_path)

    result = await entity._async_generate_data(_task([attachment]), _chat_log(hass, [attachment]))

    assert result.data == "Milk and eggs."
    parts = [
        part
        for message in client.sent[-1]
        if isinstance(message.content, list)
        for part in message.content
    ]
    assert any(part.get("type") == "image_url" for part in parts), parts


async def test_a_task_without_attachments_is_untouched(hass: HomeAssistant) -> None:
    """No attachments, no image accounting — the ordinary task still answers."""
    client = _FakeClient(AIMessageChunk(content="Milk and eggs."))
    entity = _entity(hass, client)

    result = await entity._async_generate_data(_task(), _chat_log(hass))

    assert result.data == "Milk and eggs."


# --------------------------------------------------------------------------
# Reading those files must not happen on the event loop
# --------------------------------------------------------------------------


def _record_where_it_runs(monkeypatch) -> list[bool]:
    """Patch the converter to record, per call, whether it ran on the loop.

    A worker thread has no running loop, so `get_running_loop()` raising is
    exactly the evidence that the blocking read was offloaded.
    """
    ran_on_loop: list[bool] = []
    real = ai_task_module._chatlog_to_langchain

    def _spy(*args, **kwargs):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            ran_on_loop.append(False)
        else:
            ran_on_loop.append(True)
        return real(*args, **kwargs)

    monkeypatch.setattr(ai_task_module, "_chatlog_to_langchain", _spy)
    return ran_on_loop


async def test_attachment_reading_is_offloaded_from_the_event_loop(
    hass: HomeAssistant, tmp_path, monkeypatch
) -> None:
    """`Path.read_bytes` on the loop is a reported blocking call in real HA."""
    ran_on_loop = _record_where_it_runs(monkeypatch)
    client = _FakeClient(AIMessageChunk(content="Milk and eggs."))
    entity = _entity(hass, client)
    attachment = _snapshot(tmp_path)

    await entity._async_generate_data(_task([attachment]), _chat_log(hass, [attachment]))

    assert ran_on_loop, "the converter was never called"
    assert not any(ran_on_loop), "attachment conversion ran on the event loop"


async def test_a_turn_without_attachments_is_not_offloaded(
    hass: HomeAssistant, monkeypatch
) -> None:
    """Nothing to read, nothing to hand a worker thread — one thread hop saved."""
    ran_on_loop = _record_where_it_runs(monkeypatch)
    client = _FakeClient(AIMessageChunk(content="Milk and eggs."))
    entity = _entity(hass, client)

    await entity._async_generate_data(_task(), _chat_log(hass))

    assert ran_on_loop == [True], ran_on_loop
