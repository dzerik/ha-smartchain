"""Everything this integration writes into a config entry must survive JSON.

`ConfigEntry.as_storage_fragment` serialises the whole entry — data, options
and every subentry — with `json_bytes_sorted`. A single value in there that
orjson cannot encode raises `TypeError` deep inside
`ConfigEntries._data_to_save`, and `Store._async_handle_write_data` catches
only `SerializationError` and `WriteError`, having already set `self._data =
None`. So the failure is not local: the pending write of `core.config_entries`
is dropped, every later write of that file fails the same way for *every*
integration on the system, and nothing is shown to the user. On restart the
file is whatever last wrote successfully.

The values that get us there do not come from the user directly — they come
from Home Assistant's own selector validators. `cv.TARGET_SERVICE_FIELDS`,
behind `selector.TargetSelector`, turns `entity_id: "{{ entity }}"` into a
`Template` object; `docs/USAGE.md` §7.1 teaches exactly that shape, and the
tools.yaml importer stores it as the plain string it was typed as. So the
same tool is storable when imported and unstorable when opened and re-saved.

**Normalise, then refuse.** A `Template` carries its own source text, so
rewriting it back to that string is lossless and gives the user precisely what
they typed — Home Assistant's own `TemplateSelector` already does this
(`return template.template`), which makes it the house style rather than an
invention here. The same argument covers a tuple or a set: JSON has one
sequence type, so a value that would silently change shape across a restart is
converted now, while memory and disk can still be made to agree. Anything
*else* that orjson refuses has no defined textual form, and `str(obj)` would
put a value in storage that the user never wrote — so that case is refused,
naming the field, rather than guessed at.

The refusal oracle is `homeassistant.helpers.json.json_bytes`, the exact
function `as_storage_fragment` ends at. Re-implementing "is this JSON" here
would be a second opinion free to drift from the first; asking the real
encoder cannot be wrong about its own answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.helpers.json import json_bytes
from homeassistant.helpers.template import Template

# What a refusal says. Deliberately about the field and not about the value:
# a `service_data` entry or a REST header can hold a credential, and this
# text travels to the browser.
UNSTORABLE_TEXT = "this value can not be saved — remove or retype it"


class UnstorableValue(vol.Invalid):
    """A `vol.Invalid` whose message is known to be safe to show.

    `_describe_invalid` refuses to render `str(err)` for a plain `vol.Invalid`,
    and rightly: voluptuous interpolates the offending value into its own
    messages, and the offending value here can be a bearer token. This subclass
    is the exception that keeps that rule honest — its message is the fixed
    `UNSTORABLE_TEXT` above, built from nothing the client sent, so the type
    itself is the proof that the text may travel.
    """


def normalize_storable(value: Any) -> Any:
    """Rewrite a validated form value into something JSON round-trips.

    Recursive, and total: a value it does not recognise is returned unchanged
    for `ensure_storable` to accept or refuse. It never inspects a leaf's
    contents, so a credential inside `service_data` is copied, never read.
    """
    if isinstance(value, Template):
        return value.template
    if isinstance(value, Mapping):
        return {key: normalize_storable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [normalize_storable(item) for item in value]
    return value


def ensure_storable(data: Mapping[str, Any]) -> dict[str, Any]:
    """Normalised `data`, or `vol.Invalid` naming the first field that resists.

    The error is raised with `path=[field]` rather than a formatted message so
    that `_describe_invalid` and a config flow's `errors` mapping both pick the
    field name up the way they already do for a schema failure — the caller
    needs no new error branch, and the panel can attach the message to the
    field the user is looking at.
    """
    out: dict[str, Any] = {}
    for field, value in data.items():
        normalised = normalize_storable(value)
        try:
            json_bytes(normalised)
        except TypeError as err:
            # The offending value is deliberately absent from the message.
            raise UnstorableValue(UNSTORABLE_TEXT, path=[field]) from err
        out[field] = normalised
    return out
