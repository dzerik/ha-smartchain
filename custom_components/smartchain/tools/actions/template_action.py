"""Execute a template action — render a Jinja template with tool-call args."""

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import template as template_helper

from ..model import TemplateAction


async def execute_template(
    hass: HomeAssistant,
    action: TemplateAction,
    args: dict[str, Any],
) -> str:
    """Render the template with `args` as the variable scope."""
    tpl = template_helper.Template(action.value_template, hass)
    rendered = tpl.async_render(args, parse_result=False)
    return str(rendered)
