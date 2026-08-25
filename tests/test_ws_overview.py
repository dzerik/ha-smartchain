"""The overview command that lists entries and their agents."""

import json

import pytest
from homeassistant.config_entries import ConfigSubentry, ConfigSubentryData
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    ALL_TOOLS_SENTINEL,
    CONF_ALLOWED_TOOLS,
    CONF_API_KEY,
    CONF_CHAT_MODEL,
    CONF_CHAT_MODEL_USER,
    CONF_ENGINE,
    CONF_FOLDER_ID,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SECRET = "sk-do-not-leak-me"
FOLDER = "folder-do-not-leak-me"


@pytest.fixture
async def entry(hass):
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET, CONF_FOLDER_ID: FOLDER},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)
    return entry


async def test_overview_lists_the_entry_and_its_agent(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    assert msg["success"], msg
    entries = msg["result"]["entries"]
    assert len(entries) == 1
    served = entries[0]
    assert served["entry_id"] == entry.entry_id
    assert served["engine"] == ID_OPENAI
    assert served["engine_label"] == UNIQUE_ID_OPENAI
    assert served["supports_embeddings"] is True

    agents = served["agents"]
    assert len(agents) == 1
    assert agents[0]["title"] == "Home"
    assert agents[0]["model"] == "gpt-4.1-mini"
    assert "tool_count" in agents[0]


async def test_overview_never_carries_a_credential(hass, hass_ws_client, entry):
    """The whole response, serialised, must contain no secret from entry data.

    Extended (rather than duplicated) to add an embeddings binding alongside
    the conversation agent the fixture already carries — the embeddings
    field walks the same subentries as agents does, so it must be covered by
    the same containment check rather than a second, near-identical test.
    """
    hass.config_entries.async_add_subentry(
        entry,
        ConfigSubentry(
            data={CONF_CHAT_MODEL: "text-embedding-3-small"},
            subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
            title="Embeddings",
            unique_id=None,
        ),
    )

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    served = msg["result"]["entries"][0]
    assert len(served["embeddings"]) == 1

    body = json.dumps(msg)
    assert SECRET not in body
    assert FOLDER not in body
    # Nor the key names, which would mean entry data was forwarded wholesale.
    assert CONF_API_KEY not in body


async def test_overview_requires_admin(hass, hass_ws_client, hass_admin_user, entry):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "unauthorized"


async def test_overview_with_no_entries_is_an_empty_list(hass, hass_ws_client):
    await async_setup_component(hass, DOMAIN, {})
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()
    assert msg["success"]
    assert msg["result"]["entries"] == []


async def test_embeddings_capability_follows_the_provider(hass, hass_ws_client):
    """A provider without embeddings must say so — D2 hides a tab on this."""
    from custom_components.smartchain.const import ID_ANTHROPIC, UNIQUE_ID_ANTHROPIC

    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_ANTHROPIC, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_ANTHROPIC,
        title=UNIQUE_ID_ANTHROPIC,
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    served = next(e for e in msg["result"]["entries"] if e["entry_id"] == entry.entry_id)
    assert served["supports_embeddings"] is False


async def test_tool_count_is_none_when_unrestricted(hass, hass_ws_client, entry):
    """No allowed_tools key means every tool; the panel shows "all tools"."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agent = msg["result"]["entries"][0]["agents"][0]
    assert agent["tool_count"] is None


async def test_tool_count_is_zero_when_restricted_to_nothing(hass, hass_ws_client):
    """An explicit empty list means no tool at all — the opposite of None."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_ALLOWED_TOOLS: []},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="No Tools",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agent = msg["result"]["entries"][0]["agents"][0]
    assert agent["tool_count"] == 0


async def test_tool_count_counts_a_restricted_list(hass, hass_ws_client):
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_ALLOWED_TOOLS: ["a", "b"]},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Two Tools",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agent = msg["result"]["entries"][0]["agents"][0]
    assert agent["tool_count"] == 2


async def test_tool_count_is_none_for_the_all_tools_sentinel(hass, hass_ws_client):
    """`["*"]` means "all tools", so the panel must show it the same way it
    shows `None` (never touched) — a count of 1 would be wrong and misleading."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_ALLOWED_TOOLS: [ALL_TOOLS_SENTINEL]},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="All Tools",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agent = msg["result"]["entries"][0]["agents"][0]
    assert agent["tool_count"] is None


async def test_agents_excludes_non_conversation_subentries(hass, hass_ws_client):
    """An embeddings subentry on the same entry must not show up as an agent."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            ),
            ConfigSubentryData(
                data={},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="Embeddings",
                unique_id=None,
            ),
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agents = msg["result"]["entries"][0]["agents"]
    assert len(agents) == 1
    assert agents[0]["title"] == "Home"


async def test_model_reports_model_user_when_set(hass, hass_ws_client):
    """F4: the five OpenAI-compatible providers added last week ship
    static_models=[""], so their model always lives in model_user. Dropping
    CONF_CHAT_MODEL_USER from _describe_agent would silently blank every one
    of them, and the whitespace-only test above cannot catch that because it
    falls back to the same result either way."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "", CONF_CHAT_MODEL_USER: "my-custom-model"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Custom",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agent = msg["result"]["entries"][0]["agents"][0]
    assert agent["model"] == "my-custom-model"


async def test_embeddings_lists_only_embeddings_subentries(hass, hass_ws_client):
    """The mirror of test_agents_excludes_non_conversation_subentries: a
    conversation subentry on the same entry must not show up as a binding."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini"},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            ),
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "text-embedding-3-small"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="Embeddings",
                unique_id=None,
            ),
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    served = msg["result"]["entries"][0]
    assert len(served["agents"]) == 1
    assert served["agents"][0]["title"] == "Home"
    assert len(served["embeddings"]) == 1
    assert served["embeddings"][0]["title"] == "Embeddings"


async def test_embeddings_model_reports_model_user_when_set(hass, hass_ws_client):
    """The same model_user-over-model rule agents use — untested for agents
    until a reviewer caught it, so covered here from the start."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "", CONF_CHAT_MODEL_USER: "my-custom-embedding-model"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="Custom Embeddings",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    binding = msg["result"]["entries"][0]["embeddings"][0]
    assert binding["model"] == "my-custom-embedding-model"


async def test_embeddings_reports_bound_stores(
    hass, hass_ws_client, tmp_path_factory, mock_llm_client
):
    """bound_stores names a store configured against that title, and is []
    when none is — the same data smartchain/embeddings/schema exposes,
    surfaced here too so the list can show the risk before an edit."""
    from unittest.mock import AsyncMock, MagicMock, patch

    memory_yaml = """
tools: []
memory:
  stores:
    - name: conversations
      description: "Dialogue history"
      embeddings: "Bound Embeddings"
      ingest_conversation: true
"""
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text(memory_yaml)
    hass.config.config_dir = str(cdir)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        options={},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "text-embedding-3-small"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="Bound Embeddings",
                unique_id=None,
            ),
            ConfigSubentryData(
                data={},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="Unbound Embeddings",
                unique_id=None,
            ),
        ],
    )
    entry.add_to_hass(hass)

    def _store_factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        return st

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_store_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry.create_embeddings_from_subentry",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.smartchain.get_client",
            new_callable=AsyncMock,
            return_value=mock_llm_client,
        ),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    bindings = {b["title"]: b for b in msg["result"]["entries"][0]["embeddings"]}
    assert bindings["Bound Embeddings"]["bound_stores"] == ["conversations"]
    assert bindings["Unbound Embeddings"]["bound_stores"] == []


async def test_model_falls_back_when_model_user_is_whitespace(hass, hass_ws_client):
    """A whitespace-only override must not shadow the real model — a truthiness
    check on the raw string would wrongly treat "   " as a set override."""
    await async_setup_component(hass, DOMAIN, {})
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "k"},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={CONF_CHAT_MODEL: "gpt-4.1-mini", CONF_CHAT_MODEL_USER: "   "},
                subentry_type=SUBENTRY_TYPE_CONVERSATION,
                title="Home",
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()

    agent = msg["result"]["entries"][0]["agents"][0]
    assert agent["model"] == "gpt-4.1-mini"
