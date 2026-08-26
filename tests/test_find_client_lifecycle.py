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
