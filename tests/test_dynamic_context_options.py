"""The three dynamic-context options reach the subentry form and its data."""

import json
from pathlib import Path

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

_COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "smartchain"
_TRANSLATION_FILES = {
    "strings": _COMPONENT_DIR / "strings.json",
    "en": _COMPONENT_DIR / "translations" / "en.json",
    "ru": _COMPONENT_DIR / "translations" / "ru.json",
}
_NEW_DYNAMIC_CONTEXT_KEYS = {
    CONF_DYNAMIC_ENTITY_CONTEXT,
    CONF_DYNAMIC_CONTEXT_PRESET,
    CONF_DYNAMIC_CONTEXT_ON_ASSIST,
}


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


def test_the_new_options_have_labels_everywhere_they_can_render() -> None:
    """Pin translation-key parity for the fields this subsystem added.

    ``subentry_schema`` is shared by the conversation subentry form
    (``config_subentries.conversation.step.{user,reconfigure}.data``) and the
    entry-level options form (``options.step.settings.data``). All three new
    dynamic-context keys must carry a label in all three translation files,
    in all three of those blocks — otherwise a user sees a raw key instead
    of a label wherever the shared schema is rendered.

    Narrowed to the keys this subsystem introduces. Two pre-existing fields
    (``allowed_tools``, ``enable_multi_agent_tools``) are also rendered
    conditionally by the same shared schema and already lack labels
    everywhere, in all three files — that gap predates this change and is
    reported separately rather than asserted here, since fixing it is out
    of this subsystem's scope.
    """
    for file_label, path in _TRANSLATION_FILES.items():
        data = json.loads(path.read_text(encoding="utf-8"))
        conv_step = data["config_subentries"]["conversation"]["step"]
        blocks = {
            "conv_user": conv_step["user"]["data"],
            "conv_reconfigure": conv_step["reconfigure"]["data"],
            "options_settings": data["options"]["step"]["settings"]["data"],
        }
        for block_name, block in blocks.items():
            missing = _NEW_DYNAMIC_CONTEXT_KEYS - block.keys()
            assert not missing, f"{file_label}.{block_name} is missing labels for {missing}"
