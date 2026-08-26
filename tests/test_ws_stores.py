"""Memory stores over the panel's websocket API.

The point of moving stores out of tools.yaml is that `backend.dsn` and
`backend.api_key` are real credentials — a PostgreSQL connection string embeds
a password and a qdrant key is a bearer token — and `smartchain/tools/get`
hands the raw text of tools.yaml to the browser. In a subentry they can be
accepted by a form and never echoed back, so most of what is asserted here is
about what does *not* appear in a response.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_ANTHROPIC,
    ID_OPENAI,
    SUBENTRY_TYPE_EMBEDDINGS,
    SUBENTRY_TYPE_MEMORY_STORE,
    UNIQUE_ID_ANTHROPIC,
    UNIQUE_ID_OPENAI,
)
from custom_components.smartchain.tools.memory.subentry_source import (
    store_config_from_subentry,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

PROVIDER_SECRET = "sk-provider-secret"
QDRANT_SECRET = "qdrant-token-do-not-leak"
PG_DSN = "postgresql://user:pgpassword@db.example/memories"
TITLE = "OpenAI Embeddings"
OTHER_TITLE = "Second Embeddings"


@pytest.fixture
def patched_store():
    """No real backend and no real embeddings provider — the same stand-in
    tests/test_ws_embeddings.py uses, so a save's registry rebuild does not try
    to reach a database."""

    def _factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.unavailable_reason = None
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


def _store_subentry(title: str, data: dict) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=data, subentry_type=SUBENTRY_TYPE_MEMORY_STORE, title=title, unique_id=None
    )


def _embeddings_subentry(title: str) -> ConfigSubentryData:
    return ConfigSubentryData(
        data={"model": "text-embedding-3-small"},
        subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
        title=title,
        unique_id=None,
    )


async def _make_entry(hass, *, subentries=(), titles=(TITLE,), setup=True, tmp_path=None):
    if tmp_path is not None:
        hass.config.config_dir = str(tmp_path)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: PROVIDER_SECRET},
        options={},
        unique_id=UNIQUE_ID_OPENAI,
        title=UNIQUE_ID_OPENAI,
        subentries_data=[_embeddings_subentry(title) for title in titles] + list(subentries),
    )
    entry.add_to_hass(hass)
    if setup:
        assert await async_setup_component(hass, DOMAIN, {})
        await hass.async_block_till_done()
    return entry


@pytest.fixture
async def entry(hass, tmp_path, patched_store):
    del patched_store  # active via the fixture context; only its patches matter
    return await _make_entry(hass, tmp_path=tmp_path)


def _basic(**overrides):
    data = {
        "name": "conversations",
        "embeddings": TITLE,
        "description": "Dialogue history",
        "backend_type": "sqlite_numpy",
        "source_type": "none",
        "retention_days": 90,
        "ingest_conversation": True,
    }
    data.update(overrides)
    return data


async def _save(client, entry, data, subentry_id=None):
    payload = {"type": "smartchain/store/save", "entry_id": entry.entry_id, "data": data}
    if subentry_id is not None:
        payload["subentry_id"] = subentry_id
    await client.send_json_auto_id(payload)
    return await client.receive_json()


def _stores(entry):
    return {
        sub.title: sub
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_TYPE_MEMORY_STORE
    }


# --- creating -------------------------------------------------------------


async def test_save_creates_a_store_subentry_titled_by_its_name(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    msg = await _save(client, entry, _basic())
    assert msg["success"], msg

    stores = _stores(entry)
    assert list(stores) == ["conversations"]
    # The title is the name — the same convention embeddings bindings use and
    # the one MemoryRegistry.stores_bound_to depends on.
    assert "name" not in stores["conversations"].data


async def test_a_saved_store_matches_the_one_the_same_yaml_would_build(
    hass, hass_ws_client, entry, tmp_path
):
    """One assertion pinning the UI path and the file path to one dataclass."""
    from custom_components.smartchain.tools.loader import load_tools_file

    client = await hass_ws_client(hass)
    assert (await _save(client, entry, _basic(retention_days=30)))["success"]

    yaml_path = tmp_path / "equivalent.yaml"
    yaml_path.write_text(
        "tools: []\n"
        "memory:\n"
        "  stores:\n"
        "    - name: conversations\n"
        f'      embeddings: "{TITLE}"\n'
        '      description: "Dialogue history"\n'
        "      retention_days: 30\n"
    )
    from_yaml = load_tools_file(yaml_path).memory_settings.stores[0]
    assert store_config_from_subentry(_stores(entry)["conversations"]) == from_yaml


async def test_a_saved_store_reaches_the_registry_without_a_reload_service_call(
    hass, hass_ws_client, entry
):
    """Adding a subentry fires nothing the memory subsystem listens for, so the
    store used to do nothing at all until `smartchain.reload_tools` or a
    restart — with no error to explain why.

    A *second* config entry is present on purpose. Writing a subentry reloads
    its own entry, and unloading the last entry sets `subsystems_stopped`,
    which makes the next setup rebuild the registry as a side effect — so on a
    single-entry install this assertion passes whether or not the command does
    its own rebuild, and proves nothing. With another entry alive that path is
    closed and only the explicit rebuild can satisfy it.
    """
    second = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_ANTHROPIC, CONF_API_KEY: "second"},
        options={},
        unique_id=UNIQUE_ID_ANTHROPIC,
        title=UNIQUE_ID_ANTHROPIC,
    )
    second.add_to_hass(hass)

    client = await hass_ws_client(hass)
    msg = await _save(client, entry, _basic())
    assert msg["success"], msg
    assert msg["result"]["reload_error"] is None
    assert hass.data[DOMAIN]["memory"].names() == ["conversations"]


async def test_save_rebuilds_the_registry(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    with patch("custom_components.smartchain._reload_registry", new_callable=AsyncMock) as reload:
        assert (await _save(client, entry, _basic()))["success"]
    reload.assert_awaited()


# --- credentials ----------------------------------------------------------


async def test_a_qdrant_key_never_comes_back_out(hass, hass_ws_client, entry):
    """The whole reason a store is a subentry rather than a line in a file the
    panel can read."""
    client = await hass_ws_client(hass)
    msg = await _save(
        client,
        entry,
        _basic(
            backend_type="qdrant",
            url="https://qdrant.example",
            api_key=QDRANT_SECRET,
            collection="memories",
        ),
    )
    assert msg["success"], msg
    assert _stores(entry)["conversations"].data["api_key"] == QDRANT_SECRET
    subentry_id = msg["result"]["subentry_id"]

    await client.send_json_auto_id(
        {
            "type": "smartchain/store/schema",
            "entry_id": entry.entry_id,
            "subentry_id": subentry_id,
        }
    )
    schema_msg = await client.receive_json()
    assert schema_msg["success"], schema_msg
    assert QDRANT_SECRET not in json.dumps(schema_msg)
    # What the form *is* told: that a key is held, so it can say "leave empty
    # to keep" rather than look like the key was lost.
    assert schema_msg["result"]["secrets_set"]["api_key"] is True


async def test_a_pgvector_dsn_never_comes_back_out(hass, hass_ws_client, entry):
    """A DSN embeds the database password, so it is write-only exactly as the
    qdrant key is — a distinction easy to miss, since only `api_key` looks like
    a credential by name."""
    client = await hass_ws_client(hass)
    msg = await _save(client, entry, _basic(backend_type="pgvector", dsn=PG_DSN, table="memories"))
    assert msg["success"], msg

    await client.send_json_auto_id(
        {
            "type": "smartchain/store/schema",
            "entry_id": entry.entry_id,
            "subentry_id": msg["result"]["subentry_id"],
        }
    )
    schema_msg = await client.receive_json()
    assert "pgpassword" not in json.dumps(schema_msg)
    assert schema_msg["result"]["secrets_set"]["dsn"] is True


async def test_an_omitted_key_keeps_the_stored_one(hass, hass_ws_client, entry):
    """The form never receives the key back, so an untouched edit submits it
    empty. Reading that as "clear it" would break the store on the first
    unrelated change."""
    client = await hass_ws_client(hass)
    created = await _save(
        client,
        entry,
        _basic(
            backend_type="qdrant",
            url="https://qdrant.example",
            api_key=QDRANT_SECRET,
            collection="memories",
        ),
    )
    subentry_id = created["result"]["subentry_id"]

    msg = await _save(
        client,
        entry,
        _basic(
            description="edited",
            backend_type="qdrant",
            url="https://qdrant.example",
            collection="memories",
        ),
        subentry_id=subentry_id,
    )
    assert msg["success"], msg
    stored = _stores(entry)["conversations"].data
    assert stored["api_key"] == QDRANT_SECRET
    assert stored["description"] == "edited"


async def test_switching_backend_drops_the_old_credential(hass, hass_ws_client, entry):
    """ "Empty means keep" must not outlive the field. Carrying a dsn into a
    qdrant store would leave a database password in storage for a store that no
    longer talks to a database."""
    client = await hass_ws_client(hass)
    created = await _save(
        client, entry, _basic(backend_type="pgvector", dsn=PG_DSN, table="memories")
    )
    subentry_id = created["result"]["subentry_id"]

    msg = await _save(
        client,
        entry,
        _basic(
            backend_type="qdrant",
            url="https://qdrant.example",
            api_key=QDRANT_SECRET,
            collection="memories",
        ),
        subentry_id=subentry_id,
    )
    assert msg["success"], msg
    assert "dsn" not in _stores(entry)["conversations"].data


async def test_no_response_carries_a_credential(hass, hass_ws_client, entry):
    """Success, rejection and not-found alike."""
    client = await hass_ws_client(hass)
    seen = []

    seen.append(
        await _save(
            client,
            entry,
            _basic(
                backend_type="qdrant",
                url="https://qdrant.example",
                api_key=QDRANT_SECRET,
                collection="memories",
            ),
        )
    )
    # Rejected: a bad collection name, submitted alongside the key.
    seen.append(
        await _save(
            client,
            entry,
            _basic(
                backend_type="qdrant",
                url="https://qdrant.example",
                api_key=QDRANT_SECRET,
                collection="Not A Valid Identifier",
            ),
        )
    )
    # Rejected by the schema itself, with the key present.
    seen.append(
        await _save(
            client,
            entry,
            {**_basic(backend_type="qdrant", api_key=QDRANT_SECRET), "nonsense": 1},
        )
    )
    seen.append(await _save(client, entry, _basic(api_key=QDRANT_SECRET), subentry_id="nope"))

    await client.send_json_auto_id({"type": "smartchain/store/status"})
    seen.append(await client.receive_json())

    for msg in seen:
        blob = json.dumps(msg)
        assert QDRANT_SECRET not in blob, msg
        assert PROVIDER_SECRET not in blob, msg


# --- validation -----------------------------------------------------------


async def test_an_entity_store_may_not_declare_retention(hass, hass_ws_client, entry):
    """Mirrors the YAML rule in tools/schema.py: retention would delete the
    index by age. The conditional schema simply does not declare the field, so
    PREVENT_EXTRA does the refusing."""
    client = await hass_ws_client(hass)
    msg = await _save(
        client,
        entry,
        {
            "name": "home_index",
            "embeddings": TITLE,
            "source_type": "entities",
            "preset": "optimal",
            "retention_days": 30,
        },
    )
    assert not msg["success"]
    assert "retention_days" in msg["error"]["message"]
    assert _stores(entry) == {}


async def test_an_entity_store_saves_its_own_fields(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    msg = await _save(
        client,
        entry,
        {
            "name": "home_index",
            "embeddings": TITLE,
            "source_type": "entities",
            "preset": "maximal",
            "index_states": True,
            "include": ["sensor"],
            "exclude": ["device_tracker"],
        },
    )
    assert msg["success"], msg
    config = store_config_from_subentry(_stores(entry)["home_index"])
    assert config.source.preset == "maximal"
    assert config.source.include == ["sensor"]


@pytest.mark.parametrize(
    ("data", "field"),
    [
        ({"name": "Not Valid"}, "name"),
        ({"backend_type": "pgvector", "table": "memories"}, "dsn"),
        ({"backend_type": "qdrant", "collection": "memories"}, "url"),
        ({"backend_type": "pgvector", "dsn": PG_DSN, "table": "Bad Table"}, "table"),
    ],
)
async def test_rules_the_schema_cannot_express_are_still_enforced(
    hass, hass_ws_client, entry, data, field
):
    """`vol.Match` does not serialise, so the name and identifier patterns
    cannot live in the schema the panel renders — they live in
    `validate_store_input`, which the config-flow dialog calls too."""
    client = await hass_ws_client(hass)
    msg = await _save(client, entry, _basic(**data))
    assert not msg["success"], msg
    assert msg["error"]["message"].startswith(f"invalid_data: {field}")
    assert _stores(entry) == {}


async def test_two_stores_on_one_entry_may_not_share_a_name(hass, hass_ws_client, entry):
    """Deliberately the *same* entry: the parked note on the embeddings work is
    that every collision test there builds two entries, leaving the one-entry
    case untested."""
    client = await hass_ws_client(hass)
    assert (await _save(client, entry, _basic()))["success"]
    msg = await _save(client, entry, _basic(description="a second one"))
    assert not msg["success"]
    assert msg["error"]["message"].startswith("invalid_data: name")
    assert len(_stores(entry)) == 1


async def test_a_store_may_not_bind_to_an_ambiguous_embeddings_title(
    hass, hass_ws_client, tmp_path, patched_store
):
    """A title claimed twice resolves to None and unbinds the store silently.
    Refused on the way in, not diagnosed afterwards."""
    del patched_store
    entry = await _make_entry(hass, titles=(TITLE, TITLE), tmp_path=tmp_path)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "smartchain/store/schema", "entry_id": entry.entry_id})
    schema_msg = await client.receive_json()
    assert schema_msg["result"]["embeddings_ambiguous"] == [TITLE]

    msg = await _save(client, entry, _basic())
    assert not msg["success"]
    assert msg["error"]["message"].startswith("invalid_data: embeddings")


async def test_a_store_may_not_bind_to_a_title_nobody_holds(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    msg = await _save(client, entry, _basic(embeddings="Nothing Named This"))
    assert not msg["success"]
    assert msg["error"]["message"].startswith("invalid_data: embeddings")


# --- editing and deleting -------------------------------------------------


async def test_editing_serves_current_values_and_reshapes_the_form(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    created = await _save(
        client,
        entry,
        _basic(
            backend_type="qdrant",
            url="https://qdrant.example",
            api_key=QDRANT_SECRET,
            collection="memories",
        ),
    )
    await client.send_json_auto_id(
        {
            "type": "smartchain/store/schema",
            "entry_id": entry.entry_id,
            "subentry_id": created["result"]["subentry_id"],
        }
    )
    msg = await client.receive_json()
    fields = {field["name"] for field in msg["result"]["schema"]}
    assert {"url", "collection", "verify_ssl"} <= fields
    # The other backends' fields are not declared, so <ha-form> cannot echo
    # them back into a save that PREVENT_EXTRA would then reject forever.
    assert "dsn" not in fields
    assert msg["result"]["data"]["url"] == "https://qdrant.example"
    assert msg["result"]["reactive"] == ["backend_type", "source_type"]


async def test_a_draft_backend_choice_reshapes_the_schema(hass, hass_ws_client, entry):
    """The panel keeps one form rather than a wizard, so the schema command
    accepts the values entered so far and rebuilds around them."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/store/schema",
            "entry_id": entry.entry_id,
            "data": {"backend_type": "pgvector"},
        }
    )
    msg = await client.receive_json()
    fields = {field["name"] for field in msg["result"]["schema"]}
    assert {"dsn", "table"} <= fields
    assert "url" not in fields


async def test_a_draft_credential_survives_a_reshape(hass, hass_ws_client, entry):
    """A value the client itself just sent is already the client's own, so
    echoing it back discloses nothing — and dropping it would silently erase a
    key typed before the user changed something else."""
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": "smartchain/store/schema",
            "entry_id": entry.entry_id,
            "data": {"backend_type": "qdrant", "api_key": QDRANT_SECRET},
        }
    )
    msg = await client.receive_json()
    assert msg["result"]["data"]["api_key"] == QDRANT_SECRET


async def test_delete_removes_the_store_and_rebuilds(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    created = await _save(client, entry, _basic())
    assert hass.data[DOMAIN]["memory"].names() == ["conversations"]

    await client.send_json_auto_id(
        {
            "type": "smartchain/store/delete",
            "entry_id": entry.entry_id,
            "subentry_id": created["result"]["subentry_id"],
        }
    )
    msg = await client.receive_json()
    assert msg["success"], msg
    assert msg["result"]["name"] == "conversations"
    assert _stores(entry) == {}
    assert hass.data[DOMAIN]["memory"].names() == []


async def test_store_commands_refuse_a_non_store_subentry(hass, hass_ws_client, entry):
    """The embeddings subentry on this entry must not be reachable through the
    store commands — a cross-type write would replace a binding's data with a
    store's."""
    client = await hass_ws_client(hass)
    embeddings_id = next(
        sub.subentry_id
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_TYPE_EMBEDDINGS
    )
    before = dict(entry.subentries)
    for command, extra in (
        ("schema", {}),
        ("save", {"data": _basic()}),
        ("delete", {}),
    ):
        await client.send_json_auto_id(
            {
                "type": f"smartchain/store/{command}",
                "entry_id": entry.entry_id,
                "subentry_id": embeddings_id,
                **extra,
            }
        )
        msg = await client.receive_json()
        assert not msg["success"], command
        assert msg["error"]["code"] == "not_found", command
    assert dict(entry.subentries) == before


# --- status ---------------------------------------------------------------


async def test_status_reports_a_store_that_did_not_come_up(
    hass, hass_ws_client, tmp_path, patched_store
):
    """MemoryRegistry contains a failing store so the others still start, which
    used to leave the failure invisible outside the log."""
    del patched_store
    entry = await _make_entry(
        hass,
        subentries=[_store_subentry("orphan", {"embeddings": "Nothing Named This"})],
        tmp_path=tmp_path,
    )
    client = await hass_ws_client(hass)
    await client.send_json_auto_id({"type": "smartchain/store/status"})
    msg = await client.receive_json()
    assert msg["success"], msg
    rows = {row["name"]: row for row in msg["result"]["stores"]}
    assert rows["orphan"]["ok"] is False
    assert "Nothing Named This" in rows["orphan"]["reason"]
    assert rows["orphan"]["source"] == "subentry"
    assert entry.entry_id  # the entry is what carried the store


async def test_status_reports_a_live_store(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    assert (await _save(client, entry, _basic()))["success"]
    await client.send_json_auto_id({"type": "smartchain/store/status"})
    msg = await client.receive_json()
    rows = {row["name"]: row for row in msg["result"]["stores"]}
    assert rows["conversations"] == {
        "name": "conversations",
        "ok": True,
        "reason": None,
        "source": "subentry",
        "entity_index": False,
    }


async def test_a_yaml_name_collision_is_reported_not_silent(
    hass, hass_ws_client, tmp_path_factory, patched_store
):
    """Break-it anchor: make `merge_store_sources` prefer the YAML store and
    this fails, because nothing is shadowed any more."""
    del patched_store
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text(
        "tools: []\nmemory:\n  stores:\n    - name: conversations\n"
        f'      embeddings: "{OTHER_TITLE}"\n'
    )
    entry = await _make_entry(hass, titles=(TITLE, OTHER_TITLE), tmp_path=cdir)

    client = await hass_ws_client(hass)
    msg = await _save(client, entry, _basic())
    assert msg["success"], msg
    assert msg["result"]["shadows_yaml"] is True

    await client.send_json_auto_id({"type": "smartchain/store/status"})
    status = await client.receive_json()
    assert status["result"]["shadowed_yaml"] == ["conversations"]
    assert hass.data[DOMAIN]["memory"].config_for("conversations").embeddings == TITLE


# --- overview and access --------------------------------------------------


async def test_the_overview_lists_stores_without_their_credentials(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    assert (
        await _save(
            client,
            entry,
            _basic(
                backend_type="qdrant",
                url="https://qdrant.example",
                api_key=QDRANT_SECRET,
                collection="memories",
            ),
        )
    )["success"]

    await client.send_json_auto_id({"type": "smartchain/overview"})
    msg = await client.receive_json()
    assert msg["success"], msg
    assert QDRANT_SECRET not in json.dumps(msg)
    store = msg["result"]["entries"][0]["stores"][0]
    assert store["title"] == "conversations"
    assert store["backend_type"] == "qdrant"
    assert store["secrets_set"]["api_key"] is True
    assert store["ok"] is True


async def test_store_commands_require_admin(hass, hass_ws_client, hass_admin_user, entry):
    hass_admin_user.groups = []
    client = await hass_ws_client(hass)
    for command, extra in (
        ("schema", {"entry_id": entry.entry_id}),
        ("save", {"entry_id": entry.entry_id, "data": _basic()}),
        ("delete", {"entry_id": entry.entry_id, "subentry_id": "does-not-matter"}),
        ("status", {}),
    ):
        await client.send_json_auto_id({"type": f"smartchain/store/{command}", **extra})
        msg = await client.receive_json()
        assert not msg["success"], command
        assert msg["error"]["code"] == "unauthorized", command
    assert _stores(entry) == {}


async def test_store_commands_refuse_an_unknown_entry(hass, hass_ws_client, entry):
    client = await hass_ws_client(hass)
    for command, extra in (
        ("schema", {}),
        ("save", {"data": _basic()}),
        ("delete", {"subentry_id": "x"}),
    ):
        await client.send_json_auto_id(
            {"type": f"smartchain/store/{command}", "entry_id": "no-such-entry", **extra}
        )
        msg = await client.receive_json()
        assert not msg["success"], command
        assert msg["error"]["code"] == "not_found", command
