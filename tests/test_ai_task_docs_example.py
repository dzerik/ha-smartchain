"""The AI Task example in the guides has to be an example that runs.

The audit found the documented `ai_task.generate_data` call failing service
validation for two independent reasons — `structure` written as a JSON Schema
instead of a mapping of field to selector, and an attachment without
`media_content_type` — on an entity that did not declare attachment support at
all, and then reading the result as `result.items` when the service answers
`{"conversation_id": …, "data": …}`. Every one of those is invisible to a
reader: the YAML looks plausible and only fails in front of a user.

So the example is checked against the real thing rather than re-read. The
schema here is the one `ai_task` registers with `hass.services`, not a copy of
it, and the entity is asked for the same feature flag the service checks. Both
locales are checked, because the two guides drifted apart before.
"""

from pathlib import Path
from typing import Any

import pytest
import voluptuous as vol
import yaml
from homeassistant.components import ai_task
from homeassistant.core import HomeAssistant
from homeassistant.helpers import llm
from homeassistant.setup import async_setup_component

from custom_components.smartchain.ai_task import (
    SmartChainAITaskEntity,
    _structure_to_json_schema,
)

DOCS = Path(__file__).resolve().parents[1] / "docs"
GUIDES = {"en": DOCS / "USAGE.md", "ru": DOCS / "USAGE-ru.md"}


def _section_11(guide: Path) -> str:
    """The text of section 11 of one guide."""
    text = guide.read_text(encoding="utf-8")
    start = text.index("\n## 11.")
    end = text.index("\n## 12.", start)
    return text[start:end]


def _example_call(guide: Path) -> dict[str, Any]:
    """The `ai_task.generate_data` service data from that section's YAML."""
    section = _section_11(guide)
    blocks = section.split("```yaml")[1:]
    assert blocks, f"{guide.name} section 11 has no YAML example"

    for block in blocks:
        loaded = yaml.safe_load(block.split("```")[0])
        for automation in loaded.get("automation", []):
            for step in automation.get("action", []):
                if step.get("service") == "ai_task.generate_data":
                    return step
    raise AssertionError(f"{guide.name} section 11 never calls ai_task.generate_data")


def _notification_message(guide: Path) -> str:
    """The template the example uses to read the result back."""
    section = _section_11(guide)
    for block in section.split("```yaml")[1:]:
        loaded = yaml.safe_load(block.split("```")[0])
        for automation in loaded.get("automation", []):
            for step in automation.get("action", []):
                if step.get("service") == "persistent_notification.create":
                    return step["data"]["message"]
    raise AssertionError(f"{guide.name} section 11 never reads the result back")


@pytest.fixture
async def generate_data_schema(hass: HomeAssistant):
    """The schema `ai_task` really registers for `generate_data`."""
    assert await async_setup_component(hass, "ai_task", {})
    service = hass.services.async_services_for_domain(ai_task.DOMAIN)["generate_data"]
    assert service.schema is not None
    return service.schema


@pytest.mark.parametrize("locale", sorted(GUIDES))
async def test_the_documented_call_passes_service_validation(
    generate_data_schema, locale: str
) -> None:
    """The whole `data:` block, exactly as written, through the real schema."""
    call = _example_call(GUIDES[locale])

    validated = generate_data_schema(call["data"])

    assert validated["task_name"]
    assert validated["instructions"].strip()


@pytest.mark.parametrize("locale", sorted(GUIDES))
async def test_the_documented_attachment_names_its_content_type(
    generate_data_schema, locale: str
) -> None:
    """The media selector refuses an attachment without one, quietly to a reader."""
    call = _example_call(GUIDES[locale])
    attachments = call["data"]["attachments"]

    assert isinstance(attachments, list), "the media selector wants a list of items"
    for attachment in attachments:
        assert attachment["media_content_type"], attachment
        assert attachment["media_content_type"].startswith("image/"), (
            "only images are encoded into the request; the example must use one"
        )


@pytest.mark.parametrize("locale", sorted(GUIDES))
async def test_the_documented_structure_is_a_field_mapping(
    generate_data_schema, locale: str
) -> None:
    """A JSON Schema in `structure:` would have `properties`, and would not validate.

    Validating produces a `vol.Schema` of selectors, which is what this then
    exercises end to end: convert it the way the entity does, and check a
    plausible model answer against it.
    """
    call = _example_call(GUIDES[locale])
    raw = call["data"]["structure"]

    assert "properties" not in raw, "structure is a field mapping, not a JSON Schema"
    assert "items" in raw, "the example's own field is missing"

    structure = generate_data_schema(call["data"])["structure"]
    assert isinstance(structure, vol.Schema)

    json_schema = _structure_to_json_schema(structure, None)
    assert json_schema["type"] == "object"
    assert json_schema["properties"]["items"]["type"] == "array"
    assert "items" in json_schema["required"]

    assert structure({"items": ["milk"], "expiring_soon": []}) == {
        "items": ["milk"],
        "expiring_soon": [],
    }
    with pytest.raises(vol.Invalid):
        structure({"expiring_soon": []})


@pytest.mark.parametrize("locale", sorted(GUIDES))
async def test_the_documented_template_reads_the_data_key(locale: str) -> None:
    """`result` is the whole service response; the value is under `data`."""
    message = _notification_message(GUIDES[locale])

    assert "result.data" in message
    assert "result.items" not in message


@pytest.mark.parametrize("locale", sorted(GUIDES))
async def test_the_documented_entity_id_is_an_ai_task_entity(
    generate_data_schema, locale: str
) -> None:
    """A `conversation.` entity_id here is the other easy way to write it wrong."""
    call = _example_call(GUIDES[locale])

    assert call["data"]["entity_id"].startswith("ai_task.")


async def test_our_entity_would_be_allowed_to_take_that_attachment(
    hass: HomeAssistant,
) -> None:
    """The service refuses attachments unless the entity declares support.

    Asserted against `ai_task`'s own feature flag rather than our constant, so
    the example stays runnable only while the entity really claims it.
    """

    class _Entry:
        entry_id = "docs_entry"
        data = {"engine": "gigachat"}
        options: dict[str, Any] = {}
        subentries: dict[str, Any] = {}
        runtime_data = None

    entity = SmartChainAITaskEntity(_Entry())

    assert ai_task.AITaskEntityFeature.SUPPORT_ATTACHMENTS in entity.supported_features


def test_the_selector_serializer_is_what_makes_the_conversion_possible() -> None:
    """Kept next to the example because it is why the example can be honest.

    `llm.selector_serializer` is not a nicety: the documented structure is a
    schema of selectors, and converting it without one raises.
    """
    from homeassistant.components.ai_task import (  # noqa: PLC0415
        _validate_structure_fields,
    )
    from voluptuous_openapi import convert

    structure = _validate_structure_fields(
        {"items": {"required": True, "selector": {"text": {"multiple": True}}}}
    )

    with pytest.raises(TypeError):
        convert(structure)

    assert convert(structure, custom_serializer=llm.selector_serializer)["properties"]["items"] == {
        "type": "array",
        "items": {"type": "string"},
    }
