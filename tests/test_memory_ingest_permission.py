"""Writing a turn into memory is not the same right as reading memory back.

`allowed_tools` decides which tools are bound to the model. `search_memory` is
one of them, so the list decides whether *this agent* may look things up. What
gets written into a store is decided by the store: `ingest_conversation: true`
in `tools.yaml`, documented in `docs/USAGE.md:770` as "every conversation turn
schedules a background task per store that has `ingest_conversation: true`".

Since v5.4.0 the ingest sat behind `memory_enabled`, which is
`MEMORY_TOOL_NAME in builtin_names` — a set already filtered by
`allowed_tools`. Taking `search_memory` away from an agent therefore also
stopped its conversations being recorded, quietly, with the store still
configured to record them and the docs still saying it would.

The two must move apart: ingest happens when there is somewhere to write, and
`allowed_tools` keeps deciding what the model may call.
"""

from unittest.mock import MagicMock

import pytest
from homeassistant.components.conversation import ConversationInput
from homeassistant.components.conversation.chat_log import (
    ChatLog,
    SystemContent,
    UserContent,
)
from homeassistant.core import Context, HomeAssistant
from langchain_core.messages import AIMessageChunk

from custom_components.smartchain.const import (
    CONF_ALLOWED_TOOLS,
    CONF_CHAT_HISTORY,
    CONF_ENGINE,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    DOMAIN,
    HISTORY_TOOL_NAME,
    ID_GIGACHAT,
    MEMORY_TOOL_NAME,
)
from custom_components.smartchain.conversation import SmartChainConversationEntity

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _registry(hass: HomeAssistant, *, ingest_targets: list) -> MagicMock:
    registry = MagicMock()
    registry.__len__.return_value = 1
    registry.describe.return_value = [("notes", "personal notes")]
    registry.entity_store_names.return_value = []
    registry.stores_for_conversation_ingest.return_value = ingest_targets
    hass.data.setdefault(DOMAIN, {})["memory"] = registry
    return registry


def _entity(hass: HomeAssistant, allowed: list[str]) -> SmartChainConversationEntity:
    async def _astream(_messages):
        yield AIMessageChunk(content="Завтра +18 и ясно")

    client = MagicMock()
    client.astream = _astream
    client.bind_tools = MagicMock(return_value=client)

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {CONF_ENGINE: ID_GIGACHAT, "api_key": "test"}
    entry.options = {
        CONF_PROMPT: "You are a test assistant.",
        CONF_CHAT_HISTORY: True,
        CONF_PROCESS_BUILTIN_SENTENCES: False,
        CONF_ALLOWED_TOOLS: allowed,
    }
    entry.runtime_data = client
    entry.subentries = {}
    ent = SmartChainConversationEntity(entry)
    ent.hass = hass
    return ent


def _input() -> ConversationInput:
    return ConversationInput(
        text="Какая завтра погода?",
        context=Context(),
        conversation_id="conv-ingest",
        device_id=None,
        satellite_id=None,
        language="ru",
        agent_id="test_agent",
    )


def _chat_log(hass: HomeAssistant) -> ChatLog:
    return ChatLog(
        hass,
        "conv-ingest",
        content=[SystemContent(content=""), UserContent(content="Какая завтра погода?")],
    )


async def _run(hass: HomeAssistant, ent, chat_log: ChatLog) -> list[str]:
    """Run one turn, returning the names of the background tasks it scheduled."""
    created: list[str] = []
    original = hass.async_create_background_task

    def _record(target, name, *args, **kwargs):
        created.append(name)
        target.close()
        return MagicMock()

    hass.async_create_background_task = _record
    try:
        result = await ent._async_handle_message(_input(), chat_log)
    finally:
        hass.async_create_background_task = original

    assert result.response.error_code is None, result.response
    return created


async def test_an_agent_that_may_not_search_memory_is_still_recorded(
    hass: HomeAssistant,
) -> None:
    """The store said record me; the agent's tool list has no say in that."""
    _registry(hass, ingest_targets=[MagicMock()])
    ent = _entity(hass, allowed=[HISTORY_TOOL_NAME])

    created = await _run(hass, ent, _chat_log(hass))

    assert "smartchain_memory_ingest" in created

    bound = ent._client.bind_tools.call_args[0][0]
    assert MEMORY_TOOL_NAME not in {t["name"] for t in bound}, (
        "precondition: this agent really is denied the read tool"
    )


async def test_reading_stays_denied_while_writing_happens(hass: HomeAssistant) -> None:
    """Untying the two must not hand the agent the lookup tool as a side effect.

    Ingest is a write into a store; `search_memory` is what turns a store into
    something this model can read. If loosening the write gate also bound the
    read tool, an agent deliberately kept away from the household's memory
    would have just been given it back.
    """
    _registry(hass, ingest_targets=[MagicMock()])
    ent = _entity(hass, allowed=[HISTORY_TOOL_NAME])

    await _run(hass, ent, _chat_log(hass))

    bound = ent._client.bind_tools.call_args[0][0]
    assert [t["name"] for t in bound] == [HISTORY_TOOL_NAME]


async def test_nothing_is_scheduled_when_no_store_wants_conversations(
    hass: HomeAssistant,
) -> None:
    """The other half: the right to read does not conjure a place to write.

    An agent that *is* allowed `search_memory` against a store configured with
    `ingest_conversation: false` must still schedule nothing.
    """
    _registry(hass, ingest_targets=[])
    ent = _entity(hass, allowed=[MEMORY_TOOL_NAME])

    created = await _run(hass, ent, _chat_log(hass))

    assert "smartchain_memory_ingest" not in created


async def test_no_memory_subsystem_at_all_schedules_nothing(hass: HomeAssistant) -> None:
    """No registry in `hass.data` — the ingest branch must not reach into `None`."""
    hass.data.setdefault(DOMAIN, {}).pop("memory", None)
    ent = _entity(hass, allowed=[HISTORY_TOOL_NAME])

    created = await _run(hass, ent, _chat_log(hass))

    assert "smartchain_memory_ingest" not in created
