"""Tests for enable_multi_agent_tools opt-in behaviour."""

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENABLE_MULTI_AGENT_TOOLS,
    CONF_ENGINE,
    CRITIQUE_TOOL_NAME,
    DELEGATE_MANY_TOOL_NAME,
    DOMAIN,
    ID_GIGACHAT,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _build_entity_with_options(hass, options: dict, has_siblings: bool):
    """Build an entity with stubbed runtime and sibling list."""
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
    ent = SmartChainConversationEntity(entry, subentry_id="sX", options=options)
    if has_siblings:
        ent._sibling_agents_cache = [{"name": "auditor", "sub_id": "sY"}]
    else:
        ent._sibling_agents_cache = []
    return ent


def _tools_collected_for(entity) -> list[str]:
    """Return the names of tools the entity would expose right now."""
    from custom_components.smartchain.conversation import (
        _collect_multi_agent_tool_names,
    )

    return _collect_multi_agent_tool_names(entity)


async def test_multi_agent_tools_absent_when_option_off(
    hass: HomeAssistant, mock_llm_client
) -> None:
    ent = _build_entity_with_options(
        hass, {CONF_ENABLE_MULTI_AGENT_TOOLS: False}, has_siblings=True
    )
    names = _tools_collected_for(ent)
    assert DELEGATE_MANY_TOOL_NAME not in names
    assert CRITIQUE_TOOL_NAME not in names


async def test_multi_agent_tools_absent_without_siblings(
    hass: HomeAssistant, mock_llm_client
) -> None:
    ent = _build_entity_with_options(
        hass, {CONF_ENABLE_MULTI_AGENT_TOOLS: True}, has_siblings=False
    )
    names = _tools_collected_for(ent)
    assert DELEGATE_MANY_TOOL_NAME not in names
    assert CRITIQUE_TOOL_NAME not in names


async def test_multi_agent_tools_present_when_both_on(hass: HomeAssistant, mock_llm_client) -> None:
    ent = _build_entity_with_options(hass, {CONF_ENABLE_MULTI_AGENT_TOOLS: True}, has_siblings=True)
    names = _tools_collected_for(ent)
    assert DELEGATE_MANY_TOOL_NAME in names
    assert CRITIQUE_TOOL_NAME in names
