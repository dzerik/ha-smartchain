"""MemoryRegistry resolves embeddings references and owns per-store tasks."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
)
from custom_components.smartchain.tools.memory.backends import BackendInitError
from custom_components.smartchain.tools.memory.config import (
    MemorySettings,
    StoreConfig,
)
from custom_components.smartchain.tools.memory.embeddings import EmbeddingsConfigError
from custom_components.smartchain.tools.memory.entity_index import EntityIndexer
from custom_components.smartchain.tools.memory.registry import MemoryRegistry

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def _entry_with_embeddings(hass: HomeAssistant, titles: list[str]) -> MockConfigEntry:
    from homeassistant.config_entries import ConfigSubentryData

    from custom_components.smartchain.const import SUBENTRY_TYPE_EMBEDDINGS

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "k"},
        options={},
        unique_id="GigaChat",
        subentries_data=[
            ConfigSubentryData(
                data={"model": "Embeddings"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title=title,
                unique_id=None,
            )
            for title in titles
        ],
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def patched_store():
    """Patch MemoryStore so no real backend or embeddings provider is needed."""
    made: list[MagicMock] = []

    def _factory(hass, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.backend = backend
        made.append(st)
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
        yield made


async def test_build_resolves_reference_by_title(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["GigaChat Embeddings"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[StoreConfig(name="conversations", embeddings="GigaChat Embeddings")]
        ),
        tmp_path,
    )
    assert registry.names() == ["conversations"]
    assert registry.get("conversations") is not None
    await registry.shutdown()


async def test_missing_reference_skips_only_that_store(
    hass: HomeAssistant, tmp_path, patched_store, caplog
) -> None:
    _entry_with_embeddings(hass, ["GigaChat Embeddings"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="good", embeddings="GigaChat Embeddings"),
                StoreConfig(name="bad", embeddings="Does Not Exist"),
            ]
        ),
        tmp_path,
    )
    assert registry.names() == ["good"]
    assert "Does Not Exist" in caplog.text
    assert "GigaChat Embeddings" in caplog.text  # available titles are listed
    await registry.shutdown()


async def test_duplicate_titles_skip_the_store(
    hass: HomeAssistant, tmp_path, patched_store, caplog
) -> None:
    _entry_with_embeddings(hass, ["Dup", "Dup"])
    registry = MemoryRegistry(hass)
    await registry.build(MemorySettings(stores=[StoreConfig(name="s", embeddings="Dup")]), tmp_path)
    assert registry.names() == []
    assert "duplicate" in caplog.text.lower()
    await registry.shutdown()


async def test_get_none_returns_single_store(hass: HomeAssistant, tmp_path, patched_store) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(stores=[StoreConfig(name="only", embeddings="E")]), tmp_path
    )
    assert registry.get(None) is registry.get("only")
    await registry.shutdown()


async def test_get_none_is_ambiguous_with_two_stores(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="a", embeddings="E"),
                StoreConfig(name="b", embeddings="E"),
            ]
        ),
        tmp_path,
    )
    assert registry.get(None) is None
    await registry.shutdown()


async def test_unavailable_store_is_not_registered(hass: HomeAssistant, tmp_path) -> None:
    _entry_with_embeddings(hass, ["E"])

    def _factory(hass_, embeddings, backend):
        st = MagicMock()
        st.is_available = False
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
        registry = MemoryRegistry(hass)
        await registry.build(
            MemorySettings(stores=[StoreConfig(name="s", embeddings="E")]), tmp_path
        )
    assert registry.names() == []
    await registry.shutdown()


async def test_embeddings_failure_skips_only_that_store(
    hass: HomeAssistant, tmp_path, caplog
) -> None:
    _entry_with_embeddings(hass, ["Embed A", "Embed B"])

    def _store_factory(hass_, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.backend = backend
        return st

    def _embeddings_side_effect(hass_, entry, subentry):
        if subentry.title == "Embed A":
            raise EmbeddingsConfigError("boom")
        return MagicMock()

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_store_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry.create_embeddings_from_subentry",
            side_effect=_embeddings_side_effect,
        ),
    ):
        registry = MemoryRegistry(hass)
        await registry.build(
            MemorySettings(
                stores=[
                    StoreConfig(name="bad", embeddings="Embed A"),
                    StoreConfig(name="good", embeddings="Embed B"),
                ]
            ),
            tmp_path,
        )
    assert registry.names() == ["good"]
    assert "bad" in caplog.text
    await registry.shutdown()


async def test_backend_failure_skips_only_that_store(hass: HomeAssistant, tmp_path, caplog) -> None:
    _entry_with_embeddings(hass, ["Embed A", "Embed B"])

    def _store_factory(hass_, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.backend = backend
        return st

    def _backend_side_effect(hass_, config, store_name, storage_dir):
        if store_name == "bad":
            raise BackendInitError("boom")
        return MagicMock()

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
            "custom_components.smartchain.tools.memory.registry.create_backend",
            side_effect=_backend_side_effect,
        ),
    ):
        registry = MemoryRegistry(hass)
        await registry.build(
            MemorySettings(
                stores=[
                    StoreConfig(name="bad", embeddings="Embed A"),
                    StoreConfig(name="good", embeddings="Embed B"),
                ]
            ),
            tmp_path,
        )
    assert registry.names() == ["good"]
    assert "bad" in caplog.text
    await registry.shutdown()


async def test_describe_returns_names_and_descriptions(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(stores=[StoreConfig(name="a", embeddings="E", description="First store")]),
        tmp_path,
    )
    assert registry.describe() == [("a", "First store")]
    await registry.shutdown()


async def test_conversation_ingest_targets_respect_the_flag(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="yes", embeddings="E", ingest_conversation=True),
                StoreConfig(name="no", embeddings="E", ingest_conversation=False),
            ]
        ),
        tmp_path,
    )
    targets = registry.stores_for_conversation_ingest()
    assert len(targets) == 1
    assert targets[0] is registry.get("yes")
    await registry.shutdown()


async def test_shutdown_closes_every_store(hass: HomeAssistant, tmp_path, patched_store) -> None:
    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="a", embeddings="E"),
                StoreConfig(name="b", embeddings="E"),
            ]
        ),
        tmp_path,
    )
    await registry.shutdown()

    assert registry.names() == []
    for store in patched_store:
        store.close.assert_awaited()


async def test_bare_exception_from_embeddings_skips_only_that_store(
    hass: HomeAssistant, tmp_path, caplog
) -> None:
    """A KeyError must not escape build() and take every other store with it.

    create_embeddings_from_subentry indexes entry.data[CONF_API_KEY] directly
    and builds pydantic models, so a malformed entry raises KeyError or
    ValidationError rather than EmbeddingsConfigError. Anything escaping build()
    reaches _reload_registry, which discards the whole new registry.
    """
    _entry_with_embeddings(hass, ["Embed A", "Embed B"])

    def _store_factory(hass_, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.backend = backend
        return st

    def _embeddings_side_effect(hass_, entry, subentry):
        if subentry.title == "Embed A":
            raise KeyError(CONF_API_KEY)
        return MagicMock()

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.MemoryStore",
            side_effect=_store_factory,
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry.create_embeddings_from_subentry",
            side_effect=_embeddings_side_effect,
        ),
    ):
        registry = MemoryRegistry(hass)
        await registry.build(
            MemorySettings(
                stores=[
                    StoreConfig(name="bad", embeddings="Embed A"),
                    StoreConfig(name="good", embeddings="Embed B"),
                ]
            ),
            tmp_path,
        )

    assert registry.names() == ["good"]
    assert "bad" in caplog.text
    await registry.shutdown()


async def test_an_entity_source_gets_an_indexer_not_ingest_plumbing(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    with patch(
        "custom_components.smartchain.tools.memory.registry.EntityIndexer",
        spec=EntityIndexer,
    ) as indexer_cls:
        await registry.build(
            MemorySettings(
                stores=[
                    StoreConfig(name="entities", embeddings="E", source=EntitySourceConfig()),
                    StoreConfig(name="talk", embeddings="E"),
                ]
            ),
            tmp_path,
        )

    assert registry.entity_store_names() == ["entities"]
    assert registry.indexer_for("entities") is not None
    assert registry.indexer_for("talk") is None
    indexer_cls.return_value.start.assert_called_once()
    await registry.shutdown()


async def test_an_entity_store_is_excluded_from_conversation_ingest(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    """Even if the flag defaulted true, an entity store must never take turns."""
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    with patch(
        "custom_components.smartchain.tools.memory.registry.EntityIndexer",
        spec=EntityIndexer,
    ):
        await registry.build(
            MemorySettings(
                stores=[
                    StoreConfig(name="entities", embeddings="E", source=EntitySourceConfig()),
                    StoreConfig(name="talk", embeddings="E"),
                ]
            ),
            tmp_path,
        )

    targets = registry.stores_for_conversation_ingest()
    assert targets == [registry.get("talk")]
    await registry.shutdown()


async def test_shutdown_stops_every_indexer(hass: HomeAssistant, tmp_path, patched_store) -> None:
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    with patch(
        "custom_components.smartchain.tools.memory.registry.EntityIndexer",
        spec=EntityIndexer,
    ) as indexer_cls:
        indexer_cls.return_value.stop = AsyncMock()
        await registry.build(
            MemorySettings(
                stores=[StoreConfig(name="entities", embeddings="E", source=EntitySourceConfig())]
            ),
            tmp_path,
        )
        await registry.shutdown()

    indexer_cls.return_value.stop.assert_awaited()
    assert registry.entity_store_names() == []


async def test_an_entity_store_gets_no_retention_or_poller(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    """Retention on an entity index would delete it by age."""
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.EntityIndexer",
            spec=EntityIndexer,
        ),
        patch("custom_components.smartchain.tools.memory.registry.RetentionTask") as ret,
        patch("custom_components.smartchain.tools.memory.registry.MemoryLogbookPoller") as poll,
    ):
        await registry.build(
            MemorySettings(
                stores=[StoreConfig(name="entities", embeddings="E", source=EntitySourceConfig())]
            ),
            tmp_path,
        )

    assert ret.call_count == 0
    assert poll.call_count == 0
    await registry.shutdown()


async def test_entity_indexer_construction_failure_skips_only_that_store(
    hass: HomeAssistant, tmp_path, patched_store, caplog
) -> None:
    """EntityIndexer.start() does real work (registry subscriptions, and with
    index_states on, resolve_candidates + a state listener) so it is far more
    likely to raise than constructing a RetentionTask. A raise there must not
    take the whole build() down with it.
    """
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    with patch(
        "custom_components.smartchain.tools.memory.registry.EntityIndexer",
        spec=EntityIndexer,
        side_effect=RuntimeError("boom"),
    ):
        await registry.build(
            MemorySettings(
                stores=[
                    StoreConfig(name="entities", embeddings="E", source=EntitySourceConfig()),
                    StoreConfig(name="talk", embeddings="E"),
                ]
            ),
            tmp_path,
        )

    assert registry.names() == ["talk"]
    assert registry.entity_store_names() == []
    assert registry.indexer_for("entities") is None
    assert "entities" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "boom" not in caplog.text  # type only — never the exception message
    await registry.shutdown()


async def test_registry_stays_consistent_after_an_entity_store_start_failure(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    """After a failed start, describe(), entity_store_names() and
    stores_for_conversation_ingest() must all still work and none of them may
    mention the store that failed — a KeyError here would mean the store was
    left half-registered.
    """
    from custom_components.smartchain.tools.memory.config import EntitySourceConfig

    _entry_with_embeddings(hass, ["E"])
    registry = MemoryRegistry(hass)
    with patch(
        "custom_components.smartchain.tools.memory.registry.EntityIndexer",
        spec=EntityIndexer,
        side_effect=RuntimeError("boom"),
    ):
        await registry.build(
            MemorySettings(
                stores=[
                    StoreConfig(
                        name="entities",
                        embeddings="E",
                        description="Entities",
                        source=EntitySourceConfig(),
                    ),
                    StoreConfig(name="talk", embeddings="E", description="Talk"),
                ]
            ),
            tmp_path,
        )

    assert registry.describe() == [("talk", "Talk")]
    assert registry.entity_store_names() == []
    assert registry.indexer_for("entities") is None
    targets = registry.stores_for_conversation_ingest()
    assert targets == [registry.get("talk")]
    await registry.shutdown()


async def test_bare_exception_from_create_backend_skips_only_that_store(
    hass: HomeAssistant, tmp_path, caplog
) -> None:
    """Same containment for create_backend, which can raise ValueError/OSError."""
    _entry_with_embeddings(hass, ["Embed A", "Embed B"])

    def _store_factory(hass_, embeddings, backend):
        st = MagicMock()
        st.is_available = True
        st.async_setup = AsyncMock()
        st.close = AsyncMock()
        st.backend = backend
        return st

    def _backend_side_effect(hass_, config, store_name, storage_dir):
        if store_name == "bad":
            raise ValueError("not a BackendInitError")
        return MagicMock()

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
            "custom_components.smartchain.tools.memory.registry.create_backend",
            side_effect=_backend_side_effect,
        ),
    ):
        registry = MemoryRegistry(hass)
        await registry.build(
            MemorySettings(
                stores=[
                    StoreConfig(name="bad", embeddings="Embed A"),
                    StoreConfig(name="good", embeddings="Embed B"),
                ]
            ),
            tmp_path,
        )

    assert registry.names() == ["good"]
    assert "bad" in caplog.text
    await registry.shutdown()


# --- failure visibility ---------------------------------------------------
#
# `build` contains a failing store so the others still start. That containment
# used to be total: nothing downstream could tell a *configured* store from a
# *live* one, so every command that touched memory reported success over a
# subsystem that never came up, and the only trace was a log line.


async def test_a_missing_binding_is_recorded_as_a_failure(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["Embed A"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="live", embeddings="Embed A"),
                StoreConfig(name="orphan", embeddings="Nothing Named This"),
            ]
        ),
        tmp_path,
    )
    assert registry.names() == ["live"]
    assert "Nothing Named This" in registry.failures["orphan"]
    assert "live" not in registry.failures
    await registry.shutdown()


async def test_a_backend_failure_is_recorded_with_a_safe_reason(
    hass: HomeAssistant, tmp_path
) -> None:
    """BackendInitError messages are built from literal text by every backend
    that raises one, which is why the message itself may travel."""
    _entry_with_embeddings(hass, ["Embed A"])

    with (
        patch(
            "custom_components.smartchain.tools.memory.registry.create_embeddings_from_subentry",
            return_value=MagicMock(),
        ),
        patch(
            "custom_components.smartchain.tools.memory.registry.create_backend",
            side_effect=BackendInitError("pgvector could not connect"),
        ),
    ):
        registry = MemoryRegistry(hass)
        await registry.build(
            MemorySettings(stores=[StoreConfig(name="pg", embeddings="Embed A")]), tmp_path
        )

    assert registry.failures["pg"] == "pgvector could not connect"


async def test_an_unexpected_failure_records_the_type_only(hass: HomeAssistant, tmp_path) -> None:
    """A pydantic ValidationError renders `input_value`, which on this path is
    the provider credential — so the type name is all that is kept."""
    _entry_with_embeddings(hass, ["Embed A"])

    with patch(
        "custom_components.smartchain.tools.memory.registry.create_embeddings_from_subentry",
        side_effect=ValueError("api_key=sk-super-secret is malformed"),
    ):
        registry = MemoryRegistry(hass)
        await registry.build(
            MemorySettings(stores=[StoreConfig(name="oops", embeddings="Embed A")]), tmp_path
        )

    assert "sk-super-secret" not in registry.failures["oops"]
    assert "ValueError" in registry.failures["oops"]


async def test_status_lists_live_and_failed_stores_together(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    _entry_with_embeddings(hass, ["Embed A"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(
            stores=[
                StoreConfig(name="live", embeddings="Embed A"),
                StoreConfig(name="orphan", embeddings="gone"),
            ]
        ),
        tmp_path,
        {"live": "subentry", "orphan": "yaml"},
    )
    rows = {row["name"]: row for row in registry.status()}
    assert rows["live"]["ok"] is True
    assert rows["live"]["source"] == "subentry"
    assert rows["orphan"]["ok"] is False
    assert rows["orphan"]["source"] == "yaml"
    await registry.shutdown()


async def test_a_rebuild_clears_the_previous_failures(
    hass: HomeAssistant, tmp_path, patched_store
) -> None:
    """A registry that kept a stale failure would report a store as broken long
    after the user fixed it."""
    _entry_with_embeddings(hass, ["Embed A"])
    registry = MemoryRegistry(hass)
    await registry.build(
        MemorySettings(stores=[StoreConfig(name="s", embeddings="gone")]), tmp_path
    )
    assert registry.failures
    await registry.build(
        MemorySettings(stores=[StoreConfig(name="s", embeddings="Embed A")]), tmp_path
    )
    assert registry.failures == {}
    await registry.shutdown()


async def test_a_store_that_did_not_come_up_reports_the_store_s_own_reason(
    hass: HomeAssistant, tmp_path
) -> None:
    _entry_with_embeddings(hass, ["Embed A"])

    def _factory(hass_, embeddings, backend):
        st = MagicMock()
        st.is_available = False
        st.unavailable_reason = "the embeddings provider did not answer"
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
        patch(
            "custom_components.smartchain.tools.memory.registry.create_backend",
            return_value=MagicMock(),
        ),
    ):
        registry = MemoryRegistry(hass)
        await registry.build(
            MemorySettings(stores=[StoreConfig(name="s", embeddings="Embed A")]), tmp_path
        )

    assert registry.failures["s"] == "the embeddings provider did not answer"
