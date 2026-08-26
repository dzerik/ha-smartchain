"""Lifecycle tests for the Last Analysis sensor singleton.

The sensor is a domain-wide singleton registered by whichever config entry is
set up first. These tests pin the *entity* — what `hass.states` holds — across
reload and unload, because the bookkeeping in `hass.data` that decides whether
to register it is exactly the implementation detail under change.
"""

import ast
import logging
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import homeassistant.util.dt as dt_util
import pytest
from homeassistant.const import Platform
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components import smartchain
from custom_components.smartchain import sensor as sensor_platform
from custom_components.smartchain.const import (
    CONF_API_KEY,
    CONF_ENGINE,
    DOMAIN,
    ID_GIGACHAT,
    SIGNAL_NEW_ANALYSIS,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SENSOR_ENTITY_ID = "sensor.smartchain_last_analysis"


async def _setup_entry(hass: HomeAssistant, mock_client, unique_id: str) -> MockConfigEntry:
    """Set up a real config entry so every platform (incl. sensor) is loaded."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_ENGINE: ID_GIGACHAT, CONF_API_KEY: "test-credentials"},
        options={},
        unique_id=unique_id,
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_client,
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def _assert_sensor_alive(hass: HomeAssistant, context: str) -> None:
    """The sensor exists and is a live entity, not a restored husk."""
    state = hass.states.get(SENSOR_ENTITY_ID)
    assert state is not None, f"sensor gone {context}"
    assert state.state != "unavailable", f"sensor unavailable {context}"
    assert not state.attributes.get("restored"), f"sensor only restored {context}"


async def test_sensor_survives_entry_reload(hass: HomeAssistant, mock_llm_client) -> None:
    """Reloading the entry that registered the sensor must bring it back.

    Every options/agent edit in the UI ends in `async_reload`, so a sensor that
    dies here is dead until Home Assistant itself restarts.
    """
    entry = await _setup_entry(hass, mock_llm_client, "GigaChat")
    _assert_sensor_alive(hass, "before reload")

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_reload(entry.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after reload")


async def test_sensor_survives_owner_reload_with_second_entry(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """A second hub must not stop the owner from re-registering on reload."""
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")

    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_reload(first.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after reloading the owner")


async def test_unloading_other_entry_leaves_sensor_owned(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Unloading a non-owner entry touches neither the sensor nor its ownership.

    Ownership has to be released per entry_id, not unconditionally: releasing it
    here would let the second entry try to add a *second* singleton on its way
    back in, which Home Assistant rejects as a duplicate unique_id.
    """
    await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")

    await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()
    _assert_sensor_alive(hass, "after unloading the second entry")

    caplog.clear()
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(second.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after the second entry came back")
    assert "does not generate unique IDs" not in caplog.text


async def test_sensor_moves_to_a_surviving_hub_when_its_owner_unloads(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """A permanent unload of the owner must not take the singleton down with it.

    The sensor lives on the *platform* of whichever entry registered it, so
    unloading that entry removes the entity. That is right when it was the last
    hub and wrong while another one is still serving `analyze_image`: the
    automations reading `sensor.smartchain_last_analysis` go quiet until some
    entry happens to reload.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")

    caplog.clear()
    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after the owner was unloaded for good")
    # Still one sensor for the whole of Home Assistant, now carried by the hub
    # that is still up — not a second entity added beside the first.
    ent_reg = er.async_get(hass)
    owned = [
        ent
        for ent in ent_reg.entities.values()
        if ent.platform == DOMAIN and ent.domain == "sensor"
    ]
    assert len(owned) == 1
    assert owned[0].config_entry_id == second.entry_id
    assert "does not generate unique IDs" not in caplog.text


async def test_sensor_keeps_its_reading_across_the_move(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """The move must carry the last analysis over, not blank it."""
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    await _setup_entry(hass, mock_llm_client, "GigaChat-2")

    async_dispatcher_send(
        hass,
        SIGNAL_NEW_ANALYSIS,
        {
            "response": "a cat on the porch",
            "camera_entity_id": "camera.porch",
            "message": "what do you see?",
            "timestamp": "2026-08-26T12:00:00+00:00",
        },
    )
    await hass.async_block_till_done()
    assert hass.states.get(SENSOR_ENTITY_ID).state == "a cat on the porch"

    await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(SENSOR_ENTITY_ID)
    assert state.state == "a cat on the porch"
    assert state.attributes["camera_entity_id"] == "camera.porch"


async def test_sensor_is_released_when_only_another_platform_fails_to_unload(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """One stuck platform must not cost the singleton its slot.

    `async_unload_platforms` answers for all platforms at once: a conversation
    platform that refuses to unload makes it False even though the sensor
    platform went down cleanly and took the entity with it. Gating the release
    of ownership on that combined answer leaves the slot held by an entry that
    no longer has the entity — and every other hub then skips registering it.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")

    real_unload = hass.config_entries.async_forward_entry_unload

    async def _refuse_conversation(entry, domain):
        if entry.entry_id == first.entry_id and domain == Platform.CONVERSATION:
            return False
        return await real_unload(entry, domain)

    with patch.object(
        hass.config_entries, "async_forward_entry_unload", side_effect=_refuse_conversation
    ):
        assert not await hass.config_entries.async_unload(first.entry_id)
        await hass.async_block_till_done()

    # The surviving hub reloads — as every options edit makes it do — and must
    # be able to claim a slot the half-unloaded entry has no entity for.
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_reload(second.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after the surviving hub reloaded")


async def test_a_failed_rehome_hands_the_slot_back_to_the_next_hub(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """A rehome that blows up must not leave the singleton unclaimable.

    `async_rehome_sensor` re-forwards the sensor platform to a surviving hub,
    and `async_setup_entry` claims the slot for that hub *before* the entity
    reaches the state machine. If the forward then fails, the claim is standing
    for an entry that has no entity: every other hub now skips the registration
    and `sensor.smartchain_last_analysis` is gone for the rest of the run, no
    matter how many times anything reloads. The docstring's promise — "hand the
    slot back so the next reload of any hub can retry" — is what makes the next
    hub to come up able to register it, and it has to hand it back under the id
    that actually took it, not under the id of the entry that was leaving.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")

    real_forward = hass.config_entries.async_forward_entry_setups

    async def _fail_after_the_platform_claimed(entry, platforms):
        """Let the real platform setup claim the slot, then fail the forward.

        The claim is taken by the integration's own code, not fabricated here:
        the real forward runs and only the entity itself is made unbuildable, so
        the slot ends up held for an entry that has no entity — the exact window
        the release in the `except` branch covers.
        """
        if entry.entry_id != second.entry_id or Platform.SENSOR not in platforms:
            await real_forward(entry, platforms)
            return
        with patch.object(
            sensor_platform,
            "SmartChainLastAnalysisSensor",
            side_effect=RuntimeError("the entity could not be built"),
        ):
            await real_forward(entry, platforms)
        raise RuntimeError("the forwarded setup failed")

    caplog.clear()
    with patch.object(
        hass.config_entries,
        "async_forward_entry_setups",
        side_effect=_fail_after_the_platform_claimed,
    ):
        assert await hass.config_entries.async_unload(first.entry_id)
        await hass.async_block_till_done()

    assert "Could not move the SmartChain Last Analysis sensor" in caplog.text
    stranded = hass.states.get(SENSOR_ENTITY_ID)
    assert stranded is None or stranded.attributes.get("restored"), (
        "the move did not actually fail — there is still a live entity"
    )

    # The next hub to come up must be able to register the sensor again.
    caplog.clear()
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(first.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after a hub came back up following a failed move")
    ent_reg = er.async_get(hass)
    owned = [
        ent
        for ent in ent_reg.entities.values()
        if ent.platform == DOMAIN and ent.domain == "sensor"
    ]
    assert len(owned) == 1
    assert owned[0].config_entry_id == first.entry_id
    assert "does not generate unique IDs" not in caplog.text


async def test_a_move_that_worked_leaves_the_slot_with_the_new_owner(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """The other side of judging a move by whether the entity is live.

    A check that can free the slot after a *failed* move can free it after a
    successful one too, and that failure is louder than the one it guards
    against: the entity is alive on the new owner, the slot says nobody has it,
    and the next hub to load adds a second one — which Home Assistant refuses
    as a duplicate unique_id, leaving a hub that logs an error on every setup.
    So the claim has to survive a move that worked, and the way to see that is
    to bring a hub up afterwards.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")

    assert await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after the move")
    assert hass.data[DOMAIN].get(sensor_platform.SENSOR_OWNER_KEY) == second.entry_id

    caplog.clear()
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(first.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after the other hub came back")
    assert "does not generate unique IDs" not in caplog.text
    ent_reg = er.async_get(hass)
    owned = [
        ent
        for ent in ent_reg.entities.values()
        if ent.platform == DOMAIN and ent.domain == "sensor"
    ]
    assert len(owned) == 1
    assert owned[0].config_entry_id == second.entry_id


async def test_a_rehome_that_quietly_fails_still_frees_the_slot(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """The reachable half of the same failure, which had no test and no code.

    The test above forces an exception out of `async_forward_entry_setups`, and
    that is not how a forwarded platform fails in Home Assistant:
    `entity_platform._async_setup_platform` catches `Exception`, logs it and
    returns False, and `async_forward_entry_setups` discards that answer and
    returns None. So the `except` branch in `async_rehome_sensor` covers a case
    real Home Assistant does not produce, while the case it *does* produce —
    the forward comes back clean and the platform never set up — went
    unnoticed: `async_setup_entry` had already claimed the slot for the
    receiving hub, and the claim stood for an entry with no entity. Every other
    hub then skipped the registration, so `sensor.smartchain_last_analysis` was
    gone for the rest of the run however many times anything reloaded, with
    nothing said about the singleton at all.

    Nothing here fakes the failure at the seam: the entity itself is made
    unbuildable and the real forward runs, exactly as it would if
    `async_added_to_hass` threw or the unique id were refused.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")

    caplog.clear()
    with patch.object(
        sensor_platform,
        "SmartChainLastAnalysisSensor",
        side_effect=RuntimeError("the entity could not be built"),
    ):
        assert await hass.config_entries.async_unload(first.entry_id)
        await hass.async_block_till_done()

    stranded = hass.states.get(SENSOR_ENTITY_ID)
    assert stranded is None or stranded.attributes.get("restored"), (
        "the move did not actually fail — there is still a live entity"
    )
    # The slot is the whole point: held here, no hub can ever register the
    # sensor again without a Home Assistant restart.
    assert sensor_platform.SENSOR_OWNER_KEY not in hass.data[DOMAIN], (
        f"the slot is still held by {hass.data[DOMAIN].get(sensor_platform.SENSOR_OWNER_KEY)}"
    )
    # And it is not allowed to be silent. Home Assistant logs its own platform
    # error, which says nothing about a singleton having lost its home.
    ours = [
        record
        for record in caplog.records
        if record.name.startswith("custom_components")
        and "Last Analysis sensor" in record.getMessage()
    ]
    assert ours, "nothing announced that the sensor lost its home"
    assert max(record.levelno for record in ours) >= logging.WARNING

    # The next hub to come up must be able to register it again.
    caplog.clear()
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(first.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after a hub came back up following a quiet failed move")
    ent_reg = er.async_get(hass)
    owned = [
        ent
        for ent in ent_reg.entities.values()
        if ent.platform == DOMAIN and ent.domain == "sensor"
    ]
    assert len(owned) == 1
    assert owned[0].config_entry_id == first.entry_id
    assert "does not generate unique IDs" not in caplog.text


class _SensorThatRegistersThenDies(sensor_platform.SmartChainLastAnalysisSensor):
    """A singleton that reaches the entity registry and then fails to come up.

    Every other failure test here breaks the *constructor*, which never gets as
    far as `entity_registry.async_get_or_create`: the registration stays with
    the hub that left, so both halves of `_sensor_moved_to` — what the registry
    says and what the state machine says — agree the move failed, and neither
    half is tested on its own.

    Breaking `async_added_to_hass` is what pulls them apart.
    `EntityPlatform._async_add_entity` writes the registry entry first and calls
    `add_to_platform_finish` after, so the registry already says the entity
    belongs to the receiving hub while the state machine never gets an entity at
    all. Home Assistant swallows the error — `_async_add_entities` logs it and
    carries on — so the forward comes back clean and `_sensor_moved_to` is the
    only thing left that can notice.
    """

    async def async_added_to_hass(self) -> None:
        """Fail the way a platform really fails: after the registry, before the state."""
        raise RuntimeError("the entity never finished starting")


def _sensor_registry_entry(hass: HomeAssistant) -> er.RegistryEntry:
    """The singleton's registry entry, found by unique id like the code does."""
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id("sensor", DOMAIN, sensor_platform.SENSOR_UNIQUE_ID)
    assert entity_id is not None, "the singleton was never registered"
    entry = ent_reg.async_get(entity_id)
    assert entry is not None
    return entry


def _sensor_complaints(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """Records this integration wrote about the singleton at WARNING or worse."""
    return [
        record
        for record in caplog.records
        if record.name.startswith("custom_components")
        and "Last Analysis sensor" in record.getMessage()
        and record.levelno >= logging.WARNING
    ]


async def _disable_the_sensor(
    hass: HomeAssistant, disabler: er.RegistryEntryDisabler
) -> er.RegistryEntry:
    """Turn the singleton off the way the registry does it, and let HA settle."""
    entry = _sensor_registry_entry(hass)
    er.async_get(hass).async_update_entity(entry.entity_id, disabled_by=disabler)
    await hass.async_block_till_done()
    assert hass.states.get(entry.entity_id) is None, "a disabled entity must have no state"
    return entry


async def test_an_entity_that_only_reached_the_registry_has_not_moved(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Registered on the new hub and never alive is still a failed move.

    `_sensor_moved_to` asks the registry only for entities that have no state to
    ask about — the disabled ones. For everything else the state machine is the
    authority, and this is the case that says why. The entity registry entry is
    written before the entity is started, so a platform that dies in
    `async_added_to_hass` leaves the registration pointing at the hub that
    received it while `sensor.smartchain_last_analysis` does not exist. The
    registry says "moved", the state machine says "no", and the right answer is
    "no": the claim is standing for a hub with no entity, which is precisely the
    condition that makes every other hub skip the registration for the rest of
    the run.

    This is what stops the registry test from being widened into the check for
    *all* entities. Widen it and this scenario reports a clean move, the slot
    stays claimed, and nothing is said.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")

    caplog.clear()
    with patch.object(
        sensor_platform, "SmartChainLastAnalysisSensor", _SensorThatRegistersThenDies
    ):
        assert await hass.config_entries.async_unload(first.entry_id)
        await hass.async_block_till_done()

    # What makes this different from the other failed-move tests: the registry
    # really did follow the move, so the registry alone would call it a success.
    moved_registration = _sensor_registry_entry(hass)
    assert moved_registration.config_entry_id == second.entry_id
    assert not moved_registration.disabled, "this entity is enabled — the state is the authority"
    # And there is no entity behind that registration — only the husk
    # `Entity.async_remove` leaves for a registered entity when its platform goes
    # down: `unavailable` with `restored: True`. So "is there a state?" answers
    # yes here, and the `restored` half of the check is the only thing between
    # that husk and a move reported as successful.
    husk = hass.states.get(SENSOR_ENTITY_ID)
    assert husk is not None and husk.attributes.get("restored"), (
        "the move did not actually fail — there is still a live entity"
    )

    assert _sensor_complaints(caplog), "a hub with no entity kept the slot in silence"
    assert sensor_platform.SENSOR_OWNER_KEY not in hass.data[DOMAIN], (
        f"the slot is still held by {hass.data[DOMAIN].get(sensor_platform.SENSOR_OWNER_KEY)}"
    )

    # And the freed slot is worth something: the next hub up registers it again.
    caplog.clear()
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(first.entry_id)
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after a hub came back up following a registry-only move")
    assert "does not generate unique IDs" not in caplog.text


async def test_a_user_disabled_sensor_is_not_a_failed_move(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """A sensor the user switched off is not a sensor that failed to come up.

    A disabled entity has no state by design — Home Assistant never adds it to
    the state machine. Judging the move by `hass.states.get` alone therefore
    reads every unload of the owner as a failure: an ERROR blaming a platform
    error that never happened, and the claim thrown away. `async_reload` runs on
    every options save and every agent edit, so this is not a corner case, it is
    the normal weekly life of anyone who turned the sensor off.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")
    await _disable_the_sensor(hass, er.RegistryEntryDisabler.USER)

    caplog.clear()
    assert await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    assert not _sensor_complaints(caplog), (
        f"the user's own choice was reported as a failure: "
        f"{[r.getMessage() for r in _sensor_complaints(caplog)]}"
    )
    # The choice is left standing, and the registration follows the hub that is
    # still up so re-enabling has somewhere live to land.
    registry_entry = _sensor_registry_entry(hass)
    assert registry_entry.disabled_by is er.RegistryEntryDisabler.USER
    assert registry_entry.config_entry_id == second.entry_id
    assert hass.data[DOMAIN].get(sensor_platform.SENSOR_OWNER_KEY) == second.entry_id


async def test_a_user_disabled_sensor_can_still_be_switched_back_on(
    hass: HomeAssistant, mock_llm_client
) -> None:
    """The slot must not be left in a state the user cannot get out of.

    Re-enabling an entity makes Home Assistant reload the config entry the
    registry says owns it. If the unload left that pointing at the hub that
    went away, or left the claim held by a hub with no entity, switching the
    sensor back on gets the user nothing.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    disabled = await _disable_the_sensor(hass, er.RegistryEntryDisabler.USER)

    assert await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    er.async_get(hass).async_update_entity(disabled.entity_id, disabled_by=None)
    await hass.async_block_till_done()
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=60))
        await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after the user switched it back on")
    assert _sensor_registry_entry(hass).config_entry_id == second.entry_id


async def test_a_user_disabled_sensor_survives_another_hub_loading(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """A hub coming up after the move must not fight over a disabled singleton.

    Whatever the unload decided has to hold when the next hub loads: still one
    registry entry, still the user's `disabled_by`, and no second entity offered
    under the same unique id.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    await _disable_the_sensor(hass, er.RegistryEntryDisabler.USER)

    assert await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    caplog.clear()
    with patch(
        "custom_components.smartchain.get_client",
        new_callable=AsyncMock,
        return_value=mock_llm_client,
    ):
        await hass.config_entries.async_setup(first.entry_id)
        await hass.async_block_till_done()

    assert "does not generate unique IDs" not in caplog.text
    assert not _sensor_complaints(caplog)
    ent_reg = er.async_get(hass)
    owned = [
        ent
        for ent in ent_reg.entities.values()
        if ent.platform == DOMAIN and ent.domain == "sensor"
    ]
    assert len(owned) == 1
    assert owned[0].disabled_by is er.RegistryEntryDisabler.USER
    # The hub that already carries it keeps it; a loaded owner is what makes
    # re-enabling work.
    assert hass.data[DOMAIN].get(sensor_platform.SENSOR_OWNER_KEY) == second.entry_id


async def test_an_integration_disabled_sensor_is_not_a_failed_move(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """The registry disables entities for reasons other than the user, too.

    `disabled_by: integration` looks identical from the state machine's side —
    no state — and is just as much not a failed platform setup.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    await _disable_the_sensor(hass, er.RegistryEntryDisabler.INTEGRATION)

    caplog.clear()
    assert await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    assert not _sensor_complaints(caplog)
    assert _sensor_registry_entry(hass).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.data[DOMAIN].get(sensor_platform.SENSOR_OWNER_KEY) == second.entry_id


async def test_a_hidden_sensor_moves_like_any_other(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Hidden is not disabled — the entity is live, only kept out of the UI.

    A hidden entity is added to the state machine like any other, so the move is
    judged the ordinary way and has to come out clean: no complaint, the
    registration on the surviving hub, the user's `hidden_by` untouched.

    This is the happy path only. It cannot tell the registry test from the state
    test — a live hidden entity satisfies both — so widening the registry test to
    cover hidden entities leaves it green. The test that catches that widening is
    `test_a_hidden_sensor_that_never_started_is_still_a_failed_move` below, where
    the two answers disagree.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    hidden = _sensor_registry_entry(hass)
    er.async_get(hass).async_update_entity(hidden.entity_id, hidden_by=er.RegistryEntryHider.USER)
    await hass.async_block_till_done()
    _assert_sensor_alive(hass, "while hidden")

    caplog.clear()
    assert await hass.config_entries.async_unload(first.entry_id)
    await hass.async_block_till_done()

    _assert_sensor_alive(hass, "after the owner of a hidden sensor unloaded")
    assert not _sensor_complaints(caplog)
    assert _sensor_registry_entry(hass).hidden_by is er.RegistryEntryHider.USER
    assert hass.data[DOMAIN].get(sensor_platform.SENSOR_OWNER_KEY) == second.entry_id


async def test_a_hidden_sensor_that_never_started_is_still_a_failed_move(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Where hidden and disabled have to part company, and the only place they do.

    The concession made for disabled entities — judge the move by who the
    registry says owns the entity, because there will never be a state — reads
    like something that could reasonably be extended to any registry marking.
    It cannot be extended to `hidden`. A hidden entity is a running entity; the
    hiding is a UI preference and nothing else. Extend the concession to it and
    a hidden singleton that failed to start on the receiving hub is waved
    through: the registration moved, so the check says the move worked, the
    claim stays with a hub that has no entity, and no other hub ever registers
    the sensor again.

    While the hidden entity is alive both tests agree, which is why the happy
    path above cannot see the difference. Here they disagree, and the state
    machine has to win.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    hidden = _sensor_registry_entry(hass)
    er.async_get(hass).async_update_entity(hidden.entity_id, hidden_by=er.RegistryEntryHider.USER)
    await hass.async_block_till_done()
    _assert_sensor_alive(hass, "while hidden")

    caplog.clear()
    with patch.object(
        sensor_platform, "SmartChainLastAnalysisSensor", _SensorThatRegistersThenDies
    ):
        assert await hass.config_entries.async_unload(first.entry_id)
        await hass.async_block_till_done()

    after = _sensor_registry_entry(hass)
    assert after.hidden_by is er.RegistryEntryHider.USER, "the scenario lost its hidden entity"
    assert not after.disabled, "hidden must not be confused with disabled"
    # The registry followed the move, so a registry-only verdict says "moved".
    assert after.config_entry_id == second.entry_id
    # The state machine says otherwise, and it is right.
    stranded = hass.states.get(SENSOR_ENTITY_ID)
    assert stranded is None or stranded.attributes.get("restored"), (
        "the move did not actually fail — there is still a live entity"
    )

    assert _sensor_complaints(caplog), "a hidden sensor that never started went unannounced"
    assert sensor_platform.SENSOR_OWNER_KEY not in hass.data[DOMAIN], (
        f"the slot is still held by {hass.data[DOMAIN].get(sensor_platform.SENSOR_OWNER_KEY)}"
    )


async def test_a_disabled_sensor_that_really_did_not_move_is_still_reported(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """Being disabled must not become a blanket excuse for a broken move.

    A disabled entity has no state to look at, so the check falls back on the
    registry — and the registry only says the move happened if the entity now
    belongs to the hub that received it. Accepting "disabled, therefore fine"
    without that would hand the disabled case a silent pass over exactly the
    failure the check was added for: a claim standing for a hub whose platform
    never set the entity up.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    disabled = await _disable_the_sensor(hass, er.RegistryEntryDisabler.USER)
    assert disabled.config_entry_id == first.entry_id

    caplog.clear()
    with patch.object(
        sensor_platform,
        "SmartChainLastAnalysisSensor",
        side_effect=RuntimeError("the entity could not be built"),
    ):
        assert await hass.config_entries.async_unload(first.entry_id)
        await hass.async_block_till_done()

    # The registration never left the hub that went away — the move failed.
    assert _sensor_registry_entry(hass).config_entry_id == first.entry_id
    assert _sensor_complaints(caplog), "a genuinely failed move went unannounced"
    assert sensor_platform.SENSOR_OWNER_KEY not in hass.data[DOMAIN], (
        f"the slot is still held by {hass.data[DOMAIN].get(sensor_platform.SENSOR_OWNER_KEY)}"
    )


async def test_nothing_is_rehomed_while_home_assistant_is_stopping(
    hass: HomeAssistant, mock_llm_client, caplog: pytest.LogCaptureFixture
) -> None:
    """A shutdown is not a hub going away, and must not start a platform up.

    Re-forwarding the sensor platform during shutdown builds an entity that has
    seconds to live, on an entry Home Assistant is about to tear down anyway.
    """
    first = await _setup_entry(hass, mock_llm_client, "GigaChat")
    second = await _setup_entry(hass, mock_llm_client, "GigaChat-2")
    _assert_sensor_alive(hass, "with two entries")

    forwards: list[tuple[str, tuple]] = []
    real_forward = hass.config_entries.async_forward_entry_setups

    async def _record(entry, platforms):
        forwards.append((entry.entry_id, tuple(platforms)))
        await real_forward(entry, platforms)

    caplog.clear()
    hass.set_state(CoreState.stopping)
    try:
        with patch.object(hass.config_entries, "async_forward_entry_setups", side_effect=_record):
            assert await hass.config_entries.async_unload(first.entry_id)
            await hass.async_block_till_done()
    finally:
        hass.set_state(CoreState.running)

    assert forwards == [], f"a platform was started up during shutdown: {forwards}"
    assert not _sensor_complaints(caplog)
    assert hass.data[DOMAIN].get(sensor_platform.SENSOR_OWNER_KEY) is None
    assert second.state is not None


def test_sensor_platform_is_not_imported_at_module_scope() -> None:
    """`__init__.py` keeps platform and websocket modules off its import path.

    The file states the convention on its `websocket_api` imports: those are
    deferred into the functions that need them. `.sensor` is a platform module,
    loaded by Home Assistant when the platform is forwarded, and it has no
    business being pulled in when the integration package is merely imported.
    """
    tree = ast.parse(Path(smartchain.__file__).read_text(encoding="utf-8"))
    module_level = [
        node.module for node in tree.body if isinstance(node, ast.ImportFrom) and node.level == 1
    ]
    assert "sensor" not in module_level
    assert "websocket_api" not in module_level
