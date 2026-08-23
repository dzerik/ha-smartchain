"""The retrieved block, opt-in, on the Assist path.

Home Assistant's own `llm_hass_api` handling already injects its exposed
entity list and control tools, so this path never adds the skeleton — only
the semantic hits a name-based exposure list does not surface. Off by
default, and `user_input.extra_system_prompt` is the user's own text: when
the option is off or the retrieval yields nothing, it must reach the caller
completely unchanged, not overwritten and not coerced to a different falsy
value.

Composition is driven directly through `_build_extra_system_prompt`, the
method extracted out of `_async_handle_message` for exactly this purpose —
mirroring `_build_system_prompt` from the non-Assist path.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.conversation import ConversationInput
from homeassistant.core import Context, HomeAssistant

from custom_components.smartchain.const import (
    CONF_DYNAMIC_CONTEXT_ON_ASSIST,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
)
from custom_components.smartchain.conversation import SmartChainConversationEntity
from custom_components.smartchain.tools.memory.entity_context import _RETRIEVED_HEADING
from custom_components.smartchain.tools.memory.entity_filter import EntityCandidate

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

_BUILD_RETRIEVED = "custom_components.smartchain.conversation.build_retrieved_context"
_RESOLVE_CANDIDATES = "custom_components.smartchain.tools.memory.entity_context.resolve_candidates"
_RANK_ENTITIES = "custom_components.smartchain.tools.memory.entity_context.rank_entities"


def _make_entity(hass: HomeAssistant) -> SmartChainConversationEntity:
    entry = MagicMock()
    entry.entry_id = "test"
    entry.data = {CONF_ENGINE: ID_GIGACHAT}
    entry.options = {}
    entry.runtime_data = MagicMock()
    entry.subentries = {}

    ent = SmartChainConversationEntity(entry)
    ent.hass = hass
    return ent


def _make_input(
    text: str = "Hello, assistant!", extra_system_prompt: str | None = None
) -> ConversationInput:
    return ConversationInput(
        text=text,
        context=Context(),
        conversation_id=None,
        device_id=None,
        satellite_id=None,
        language="ru",
        agent_id="test_agent",
        extra_system_prompt=extra_system_prompt,
    )


def _cand(entity_id: str, name: str, area: str = "Кухня") -> EntityCandidate:
    return EntityCandidate(
        entity_id=entity_id,
        domain=entity_id.split(".")[0],
        name=name,
        area=area,
        device="",
        device_class="",
        aliases=(),
    )


async def test_off_by_default_nothing_is_added(hass: HomeAssistant) -> None:
    entity = _make_entity(hass)
    options: dict = {}  # CONF_DYNAMIC_CONTEXT_ON_ASSIST unset -> default off
    user_input = _make_input(extra_system_prompt="original text")

    with patch(_BUILD_RETRIEVED, new=AsyncMock()) as mock_build:
        result = await entity._build_extra_system_prompt(options, user_input)

    assert result == user_input.extra_system_prompt
    mock_build.assert_not_called()


async def test_off_by_default_none_stays_none(hass: HomeAssistant) -> None:
    """The falsy-but-not-empty-string case: None must stay None, not become ""."""
    entity = _make_entity(hass)
    options: dict = {}
    user_input = _make_input(extra_system_prompt=None)

    with patch(_BUILD_RETRIEVED, new=AsyncMock()):
        result = await entity._build_extra_system_prompt(options, user_input)

    assert result is None


async def test_on_appends_the_retrieved_block(hass: HomeAssistant) -> None:
    entity = _make_entity(hass)
    options = {CONF_DYNAMIC_CONTEXT_ON_ASSIST: True}
    user_input = _make_input(text="чем посушить волосы")
    cand = _cand("switch.socket_hairdryer", "Розетка фена")
    hass.states.async_set("switch.socket_hairdryer", "on", {})

    with (
        patch(_RESOLVE_CANDIDATES, return_value={cand.entity_id: cand}),
        patch(_RANK_ENTITIES, new=AsyncMock(return_value=[cand])),
    ):
        result = await entity._build_extra_system_prompt(options, user_input)

    assert result is not None
    assert result.endswith("switch.socket_hairdryer — Розетка фена [Кухня] = on")
    assert "switch.socket_hairdryer" in result


async def test_pre_existing_extra_system_prompt_survives(hass: HomeAssistant) -> None:
    """Overwriting the user's own extra prompt would be a data-losing bug."""
    entity = _make_entity(hass)
    options = {CONF_DYNAMIC_CONTEXT_ON_ASSIST: True}
    user_input = _make_input(text="потолок", extra_system_prompt="Будь краток.")
    cand = _cand("light.ceiling", "Потолочный")
    hass.states.async_set("light.ceiling", "on", {})

    with (
        patch(_RESOLVE_CANDIDATES, return_value={cand.entity_id: cand}),
        patch(_RANK_ENTITIES, new=AsyncMock(return_value=[cand])),
    ):
        result = await entity._build_extra_system_prompt(options, user_input)

    assert result is not None
    assert "Будь краток." in result
    assert result.index("Будь краток.") < result.index("light.ceiling")


async def test_the_skeleton_is_not_added_on_this_path(hass: HomeAssistant) -> None:
    """HA already listed the entities; the area/domain map must not appear."""
    entity = _make_entity(hass)
    options = {CONF_DYNAMIC_CONTEXT_ON_ASSIST: True}
    user_input = _make_input(text="потолок")
    cand = _cand("light.ceiling", "Потолочный")
    hass.states.async_set("light.ceiling", "on", {})

    # A skeleton cache IS installed, with a distinctive marker: if the
    # skeleton ever leaked onto this path, this is what would prove it.
    skeleton_cache = MagicMock()
    skeleton_cache.get.return_value = "Кухня — light: Потолочный"
    hass.data.setdefault(DOMAIN, {})["entity_skeleton"] = skeleton_cache

    with (
        patch(_RESOLVE_CANDIDATES, return_value={cand.entity_id: cand}),
        patch(_RANK_ENTITIES, new=AsyncMock(return_value=[cand])),
    ):
        result = await entity._build_extra_system_prompt(options, user_input)

    assert result is not None
    assert _RETRIEVED_HEADING in result
    assert "Кухня — light: Потолочный" not in result
    skeleton_cache.get.assert_not_called()


async def test_a_retrieval_failure_leaves_the_extra_prompt_untouched(hass: HomeAssistant) -> None:
    """`build_retrieved_context` is documented to never raise: it signals an

    internal failure by returning "" rather than propagating an exception
    (see `tests/test_entity_context.py::test_a_failing_retrieval_leaves_the_skeleton`
    for the same contract on the sibling path). This exercises the composer
    against that real contract — not against a mock that violates it — the
    same way `_build_system_prompt`'s failure test drives `build_entity_context`
    through a `None`/"" return rather than a raise.
    """
    entity = _make_entity(hass)
    options = {CONF_DYNAMIC_CONTEXT_ON_ASSIST: True}
    user_input = _make_input(text="потолок", extra_system_prompt="Будь краток.")

    with patch(_BUILD_RETRIEVED, new=AsyncMock(return_value="")):
        result = await entity._build_extra_system_prompt(options, user_input)

    assert result == "Будь краток."
