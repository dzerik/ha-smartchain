"""Decide which Home Assistant entities belong in an entity index.

Deliberately free of I/O and of any dependency on a running indexer: the
`search_entities` tool calls this directly when its store is unavailable, and
that fallback is only real if candidate selection needs nothing but the
registries and the state machine.
"""

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from ...const import (
    ENTITY_MEANINGFUL_DEVICE_CLASSES,
    ENTITY_MINIMAL_DOMAINS,
    ENTITY_OPTIMAL_EXTRA_DOMAINS,
)
from .config import EntitySourceConfig

_HIDDEN_CATEGORIES = {"config", "diagnostic"}


@dataclass(frozen=True)
class EntityCandidate:
    """One entity as the index and the tool both see it."""

    entity_id: str
    domain: str
    name: str
    area: str
    device: str
    device_class: str
    aliases: tuple[str, ...]


def _category_value(entity_category: object) -> str:
    """EntityCategory is an enum in the registry and absent for state-only entities."""
    if entity_category is None:
        return ""
    return getattr(entity_category, "value", str(entity_category))


def _preset_allows(
    preset: str,
    domain: str,
    device_class: str,
    category: str,
    *,
    hidden: bool,
    disabled: bool,
) -> bool:
    if preset == "paranoid":
        return True
    if hidden or disabled:
        return False
    if preset == "maximal":
        return True

    if category in _HIDDEN_CATEGORIES:
        return False
    if domain in ENTITY_MINIMAL_DOMAINS:
        return True
    if preset == "minimal":
        return False

    if domain in ENTITY_OPTIMAL_EXTRA_DOMAINS:
        return True
    if domain in ("sensor", "binary_sensor"):
        return device_class in ENTITY_MEANINGFUL_DEVICE_CLASSES
    return False


def _selected(selectors: list[str], entity_id: str, domain: str) -> bool:
    """A selector is a bare domain or a full entity_id."""
    return entity_id in selectors or domain in selectors


def resolve_candidates(
    hass: HomeAssistant, config: EntitySourceConfig
) -> dict[str, EntityCandidate]:
    """Every entity this source should index, keyed by entity_id."""
    ent_reg = er.async_get(hass)
    dev_reg = dr.async_get(hass)
    area_reg = ar.async_get(hass)

    def _area_name(area_id: str | None) -> str:
        if not area_id:
            return ""
        area = area_reg.async_get_area(area_id)
        return area.name if area else ""

    raw: dict[str, tuple[EntityCandidate, str, bool, bool]] = {}

    for entry in ent_reg.entities.values():
        domain = entry.entity_id.split(".")[0]
        device = dev_reg.async_get(entry.device_id) if entry.device_id else None
        area_id = entry.area_id or (device.area_id if device else None)
        device_class = entry.device_class or entry.original_device_class or ""
        raw[entry.entity_id] = (
            EntityCandidate(
                entity_id=entry.entity_id,
                domain=domain,
                name=entry.name or entry.original_name or entry.entity_id,
                area=_area_name(area_id),
                device=(device.name_by_user or device.name) if device else "",
                device_class=device_class,
                aliases=tuple(sorted(entry.aliases or ())),
            ),
            _category_value(entry.entity_category),
            entry.hidden_by is not None,
            entry.disabled_by is not None,
        )

    # Entities created by legacy YAML platforms, templates and groups never
    # reach the entity registry. Skipping them would silently gut `maximal`.
    for state in hass.states.async_all():
        if state.entity_id in raw:
            continue
        domain = state.entity_id.split(".")[0]
        raw[state.entity_id] = (
            EntityCandidate(
                entity_id=state.entity_id,
                domain=domain,
                name=state.attributes.get("friendly_name") or state.entity_id,
                area="",
                device="",
                device_class=state.attributes.get("device_class") or "",
                aliases=(),
            ),
            "",
            False,
            False,
        )

    chosen: dict[str, EntityCandidate] = {}
    for entity_id, (cand, category, hidden, disabled) in raw.items():
        keep = _preset_allows(
            config.preset,
            cand.domain,
            cand.device_class,
            category,
            hidden=hidden,
            disabled=disabled,
        )
        if not keep and _selected(config.include, entity_id, cand.domain):
            keep = True
        if keep and _selected(config.exclude, entity_id, cand.domain):
            keep = False
        if keep:
            chosen[entity_id] = cand
    return chosen
