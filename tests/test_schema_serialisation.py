"""The panel's forms have to be serialised by the library Home Assistant speaks.

`cv.custom_serializer` handles the types a plain converter does not know, and
signals "I do not know this one either" by returning an `UNSUPPORTED` sentinel.
The converter recognises that sentinel *by identity* — and there are now two of
them. Home Assistant 2026.8 and earlier used `voluptuous-serialize`; 2026.9
switched to `probatio`, and its `UNSUPPORTED` is a different object.

Pair the wrong two and nothing raises. The converter simply fails to recognise
the other library's sentinel, treats it as a serialised value, and puts the
object itself into the payload — where Home Assistant's websocket layer meets
something JSON cannot encode and the panel is told "Invalid JSON in response".
Every form served by `websocket_api` breaks at once, on an installation whose
only sin was updating Home Assistant.

So the invariant is not "voluptuous-serialize is installed" but "our converter
and `cv.custom_serializer` come from the same library".
"""

import json
from types import SimpleNamespace

import homeassistant.helpers.config_validation as cv
import probatio
import voluptuous as vol
import voluptuous_serialize
from homeassistant.helpers import selector

from custom_components.smartchain.websocket_api import _pick_converter, _to_field_list


def test_our_converter_and_home_assistants_share_one_unsupported() -> None:
    """The invariant, checked against whichever Home Assistant is installed.

    `cv.custom_serializer` returns its library's sentinel for a type it cannot
    describe; ours has to be that same object, or it ends up in the payload.
    """
    theirs = cv.custom_serializer(object())
    convert, ours = _pick_converter(cv)

    assert theirs is ours, (
        "cv.custom_serializer returns a sentinel our converter will not "
        f"recognise: {theirs!r} is not {ours!r}"
    )
    assert convert is not None


def test_the_choice_follows_home_assistant_rather_than_what_is_installed() -> None:
    """Both libraries are installed here, so availability cannot be the test.

    Simulates the 2026.9 shape — `config_validation` importing `to_field_list`
    — and requires the pick to move with it. Before the fix the converter was
    a module-level `voluptuous_serialize.convert`, which no simulation could
    move, which is precisely why the upgrade broke it.
    """
    modern = SimpleNamespace(
        to_field_list=probatio.to_field_list,
        UNSUPPORTED=probatio.UNSUPPORTED,
        custom_serializer=lambda schema: probatio.UNSUPPORTED,
    )
    convert, sentinel = _pick_converter(modern)
    assert convert is probatio.to_field_list
    assert sentinel is probatio.UNSUPPORTED

    legacy = SimpleNamespace(custom_serializer=lambda schema: voluptuous_serialize.UNSUPPORTED)
    convert, sentinel = _pick_converter(legacy)
    assert convert is voluptuous_serialize.convert
    assert sentinel is voluptuous_serialize.UNSUPPORTED


def test_a_form_with_a_selector_survives_json() -> None:
    """The user-visible symptom, reproduced end to end.

    A selector is exactly what `cv.custom_serializer` exists for, so a schema
    holding one is what carries the sentinel out when the pair is mismatched.
    `json.dumps` is the same wall Home Assistant's websocket layer hits.
    """
    schema = vol.Schema(
        {
            vol.Required("name"): str,
            vol.Optional("backend"): selector.SelectSelector(
                selector.SelectSelectorConfig(options=["sqlite_numpy", "qdrant"])
            ),
        }
    )
    json.dumps(_to_field_list(schema))


def test_a_type_we_cannot_describe_fails_loudly_or_not_at_all() -> None:
    """Never quietly, which is the whole shape of the bug this file is about.

    A converter that cannot describe a field has two honest options: refuse, or
    produce something JSON can carry. `voluptuous-serialize` refuses, with
    `ValueError`. What it must never do is hand back an object that only fails
    later, in the websocket layer, as "Invalid JSON in response" — a message
    naming neither the field nor the form.

    Deliberately not asserting *which* option: the two libraries need not agree,
    and pinning one would make this test a false alarm the next time Home
    Assistant changes horses. The guarantee is that the failure is not silent.
    """

    class Unserialisable:
        """Not a voluptuous validator and not JSON — nobody can describe this."""

    schema = vol.Schema({vol.Required("ok"): str, vol.Optional("weird"): Unserialisable})

    try:
        fields = _to_field_list(schema)
    except (ValueError, TypeError):
        return  # refused, which is loud enough
    json.dumps(fields)  # or carried something JSON accepts
