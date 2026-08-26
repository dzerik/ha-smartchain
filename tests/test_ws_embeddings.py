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
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentry, ConfigSubentryData
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CAPABILITY_CHAT,
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

# The real translation file, read directly rather than duplicated as string
# literals — F1's regression test compares against these, not a second copy
# that could drift out of sync with what the panel actually receives.
_TRANSLATIONS_EN = json.loads(
    (
        Path(__file__).parents[1] / "custom_components" / "smartchain" / "translations" / "en.json"
    ).read_text()
)

# Disjoint on purpose (F2): a fake that returned the same list for both
# purposes could never tell a chat-purpose fetch from an embeddings-purpose
# one apart, so a mutation that fetches the wrong purpose — or a cache key
# that stops distinguishing them — would leave every test in this file
# passing regardless.
_CHAT_MODELS = ["", "gpt-4.1-mini"]
_EMBEDDING_MODELS = ["", "text-embedding-3-small"]


async def _fake_fetch_models(hass, engine, data, *, purpose=CAPABILITY_CHAT, **kwargs):
    return _EMBEDDING_MODELS if purpose == CAPABILITY_EMBEDDINGS else _CHAT_MODELS


@pytest.fixture(autouse=True)
def _models():
    """A purpose-aware stand-in model list — see `_fake_fetch_models`."""
    with patch(
        "custom_components.smartchain.websocket_api.async_fetch_models",
        side_effect=_fake_fetch_models,
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
    assert msg["result"]["descriptions"]
    assert msg["result"]["bound_stores"] == []
    assert msg["result"]["title_taken_by"] is None


async def test_schema_serves_the_embeddings_label_not_the_conversation_one(
    hass, hass_ws_client, entry
):
    """F1: `config_subentries` holds both conversation and embeddings, which
    declare the field names `model` and `model_user` with different meanings
    (`Embedding model` vs `Completion Model`). Flattening the whole category
    with `setdefault` let whichever type's keys the translation loader
    iterated first win for *both* forms — a real label, just for the wrong
    form. Checked against the actual translations/en.json content, not
    merely for "the two differ", since two labels can differ and both still
    be wrong.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/embeddings/schema", "entry_id": entry.entry_id}
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    labels = msg["result"]["labels"]
    embeddings_data = _TRANSLATIONS_EN["config_subentries"]["embeddings"]["step"]["user"]["data"]
    conversation_data = _TRANSLATIONS_EN["config_subentries"]["conversation"]["step"]["user"][
        "data"
    ]
    # The file itself must actually diverge, or this test would prove nothing.
    assert embeddings_data["model"] != conversation_data["model"]
    assert embeddings_data["model_user"] != conversation_data["model_user"]

    assert labels["name"] == embeddings_data["name"]
    assert labels["model"] == embeddings_data["model"]
    assert labels["model_user"] == embeddings_data["model_user"]
    assert labels["model"] != conversation_data["model"]
    assert labels["model_user"] != conversation_data["model_user"]


async def test_schema_serves_the_embeddings_description_not_the_conversation_one(
    hass, hass_ws_client, entry
):
    """F1's description-map guise: `config_subentries` holds both conversation
    and embeddings, which declare `model` and `model_user` with different
    meanings. A category-wide flatten would let whichever type's
    `data_description` the translation loader iterated first win for both
    forms. Checked against the actual translations/en.json content, since two
    descriptions can differ and both still be wrong.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": "smartchain/embeddings/schema", "entry_id": entry.entry_id}
    )
    msg = await client.receive_json()
    assert msg["success"], msg

    descriptions = msg["result"]["descriptions"]
    embeddings_data = _TRANSLATIONS_EN["config_subentries"]["embeddings"]["step"]["user"][
        "data_description"
    ]
    conversation_data = _TRANSLATIONS_EN["config_subentries"]["conversation"]["step"]["user"][
        "data_description"
    ]
    # The file itself must actually diverge, or this test would prove nothing.
    assert embeddings_data["model"] != conversation_data["model"]
    assert embeddings_data["model_user"] != conversation_data["model_user"]

    assert descriptions["name"] == embeddings_data["name"]
    assert descriptions["model"] == embeddings_data["model"]
    assert descriptions["model_user"] == embeddings_data["model_user"]
    assert descriptions["model"] != conversation_data["model"]
    assert descriptions["model_user"] != conversation_data["model_user"]


async def test_save_uses_the_embeddings_model_purpose(hass, hass_ws_client, entry, _models):
    """The mirror of the schema purpose test: save must fetch with
    CAPABILITY_EMBEDDINGS too, not just the form that renders it."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry.entry_id,
            "data": {"name": "Purpose Check", "model": "text-embedding-3-small"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert _models.call_args.kwargs["purpose"] == CAPABILITY_EMBEDDINGS


async def test_embeddings_save_still_works_after_visiting_the_agent_tab(
    hass, hass_ws_client, entry, _models
):
    """F2: with a purpose-blind cache key (or a save that quietly fetched the
    chat list), the embeddings tab becomes unusable — no embedding model
    accepted — the moment a user had already opened the Agents tab in the
    same session, because the per-entry model cache is already warm with the
    wrong list by the time the embeddings command asks for one.
    """
    client = await hass_ws_client(hass)

    # Visiting the Agents tab first warms the per-entry model cache under the
    # chat purpose.
    await client.send_json_auto_id({"type": "smartchain/agent/schema", "entry_id": entry.entry_id})
    agent_msg = await client.receive_json()
    assert agent_msg["success"], agent_msg

    # An embedding-only model name: absent from the chat list this fixture
    # serves, so a save that reused (or refetched under) the chat purpose
    # could not have accepted it.
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry.entry_id,
            "data": {"name": "After Agents Tab", "model": "text-embedding-3-small"},
        }
    )
    embed_msg = await client.receive_json()
    assert embed_msg["success"], embed_msg


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
    # F3: names *where* the title is already used, not just that it is.
    assert "OpenAI A" in msg["error"]["message"]
    # Nothing was written: entry_b still has no subentries at all.
    assert entry_b.subentries == {}


async def test_a_taken_title_and_a_missing_name_get_different_messages(hass, hass_ws_client):
    """F3: both used to render the identical 'invalid_data: name', so a user
    was told a name was wrong but never why."""
    entry_a = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: SECRET},
        unique_id="OpenAI A",
        title="OpenAI A",
        subentries_data=[
            ConfigSubentryData(
                data={"model": "m"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title="Taken",
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
            "data": {"name": "Taken", "model": "text-embedding-3-small"},
        }
    )
    taken_msg = await client.receive_json()

    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry_b.entry_id,
            "data": {"model": "text-embedding-3-small"},
        }
    )
    missing_msg = await client.receive_json()

    assert not taken_msg["success"] and not missing_msg["success"]
    assert taken_msg["error"]["code"] == missing_msg["error"]["code"] == "invalid_data"
    assert taken_msg["error"]["message"] != missing_msg["error"]["message"]
    assert "OpenAI A" in taken_msg["error"]["message"]
    assert "OpenAI A" not in missing_msg["error"]["message"]


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
    # F3: the entry title that already holds it, not merely a signal that
    # something does.
    assert msg["result"]["title_taken_by"] == "OpenAI B"


async def test_save_with_a_new_unique_title_succeeds_despite_an_existing_collision(
    hass, hass_ws_client
):
    """The recovery path named in the review: two bindings already share a
    title, and one of them is renamed away to a title nobody else holds."""
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
            "type": "smartchain/embeddings/save",
            "entry_id": entry_a.entry_id,
            "subentry_id": subentry_a_id,
            "data": {"name": "Totally New Title", "model": "text-embedding-3-small"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert entry_a.subentries[subentry_a_id].title == "Totally New Title"


async def test_save_can_keep_its_own_title_while_a_collision_with_someone_else_persists(
    hass, hass_ws_client
):
    """F4: `_title_claimed_by_another` used to return its "more than one
    claimant" sentinel before ever excluding the subentry being edited, so
    resaving a binding under its own unchanged title — the one edit possible
    without first deciding how to rename — was refused even though this
    write does not change who holds what. Renaming away (the test above) was
    never actually blocked; only this no-op-on-the-title case was.
    """
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
            "type": "smartchain/embeddings/save",
            "entry_id": entry_a.entry_id,
            "subentry_id": subentry_a_id,
            "data": {"name": "Dup", "model": "text-embedding-3-small"},
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg


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


async def test_renaming_a_binding_on_a_custom_model_is_not_refused(hass, hass_ws_client, entry):
    """The dead end the docs walk people into.

    `subentry_schema` unions an agent's stored model into its own dropdown so
    that opening an agent to change one field cannot be refused over another
    the user never touched. `embeddings_subentry_schema` was not given the same
    union, and the omission bites harder here: `_resolve_embeddings_model`
    collapses a Custom Model name into `model`, and the release notes tell
    users to type the model into Custom Model whenever the shipped list has not
    caught up — which, with `EMBEDDING_MODELS_GIGACHAT` stale, was routine.

    So the stored value is one the dropdown does not offer, and the *next*
    save is rejected on the model field. No unreachable provider and no failed
    fetch is needed: this test's fetch succeeds throughout. The save here
    changes nothing but the name.
    """
    client = await hass_ws_client(hass)

    # A model this fixture's provider list does not contain — the shape of a
    # name typed into Custom Model.
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry.entry_id,
            "data": {"name": "Embeddings Two", "model_user": "Embeddings-2"},
        }
    )
    created = await client.receive_json()
    assert created["success"], created
    subentry_id = created["result"]["subentry_id"]
    assert entry.subentries[subentry_id].data["model"] == "Embeddings-2"
    assert "Embeddings-2" not in _EMBEDDING_MODELS  # or this proves nothing

    # The form is rendered from the stored data, so this is what the panel
    # sends back when the user edits only the name.
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
            "data": {
                "name": "Embeddings Two Renamed",
                "model": "Embeddings-2",
                "model_user": "Embeddings-2",
            },
        }
    )
    renamed = await client.receive_json()
    assert renamed["success"], renamed
    assert entry.subentries[subentry_id].title == "Embeddings Two Renamed"
    assert entry.subentries[subentry_id].data["model"] == "Embeddings-2"


async def test_schema_offers_the_stored_model_back(hass, hass_ws_client, entry):
    """The same fix seen from the form rather than the save.

    A dropdown that omits the value it is being pre-filled with is a control
    the user cannot leave alone, so the union has to be visible in the options
    the panel receives — not merely tolerated by the validator.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry.entry_id,
            "data": {"name": "Custom", "model_user": "Embeddings-3B-2025-09"},
        }
    )
    created = await client.receive_json()
    assert created["success"], created

    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/schema",
            "entry_id": entry.entry_id,
            "subentry_id": created["result"]["subentry_id"],
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    model_field = next(f for f in msg["result"]["schema"] if f["name"] == "model")
    assert "Embeddings-3B-2025-09" in model_field["selector"]["select"]["options"]
    # And it is what the field is pre-filled with, so the two agree.
    assert model_field["description"]["suggested_value"] == "Embeddings-3B-2025-09"


async def test_an_off_list_model_is_refused_in_words_not_a_machine_key(hass, hass_ws_client, entry):
    """When the model *is* genuinely the problem, say so in a sentence.

    The union above removes the common cause of this rejection but not the
    rejection itself — a panel left open across a provider change can still
    submit a model no list contains. `ws_agent_save` was taught to answer that
    with the `model_unknown` sentence in v5.4.10; this command was left
    reporting the bare `invalid_data: model` the same release had just removed
    from the agent form, which is the machine key a user cannot act on.
    """
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/embeddings/save",
            "entry_id": entry.entry_id,
            "data": {"name": "Off List", "model": "a-model-no-list-contains"},
        }
    )
    msg = await client.receive_json()
    assert not msg["success"]
    assert msg["error"]["code"] == "invalid_data"
    message = msg["error"]["message"]
    # Still names the field, so the panel can attach it to the right control.
    assert message.startswith("invalid_data: model")
    # But no longer *only* the field.
    assert "—" in message, f"no human sentence in {message!r}"
    embeddings_text = _TRANSLATIONS_EN["config_subentries"]["embeddings"]["error"]["model_unknown"]
    assert embeddings_text in message
    # The embeddings form's own sentence, not the conversation one.
    conversation_text = _TRANSLATIONS_EN["config_subentries"]["conversation"]["error"][
        "model_unknown"
    ]
    assert embeddings_text != conversation_text
    assert conversation_text not in message
