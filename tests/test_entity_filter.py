"""Preset expansion decides what the home looks like to the model."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.config import EntitySourceConfig
from custom_components.smartchain.tools.memory.entity_filter import (
    EntityCandidate,
    resolve_candidates,
)


def _entry(
    entity_id: str,
    *,
    name: str = "",
    area_id: str | None = None,
    device_id: str | None = None,
    device_class: str | None = None,
    entity_category: EntityCategory | None = None,
    hidden: bool = False,
    disabled: bool = False,
    aliases: set[str] | None = None,
) -> MagicMock:
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.name = name or None
    entry.original_name = name or entity_id
    entry.area_id = area_id
    entry.device_id = device_id
    entry.device_class = device_class
    entry.original_device_class = device_class
    entry.entity_category = entity_category
    entry.hidden_by = "user" if hidden else None
    entry.disabled_by = "user" if disabled else None
    entry.aliases = aliases or set()
    return entry


@pytest.fixture
async def home(hass: HomeAssistant):
    """A small home covering every branch the presets can take."""
    entries = [
        _entry("light.ceiling", name="Потолок", area_id="kitchen", aliases={"люстра"}),
        _entry("switch.socket", name="Кофеварка", area_id="kitchen"),
        _entry("sensor.temp", name="Температура", area_id="kitchen", device_class="temperature"),
        _entry("sensor.battery", name="Батарея", device_class="battery"),
        _entry("sensor.uptime", name="Аптайм", entity_category=EntityCategory.DIAGNOSTIC),
        _entry("update.firmware", name="Прошивка"),
        _entry("light.hidden_one", name="Скрытый", hidden=True),
        _entry("light.disabled_one", name="Отключённый", disabled=True),
    ]
    ent_reg = MagicMock()
    ent_reg.entities = {e.entity_id: e for e in entries}

    area = MagicMock()
    area.name = "Кухня"
    area_reg = MagicMock()
    area_reg.async_get_area.side_effect = lambda aid: area if aid == "kitchen" else None

    dev_reg = MagicMock()
    dev_reg.async_get.return_value = None

    # A template sensor that exists only in the state machine.
    hass.states.async_set(
        "sensor.template_only", "42", {"friendly_name": "Шаблонный", "device_class": "humidity"}
    )
    for e in entries:
        if not e.disabled_by:
            hass.states.async_set(e.entity_id, "on", {"friendly_name": e.original_name})

    with (
        patch(
            "custom_components.smartchain.tools.memory.entity_filter.er.async_get",
            return_value=ent_reg,
        ),
        patch(
            "custom_components.smartchain.tools.memory.entity_filter.ar.async_get",
            return_value=area_reg,
        ),
        patch(
            "custom_components.smartchain.tools.memory.entity_filter.dr.async_get",
            return_value=dev_reg,
        ),
    ):
        yield


def _ids(hass, **kwargs) -> set[str]:
    return set(resolve_candidates(hass, EntitySourceConfig(**kwargs)))


def test_minimal_is_controllables_only(hass: HomeAssistant, home) -> None:
    assert _ids(hass, preset="minimal") == {"light.ceiling", "switch.socket"}


def test_optimal_adds_meaningful_sensors(hass: HomeAssistant, home) -> None:
    assert _ids(hass, preset="optimal") == {
        "light.ceiling",
        "switch.socket",
        "sensor.temp",
        "sensor.template_only",
    }


def test_optimal_drops_noise_and_diagnostics(hass: HomeAssistant, home) -> None:
    got = _ids(hass, preset="optimal")
    assert "sensor.battery" not in got
    assert "sensor.uptime" not in got
    assert "update.firmware" not in got


def test_maximal_takes_everything_visible(hass: HomeAssistant, home) -> None:
    got = _ids(hass, preset="maximal")
    assert "update.firmware" in got
    assert "sensor.battery" in got
    assert "sensor.uptime" in got
    assert "light.hidden_one" not in got
    assert "light.disabled_one" not in got


def test_paranoid_takes_hidden_and_disabled_too(hass: HomeAssistant, home) -> None:
    got = _ids(hass, preset="paranoid")
    assert "light.hidden_one" in got
    assert "light.disabled_one" in got


def test_state_only_entities_are_not_lost(hass: HomeAssistant, home) -> None:
    """Template sensors have no registry entry and would otherwise vanish."""
    assert "sensor.template_only" in _ids(hass, preset="maximal")


def test_include_adds_on_top_of_the_preset(hass: HomeAssistant, home) -> None:
    got = _ids(hass, preset="minimal", include=["sensor.battery"])
    assert "sensor.battery" in got
    assert "sensor.temp" not in got


def test_include_accepts_a_bare_domain(hass: HomeAssistant, home) -> None:
    assert "update.firmware" in _ids(hass, preset="minimal", include=["update"])


def test_exclude_wins_over_the_preset(hass: HomeAssistant, home) -> None:
    assert "light.ceiling" not in _ids(hass, preset="minimal", exclude=["light.ceiling"])


def test_exclude_wins_over_include(hass: HomeAssistant, home) -> None:
    got = _ids(hass, preset="minimal", include=["sensor.battery"], exclude=["sensor.battery"])
    assert "sensor.battery" not in got


def test_exclude_accepts_a_bare_domain(hass: HomeAssistant, home) -> None:
    assert not [
        e for e in _ids(hass, preset="maximal", exclude=["update"]) if e.startswith("update.")
    ]


def test_candidate_carries_the_searchable_fields(hass: HomeAssistant, home) -> None:
    cand = resolve_candidates(hass, EntitySourceConfig(preset="minimal"))["light.ceiling"]
    assert isinstance(cand, EntityCandidate)
    assert cand.domain == "light"
    assert cand.name == "Потолок"
    assert cand.area == "Кухня"
    assert cand.aliases == ("люстра",)
