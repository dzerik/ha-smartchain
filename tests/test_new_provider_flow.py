"""Config flow for the providers added by the table."""

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.smartchain.config_flow import ENGINE_SCHEMA
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_ENGINE,
    CONF_SKIP_VALIDATION,
    DOMAIN,
    ID_GROQ,
    ID_LMSTUDIO,
    OPENAI_COMPATIBLE,
    UNIQUE_ID,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def test_every_row_has_a_step_schema():
    for engine in OPENAI_COMPATIBLE:
        assert engine in ENGINE_SCHEMA, engine


def test_every_row_has_a_named_step():
    from custom_components.smartchain.config_flow import ConfigFlow

    for engine in OPENAI_COMPATIBLE:
        assert hasattr(ConfigFlow, f"async_step_{engine}"), engine


async def test_hosted_provider_flow_creates_an_entry(hass, mock_get_client):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_GROQ}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == ID_GROQ

    # The flow calls `validate_client` through the name bound in config_flow's
    # own namespace (`from .client_util import ... validate_client`), so the
    # patch has to target config_flow, not client_util, to take effect.
    with patch("custom_components.smartchain.config_flow.validate_client"):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_API_KEY: "k", CONF_SKIP_VALIDATION: True},
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == UNIQUE_ID[ID_GROQ]
    assert result["data"][CONF_ENGINE] == ID_GROQ


async def test_local_provider_flow_needs_no_api_key(hass, mock_get_client):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_LMSTUDIO}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_BASE_URL: "http://localhost:1234/v1",
            CONF_SKIP_VALIDATION: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_BASE_URL] == "http://localhost:1234/v1"


async def test_local_step_prefills_the_row_default(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ENGINE: ID_LMSTUDIO}
    )
    defaults = {
        key.schema: key.default()
        for key in result["data_schema"].schema
        if getattr(key, "default", None) is not None and callable(key.default)
    }
    assert defaults[CONF_BASE_URL] == OPENAI_COMPATIBLE[ID_LMSTUDIO].default_base_url


def test_every_row_has_translations_in_both_locales():
    import json
    from pathlib import Path

    root = (
        Path(__file__).resolve().parent.parent / "custom_components" / "smartchain" / "translations"
    )
    for locale in ("en", "ru"):
        data = json.loads((root / f"{locale}.json").read_text(encoding="utf-8"))
        steps = data["config"]["step"]
        for engine in OPENAI_COMPATIBLE:
            assert engine in steps, f"{locale}: {engine}"
            assert steps[engine].get("title"), f"{locale}: {engine} title"
            fields = steps[engine].get("data", {})
            for field in ENGINE_SCHEMA[engine].schema:
                assert field.schema in fields, f"{locale}: {engine}.{field.schema}"
