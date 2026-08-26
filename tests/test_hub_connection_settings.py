"""The connection switches belong to the hub, and only to the hub.

v5.1.0 moved `verify_ssl` and `profanity` onto the config entry on the grounds
that they describe a connection to a provider rather than an agent. The move
was only half done: `subentry_schema` went on declaring both for GigaChat, with
a voluptuous `default=`, so every agent save injected them whether or not the
user had ever seen the field — and `client_util.get_client` preferred the
agent's copy over `entry.options`. A hub set to `verify_ssl: False` built its
client with the agent's `True`. The hub form was a placebo.

These tests pin the whole path: the agent form does not offer the fields, the
values already stored on agents are moved onto the entry rather than dropped,
and the value the client is actually constructed with is the hub's.
"""

from unittest.mock import patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.config_flow import subentry_schema
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_PROFANITY,
    CONF_TEMPERATURE,
    CONF_VERIFY_SSL,
    DOMAIN,
    ID_GIGACHAT,
    SUBENTRY_TYPE_CONVERSATION,
    UNIQUE_ID_GIGACHAT,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _entry(hass: HomeAssistant, *, options: dict, agent_data: dict) -> MockConfigEntry:
    """A GigaChat hub with one agent, at the minor version v5.4.0 shipped."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test-credentials"},
        options=options,
        unique_id=UNIQUE_ID_GIGACHAT,
        title="GigaChat",
        minor_version=3,
        subentries_data=[
            {
                "data": agent_data,
                "subentry_type": SUBENTRY_TYPE_CONVERSATION,
                "title": "Agent",
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)
    return entry


def _agent(entry) -> dict:
    return dict(
        next(
            sub
            for sub in entry.subentries.values()
            if sub.subentry_type == SUBENTRY_TYPE_CONVERSATION
        ).data
    )


async def _setup(hass: HomeAssistant, entry) -> dict:
    """Run setup for real down to the GigaChat constructor; return its kwargs."""
    with patch("custom_components.smartchain.client_util.GigaChat") as giga:
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return giga.call_args.kwargs


def test_the_agent_form_does_not_offer_the_connection_switches(hass: HomeAssistant) -> None:
    """The declaration is the whole bug: `vol.Optional(..., default=...)` makes
    voluptuous inject the key into every save, so merely declaring the field
    overrode the hub even for a user who never touched it."""
    fields = {str(key.schema) for key in subentry_schema(hass, UNIQUE_ID_GIGACHAT, {}).schema}
    assert CONF_VERIFY_SSL not in fields
    assert CONF_PROFANITY not in fields

    # And nothing is injected into a save that did not ask for it.
    saved = subentry_schema(hass, UNIQUE_ID_GIGACHAT, {})({CONF_CHAT_MODEL: "GigaChat"})
    assert CONF_VERIFY_SSL not in saved
    assert CONF_PROFANITY not in saved


async def test_the_hub_value_reaches_the_client(hass: HomeAssistant) -> None:
    """The reproduction, inverted. The agent carries the opposite of the hub on
    both keys; the client must be built with the hub's."""
    entry = _entry(
        hass,
        options={CONF_VERIFY_SSL: False, CONF_PROFANITY: True},
        agent_data={
            CONF_CHAT_MODEL: "GigaChat",
            CONF_TEMPERATURE: 0.4,
            CONF_VERIFY_SSL: True,
            CONF_PROFANITY: False,
        },
    )

    passed = await _setup(hass, entry)

    assert passed["verify_ssl_certs"] is False
    assert passed["profanity_check"] is True
    # The agent's names must not reach the constructor under any spelling.
    assert CONF_VERIFY_SSL not in passed
    assert CONF_PROFANITY not in passed


async def test_the_hub_wins_and_the_agents_copy_is_deleted(hass: HomeAssistant, caplog) -> None:
    """The entry already answers the question, so the agent's copy is dead
    configuration — and a disagreement is said out loud, since that is the one
    case where somebody's client changes."""
    entry = _entry(
        hass,
        options={CONF_VERIFY_SSL: False, CONF_PROFANITY: True},
        agent_data={CONF_CHAT_MODEL: "GigaChat", CONF_VERIFY_SSL: True, CONF_PROFANITY: False},
    )

    await _setup(hass, entry)

    assert dict(entry.options) == {CONF_VERIFY_SSL: False, CONF_PROFANITY: True}
    agent = _agent(entry)
    assert CONF_VERIFY_SSL not in agent
    assert CONF_PROFANITY not in agent
    assert entry.minor_version == 4
    assert "is what is used from now on" in caplog.text


async def test_an_agent_value_is_lifted_onto_a_hub_that_has_none(hass: HomeAssistant) -> None:
    """The one case where removing the field could have changed a working
    install: the agent's value *was* what the client was built with. It moves
    up to the connection rather than being dropped, so the client is built the
    same way it was before the upgrade."""
    entry = _entry(
        hass,
        options={},
        agent_data={CONF_CHAT_MODEL: "GigaChat", CONF_VERIFY_SSL: True, CONF_PROFANITY: True},
    )

    passed = await _setup(hass, entry)

    assert dict(entry.options) == {CONF_VERIFY_SSL: True, CONF_PROFANITY: True}
    assert _agent(entry) == {CONF_CHAT_MODEL: "GigaChat"}
    # Which is the point of promoting it: `True` is not the default for either.
    assert passed["verify_ssl_certs"] is True
    assert passed["profanity_check"] is True


async def test_a_stale_agent_value_reaching_get_client_is_inert(hass: HomeAssistant) -> None:
    """The migration deletes the agent's copy, so nothing should put these keys
    in `common_args` any more. Belt and braces for the copy that survives
    anyway — hand-edited storage, an old backup restored over the top: whatever
    arrives here is discarded, not preferred, and not handed to GigaChat under
    a name it does not know."""
    from custom_components.smartchain.client_util import get_client

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test-credentials"},
        options={CONF_VERIFY_SSL: False, CONF_PROFANITY: True},
        unique_id=UNIQUE_ID_GIGACHAT,
    )
    entry.add_to_hass(hass)

    with patch("custom_components.smartchain.client_util.GigaChat") as giga:
        await get_client(
            hass,
            ID_GIGACHAT,
            entry,
            {"model": "GigaChat", CONF_VERIFY_SSL: True, CONF_PROFANITY: False},
        )

    passed = giga.call_args.kwargs
    assert passed["verify_ssl_certs"] is False
    assert passed["profanity_check"] is True
    assert CONF_VERIFY_SSL not in passed
    assert CONF_PROFANITY not in passed


async def test_a_provider_with_no_connection_settings_is_untouched(hass: HomeAssistant) -> None:
    """`CONNECTION_KEYS` is empty for every provider but GigaChat, so the
    migration must be a no-op there rather than reaching for names it does not
    own."""
    from custom_components.smartchain.const import ID_OPENAI

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sk-test"},
        options={},
        unique_id="OpenAI",
        title="OpenAI",
        minor_version=3,
        subentries_data=[
            {
                "data": {CONF_CHAT_MODEL: "gpt-4o", CONF_VERIFY_SSL: True},
                "subentry_type": SUBENTRY_TYPE_CONVERSATION,
                "title": "Agent",
                "unique_id": None,
            }
        ],
    )
    entry.add_to_hass(hass)

    with patch("custom_components.smartchain.client_util.ChatOpenAI"):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert dict(entry.options) == {}
    assert _agent(entry) == {CONF_CHAT_MODEL: "gpt-4o", CONF_VERIFY_SSL: True}
    assert entry.minor_version == 4


async def test_toggling_verify_ssl_refetches_the_model_list(hass: HomeAssistant):
    """A hub switch that feeds the fetch must invalidate what the fetch cached.

    Verify SSL began reaching the GigaChat model listing in v5.4.11. That made
    the panel's per-entry model cache newly wrong rather than merely stale:
    nothing invalidated it but an explicit Refresh models, so someone whose
    network requires certificate checking would turn the switch on, reopen the
    panel and be served the list cached from the connection that was failing —
    the switch looking broken rather than applied.
    """
    from custom_components.smartchain.websocket_api import _models_for

    entry = _entry(hass, options={CONF_VERIFY_SSL: False}, agent_data={})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    fetched: list[bool] = []

    async def fake_fetch(hass_, engine, data, **kwargs):
        fetched.append(data.get(CONF_VERIFY_SSL))
        return ["", "GigaChat-2-Max"]

    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        side_effect=fake_fetch,
    ):
        await _models_for(hass, entry, refresh=False)
        # Warm: a second read must not refetch, or this test could not tell
        # invalidation from an absent cache.
        await _models_for(hass, entry, refresh=False)
        assert fetched == [False]

        hass.config_entries.async_update_entry(entry, options={CONF_VERIFY_SSL: True})
        await hass.async_block_till_done()

        await _models_for(hass, entry, refresh=False)

    assert fetched == [False, True], (
        "the model list was still served from the cache built over the old connection"
    )


async def test_an_agent_save_does_not_throw_the_model_cache_away(hass: HomeAssistant):
    """The other half of the same rule.

    `update_listener` fires for every write to the entry, agent subentries
    included, and an agent's prompt has nothing to do with which models the
    provider serves. Invalidating on all of them would leave the cache barely
    worth having — the panel would pay a network round trip on every click
    between agents, which is the cost the cache exists to avoid.
    """
    from custom_components.smartchain.websocket_api import _models_for

    entry = _entry(hass, options={CONF_VERIFY_SSL: True}, agent_data={})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    calls = 0

    async def fake_fetch(hass_, engine, data, **kwargs):
        nonlocal calls
        calls += 1
        return ["", "GigaChat-2-Max"]

    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        side_effect=fake_fetch,
    ):
        await _models_for(hass, entry, refresh=False)
        assert calls == 1

        subentry = next(iter(entry.subentries.values()))
        hass.config_entries.async_update_subentry(
            entry, subentry, data={CONF_CHAT_MODEL: "GigaChat-2-Max", "prompt": "new prompt"}
        )
        await hass.async_block_till_done()

        await _models_for(hass, entry, refresh=False)

    assert calls == 1, "an agent edit refetched the model list"
