"""The embeddings subentry type appears only for capable providers."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.config_flow import ConfigFlow
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_ANTHROPIC,
    ID_DEEPSEEK,
    ID_GIGACHAT,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _entry(hass: HomeAssistant, engine: str, unique_id: str) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: engine, CONF_API_KEY: "k"},
        options={},
        unique_id=unique_id,
    )
    entry.add_to_hass(hass)
    return entry


async def test_capable_provider_offers_embeddings(hass: HomeAssistant) -> None:
    entry = _entry(hass, ID_GIGACHAT, "GigaChat")
    types = ConfigFlow.async_get_supported_subentry_types(entry)
    assert SUBENTRY_TYPE_CONVERSATION in types
    assert SUBENTRY_TYPE_EMBEDDINGS in types


async def test_deepseek_does_not_offer_embeddings(hass: HomeAssistant) -> None:
    entry = _entry(hass, ID_DEEPSEEK, "DeepSeek")
    types = ConfigFlow.async_get_supported_subentry_types(entry)
    assert SUBENTRY_TYPE_CONVERSATION in types
    assert SUBENTRY_TYPE_EMBEDDINGS not in types


async def test_anthropic_does_not_offer_embeddings(hass: HomeAssistant) -> None:
    entry = _entry(hass, ID_ANTHROPIC, "Anthropic")
    types = ConfigFlow.async_get_supported_subentry_types(entry)
    assert SUBENTRY_TYPE_EMBEDDINGS not in types


async def test_flow_creates_subentry_with_selected_model(hass: HomeAssistant) -> None:
    entry = _entry(hass, ID_GIGACHAT, "GigaChat")

    with patch(
        "custom_components.smartchain.config_flow.async_fetch_models",
        new_callable=AsyncMock,
        return_value=["", "Embeddings", "EmbeddingsGigaR"],
    ):
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_EMBEDDINGS),
            context={"source": "user"},
        )
        assert result["type"] == "form"
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"name": "GigaChat Embeddings", "model": "Embeddings", "model_user": ""},
        )

    assert result["type"] == "create_entry"
    assert result["title"] == "GigaChat Embeddings"
    assert result["data"]["model"] == "Embeddings"


async def test_custom_model_name_wins_over_selection(hass: HomeAssistant) -> None:
    entry = _entry(hass, ID_GIGACHAT, "GigaChat")

    with patch(
        "custom_components.smartchain.config_flow.async_fetch_models",
        new_callable=AsyncMock,
        return_value=["", "Embeddings"],
    ):
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_EMBEDDINGS),
            context={"source": "user"},
        )
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"name": "Custom", "model": "Embeddings", "model_user": "EmbeddingsGigaR"},
        )

    assert result["data"]["model"] == "EmbeddingsGigaR"


async def test_fetch_is_called_with_embeddings_purpose(hass: HomeAssistant) -> None:
    from custom_components.smartchain.const import CAPABILITY_EMBEDDINGS

    entry = _entry(hass, ID_GIGACHAT, "GigaChat")
    with patch(
        "custom_components.smartchain.config_flow.async_fetch_models",
        new_callable=AsyncMock,
        return_value=["", "Embeddings"],
    ) as fetch:
        await hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_EMBEDDINGS),
            context={"source": "user"},
        )
    assert fetch.await_args.kwargs["purpose"] == CAPABILITY_EMBEDDINGS
