"""`verify_ssl` on the SSE and streamable-HTTP MCP transports.

USAGE.md §8.3 promises "`verify_ssl: false` is honoured for SSE/HTTP transports
via a custom httpx client factory". Until this file, neither branch of
`_open_transport` nor `_insecure_httpx_factory` was executed by any test — the
only `connect()` test drives stdio, which has no TLS at all.

The mutation that matters here is the reverse one. Substituting the insecure
factory unconditionally silently drops certificate verification for *every*
remote MCP server, including the ones whose `headers` carry a bearer token, and
leaves the whole suite green. So each test below pins both directions: the
factory is installed at `verify_ssl: false` and absent at `verify_ssl: true`.
"""

import ssl
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from custom_components.smartchain.tools.mcp.client import (
    MCPClient,
    _insecure_httpx_factory,
)
from custom_components.smartchain.tools.mcp.config import HTTPConfig, SSEConfig


def _session_ctx():
    """A patched ClientSession context whose initialize() is a no-op."""
    session = MagicMock()
    session.initialize = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return session, ctx


def _transport_ctx(streams):
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=streams)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


@pytest.mark.parametrize("verify_ssl", [True, False])
async def test_sse_transport_installs_insecure_factory_only_when_disabled(
    verify_ssl: bool,
) -> None:
    cfg = SSEConfig(
        name="brave",
        url="https://example.com/mcp/brave",
        headers={"Authorization": "Bearer s3cret"},
        timeout=17,
        verify_ssl=verify_ssl,
    )
    session, session_ctx = _session_ctx()
    sse_ctx = _transport_ctx((MagicMock(), MagicMock()))

    with (
        patch(
            "custom_components.smartchain.tools.mcp.client.sse_client",
            return_value=sse_ctx,
        ) as sse,
        patch(
            "custom_components.smartchain.tools.mcp.client.ClientSession",
            return_value=session_ctx,
        ),
    ):
        client = MCPClient(cfg)
        await client.connect()
        assert client._session is session
        await client.close()

    url, kwargs = sse.call_args.args[0], sse.call_args.kwargs
    assert url == "https://example.com/mcp/brave"
    assert kwargs["headers"] == {"Authorization": "Bearer s3cret"}
    assert kwargs["timeout"] == 17
    if verify_ssl:
        assert "httpx_client_factory" not in kwargs
    else:
        assert kwargs["httpx_client_factory"] is _insecure_httpx_factory


@pytest.mark.parametrize("verify_ssl", [True, False])
async def test_http_transport_installs_insecure_factory_only_when_disabled(
    verify_ssl: bool,
) -> None:
    cfg = HTTPConfig(
        name="github",
        url="https://api.example.com/mcp/github",
        headers={"Authorization": "Bearer s3cret"},
        timeout=23,
        verify_ssl=verify_ssl,
    )
    session, session_ctx = _session_ctx()
    read, write, extra = MagicMock(), MagicMock(), MagicMock()
    http_ctx = _transport_ctx((read, write, extra))

    with (
        patch(
            "custom_components.smartchain.tools.mcp.client.streamablehttp_client",
            return_value=http_ctx,
        ) as http,
        patch(
            "custom_components.smartchain.tools.mcp.client.ClientSession",
            return_value=session_ctx,
        ) as session_cls,
    ):
        client = MCPClient(cfg)
        await client.connect()
        assert client._session is session
        await client.close()

    url, kwargs = http.call_args.args[0], http.call_args.kwargs
    assert url == "https://api.example.com/mcp/github"
    assert kwargs["headers"] == {"Authorization": "Bearer s3cret"}
    assert kwargs["timeout"] == 23
    if verify_ssl:
        assert "httpx_client_factory" not in kwargs
    else:
        assert kwargs["httpx_client_factory"] is _insecure_httpx_factory
    # The third stream element is Streamable HTTP's session-id callback, not a
    # stream; passing it on would make ClientSession(*streams) raise.
    assert session_cls.call_args.args == (read, write)


def test_insecure_factory_really_disables_certificate_verification() -> None:
    """The factory's whole purpose: an httpx client that does not check certs."""
    client = _insecure_httpx_factory()
    context = client._transport._pool._ssl_context
    assert context.verify_mode == ssl.CERT_NONE
    assert context.check_hostname is False


def test_insecure_factory_forwards_headers_auth_and_timeout() -> None:
    """The mcp SDK hands the factory the per-request settings; none may be dropped."""
    auth = httpx.BasicAuth("u", "p")
    timeout = httpx.Timeout(5.0)
    client = _insecure_httpx_factory(
        headers={"Authorization": "Bearer s3cret"},
        timeout=timeout,
        auth=auth,
    )
    assert client.headers["authorization"] == "Bearer s3cret"
    assert client.timeout == timeout
    assert client.auth is auth
    assert client.follow_redirects is True


def test_insecure_factory_defaults_to_the_sdk_read_timeout() -> None:
    """With no timeout supplied the factory must not fall back to httpx's 5 s.

    MCP servers stream long-running tool results; the SDK's own factory uses a
    300 s read timeout, and a 5 s one would abort them.
    """
    client = _insecure_httpx_factory()
    assert client.timeout.read == 300
    assert client.timeout.connect == 30
