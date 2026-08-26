"""Every key the repair flows can show must exist in all three string files.

`strings.json` had already drifted 98 keys behind `translations/en.json` when
this audit started. A missing key is not a crash — Home Assistant falls back to
the raw key — so a reauth dialog titled `reauth_confirm` with a button labelled
`invalid_auth` is exactly the kind of quiet degradation nothing was watching.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent / "custom_components" / "smartchain"
FILES = {
    "strings.json": ROOT / "strings.json",
    "translations/en.json": ROOT / "translations" / "en.json",
    "translations/ru.json": ROOT / "translations" / "ru.json",
}

# The step ids `ConfigFlow` can show from a repair flow, and the outcomes it
# can end on. Written out rather than derived from the module under test: a
# list generated from the code cannot notice the code dropping a key.
REPAIR_STEPS = ("reauth_confirm", "reconfigure")
REPAIR_ABORTS = ("reauth_successful", "reconfigure_successful")
REPAIR_ERRORS = ("invalid_auth",)


@pytest.fixture(params=sorted(FILES))
def catalogue(request) -> dict:
    return json.loads(FILES[request.param].read_text(encoding="utf-8"))


@pytest.mark.parametrize("step", REPAIR_STEPS)
def test_every_repair_step_has_a_title_and_fields(catalogue: dict, step: str) -> None:
    section = catalogue["config"]["step"]
    assert step in section
    assert section[step].get("title")
    # The form is built from `ENGINE_SCHEMA`, whose fields are shared across
    # every provider; an unlabelled field renders as `api_key`.
    assert section[step].get("data")


@pytest.mark.parametrize("reason", REPAIR_ABORTS)
def test_every_repair_outcome_has_a_sentence(catalogue: dict, reason: str) -> None:
    assert catalogue["config"]["abort"].get(reason)


@pytest.mark.parametrize("key", REPAIR_ERRORS)
def test_every_repair_error_has_a_sentence(catalogue: dict, key: str) -> None:
    assert catalogue["config"]["error"].get(key)


def test_the_repair_steps_label_the_same_fields_everywhere() -> None:
    """One file labelling `folder_id` and another not is the drift itself."""
    per_file = {
        name: {
            step: set(json.loads(path.read_text(encoding="utf-8"))["config"]["step"][step]["data"])
            for step in REPAIR_STEPS
        }
        for name, path in FILES.items()
    }
    reference = per_file["strings.json"]
    for name, steps in per_file.items():
        assert steps == reference, name
