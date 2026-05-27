"""Tests for the template action executor."""

from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.actions.template_action import execute_template
from custom_components.smartchain.tools.model import TemplateAction


async def test_template_renders_with_args(hass: HomeAssistant) -> None:
    """Args are exposed as Jinja variables."""
    action = TemplateAction(value_template="hello {{ name }}")
    result = await execute_template(hass, action, {"name": "world"})
    assert result == "hello world"


async def test_template_renders_with_hass_state(hass: HomeAssistant) -> None:
    """Template has access to HA `states()` function."""
    hass.states.async_set("sensor.test", "42")
    action = TemplateAction(value_template="{{ states('sensor.test') }}")
    result = await execute_template(hass, action, {})
    assert result == "42"


async def test_template_returns_string_even_for_numbers(hass: HomeAssistant) -> None:
    """parse_result=False ensures a numeric template still returns a string."""
    action = TemplateAction(value_template="{{ 1 + 2 }}")
    result = await execute_template(hass, action, {})
    assert result == "3"
    assert isinstance(result, str)
