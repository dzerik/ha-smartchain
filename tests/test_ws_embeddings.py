"""Embeddings bindings over the panel's websocket API.

A memory store binds to an embeddings subentry *by title*, and
MemoryRegistry._embeddings_subentries maps a title claimed by more than one
subentry to None — silently unbinding every store that referenced it, exactly
as a rename does. The panel shows every SmartChain entry at once and invites
creating embeddings bindings side by side, which makes that collision far
easier to reach than the one-entry-at-a-time flow dialog ever was. These
commands exist to make the backend answer, before a write: which stores are
bound to a title, and is a candidate title already claimed elsewhere.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentry, ConfigSubentryData
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CAPABILITY_EMBEDDINGS,
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_CONVERSATION,
    SUBENTRY_TYPE_EMBEDDINGS,
    UNIQUE_ID_OPENAI,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SECRET = "sk-embeddings-secret"

_MEMORY_YAML = """
tools: []
memory:
  stores:
    - name: conversations
      description: "Dialogue history"
      embeddings: "{title}"
      ingest_conversation: true
"""


@pytest.fixture(autouse=True)
def _models():
    """A stand-in model list. Individual tests still assert on the *purpose*
    the fetch was called with — this fixture only avoids a real network call.
    """
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        return_value=["", "text-embedding-3-small"],
    ) as fetch:
        yield fetch


@pytest.fixture
async def entry(hass):
    """An OpenAI entry with the domain set up, no memory store configured.

    Sufficient for every test that does not need a live MemoryRegistry
    binding (purpose, admin, credential-leak, cross-type guard).
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
    )
    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    return entry


@pytest.fixture
def patched_store():
    """Patch MemoryStore and embeddings construction so registry.build() needs
    no real backend or embeddings provider — same technique as
    tests/test_memory_multi_store.py."""

    def _factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        return st

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry.create_embeddings_from_subentry",
            return_value=MagicMock(),
        ),
    ):
        yield


async def _setup_with_memory_store(
    hass, tmp_path_factory, mock_llm_client, patched_store, *, title="Bound Embeddings"
):
    """A real entry with an embeddings subentry and a memory store bound to
    its title, built through the integration's normal setup — the same path
    tests/test_memory_multi_store.py uses — so MemoryRegistry.build actually
    resolves the binding rather than a hand-built stand-in.
    """
    del patched_store  # active via the fixture context; only its patches matter here
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text(_MEMORY_YAML.format(title=title))
    hass.config.config_dir = str(cdir)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET},
        options={},
        unique_id=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={"model": "text-embedding-3-small"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title=title,
                unique_id=None,
            )
        ],
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


async def test_schema_uses_the_embeddings_model_purpose(hass, hass_ws_client, entry, _models):
    """A chat model list here would offer models that cannot embed."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/embeddings/schema", "entry_id": entry.entry_id}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert _models.call_args.kwargs["purpose"] == CAPABILITY_EMBEDDINGS


async def test_schema_command_returns_renderable_fields(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/embeddings/schema", "entry_id": entry.entry_id}
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["schema"]
    assert msg["result"]["labels"]
    assert msg["result"]["bound_stores"] == []
    assert msg["result"]["title_taken_by"] is None


async def test_save_creates_a_new_embeddings_subentry(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry.entry_id,
            "data": {"name": "My Embeddings", "model": "text-embedding-3-small"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    subentry = entry.subentries[msg["result"]["subentry_id"]]
    assert subentry.title == "My Embeddings"
    assert subentry.subentry_type == SUBENTRY_TYPE_EMBEDDINGS
    assert subentry.data["model"] == "text-embedding-3-small"


async def test_save_reports_a_title_already_taken(hass, hass_ws_client):
    """MemoryRegistry maps a duplicated title to None, silently unbinding the
    store. The panel must be able to warn before writing — including when the
    collision spans two different config entries, which the panel's
    all-entries-at-once view makes easy to reach.
    """
    entry_a = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET},
        unique_id="OpenAI A",
        title="OpenAI A",
        subentries_data=[
            ConfigSubentryData(
                data={"model": "text-embedding-3-small"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="Shared Title",
                unique_id=None,
            )
        ],
    )
    entry_a.add_to_hass(hass)

    entry_b = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET},
        unique_id="OpenAI B",
        title="OpenAI B",
    )
    entry_b.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry_b.entry_id,
            "data": {"name": "Shared Title", "model": "text-embedding-3-small"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"], msg
    assert msg["error"]["code"] == "invalid_data"
    # Nothing was written: entry_b still has no subentries at all.
    assert entry_b.subentries == {}


async def test_save_permits_keeping_an_agents_own_title(hass, hass_ws_client, entry):
    """Saving a subentry back under its own current title must not be
    refused as a collision against itself."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry.entry_id,
            "data": {"name": "Mine", "model": "text-embedding-3-small"},
        }
    )
    created = await client.receive_json()
    subentry_id = created["result"]["subentry_id"]

    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
            "data": {"name": "Mine", "model": "text-embedding-3-small"},
        }
    )
    updated = await client.receive_json()
    assert updated["success"], updated


async def test_schema_reports_which_stores_are_bound(
    hass, hass_ws_client, tmp_path_factory, mock_llm_client, patched_store
):
    """A configured memory store bound to this subentry's title, so the panel
    can warn before a rename."""
    memory_entry = await _setup_with_memory_store(
        hass, tmp_path_factory, mock_llm_client, patched_store
    )
    subentry_id = next(iter(memory_entry.subentries))

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/schema",
            "entry_id": memory_entry.entry_id,
            "subentry_id": subentry_id,
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["bound_stores"] == ["conversations"]


async def test_schema_reports_a_pre_existing_title_collision(hass, hass_ws_client):
    """title_taken_by flags that this subentry's *current* title already
    collides with another subentry elsewhere — a state the collision guard on
    save is meant to prevent, but which this command must still be able to
    report if it is ever reached (a race, or data predating the guard)."""
    entry_a = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET},
        unique_id="OpenAI A",
        title="OpenAI A",
        subentries_data=[
            ConfigSubentryData(
                data={"model": "m"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="Dup",
                unique_id=None,
            )
        ],
    )
    entry_a.add_to_hass(hass)
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET},
        unique_id="OpenAI B",
        title="OpenAI B",
        subentries_data=[
            ConfigSubentryData(
                data={"model": "m"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="Dup",
                unique_id=None,
            )
        ],
    )
    entry_b.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})

    subentry_a_id = next(iter(entry_a.subentries))

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/schema",
            "entry_id": entry_a.entry_id,
            "subentry_id": subentry_a_id,
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["title_taken_by"] is not None


async def test_delete_reports_bound_stores_rather_than_silently_breaking_them(
    hass, hass_ws_client, tmp_path_factory, mock_llm_client, patched_store
):
    memory_entry = await _setup_with_memory_store(
        hass, tmp_path_factory, mock_llm_client, patched_store
    )
    subentry_id = next(iter(memory_entry.subentries))

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/delete",
            "entry_id": memory_entry.entry_id,
            "subentry_id": subentry_id,
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["bound_stores"] == ["conversations"]
    assert subentry_id not in memory_entry.subentries


@pytest.mark.parametrize("command", ["save", "delete"])
async def test_save_and_delete_reject_a_conversation_subentry(hass, hass_ws_client, entry, command):
    """The mirror of D1's guard: agent commands reject embeddings subentries,
    so embeddings commands must reject agents."""
    convo = ConfigSubentry(
        data={},
        subentry_type=SUBENTRY_TYPE_CONVERSATION,
        title="Agent",
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, convo)
    before = dict(entry.subentries)

    client = await hass_ws_client(hass)
    payload = {
        "type": f"smartchain/embeddings/{command}",
        "entry_id": entry.entry_id,
        "subentry_id": convo.subentry_id,
    }
    if command == "save":
        payload["data"] = {"name": "New Name", "model": "text-embedding-3-small"}
    await client.send_json_auto_id(payload)
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "not_found"
    # Rejected save must write nothing; rejected delete must remove nothing.
    assert dict(entry.subentries) == before


async def test_embeddings_commands_require_admin(hass, hass_ws_client, hass_admin_user, entry):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    for command, extra in (
        ("schema", {}),
        ("save", {"data": {"name": "X", "model": "text-embedding-3-small"}}),
        ("delete", {"subentry_id": "does-not-matter"}),
    ):
        payload = {
            "type": f"smartchain/embeddings/{command}",
            "entry_id": entry.entry_id,
            **extra,
        }
        await client.send_json_auto_id(payload)
        msg = await client.receive_json()
        assert not msg["success"], command
        assert msg["error"]["code"] == "unauthorized", command
    assert entry.subentries == {}


async def test_embeddings_responses_carry_no_credential(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/embeddings/schema", "entry_id": entry.entry_id}
    )
    schema_msg = await client.receive_json()

    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry.entry_id,
            "data": {"name": "Creds", "model": "text-embedding-3-small"},
        }
    )
    save_msg = await client.receive_json()

    body = json.dumps([schema_msg, save_msg])
    assert SECRET not in body
    assert CONF_API_KEY not in body
