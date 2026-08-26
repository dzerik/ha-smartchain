"""One inventory of an agent's tools, and the gates that decide it.

The user's complaint was that an agent shows no choice of the tools connected
to it. Two causes, both real: the `allowed_tools` picker only rendered when the
tools registry was non-empty, and the six built-ins were governed by two
switches elsewhere in the form and four conditions in no form at all. So there
was nowhere to look.

These tests pin the fix: `allowed_tools` is the single control, it lists every
tool the agent could have, and `tools/inventory.py` is the only place that
decides — which is checked here by driving a real message and comparing what
was bound against what the inventory reported.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.conversation.chat_log import (
    AssistantContent,
    SystemContent,
    UserContent,
)
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import Context, HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    ALL_TOOLS_SENTINEL,
    BUILTIN_TOOL_NAMES,
    CONF_ALLOWED_TOOLS,
    CONF_API_KEY,
    CONF_CHAT_HISTORY,
    CONF_CHAT_MODEL,
    CONF_ENABLE_HISTORY_TOOL,
    CONF_ENABLE_MULTI_AGENT_TOOLS,
    CONF_ENGINE,
    CONF_PROCESS_BUILTIN_SENTENCES,
    CONF_PROMPT,
    CRITIQUE_TOOL_NAME,
    DELEGATE_MANY_TOOL_NAME,
    DELEGATE_TOOL_NAME,
    DOMAIN,
    ENTITY_TOOL_NAME,
    HISTORY_TOOL_NAME,
    ID_OPENAI,
    MEMORY_TOOL_NAME,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
    UNIQUE_ID_OPENAI,
)
from custom_components.smartchain.tools.inventory import (
    REASON_NO_ENTITY_STORE,
    REASON_NO_MEMORY_STORE,
    REASON_NO_SIBLINGS,
    REASON_NOT_ALLOWED,
    describe_agent_tools,
)
from custom_components.smartchain.tools.model import CustomTool, TemplateAction

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

AGENT_DATA = {
    CONF_CHAT_MODEL: "gpt-4.1-mini",
    CONF_PROMPT: "You are a test assistant.",
    CONF_CHAT_HISTORY: True,
    CONF_PROCESS_BUILTIN_SENTENCES: False,
}


def _entry(hass, *agents, embeddings=False) -> MockConfigEntry:
    """An entry carrying `agents` conversation subentries, by title."""
    subentries = [
        ConfigSubentryData(
            data={**AGENT_DATA, **data},
            subentry_type=SUBENTRY_TYPE_CONVERSATION,
            title=title,
            unique_id=None,
        )
        for title, data in agents
    ]
    if embeddings:
        subentries.append(
            ConfigSubentryData(
                data={"name": "vectors", "model": "text-embedding-3-small"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="vectors",
                unique_id=None,
            )
        )
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sekrit-key"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=subentries,
        # Already migrated: these subentries are written the v5.4.0 way.
        minor_version=3,
    )
    entry.add_to_hass(hass)
    return entry


def _agent(entry, title: str):
    return next(sub for sub in entry.subentries.values() if sub.title == title)


def _rows(hass, entry, title) -> dict[str, dict]:
    subentry = _agent(entry, title)
    return {
        row["name"]: row
        for row in describe_agent_tools(hass, entry, subentry.subentry_id, subentry.data)
    }


def _memory_registry(hass, *, stores=(), entity_stores=()):
    """Stand in for the memory registry with a chosen shape."""
    registry = MagicMock()
    registry.__len__ = MagicMock(return_value=len(stores))
    registry.entity_store_names = MagicMock(return_value=list(entity_stores))
    hass.data.setdefault(DOMAIN, {})["memory"] = registry
    return registry


# ---------------------------------------------------------------------------
# Every gate, on and off
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", list(BUILTIN_TOOL_NAMES))
async def test_a_built_in_is_off_when_the_list_omits_it(hass: HomeAssistant, name: str) -> None:
    """`allowed_tools` is authoritative for built-ins too.

    Before v5.4.0 every built-in at `conversation.py:382-405` was appended
    unconditionally, so an agent "restricted to one custom tool" still received
    `search_memory`, `search_entities`, `ask_agent` and the history tool while
    the panel told the user otherwise.
    """
    await async_setup_component(hass, DOMAIN, {})
    _memory_registry(hass, stores=["notes"], entity_stores=["home"])
    entry = _entry(
        hass,
        ("Home", {CONF_ALLOWED_TOOLS: [n for n in BUILTIN_TOOL_NAMES if n != name]}),
        ("Auditor", {}),
    )

    rows = _rows(hass, entry, "Home")

    assert rows[name]["enabled"] is False
    assert rows[name]["reason"] == REASON_NOT_ALLOWED
    # ... and the others are on, so the parametrisation is testing this name
    # and not some accident of the fixture.
    for other in BUILTIN_TOOL_NAMES:
        if other != name:
            assert rows[other]["enabled"] is True, other


@pytest.mark.parametrize("name", list(BUILTIN_TOOL_NAMES))
async def test_a_built_in_is_on_when_the_list_names_it(hass: HomeAssistant, name: str) -> None:
    await async_setup_component(hass, DOMAIN, {})
    _memory_registry(hass, stores=["notes"], entity_stores=["home"])
    entry = _entry(hass, ("Home", {CONF_ALLOWED_TOOLS: [name]}), ("Auditor", {}))

    rows = _rows(hass, entry, "Home")

    assert rows[name]["enabled"] is True
    assert rows[name]["reason"] == ""
    assert rows[name]["source"] == "builtin"


async def test_the_inventory_reports_why_a_built_in_is_unavailable(hass: HomeAssistant) -> None:
    """Off because it *cannot* work is a different answer from off because it
    is not allowed, and the list has to say which."""
    await async_setup_component(hass, DOMAIN, {})
    _memory_registry(hass)
    entry = _entry(hass, ("Home", {CONF_ALLOWED_TOOLS: list(BUILTIN_TOOL_NAMES)}))

    rows = _rows(hass, entry, "Home")

    assert rows[DELEGATE_TOOL_NAME]["reason"] == REASON_NO_SIBLINGS
    assert rows[DELEGATE_MANY_TOOL_NAME]["reason"] == REASON_NO_SIBLINGS
    assert rows[CRITIQUE_TOOL_NAME]["reason"] == REASON_NO_SIBLINGS
    assert rows[MEMORY_TOOL_NAME]["reason"] == REASON_NO_MEMORY_STORE
    assert rows[ENTITY_TOOL_NAME]["reason"] == REASON_NO_ENTITY_STORE
    # The history tool has no precondition at all — it is on because it is
    # listed, which is the whole of its gate now.
    assert rows[HISTORY_TOOL_NAME]["enabled"] is True


async def test_an_embeddings_subentry_is_not_a_sibling(hass: HomeAssistant) -> None:
    """`ask_agent` needs another *conversation* agent on the same entry.

    The old `enable_multi_agent_tools` form gate asked whether any entry had
    any two subentries, so an embeddings binding made the switch appear where
    it could not work.
    """
    await async_setup_component(hass, DOMAIN, {})
    entry = _entry(hass, ("Home", {CONF_ALLOWED_TOOLS: list(BUILTIN_TOOL_NAMES)}), embeddings=True)

    rows = _rows(hass, entry, "Home")

    assert rows[DELEGATE_TOOL_NAME]["reason"] == REASON_NO_SIBLINGS
    assert rows[DELEGATE_MANY_TOOL_NAME]["reason"] == REASON_NO_SIBLINGS


async def test_a_second_agent_makes_delegation_available(hass: HomeAssistant) -> None:
    await async_setup_component(hass, DOMAIN, {})
    entry = _entry(
        hass,
        ("Home", {CONF_ALLOWED_TOOLS: list(BUILTIN_TOOL_NAMES)}),
        ("Auditor", {}),
        embeddings=True,
    )

    rows = _rows(hass, entry, "Home")

    assert rows[DELEGATE_TOOL_NAME]["enabled"] is True
    assert rows[DELEGATE_MANY_TOOL_NAME]["enabled"] is True


async def test_ask_agents_and_critique_are_now_separable(hass: HomeAssistant) -> None:
    """One switch used to hold both. Two list entries hold them apart — an
    agent may fan out without also being allowed to ask for a review."""
    await async_setup_component(hass, DOMAIN, {})
    entry = _entry(hass, ("Home", {CONF_ALLOWED_TOOLS: [DELEGATE_MANY_TOOL_NAME]}), ("Aud", {}))

    rows = _rows(hass, entry, "Home")

    assert rows[DELEGATE_MANY_TOOL_NAME]["enabled"] is True
    assert rows[CRITIQUE_TOOL_NAME]["enabled"] is False


# ---------------------------------------------------------------------------
# Custom tools, and where they come from
# ---------------------------------------------------------------------------


def _register(hass, *names):
    hass.data[DOMAIN]["tools"].replace_all(
        [
            CustomTool(
                name=name,
                description="x",
                parameters={"type": "object", "properties": {}},
                action=TemplateAction(value_template="x"),
            )
            for name in names
        ]
    )


async def test_the_sentinel_admits_custom_tools_but_not_built_ins(hass: HomeAssistant) -> None:
    await async_setup_component(hass, DOMAIN, {})
    _memory_registry(hass, stores=["notes"])
    entry = _entry(hass, ("Home", {CONF_ALLOWED_TOOLS: [ALL_TOOLS_SENTINEL]}))
    _register(hass, "ping", "pong")

    rows = _rows(hass, entry, "Home")

    assert rows["ping"]["enabled"] is True
    assert rows["pong"]["enabled"] is True
    assert rows[MEMORY_TOOL_NAME]["enabled"] is False
    assert rows[MEMORY_TOOL_NAME]["reason"] == REASON_NOT_ALLOWED


async def test_a_custom_tool_that_is_off_is_still_listed(hass: HomeAssistant) -> None:
    """The point of the inventory: a list of only the live tools says what is
    on but never what is missing."""
    await async_setup_component(hass, DOMAIN, {})
    entry = _entry(hass, ("Home", {CONF_ALLOWED_TOOLS: ["ping"]}))
    _register(hass, "ping", "pong")

    rows = _rows(hass, entry, "Home")

    assert rows["pong"]["enabled"] is False
    assert rows["pong"]["reason"] == REASON_NOT_ALLOWED
    assert rows["pong"]["source"] == "yaml"


# ---------------------------------------------------------------------------
# The legacy shape: switches, honoured only where no list exists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("switch", "names"),
    [
        (CONF_ENABLE_HISTORY_TOOL, [HISTORY_TOOL_NAME]),
        (CONF_ENABLE_MULTI_AGENT_TOOLS, [DELEGATE_MANY_TOOL_NAME, CRITIQUE_TOOL_NAME]),
    ],
)
@pytest.mark.parametrize("value", [True, False])
async def test_a_legacy_switch_still_speaks_without_a_list(
    hass: HomeAssistant, switch: str, names: list[str], value: bool
) -> None:
    """An agent with no `allowed_tools` key — never migrated, or built by a
    downstream integration — keeps the behaviour its switches described."""
    await async_setup_component(hass, DOMAIN, {})
    entry = _entry(hass, ("Home", {switch: value}), ("Auditor", {}))

    rows = _rows(hass, entry, "Home")

    for name in names:
        assert rows[name]["enabled"] is value, name


async def test_the_migration_writes_the_switches_into_the_list(hass: HomeAssistant) -> None:
    """After 2 -> 3 the two switches are gone and the list says what they said,
    so nothing is left that could disagree with it."""
    from custom_components.smartchain import _migrate_agent_tool_lists

    await async_setup_component(hass, DOMAIN, {})
    entry = _entry(
        hass,
        ("Home", {CONF_ENABLE_HISTORY_TOOL: True, CONF_ENABLE_MULTI_AGENT_TOOLS: False}),
    )

    _migrate_agent_tool_lists(hass, entry)

    data = _agent(entry, "Home").data
    assert CONF_ENABLE_HISTORY_TOOL not in data
    assert CONF_ENABLE_MULTI_AGENT_TOOLS not in data
    assert data[CONF_ALLOWED_TOOLS] == [
        ALL_TOOLS_SENTINEL,
        HISTORY_TOOL_NAME,
        DELEGATE_TOOL_NAME,
        MEMORY_TOOL_NAME,
        ENTITY_TOOL_NAME,
    ]

    # Idempotent: running it again changes nothing.
    before = dict(data)
    _migrate_agent_tool_lists(hass, entry)
    assert dict(_agent(entry, "Home").data) == before


# ---------------------------------------------------------------------------
# The assertion that stops the report and the runtime drifting
# ---------------------------------------------------------------------------


def _chat_log():
    chat_log = MagicMock()
    chat_log.conversation_id = "conv"
    chat_log.content = [SystemContent(content=""), UserContent(content="hello")]
    chat_log.async_add_assistant_content_without_tools = MagicMock()
    chat_log.llm_api = None
    chat_log.unresponded_tool_results = False

    async def _stream(agent_id, stream):
        collected = ""
        async for delta in stream:
            if "content" in delta:
                collected += delta["content"]
        content = AssistantContent(agent_id=agent_id, content=collected)
        chat_log.content.append(content)
        yield content

    chat_log.async_add_delta_content_stream = _stream
    return chat_log


async def test_the_inventory_equals_what_the_agent_is_bound_with(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """Drive a real message, capture `bind_tools`, and compare.

    Without this the command is decorative: `_describe_agent` and
    `_async_handle_message` each had their own idea of an agent's tools before
    v5.4.0, and that is exactly how the report came to omit every built-in.

    The fixture is deliberately asymmetric — every structural precondition is
    satisfied (a sibling agent, a memory store, an entity store) while only two
    built-ins are allowed. If the agent were allowed all of them, one built-in
    standing in for another in the runtime assembly would bind the same set and
    this test would not notice. Found exactly that way.
    """
    from custom_components.smartchain.conversation import SmartChainConversationEntity

    await async_setup_component(hass, DOMAIN, {})
    _memory_registry(hass, stores=["notes"], entity_stores=["home"])
    entry = _entry(
        hass,
        (
            "Home",
            {CONF_ALLOWED_TOOLS: [ALL_TOOLS_SENTINEL, HISTORY_TOOL_NAME, MEMORY_TOOL_NAME]},
        ),
        ("Auditor", {}),
    )
    _register(hass, "ping", "pong")

    subentry = _agent(entry, "Home")
    entity = SmartChainConversationEntity(
        entry, subentry_id=subentry.subentry_id, options=dict(subentry.data)
    )
    entity.hass = hass
    entry.runtime_data = {subentry.subentry_id: mock_llm_client}
    mock_llm_client.bind_tools = MagicMock(return_value=mock_llm_client)

    chat_log = _chat_log()
    with (
        patch.object(chat_log, "async_provide_llm_data", new_callable=AsyncMock),
        patch(
            "custom_components.smartchain.tools.memory.search_tool.get_memory_tool_definition",
            return_value={"name": MEMORY_TOOL_NAME, "description": "", "parameters": {}},
        ),
    ):
        await entity._async_handle_message(
            llm_conversation_input(),
            chat_log,
        )

    bound = {tool["name"] for tool in mock_llm_client.bind_tools.call_args[0][0]}
    reported = {
        row["name"]
        for row in describe_agent_tools(hass, entry, subentry.subentry_id, subentry.data)
        if row["enabled"]
    }
    assert bound == reported
    # And it is not vacuously equal: this agent really does have both kinds.
    assert HISTORY_TOOL_NAME in bound
    assert "ping" in bound


def llm_conversation_input():
    from homeassistant.components.conversation import ConversationInput

    return ConversationInput(
        text="hello",
        context=Context(),
        conversation_id="conv",
        device_id=None,
        satellite_id=None,
        language="en",
        agent_id="test_agent",
    )


# ---------------------------------------------------------------------------
# The form: one control, always rendered, never silently discarded
# ---------------------------------------------------------------------------


async def test_allowed_tools_renders_with_an_empty_registry(hass: HomeAssistant) -> None:
    """Cause #1 of the complaint: the picker was gated on a non-empty tools
    registry, so a user with no custom tools had never seen the field."""
    from custom_components.smartchain.config_flow import subentry_schema

    await async_setup_component(hass, DOMAIN, {})
    assert len(hass.data[DOMAIN]["tools"]) == 0

    schema = subentry_schema(hass, UNIQUE_ID_OPENAI, {}, models=["gpt-4.1-mini"])

    assert CONF_ALLOWED_TOOLS in {str(key.schema) for key in schema.schema}


async def test_the_switches_are_gone_from_the_form(hass: HomeAssistant) -> None:
    """Two controls for one thing is worse than either alone: the list is
    authoritative, so the switches must not also be offered."""
    from custom_components.smartchain.config_flow import subentry_schema

    await async_setup_component(hass, DOMAIN, {})
    declared = {
        str(key.schema) for key in subentry_schema(hass, UNIQUE_ID_OPENAI, {}, models=["m"]).schema
    }

    assert CONF_ENABLE_HISTORY_TOOL not in declared
    assert CONF_ENABLE_MULTI_AGENT_TOOLS not in declared


async def test_the_form_prefills_with_what_the_agent_can_actually_do(hass: HomeAssistant) -> None:
    """A legacy agent opens showing its real inventory rather than an empty
    field, so saving the form is what finally writes the list down."""
    from custom_components.smartchain.config_flow import subentry_schema

    await async_setup_component(hass, DOMAIN, {})
    schema = subentry_schema(
        hass,
        UNIQUE_ID_OPENAI,
        {CONF_ENABLE_HISTORY_TOOL: True},
        models=["m"],
    )

    key = next(k for k in schema.schema if str(k.schema) == CONF_ALLOWED_TOOLS)
    assert HISTORY_TOOL_NAME in key.description["suggested_value"]
    assert CRITIQUE_TOOL_NAME not in key.description["suggested_value"]


async def test_saving_an_agent_keeps_an_undeclared_key(hass, hass_ws_client) -> None:
    """`ws_agent_schema` strips keys the current schema does not declare, and
    `ws_agent_save` used to replace `subentry.data` wholesale — so opening and
    saving an agent destroyed any stored value that happened to be out of
    schema. A stale `enable_multi_agent_tools` is one such key today."""
    await async_setup_component(hass, DOMAIN, {})
    entry = _entry(hass, ("Home", {CONF_ENABLE_MULTI_AGENT_TOOLS: True}))
    subentry_id = _agent(entry, "Home").subentry_id

    client = await hass_ws_client(hass)
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "gpt-4.1-mini"],
    ):
        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/schema",
                "entry_id": entry.entry_id,
                "subentry_id": subentry_id,
            }
        )
        served = (await client.receive_json())["result"]["data"]
        assert CONF_ENABLE_MULTI_AGENT_TOOLS not in served

        await client.send_json_auto_id(
            {
                "type": "smartchain/agent/save",
                "entry_id": entry.entry_id,
                "subentry_id": subentry_id,
                "data": served,
            }
        )
        assert (await client.receive_json())["success"]

    assert entry.subentries[subentry_id].data[CONF_ENABLE_MULTI_AGENT_TOOLS] is True


# ---------------------------------------------------------------------------
# The websocket command the panel reads
# ---------------------------------------------------------------------------


async def test_the_reconfigure_flow_keeps_an_undeclared_key_too(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """Home Assistant's own Devices & Services dialog goes through
    `ConversationSubentryFlow._validate_and_update`, not through the websocket
    command, and it had the same wholesale replacement. Two copies of the fix,
    two tests — a fix applied to one path only is the defect moved, not closed.
    """
    from homeassistant.data_entry_flow import FlowResultType

    entry = _entry(hass, ("Home", {CONF_ENABLE_MULTI_AGENT_TOOLS: True}))
    subentry_id = _agent(entry, "Home").subentry_id
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, SUBENTRY_TYPE_CONVERSATION),
        context={"source": "reconfigure", "subentry_id": subentry_id},
    )
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"],
        {CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_PROMPT: "still tuned"},
    )

    assert result["type"] is FlowResultType.ABORT
    data = entry.subentries[subentry_id].data
    assert data[CONF_PROMPT] == "still tuned"
    assert data[CONF_ENABLE_MULTI_AGENT_TOOLS] is True


async def test_agent_tools_command_returns_the_inventory(hass, hass_ws_client) -> None:
    await async_setup_component(hass, DOMAIN, {})
    entry = _entry(hass, ("Home", {CONF_ALLOWED_TOOLS: [HISTORY_TOOL_NAME]}))
    subentry_id = _agent(entry, "Home").subentry_id

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/tools",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
        }
    )
    msg = await client.receive_json()

    assert msg["success"], msg
    rows = {row["name"]: row for row in msg["result"]["tools"]}
    assert set(rows) == set(BUILTIN_TOOL_NAMES)
    assert rows[HISTORY_TOOL_NAME]["enabled"] is True
    assert rows[MEMORY_TOOL_NAME]["enabled"] is False


async def test_agent_tools_carries_no_credential(hass, hass_ws_client) -> None:
    """The response says what an agent can do, never how it connects."""
    import json

    await async_setup_component(hass, DOMAIN, {})
    entry = _entry(hass, ("Home", {}))
    subentry_id = _agent(entry, "Home").subentry_id

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/tools",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
        }
    )
    msg = await client.receive_json()

    assert "sekrit-key" not in json.dumps(msg)


async def test_agent_tools_rejects_an_unknown_agent(hass, hass_ws_client) -> None:
    await async_setup_component(hass, DOMAIN, {})
    entry = _entry(hass, ("Home", {}), embeddings=True)
    embeddings_id = next(
        sub.subentry_id
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_TYPE_EMBEDDINGS
    )

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/tools",
            "entry_id": entry.entry_id,
            "subentry_id": embeddings_id,
        }
    )
    msg = await client.receive_json()

    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"


async def test_agent_tools_is_admin_only(hass, hass_ws_client, hass_admin_user) -> None:
    await async_setup_component(hass, DOMAIN, {})
    entry = _entry(hass, ("Home", {}))
    subentry_id = _agent(entry, "Home").subentry_id

    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/agent/tools",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
        }
    )
    msg = await client.receive_json()

    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"


async def test_the_overview_count_matches_the_inventory(hass, hass_ws_client) -> None:
    """`_describe_agent.tool_count` is recomputed from the same inventory, so
    the Agents tab column cannot understate the real capability set again."""
    await async_setup_component(hass, DOMAIN, {})
    _memory_registry(hass, stores=["notes"])
    entry = _entry(hass, ("Home", {CONF_ALLOWED_TOOLS: [ALL_TOOLS_SENTINEL, MEMORY_TOOL_NAME]}))
    _register(hass, "ping")
    subentry = _agent(entry, "Home")

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    overview = await client.receive_json()

    agent = overview["result"]["entries"][0]["agents"][0]
    inventory = describe_agent_tools(hass, entry, subentry.subentry_id, subentry.data)
    assert agent["tool_count"] == sum(1 for row in inventory if row["enabled"])
    assert agent["tool_total"] == len(inventory)
    assert agent["tool_count"] == 2  # search_memory + ping
