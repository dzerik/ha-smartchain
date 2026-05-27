"""Tests for the REST action executor."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.actions.rest_action import execute_rest
from custom_components.smartchain.tools.model import RESTAction


def _async_cm(value):
    """Build an async context manager that yields `value`."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=value)
    cm.__aexit__ = AsyncMock(return_value=None)
    return cm


async def test_rest_get_returns_text(hass: HomeAssistant) -> None:
    """A GET request in text mode returns the response body as-is."""
    action = RESTAction(method="GET", url="https://example.com/x?q={{ q }}", response_format="text")

    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.text = AsyncMock(return_value="hello")
    session = MagicMock()
    session.request = MagicMock(return_value=_async_cm(fake_resp))

    with patch(
        "custom_components.smartchain.tools.actions.rest_action.async_get_clientsession",
        return_value=session,
    ):
        result = await execute_rest(hass, action, {"q": "abc"})

    assert result == "hello"
    session.request.assert_called_once()
    call_kwargs = session.request.call_args.kwargs
    assert call_kwargs["url"].endswith("?q=abc")


async def test_rest_get_returns_json(hass: HomeAssistant) -> None:
    """A GET in json mode returns the body as a JSON string."""
    action = RESTAction(method="GET", url="https://example.com", response_format="json")

    fake_resp = MagicMock()
    fake_resp.status = 200
    fake_resp.json = AsyncMock(return_value={"temp": 20})
    session = MagicMock()
    session.request = MagicMock(return_value=_async_cm(fake_resp))

    with patch(
        "custom_components.smartchain.tools.actions.rest_action.async_get_clientsession",
        return_value=session,
    ):
        result = await execute_rest(hass, action, {})

    assert result == '{"temp": 20}'


async def test_rest_http_error_returns_error_string(hass: HomeAssistant) -> None:
    """Non-2xx status produces an LLM-readable error string."""
    action = RESTAction(method="GET", url="https://example.com")

    fake_resp = MagicMock()
    fake_resp.status = 500
    fake_resp.text = AsyncMock(return_value="boom")
    session = MagicMock()
    session.request = MagicMock(return_value=_async_cm(fake_resp))

    with patch(
        "custom_components.smartchain.tools.actions.rest_action.async_get_clientsession",
        return_value=session,
    ):
        result = await execute_rest(hass, action, {})

    assert "500" in result


async def test_rest_timeout_returns_error_string(hass: HomeAssistant) -> None:
    """A TimeoutError from the request is reported as an LLM-readable string."""
    action = RESTAction(method="GET", url="https://example.com", timeout=1)

    def raise_timeout(*args, **kwargs):
        raise TimeoutError

    session = MagicMock()
    session.request = MagicMock(side_effect=raise_timeout)

    with patch(
        "custom_components.smartchain.tools.actions.rest_action.async_get_clientsession",
        return_value=session,
    ):
        result = await execute_rest(hass, action, {})

    assert result == "Error: request timed out"
