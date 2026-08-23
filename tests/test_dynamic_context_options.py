"""The three dynamic-context options reach the subentry form and its data."""

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_DYNAMIC_CONTEXT_ON_ASSIST,
    CONF_DYNAMIC_CONTEXT_PRESET,
    CONF_DYNAMIC_ENTITY_CONTEXT,
    CONF_ENGINE,
    DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST,
    DEFAULT_DYNAMIC_ENTITY_CONTEXT,
    DOMAIN,
    ENTITY_DEFAULT_PRESET,
    ENTITY_PRESETS,
    ID_GIGACHAT,
    SUBENTRY_TYPE_CONVERSATION,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def test_defaults_are_what_the_spec_says() -> None:
    """On by default; Assist off by default; preset matches subsystem B's."""
    assert DEFAULT_DYNAMIC_ENTITY_CONTEXT is True
    assert DEFAULT_DYNAMIC_CONTEXT_ON_ASSIST is False
    assert ENTITY_DEFAULT_PRESET in ENTITY_PRESETS


async def test_the_three_fields_appear_on_the_conversation_form(
    hass: HomeAssistant, mock_get_client
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_CONVERSATION), context={"source": "user"}
    )

    keys = {str(k.schema) for k in result["data_schema"].schema}
    assert CONF_DYNAMIC_ENTITY_CONTEXT in keys
    assert CONF_DYNAMIC_CONTEXT_PRESET in keys
    assert CONF_DYNAMIC_CONTEXT_ON_ASSIST in keys


async def test_the_options_round_trip_into_subentry_data(
    hass: HomeAssistant, mock_get_client
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_CONVERSATION), context={"source": "user"}
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {
            "model": "",
            "model_user": "custom-model",
            CONF_DYNAMIC_ENTITY_CONTEXT: False,
            CONF_DYNAMIC_CONTEXT_PRESET: "minimal",
            CONF_DYNAMIC_CONTEXT_ON_ASSIST: True,
        },
    )

    assert result["type"] == "create_entry"
    assert result["data"][CONF_DYNAMIC_ENTITY_CONTEXT] is False
    assert result["data"][CONF_DYNAMIC_CONTEXT_PRESET] == "minimal"
    assert result["data"][CONF_DYNAMIC_CONTEXT_ON_ASSIST] is True
