"""`_find_client` must survive config entries that are not loaded.

`async_entries` hands back disabled, never-loaded and failed entries too, and
Home Assistant *deletes* `ConfigEntry.runtime_data` on unload — it is a bare
annotation, not a default. Touching it on such an entry raises AttributeError
out of `smartchain.ask`, `smartchain.analyze_image` and the public
`async_generate_structured` helper, even when another hub is perfectly healthy.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from langchain_core.messages import AIMessage
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain import _find_client
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    CONF_PROMPT,
    DOMAIN,
    ID_GIGACHAT,
    SUBENTRY_TYPE_CONVERSATION,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _client(tag: str) -> MagicMock:
    """A distinguishable stand-in for a LangChain chat client."""
    client = MagicMock(name=tag)
    client.tag = tag
    client.ainvoke = AsyncMock(return_value=AIMessage(content=f"answer from {tag}"))
    return client


async def _setup_entry(hass: HomeAssistant, client, unique_id: str) -> MockConfigEntry:
    """Set up a real config entry carrying one agent, backed by `client`."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test-credentials"},
        options={},
        unique_id=unique_id,
        minor_version=4,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_PROMPT: "You are helpful."},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title=f"Agent {unique_id}",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_find_client_skips_unloaded_entry(hass: HomeAssistant) -> None:
    """An unloaded hub must not hide the loaded one behind an AttributeError."""
    dead, alive = _client("dead"), _client("alive")
    first = await _setup_entry(hass, dead, "GigaChat")
    await _setup_entry(hass, alive, "GigaChat-2")

    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    assert _find_client(hass) is alive


async def test_find_client_by_entity_id_skips_unloaded_entry(hass: HomeAssistant) -> None:
    """The entity_id-routed lookup walks the same entries and must skip them too."""
    dead, alive = _client("dead"), _client("alive")
    first = await _setup_entry(hass, dead, "GigaChat")
    second = await _setup_entry(hass, alive, "GigaChat-2")

    ent_reg = er.async_get(hass)
    agent_ids = [
        ent.entity_id
        for ent in er.async_entries_for_config_entry(ent_reg, second.entry_id)
        if ent.domain == "conversation"
    ]
    assert agent_ids, "expected the second entry to own a conversation agent"

    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    assert _find_client(hass, agent_ids[0]) is alive


async def test_find_client_returns_none_when_nothing_is_loaded(hass: HomeAssistant) -> None:
    """With no loaded entry the contract is None — never an exception.

    `_handle_ask` / `_handle_analyze_image` answer "No SmartChain agent
    available." on a falsy result, and `async_generate_structured` documents
    `Raises: RuntimeError`. Both contracts need the falsy return to happen.
    """
    only = await _setup_entry(hass, _client("dead"), "GigaChat")
    await hass.config_entries.async_unload(only.entry_id)
    await hass.async_block_till_done()

    assert _find_client(hass) is None


async def test_ask_service_answers_gracefully_with_unloaded_entry(hass: HomeAssistant) -> None:
    """The documented graceful answer must actually be reachable."""
    only = await _setup_entry(hass, _client("dead"), "GigaChat")
    await hass.config_entries.async_unload(only.entry_id)
    await hass.async_block_till_done()

    response = await hass.services.async_call(
        DOMAIN, "ask", {"message": "hello"}, blocking=True, return_response=True
    )
    assert response == {"response": "No SmartChain agent available."}


async def test_generate_structured_raises_runtime_error(hass: HomeAssistant) -> None:
    """The public helper's documented `Raises: RuntimeError` must hold."""
    from pydantic import BaseModel

    from custom_components.smartchain.helpers import async_generate_structured

    class Answer(BaseModel):
        text: str

    only = await _setup_entry(hass, _client("dead"), "GigaChat")
    await hass.config_entries.async_unload(only.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(RuntimeError, match="No SmartChain client available"):
        await async_generate_structured(hass, schema=Answer, prompt="hi")


def _agent_entity_id(hass: HomeAssistant, entry: MockConfigEntry, domain: str) -> str:
    """The entity_id the given entry owns in `domain` (conversation / ai_task)."""
    ent_reg = er.async_get(hass)
    ids = [
        ent.entity_id
        for ent in er.async_entries_for_config_entry(ent_reg, entry.entry_id)
        if ent.domain == domain
    ]
    assert ids, f"expected the entry to own a {domain} entity"
    return ids[0]


async def test_named_agent_that_cannot_be_resolved_is_an_error(hass: HomeAssistant) -> None:
    """A named agent that resolves to nothing must never answer as another hub.

    Silently falling through to "first client of the first entry" hands the
    caller a different provider, model and system prompt under the entity_id
    they asked for, with nothing in the answer to say so.
    """
    dead, alive = _client("dead"), _client("alive")
    first = await _setup_entry(hass, dead, "GigaChat")
    await _setup_entry(hass, alive, "GigaChat-2")

    target = _agent_entity_id(hass, first, "conversation")
    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError, match=target):
        _find_client(hass, target)


async def test_unknown_entity_id_is_an_error(hass: HomeAssistant) -> None:
    """An entity_id belonging to nothing at all is a caller error, not a fallback."""
    await _setup_entry(hass, _client("alive"), "GigaChat")

    with pytest.raises(HomeAssistantError, match="conversation.nope"):
        _find_client(hass, "conversation.nope")


async def test_ask_service_reports_an_unresolvable_entity_id(hass: HomeAssistant) -> None:
    """`smartchain.ask` must fail visibly rather than answer from another hub."""
    dead, alive = _client("dead"), _client("alive")
    first = await _setup_entry(hass, dead, "GigaChat")
    await _setup_entry(hass, alive, "GigaChat-2")

    target = _agent_entity_id(hass, first, "conversation")
    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError, match=target):
        await hass.services.async_call(
            DOMAIN,
            "ask",
            {"message": "hello", "entity_id": target},
            blocking=True,
            return_response=True,
        )
    assert alive.ainvoke.await_count == 0


async def test_ai_task_entity_id_routes_to_its_own_client(hass: HomeAssistant) -> None:
    """`ai_task.*` unique_ids carry a suffix — they must resolve, not error.

    `ai_task` entities are registered as `{entry_id}_{subentry_id}_ai_task`,
    which never equals `{entry_id}_{subentry_id}`. Without the suffix the
    lookup misses and answers with whichever client happens to come first.
    """
    first_client, second_client = _client("first"), _client("second")
    await _setup_entry(hass, first_client, "GigaChat")
    second = await _setup_entry(hass, second_client, "GigaChat-2")

    target = _agent_entity_id(hass, second, "ai_task")

    assert _find_client(hass, target) is second_client


async def test_generate_structured_names_the_agent_it_could_not_resolve(
    hass: HomeAssistant,
) -> None:
    """The public helper must not quietly answer with somebody else's model."""
    from pydantic import BaseModel

    from custom_components.smartchain.helpers import async_generate_structured

    class Answer(BaseModel):
        text: str

    alive = _client("alive")
    await _setup_entry(hass, alive, "GigaChat")

    with pytest.raises(RuntimeError, match="conversation.smartchain_ghost"):
        await async_generate_structured(
            hass,
            schema=Answer,
            prompt="hi",
            agent_id="conversation.smartchain_ghost",
        )
    assert alive.ainvoke.await_count == 0


async def test_analyze_image_reports_an_unresolvable_entity_id(hass: HomeAssistant) -> None:
    """`analyze_image` routes through the same lookup and must fail the same way.

    It is the service whose result feeds `sensor.smartchain_last_analysis`, so a
    silent substitution here writes another hub's description of the camera into
    the sensor every automation reads.
    """
    dead, alive = _client("dead"), _client("alive")
    first = await _setup_entry(hass, dead, "GigaChat")
    await _setup_entry(hass, alive, "GigaChat-2")

    target = _agent_entity_id(hass, first, "conversation")
    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    image = MagicMock()
    image.content = b"\xff\xd8\xff\xe0fake_jpeg_data"
    image.content_type = "image/jpeg"

    with (
        patch("custom_components.smartchain.async_get_image", return_value=image),
        pytest.raises(HomeAssistantError, match=target),
    ):
        await hass.services.async_call(
            DOMAIN,
            "analyze_image",
            {
                "message": "what do you see?",
                "camera_entity_id": "camera.front_door",
                "entity_id": target,
            },
            blocking=True,
            return_response=True,
        )
    assert alive.ainvoke.await_count == 0
