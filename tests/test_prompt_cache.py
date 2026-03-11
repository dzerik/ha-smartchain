"""Tests for SmartChain prompt caching."""

import time
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant

from custom_components.smartchain.const import CONF_ENGINE, ID_GIGACHAT
from custom_components.smartchain.conversation import (
    PROMPT_CACHE_TTL,
    SmartChainConversationEntity,
)


def _make_entity(hass: HomeAssistant):
    """Create a test entity with hass attached."""
    entry = MagicMock()
    entry.entry_id = "test"
    entry.data = {CONF_ENGINE: ID_GIGACHAT}
    entry.options = {}
    entry.runtime_data = MagicMock()
    entry.subentries = {}

    ent = SmartChainConversationEntity(entry)
    ent.hass = hass
    return ent


async def test_prompt_cache_returns_same_result(hass: HomeAssistant):
    """Test that cached prompt returns same result within TTL."""
    entity = _make_entity(hass)
    raw = "Hello {{ ha_name }}"

    result1 = entity._render_prompt_cached(raw)
    result2 = entity._render_prompt_cached(raw)

    assert result1 == result2
    assert entity._prompt_cache_key == raw


async def test_prompt_cache_invalidates_on_different_key(hass: HomeAssistant):
    """Test that cache is invalidated when prompt template changes."""
    entity = _make_entity(hass)

    result1 = entity._render_prompt_cached("Prompt A {{ ha_name }}")
    assert "Prompt A" in result1

    result2 = entity._render_prompt_cached("Prompt B {{ ha_name }}")
    assert "Prompt B" in result2
    assert entity._prompt_cache_key == "Prompt B {{ ha_name }}"


async def test_prompt_cache_invalidates_after_ttl(hass: HomeAssistant):
    """Test that cache expires after TTL and re-renders."""
    entity = _make_entity(hass)
    raw = "Test {{ ha_name }}"

    result1 = entity._render_prompt_cached(raw)
    assert entity._prompt_cache is not None

    # Manually expire the cache
    entity._prompt_cache_time = time.monotonic() - PROMPT_CACHE_TTL - 1

    # Force re-render by calling again (template re-evaluates)
    result2 = entity._render_prompt_cached(raw)

    # Cache should be refreshed (new timestamp)
    assert (time.monotonic() - entity._prompt_cache_time) < 1.0
    assert result1 == result2  # Same prompt, same render


async def test_prompt_cache_initially_empty(hass: HomeAssistant):
    """Test that cache starts empty."""
    entity = _make_entity(hass)
    assert entity._prompt_cache is None
    assert entity._prompt_cache_key is None
