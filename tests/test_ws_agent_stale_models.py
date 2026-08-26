"""An agent whose stored model is not in the list we can fetch right now.

The real user this reproduces: two GigaChat agents on `GigaChat-2-Max` and
`GigaChat-2-Pro`, neither of which the static list has ever heard of. Their
first hour goes wrong when the provider is momentarily unreachable, because
four separate defects compound — the static list is stale, a failed fetch is
substituted for an answer, that substitute is cached as though it were one,
and the save it breaks says `invalid_data: model` and nothing else.
"""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_ENGINE,
    CONF_PROMPT,
    DOMAIN,
    ID_GIGACHAT,
    MODELS_GIGACHAT,
    SUBENTRY_TYPE_CONVERSATION,
    UNIQUE_ID_GIGACHAT,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

STORED_MODEL = "GigaChat-2-Max"
SIBLING_MODEL = "GigaChat-2-Pro"


def _model_list(*names):
    """What `GigaChat.get_models()` returns, shaped as the SDK shapes it."""
    result = MagicMock()
    result.data = [MagicMock(id_=name) for name in names]
    return result


@pytest.fixture
async def entry(hass):
    """A GigaChat hub with the two agents the user actually has."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "creds"},
        unique_id=UNIQUE_ID_GIGACHAT,
        title=UNIQUE_ID_GIGACHAT,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: STORED_MODEL, CONF_PROMPT: "carefully tuned"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title=STORED_MODEL,
                unique_id=None,
            ),
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: SIBLING_MODEL, CONF_PROMPT: "also tuned"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title=SIBLING_MODEL,
                unique_id=None,
            ),
        ],
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    return entry


def _agent(entry, model):
    return next(
        sub
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_TYPE_CONVERSATION and sub.data[CONF_CHAT_MODEL] == model
    )


# --- D1: the static list -----------------------------------------------------


@pytest.mark.parametrize(
    "model",
    ["GigaChat-2", "GigaChat-2-Pro", "GigaChat-2-Max", "GigaChat-3-Ultra"],
)
def test_static_list_knows_the_models_gigachat_serves(model):
    """The fallback list is what the user sees when the provider is unreachable.

    Every name here is one the GigaChat API actually accepts today; the
    first-generation names above them are kept because a stored value must
    never vanish from the list it is validated against.
    """
    assert model in MODELS_GIGACHAT


# --- D2 + D3: a blip must not be cached as an answer -------------------------


async def test_a_failed_fetch_is_retried_not_remembered(hass, hass_ws_client, entry):
    """One blip while the panel opens must not outlive the blip.

    First schema request fails at the transport; the second, with the network
    back, must reach the provider again rather than serve the substitute the
    first one fell back to.
    """
    client = await hass_ws_client(hass)
    agent = _agent(entry, STORED_MODEL)

    giga = MagicMock()
    giga.get_models.side_effect = [
        OSError("connection reset"),
        _model_list("GigaChat-2", SIBLING_MODEL, STORED_MODEL),
    ]

    with patch("custom_components.smartchain.client_util.GigaChat", return_value=giga):
        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/schema",
                "entry_id": entry.entry_id,
                "subentry_id": agent.subentry_id,
            }
        )
        first = await client.receive_json()
        assert first["success"], first

        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/schema",
                "entry_id": entry.entry_id,
                "subentry_id": agent.subentry_id,
            }
        )
        second = await client.receive_json()
        assert second["success"], second

    def options(msg):
        field = next(f for f in msg["result"]["schema"] if f["name"] == CONF_CHAT_MODEL)
        # A model select carries bare strings; a labelled one would carry dicts.
        return [
            option if isinstance(option, str) else option["value"]
            for option in field["selector"]["select"]["options"]
        ]

    # The blip was retried, so the second open carries the fetched list.
    assert giga.get_models.call_count == 2
    assert SIBLING_MODEL in options(second)
    # And even the failed one keeps the agent's own model selectable.
    assert STORED_MODEL in options(first)


# --- D4: the refusal must be a sentence --------------------------------------


async def test_stored_model_stays_editable_while_the_list_is_stale(hass, hass_ws_client, entry):
    """Editing the prompt of an agent whose model we cannot currently list.

    The user touched the prompt, not the model. A save that rejects the model
    they never edited is the dead end; it must save.
    """
    client = await hass_ws_client(hass)
    agent = _agent(entry, STORED_MODEL)

    giga = MagicMock()
    giga.get_models.side_effect = OSError("connection reset")

    with patch("custom_components.smartchain.client_util.GigaChat", return_value=giga):
        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/save",
                "entry_id": entry.entry_id,
                "subentry_id": agent.subentry_id,
                "data": {CONF_CHAT_MODEL: STORED_MODEL, CONF_PROMPT: "a better prompt"},
            }
        )
        msg = await client.receive_json()

    assert msg["success"], msg
    assert entry.subentries[agent.subentry_id].data[CONF_PROMPT] == "a better prompt"
    assert entry.subentries[agent.subentry_id].data[CONF_CHAT_MODEL] == STORED_MODEL


async def test_a_model_in_neither_list_stays_editable(hass, hass_ws_client, entry):
    """The same, for a model the shipped list cannot rescue either.

    `GigaChat-2-Max` is in the static list now, so the test above would pass
    even if the schema never made room for a stored model. This one uses a
    name nothing has heard of — a private deployment, or simply the next model
    Sber ships — which is the case the static list can never cover.
    """
    client = await hass_ws_client(hass)
    agent = _agent(entry, SIBLING_MODEL)
    private = "GigaChat-2-Corp-Internal"
    hass.config_entries.async_update_subentry(
        entry, agent, data={**agent.data, CONF_CHAT_MODEL: private}
    )

    giga = MagicMock()
    giga.get_models.return_value = _model_list("GigaChat-2", STORED_MODEL)

    with patch("custom_components.smartchain.client_util.GigaChat", return_value=giga):
        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/save",
                "entry_id": entry.entry_id,
                "subentry_id": agent.subentry_id,
                "data": {CONF_CHAT_MODEL: private, CONF_PROMPT: "an edited prompt"},
            }
        )
        msg = await client.receive_json()

    assert msg["success"], msg
    saved = entry.subentries[agent.subentry_id].data
    assert saved[CONF_CHAT_MODEL] == private
    assert saved[CONF_PROMPT] == "an edited prompt"


async def test_an_unknown_model_is_refused_in_a_sentence(hass, hass_ws_client, entry):
    """A model that is neither listed nor stored still has to explain itself."""
    client = await hass_ws_client(hass)
    agent = _agent(entry, STORED_MODEL)

    giga = MagicMock()
    giga.get_models.return_value = _model_list("GigaChat-2", SIBLING_MODEL)

    with patch("custom_components.smartchain.client_util.GigaChat", return_value=giga):
        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/save",
                "entry_id": entry.entry_id,
                "subentry_id": agent.subentry_id,
                "data": {CONF_CHAT_MODEL: "GigaChat-9-Imaginary", CONF_PROMPT: "hi"},
            }
        )
        msg = await client.receive_json()

    assert not msg["success"]
    message = msg["error"]["message"]
    assert message.startswith(f"invalid_data: {CONF_CHAT_MODEL}")
    # A sentence after the em dash, not just the field name.
    _, _, sentence = message.partition("—")
    assert len(sentence.split()) > 4, message
