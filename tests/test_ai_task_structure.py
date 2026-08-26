"""A structured AI Task must actually be structured.

`task.structure` used to be read as a boolean: "the caller wants JSON, so try
`json_loads` on whatever came back". The schema itself never left Home
Assistant — it was not sent to the model in any form, and it was never used to
check the answer. So the documented promise, "the response is validated against
`structure`", was carried by nothing: a model that invented different field
names, or wrapped its JSON in a markdown fence, produced either a silently
wrong dict or a failed task, and a model that happened to emit valid JSON of
the wrong shape was reported as a success.

The consumer is what makes that intolerable. `ai_task.generate_data` answers an
automation, which reads `result.data['items']` and carries on; there is nobody
to re-ask. So these tests pin three things down:

* the schema reaches the model — asserted on the request that was sent, not on
  a mock's call count;
* the answer is run through `task.structure` before it is returned, coercions
  and all;
* an answer that does not fit is an error, never a quieter success.

The structures here are built by `ai_task._validate_structure_fields`, the same
function the `ai_task.generate_data` service uses, so the schema under test is
the object HA really hands us — a `vol.Schema` whose values are *selectors*,
not a hand-written JSON Schema.
"""

import json
from typing import Any

import pytest
from homeassistant.components import ai_task
from homeassistant.components.ai_task import _validate_structure_fields
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
from custom_components.smartchain.const import (
    CONF_ENGINE,
    ID_ANTHROPIC,
    ID_GIGACHAT,
    ID_OLLAMA,
)


class _FakeClient:
    """A chat client that records what it was bound with and what it was sent."""

    def __init__(self, *chunks: AIMessageChunk, bind_raises: Exception | None = None) -> None:
        self._chunks = chunks
        self.bind_kwargs: dict[str, Any] | None = None
        self.sent: list[list[Any]] = []
        self._bind_raises = bind_raises

    def bind(self, **kwargs: Any) -> "_FakeClient":
        if self._bind_raises is not None:
            raise self._bind_raises
        self.bind_kwargs = kwargs
        return self

    async def astream(self, messages):
        self.sent.append(list(messages))
        for chunk in self._chunks:
            yield chunk

    @property
    def prompt_text(self) -> str:
        """Every bit of text in the last request, joined."""
        assert self.sent, "the model was never called"
        return "\n".join(str(message.content) for message in self.sent[-1])


def _entity(hass: HomeAssistant, client: _FakeClient, engine: str) -> SmartChainAITaskEntity:
    """An AI Task entity for `engine` backed by `client`."""

    class _Entry:
        entry_id = "test_entry"
        data = {CONF_ENGINE: engine, "api_key": "test"}
        options: dict[str, Any] = {}
        subentries: dict[str, Any] = {}
        runtime_data = client

    entry = _Entry()
    entry.runtime_data = client
    ent = SmartChainAITaskEntity(entry)
    ent.hass = hass
    ent._attr_entity_id = "ai_task.smartchain_test"
    return ent


def _chat_log(hass: HomeAssistant) -> ChatLog:
    chat_log = ChatLog(hass, "conv-structured")
    chat_log.content = [
        SystemContent(content="You are a Home Assistant expert."),
        UserContent(content="List what is in the fridge"),
    ]
    chat_log.llm_api = None
    return chat_log


def _structure():
    """The fridge structure, built exactly the way the service builds it."""
    return _validate_structure_fields(
        {
            "items": {
                "description": "What is in the fridge",
                "required": True,
                "selector": {"text": {"multiple": True}},
            },
            "restock": {
                "description": "Whether a shop run is needed",
                "required": True,
                "selector": {"boolean": None},
            },
        }
    )


def _task(structure: Any = None, attachments: list[Attachment] | None = None):
    return ai_task.GenDataTask(
        name="fridge_inventory",
        instructions="List what is in the fridge",
        structure=structure,
        attachments=attachments,
    )


_GOOD_JSON = '{"items": ["milk", "eggs"], "restock": "true"}'


# --------------------------------------------------------------------------
# The schema reaches the model
# --------------------------------------------------------------------------


async def test_the_schema_is_in_what_we_send_to_a_prompt_only_provider(
    hass: HomeAssistant,
) -> None:
    """GigaChat has no schema keyword, so the schema has to be in the text.

    Asserted on the messages the client actually received, so a change that
    builds the instruction but forgets to send it fails here.
    """
    client = _FakeClient(AIMessageChunk(content=_GOOD_JSON))
    entity = _entity(hass, client, ID_GIGACHAT)

    await entity._async_generate_data(_task(_structure()), _chat_log(hass))

    prompt = client.prompt_text
    assert '"items"' in prompt
    assert '"restock"' in prompt
    assert '"type": "array"' in prompt
    assert '"type": "boolean"' in prompt
    # `required` is the half of the contract a bare list of field names loses.
    assert '"required"' in prompt


async def test_the_schema_carries_the_field_descriptions(hass: HomeAssistant) -> None:
    """The descriptions are the only prose telling the model what a field means."""
    client = _FakeClient(AIMessageChunk(content=_GOOD_JSON))
    entity = _entity(hass, client, ID_GIGACHAT)

    await entity._async_generate_data(_task(_structure()), _chat_log(hass))

    assert "What is in the fridge" in client.prompt_text
    assert "Whether a shop run is needed" in client.prompt_text


async def test_the_user_instructions_survive_the_added_contract(hass: HomeAssistant) -> None:
    """The response-format block is added to the request, not put in place of it."""
    client = _FakeClient(AIMessageChunk(content=_GOOD_JSON))
    entity = _entity(hass, client, ID_GIGACHAT)

    await entity._async_generate_data(_task(_structure()), _chat_log(hass))

    prompt = client.prompt_text
    assert "List what is in the fridge" in prompt
    assert "You are a Home Assistant expert." in prompt


async def test_ollama_is_given_the_schema_natively(hass: HomeAssistant) -> None:
    """Ollama takes a JSON Schema in `format`, so it gets one there.

    The whole schema is asserted, not just its presence: a binding that sent
    an empty object or the string "json" would constrain nothing.
    """
    client = _FakeClient(AIMessageChunk(content=_GOOD_JSON))
    entity = _entity(hass, client, ID_OLLAMA)

    await entity._async_generate_data(_task(_structure()), _chat_log(hass))

    assert client.bind_kwargs is not None, "the schema was never bound to the client"
    sent_schema = client.bind_kwargs["format"]
    assert sent_schema["type"] == "object"
    assert set(sent_schema["properties"]) == {"items", "restock"}
    assert sent_schema["properties"]["items"] == {
        "type": "array",
        "items": {"type": "string"},
        "description": "What is in the fridge",
    }
    assert sorted(sent_schema["required"]) == ["items", "restock"]


async def test_the_natively_bound_schema_is_not_also_pasted_into_the_prompt(
    hass: HomeAssistant,
) -> None:
    """One contract, one place. The provider enforces it; the prompt stays clean."""
    client = _FakeClient(AIMessageChunk(content=_GOOD_JSON))
    entity = _entity(hass, client, ID_OLLAMA)

    await entity._async_generate_data(_task(_structure()), _chat_log(hass))

    assert '"type": "array"' not in client.prompt_text


async def test_a_provider_with_no_schema_keyword_is_never_bound(hass: HomeAssistant) -> None:
    """Anthropic has no such keyword; sending one would be a request error."""
    client = _FakeClient(AIMessageChunk(content=_GOOD_JSON))
    entity = _entity(hass, client, ID_ANTHROPIC)

    await entity._async_generate_data(_task(_structure()), _chat_log(hass))

    assert client.bind_kwargs is None
    assert '"type": "array"' in client.prompt_text


async def test_a_refused_native_binding_falls_back_to_the_prompt(hass: HomeAssistant) -> None:
    """An Ollama client too old for a schema in `format` must still finish the task."""
    client = _FakeClient(
        AIMessageChunk(content=_GOOD_JSON),
        bind_raises=TypeError("unexpected keyword argument 'format'"),
    )
    entity = _entity(hass, client, ID_OLLAMA)

    result = await entity._async_generate_data(_task(_structure()), _chat_log(hass))

    assert client.bind_kwargs is None
    assert '"type": "array"' in client.prompt_text
    assert result.data == {"items": ["milk", "eggs"], "restock": True}


async def test_an_unstructured_task_gets_no_response_format_block(hass: HomeAssistant) -> None:
    """A free-text task must not be told to answer in JSON."""
    client = _FakeClient(AIMessageChunk(content="Milk and eggs."))
    entity = _entity(hass, client, ID_GIGACHAT)

    result = await entity._async_generate_data(_task(), _chat_log(hass))

    assert result.data == "Milk and eggs."
    assert "JSON Schema" not in client.prompt_text
    assert client.bind_kwargs is None


# --------------------------------------------------------------------------
# The answer is validated
# --------------------------------------------------------------------------


async def test_the_returned_data_went_through_the_structure(hass: HomeAssistant) -> None:
    """`restock` left the model as the string "true" and comes back as a bool.

    Only running `task.structure(data)` can do that, so this fails the moment
    the validation step is dropped or reduced to a shape check.
    """
    client = _FakeClient(AIMessageChunk(content=_GOOD_JSON))
    entity = _entity(hass, client, ID_GIGACHAT)

    result = await entity._async_generate_data(_task(_structure()), _chat_log(hass))

    assert result.data == {"items": ["milk", "eggs"], "restock": True}
    assert result.data["restock"] is True


async def test_a_missing_required_field_fails_the_task(hass: HomeAssistant) -> None:
    """Valid JSON of the wrong shape is the failure mode with no other guard."""
    client = _FakeClient(AIMessageChunk(content='{"items": ["milk"]}'))
    entity = _entity(hass, client, ID_GIGACHAT)

    with pytest.raises(HomeAssistantError, match="does not match"):
        await entity._async_generate_data(_task(_structure()), _chat_log(hass))


async def test_an_invented_field_fails_the_task(hass: HomeAssistant) -> None:
    """The automation reads the keys it asked for; an extra one means a wrong answer."""
    client = _FakeClient(
        AIMessageChunk(content='{"items": ["milk"], "restock": false, "aisle": "3"}')
    )
    entity = _entity(hass, client, ID_GIGACHAT)

    with pytest.raises(HomeAssistantError, match="does not match"):
        await entity._async_generate_data(_task(_structure()), _chat_log(hass))


async def test_a_wrongly_typed_field_fails_the_task(hass: HomeAssistant) -> None:
    """A string where a list was asked for cannot be joined by a template."""
    client = _FakeClient(AIMessageChunk(content='{"items": "milk", "restock": false}'))
    entity = _entity(hass, client, ID_GIGACHAT)

    with pytest.raises(HomeAssistantError, match="does not match"):
        await entity._async_generate_data(_task(_structure()), _chat_log(hass))


async def test_the_failure_names_the_field_that_was_wrong(hass: HomeAssistant) -> None:
    """A log line saying only "invalid" costs the reader the debugging session."""
    client = _FakeClient(AIMessageChunk(content='{"items": ["milk"]}'))
    entity = _entity(hass, client, ID_GIGACHAT)

    with pytest.raises(HomeAssistantError, match="restock"):
        await entity._async_generate_data(_task(_structure()), _chat_log(hass))


async def test_a_json_list_where_an_object_was_asked_for_fails(hass: HomeAssistant) -> None:
    """`json_loads` accepts a list happily; the structure does not."""
    client = _FakeClient(AIMessageChunk(content='["milk", "eggs"]'))
    entity = _entity(hass, client, ID_GIGACHAT)

    with pytest.raises(HomeAssistantError):
        await entity._async_generate_data(_task(_structure()), _chat_log(hass))


# --------------------------------------------------------------------------
# The answer is parsed out of what models really send
# --------------------------------------------------------------------------


async def test_a_markdown_fenced_answer_is_parsed(hass: HomeAssistant) -> None:
    """Fencing JSON is the single most common thing a model does to it.

    The fence is the *only* thing that can recover this answer: there is a
    discarded draft object before it, so grabbing the outermost braces spans
    both objects and the backticks between them and parses as nothing. That
    is deliberate — a fenced test whose text a brace-scan could also rescue
    proves nothing about the fence.
    """
    answer = f'Draft: {{"items": ["butter"], "restock": false}}\n\n```json\n{_GOOD_JSON}\n```'
    client = _FakeClient(AIMessageChunk(content=answer))
    entity = _entity(hass, client, ID_GIGACHAT)

    result = await entity._async_generate_data(_task(_structure()), _chat_log(hass))

    # The fenced answer, not the draft that came first.
    assert result.data == {"items": ["milk", "eggs"], "restock": True}


async def test_an_unlabelled_fence_is_parsed(hass: HomeAssistant) -> None:
    """Not every model writes the language after the backticks.

    Trailing prose with a brace in it again leaves the fence as the only
    route to the answer.
    """
    answer = f"```\n{_GOOD_JSON}\n```\n\nNote: {{see the list above}}"
    client = _FakeClient(AIMessageChunk(content=answer))
    entity = _entity(hass, client, ID_GIGACHAT)

    result = await entity._async_generate_data(_task(_structure()), _chat_log(hass))

    assert result.data == {"items": ["milk", "eggs"], "restock": True}


async def test_prose_around_the_json_is_stripped(hass: HomeAssistant) -> None:
    """A sentence of preamble used to turn a perfectly good answer into a failure."""
    client = _FakeClient(
        AIMessageChunk(content=f"Sure! Here is the inventory:\n\n{_GOOD_JSON}\n\nHope that helps.")
    )
    entity = _entity(hass, client, ID_GIGACHAT)

    result = await entity._async_generate_data(_task(_structure()), _chat_log(hass))

    assert result.data == {"items": ["milk", "eggs"], "restock": True}


async def test_text_with_no_json_at_all_still_fails(hass: HomeAssistant) -> None:
    """Recovering more must not turn "no answer" into a recovered one."""
    client = _FakeClient(AIMessageChunk(content="I could not see the fridge."))
    entity = _entity(hass, client, ID_GIGACHAT)

    with pytest.raises(HomeAssistantError, match="Failed to parse"):
        await entity._async_generate_data(_task(_structure()), _chat_log(hass))


async def test_a_fenced_but_broken_object_still_fails(hass: HomeAssistant) -> None:
    """Truncated JSON inside a fence is a failed task, not a partial dict."""
    client = _FakeClient(AIMessageChunk(content='```json\n{"items": ["milk",\n```'))
    entity = _entity(hass, client, ID_GIGACHAT)

    with pytest.raises(HomeAssistantError, match="Failed to parse"):
        await entity._async_generate_data(_task(_structure()), _chat_log(hass))


# --------------------------------------------------------------------------
# Attachments
# --------------------------------------------------------------------------


async def test_the_entity_declares_attachment_support(hass: HomeAssistant) -> None:
    """Without the flag `ai_task.generate_data` refuses every attachment.

    The image path exists — `_chatlog_to_langchain` base64-encodes attachments
    into the request — so the documented camera example only fails on the
    declaration.
    """
    entity = _entity(hass, _FakeClient(), ID_GIGACHAT)

    assert ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS in entity.supported_features
    assert ai_task.AITaskEntityFeature.GENERATE_DATA in entity.supported_features


async def test_an_attachment_we_cannot_send_is_an_error(hass: HomeAssistant) -> None:
    """Only images are encoded into the request; anything else would vanish.

    Declaring attachment support while dropping a PDF on the floor would make
    the task succeed on an answer the model never saw the file for.
    """
    client = _FakeClient(AIMessageChunk(content="Milk and eggs."))
    entity = _entity(hass, client, ID_GIGACHAT)
    task = _task(
        attachments=[
            Attachment(
                media_content_id="media-source://media_source/local/list.pdf",
                mime_type="application/pdf",
                path="/tmp/list.pdf",
            )
        ]
    )

    with pytest.raises(HomeAssistantError, match="application/pdf"):
        await entity._async_generate_data(task, _chat_log(hass))


async def test_an_image_attachment_is_accepted(hass: HomeAssistant) -> None:
    """The guard must not cost the camera snapshot the example is built on."""
    client = _FakeClient(AIMessageChunk(content="Milk and eggs."))
    entity = _entity(hass, client, ID_GIGACHAT)
    task = _task(
        attachments=[
            Attachment(
                media_content_id="media-source://camera/camera.fridge",
                mime_type="image/jpeg",
                path="/tmp/does-not-exist.jpg",
            )
        ]
    )

    result = await entity._async_generate_data(task, _chat_log(hass))

    assert result.data == "Milk and eggs."


# --------------------------------------------------------------------------
# The schema conversion itself
# --------------------------------------------------------------------------


def test_the_structure_converts_only_with_the_selector_serializer() -> None:
    """The values of `task.structure` are selectors, and plain `convert` chokes.

    This is why the conversion cannot be a bare `voluptuous_openapi.convert`:
    without the serializer it does not produce a poorer schema, it raises.
    """
    from voluptuous_openapi import convert

    from custom_components.smartchain.ai_task import _structure_to_json_schema

    with pytest.raises(TypeError):
        convert(_structure())

    schema = _structure_to_json_schema(_structure(), None)
    assert json.loads(json.dumps(schema))["properties"]["restock"]["type"] == "boolean"
