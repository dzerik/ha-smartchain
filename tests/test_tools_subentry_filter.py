"""Tests for the allowed_tools subentry filter."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    ALL_TOOLS_SENTINEL,
    CONF_ALLOWED_TOOLS,
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
)
from custom_components.smartchain.tools.model import (
    CustomTool,
    TemplateAction,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _make_tool(name: str) -> CustomTool:
    return CustomTool(
        name=name,
        description="x",
        parameters={"type": "object", "properties": {}},
        action=TemplateAction(value_template="x"),
    )


async def test_allowed_tools_filter_returns_subset(hass: HomeAssistant, mock_llm_client) -> None:
    """When `allowed_tools` is set on a subentry, only those tools are exposed."""
    from custom_components.smartchain.conversation import (
        SmartChainConversationEntity,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = hass.data[DOMAIN]["tools"]
    registry.replace_all([_make_tool("a"), _make_tool("b"), _make_tool("c")])

    ent = SmartChainConversationEntity(
        entry, subentry_id=None, options={CONF_ALLOWED_TOOLS: ["a", "c"]}
    )
    selected = ent._collect_custom_tools(registry)

    assert [t.name for t in selected] == ["a", "c"]


async def test_allowed_tools_absent_returns_all(hass: HomeAssistant, mock_llm_client) -> None:
    """When `allowed_tools` key is absent, all registered tools are exposed."""
    from custom_components.smartchain.conversation import (
        SmartChainConversationEntity,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = hass.data[DOMAIN]["tools"]
    registry.replace_all([_make_tool("a"), _make_tool("b")])

    ent = SmartChainConversationEntity(entry, subentry_id=None, options={})
    selected = ent._collect_custom_tools(registry)
    assert {t.name for t in selected} == {"a", "b"}


async def test_allowed_tools_empty_list_returns_none(hass: HomeAssistant, mock_llm_client) -> None:
    """An explicit empty list means no custom tools are exposed."""
    from custom_components.smartchain.conversation import (
        SmartChainConversationEntity,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = hass.data[DOMAIN]["tools"]
    registry.replace_all([_make_tool("a")])

    ent = SmartChainConversationEntity(entry, subentry_id=None, options={CONF_ALLOWED_TOOLS: []})
    selected = ent._collect_custom_tools(registry)
    assert selected == []


async def test_allowed_tools_sentinel_returns_all(hass: HomeAssistant, mock_llm_client) -> None:
    """`["*"]` (the ALL_TOOLS_SENTINEL) means every tool, same as `allowed is None`.

    This is the escape hatch for the one-way trap: once a user has touched
    the field, selecting the sentinel is the only gesture that gets back to
    "all tools" through the UI.
    """
    from custom_components.smartchain.conversation import (
        SmartChainConversationEntity,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = hass.data[DOMAIN]["tools"]
    registry.replace_all([_make_tool("a"), _make_tool("b"), _make_tool("c")])

    ent = SmartChainConversationEntity(
        entry, subentry_id=None, options={CONF_ALLOWED_TOOLS: [ALL_TOOLS_SENTINEL]}
    )
    selected = ent._collect_custom_tools(registry)
    assert {t.name for t in selected} == {"a", "b", "c"}


async def test_allowed_tools_sentinel_mixed_with_names_still_returns_all(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """The sentinel wins even if real tool names are also present in the list —
    the picker should never produce this combination, but the resolver must
    not silently narrow to the co-selected names if it ever does."""
    from custom_components.smartchain.conversation import (
        SmartChainConversationEntity,
    )

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test"},
        options={},
        unique_id="GigaChat",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = hass.data[DOMAIN]["tools"]
    registry.replace_all([_make_tool("a"), _make_tool("b"), _make_tool("c")])

    ent = SmartChainConversationEntity(
        entry, subentry_id=None, options={CONF_ALLOWED_TOOLS: [ALL_TOOLS_SENTINEL, "a"]}
    )
    selected = ent._collect_custom_tools(registry)
    assert {t.name for t in selected} == {"a", "b", "c"}
