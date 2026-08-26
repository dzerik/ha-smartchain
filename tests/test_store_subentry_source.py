"""Memory stores read out of config subentries, and merged with tools.yaml.

A store used to have exactly one source — the `memory:` block of tools.yaml.
It now has two, and the interesting behaviour is entirely at the seam: both
sources must produce the *same* dataclass, an existing tools.yaml must keep
working untouched, and a name defined in both must resolve one way, loudly.
"""

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import ConfigSubentryData
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_OPENAI,
    SUBENTRY_TYPE_EMBEDDINGS,
    SUBENTRY_TYPE_MEMORY_STORE,
    UNIQUE_ID_OPENAI,
)
from custom_components.smartchain.tools.loader import load_tools_file
from custom_components.smartchain.tools.memory.config import StoreConfig
from custom_components.smartchain.tools.memory.subentry_source import (
    SOURCE_SUBENTRY,
    SOURCE_YAML,
    merge_store_sources,
    store_config_from_subentry,
    stores_from_subentries,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

TITLE = "OpenAI Embeddings"
OTHER_TITLE = "Second Embeddings"


@pytest.fixture
def patched_store():
    """MemoryStore and embeddings construction stubbed out, so build() needs no
    real backend and no real provider — the technique tests/test_memory_multi_store
    and tests/test_ws_embeddings already use."""

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


def _subentry(title: str, data: dict) -> ConfigSubentryData:
    return ConfigSubentryData(
        data=data, subentry_type=SUBENTRY_TYPE_MEMORY_STORE, title=title, unique_id=None
    )


def _entry(hass: HomeAssistant, *, stores=(), titles=(TITLE,)) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_OPENAI, CONF_API_KEY: "sk-not-a-real-key"},
        options={},
        unique_id=UNIQUE_ID_OPENAI,
        subentries_data=[
            ConfigSubentryData(
                data={"model": "text-embedding-3-small"},
                subentry_type=SUBENTRY_TYPE_EMBEDDINGS,
                title=title,
                unique_id=None,
            )
            for title in titles
        ]
        + list(stores),
    )
    entry.add_to_hass(hass)
    return entry


# --- one dataclass, two sources -----------------------------------------


def test_subentry_and_yaml_produce_the_same_store_config(hass, tmp_path) -> None:
    """The assertion that pins the two paths together.

    If they drift, a store behaves differently depending on where it was
    written, which is exactly the failure this whole item exists to avoid.
    """
    yaml_path = tmp_path / "tools.yaml"
    yaml_path.write_text(
        "tools: []\n"
        "memory:\n"
        "  stores:\n"
        "    - name: conversations\n"
        '      embeddings: "OpenAI Embeddings"\n'
        '      description: "Dialogue history"\n'
        "      retention_days: 30\n"
        "      ingest_conversation: true\n"
    )
    from_yaml = load_tools_file(yaml_path).memory_settings.stores[0]

    subentry = MagicMock()
    subentry.title = "conversations"
    subentry.data = {
        "embeddings": TITLE,
        "description": "Dialogue history",
        "backend_type": "sqlite_numpy",
        "source_type": "none",
        "retention_days": 30,
        "ingest_conversation": True,
    }
    assert store_config_from_subentry(subentry) == from_yaml


def test_entity_source_subentry_matches_its_yaml_twin(hass, tmp_path) -> None:
    yaml_path = tmp_path / "tools.yaml"
    yaml_path.write_text(
        "tools: []\n"
        "memory:\n"
        "  stores:\n"
        "    - name: home_index\n"
        '      embeddings: "OpenAI Embeddings"\n'
        "      source:\n"
        "        type: entities\n"
        "        preset: maximal\n"
        "        index_states: true\n"
        "        include: [sensor]\n"
        "        exclude: [device_tracker]\n"
    )
    from_yaml = load_tools_file(yaml_path).memory_settings.stores[0]

    subentry = MagicMock()
    subentry.title = "home_index"
    subentry.data = {
        "embeddings": TITLE,
        "description": "",
        "backend_type": "sqlite_numpy",
        "source_type": "entities",
        "preset": "maximal",
        "index_states": True,
        "include": ["sensor"],
        "exclude": ["device_tracker"],
    }
    assert store_config_from_subentry(subentry) == from_yaml


def test_a_number_selector_float_becomes_an_int(hass) -> None:
    """NumberSelector hands back a float; StoreConfig.retention_days is an int,
    and RetentionTask does date arithmetic with it."""
    subentry = MagicMock()
    subentry.title = "conversations"
    subentry.data = {"embeddings": TITLE, "retention_days": 30.0}
    assert store_config_from_subentry(subentry).retention_days == 30


# --- collecting them ------------------------------------------------------


async def test_stores_from_subentries_collects_every_entry(hass) -> None:
    _entry(
        hass,
        stores=[
            _subentry("conversations", {"embeddings": TITLE}),
            _subentry("notes", {"embeddings": TITLE}),
        ],
    )
    names = [store.name for store in stores_from_subentries(hass)]
    assert names == ["conversations", "notes"]


async def test_two_subentries_with_one_name_keep_the_first(hass, caplog) -> None:
    """Nothing in Home Assistant stops two subentries sharing a title, and the
    registry keys stores by name — so the second would silently replace the
    first. It is dropped with an error instead."""
    _entry(
        hass,
        stores=[
            _subentry("conversations", {"embeddings": TITLE}),
            _subentry("conversations", {"embeddings": OTHER_TITLE}),
        ],
        titles=(TITLE, OTHER_TITLE),
    )
    with caplog.at_level(logging.ERROR):
        stores = stores_from_subentries(hass)
    assert [store.embeddings for store in stores] == [TITLE]
    assert "both named 'conversations'" in caplog.text


# --- merging --------------------------------------------------------------


def test_merge_keeps_both_sources() -> None:
    settings, sources, shadowed = merge_store_sources(
        [StoreConfig(name="from_yaml", embeddings=TITLE)],
        [StoreConfig(name="from_ui", embeddings=TITLE)],
    )
    assert sorted(settings.names()) == ["from_ui", "from_yaml"]
    assert sources == {"from_yaml": SOURCE_YAML, "from_ui": SOURCE_SUBENTRY}
    assert shadowed == []


def test_merge_prefers_the_subentry_and_says_so(caplog) -> None:
    """The subentry wins because it is the one the panel can edit. Losing to a
    file the UI cannot safely rewrite would make the UI a read-only display of
    something it appears to control."""
    with caplog.at_level(logging.WARNING):
        settings, sources, shadowed = merge_store_sources(
            [StoreConfig(name="conversations", embeddings="from-yaml")],
            [StoreConfig(name="conversations", embeddings="from-subentry")],
        )
    assert [store.embeddings for store in settings.stores] == ["from-subentry"]
    assert sources == {"conversations": SOURCE_SUBENTRY}
    assert shadowed == ["conversations"]
    assert "defined both in tools.yaml and as a config subentry" in caplog.text


# --- through the real reload path ----------------------------------------


async def _setup(hass, tmp_path_factory, yaml_text: str, stores) -> MockConfigEntry:
    cdir = tmp_path_factory.mktemp("ha")
    (cdir / "smartchain").mkdir()
    (cdir / "smartchain" / "tools.yaml").write_text(yaml_text)
    hass.config.config_dir = str(cdir)
    entry = _entry(hass, stores=stores, titles=(TITLE, OTHER_TITLE))
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    return entry


async def test_an_existing_tools_yaml_still_works(hass, tmp_path_factory, patched_store) -> None:
    """The regression that matters most: a user with a tools.yaml must not lose
    their stores by upgrading into a release that added the UI."""
    await _setup(
        hass,
        tmp_path_factory,
        f'tools: []\nmemory:\n  stores:\n    - name: conversations\n      embeddings: "{TITLE}"\n',
        stores=[],
    )
    registry = hass.data[DOMAIN]["memory"]
    assert registry.names() == ["conversations"]
    assert registry.sources == {"conversations": SOURCE_YAML}


async def test_a_subentry_store_reaches_the_registry(hass, tmp_path_factory, patched_store) -> None:
    await _setup(
        hass,
        tmp_path_factory,
        "tools: []\n",
        stores=[_subentry("notes", {"embeddings": TITLE})],
    )
    registry = hass.data[DOMAIN]["memory"]
    assert registry.names() == ["notes"]
    assert registry.sources == {"notes": SOURCE_SUBENTRY}


async def test_a_subentry_store_shadows_the_yaml_store_of_the_same_name(
    hass, tmp_path_factory, patched_store
) -> None:
    """Break-it check anchor: flipping `merge_store_sources` to prefer the YAML
    store makes this fail, because the surviving store's binding is the other
    source's."""
    await _setup(
        hass,
        tmp_path_factory,
        f'tools: []\nmemory:\n  stores:\n    - name: conversations\n      embeddings: "{TITLE}"\n',
        stores=[_subentry("conversations", {"embeddings": OTHER_TITLE})],
    )
    registry = hass.data[DOMAIN]["memory"]
    assert registry.names() == ["conversations"]
    assert registry.config_for("conversations").embeddings == OTHER_TITLE
    assert registry.sources == {"conversations": SOURCE_SUBENTRY}
    assert hass.data[DOMAIN]["store_shadowed"] == ["conversations"]


async def test_config_dir_yaml_is_untouched_when_only_subentries_exist(
    hass, tmp_path_factory, patched_store
) -> None:
    """No tools.yaml at all is the normal state for a fresh install; the store
    subentry must not need one."""
    cdir = tmp_path_factory.mktemp("ha")
    hass.config.config_dir = str(cdir)
    _entry(hass, stores=[_subentry("notes", {"embeddings": TITLE})])
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert not (Path(cdir) / "smartchain" / "tools.yaml").exists()
    assert hass.data[DOMAIN]["memory"].names() == ["notes"]
