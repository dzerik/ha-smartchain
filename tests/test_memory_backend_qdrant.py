"""Tests for the Qdrant REST backend against a mocked aiohttp session."""

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.base import (
    BackendInitError,
    VectorRecord,
)
from custom_components.smartchain.tools.memory.backends.qdrant import (
    QdrantBackend,
    QdrantError,
    build_qdrant_filter,
    point_id_for,
    strip_userinfo,
)


def test_point_id_is_deterministic_uuid() -> None:
    a = point_id_for("logbook_abc123")
    b = point_id_for("logbook_abc123")
    c = point_id_for("logbook_other")
    assert a == b
    assert a != c
    assert len(a) == 36 and a.count("-") == 4


def test_build_qdrant_filter_empty() -> None:
    assert build_qdrant_filter(None) is None
    assert build_qdrant_filter({}) is None


def test_build_qdrant_filter_conditions() -> None:
    flt = build_qdrant_filter({"kind": "logbook", "agent_id": "a1"})
    assert flt == {
        "must": [
            {"key": "metadata.kind", "match": {"value": "logbook"}},
            {"key": "metadata.agent_id", "match": {"value": "a1"}},
        ]
    }


def test_filter_keys_match_the_nesting_upsert_writes(hass: HomeAssistant) -> None:
    """The filter path must address the payload shape `upsert` actually stores.

    `upsert` writes {"doc_id": …, "text": …, "metadata": {...}}, so a filter on
    a bare "kind" addresses a payload key that does not exist and matches
    nothing — which silently empties every filtered search and delete.
    """
    record = VectorRecord("d", [1.0, 0.0, 0.0], "t", {"kind": "logbook"})
    payload = {"doc_id": record.doc_id, "text": record.text, "metadata": record.metadata}

    key = build_qdrant_filter({"kind": "logbook"})["must"][0]["key"]
    container, _, leaf = key.rpartition(".")
    assert container == "metadata"
    assert payload[container][leaf] == "logbook"


def _response(status: int = 200, payload: dict | None = None):
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=payload or {})
    resp.text = AsyncMock(return_value="")
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=resp)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


@pytest.fixture
def session_and_calls():
    """A mocked aiohttp session recording (method, url, json) per request."""
    calls: list[tuple[str, str, dict | None]] = []
    responses: dict[str, object] = {}

    def _request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        # Extract the path from any URL, credentialed hosts included.
        rest = url.split("://", 1)[-1]
        path = "/" + rest.split("/", 1)[1] if "/" in rest else "/"
        # Try method+path first, then suffix-only
        method_path = f"{method} {path}"
        if method_path in responses:
            return responses[method_path]
        for suffix, resp in responses.items():
            if url.endswith(suffix):
                return resp
        return _response(200, {"result": {}})

    session = MagicMock()
    session.request = MagicMock(side_effect=_request)
    return session, calls, responses


async def test_initialize_creates_collection_with_dimension(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, calls, responses = session_and_calls
    responses["GET /collections/mem"] = _response(404, {})
    responses["PUT /collections/mem"] = _response(200, {"result": {}})

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
        await be.initialize(768)

    assert be.is_available is True
    creates = [c for c in calls if c[0] == "PUT" and c[1].endswith("/collections/mem")]
    assert creates
    assert creates[0][2]["vectors"] == {"size": 768, "distance": "Cosine"}


async def test_initialize_dimension_mismatch_raises(hass: HomeAssistant, session_and_calls) -> None:
    session, _calls, responses = session_and_calls
    responses["GET /collections/mem"] = _response(
        200, {"result": {"config": {"params": {"vectors": {"size": 768}}}}}
    )

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
        with pytest.raises(BackendInitError, match="1536"):
            await be.initialize(1536)
    assert be.is_available is False


async def test_api_key_travels_in_header(hass: HomeAssistant, session_and_calls) -> None:
    session, _calls, responses = session_and_calls
    responses["GET /collections/mem"] = _response(404, {})
    responses["PUT /collections/mem"] = _response(200, {"result": {}})

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", "secret-key", True)
        await be.initialize(3)

    headers = session.request.call_args.kwargs["headers"]
    assert headers["api-key"] == "secret-key"


async def test_upsert_maps_doc_id_and_keeps_original_in_payload(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, calls, responses = session_and_calls
    responses["GET /collections/mem"] = _response(404, {})
    responses["PUT /collections/mem"] = _response(200, {"result": {}})

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
        await be.initialize(3)
        await be.upsert([VectorRecord("logbook_abc", [1.0, 0.0, 0.0], "ta", {"kind": "logbook"})])

    points_calls = [c for c in calls if "/points" in c[1] and c[0] == "PUT"]
    assert points_calls
    point = points_calls[0][2]["points"][0]
    assert point["id"] == point_id_for("logbook_abc")
    assert point["payload"]["doc_id"] == "logbook_abc"
    assert point["payload"]["text"] == "ta"


async def test_query_translates_filter_and_maps_score(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, calls, responses = session_and_calls
    responses["GET /collections/mem"] = _response(404, {})
    responses["PUT /collections/mem"] = _response(200, {"result": {}})
    responses["POST /collections/mem/points/search"] = _response(
        200,
        {
            "result": [
                {
                    "score": 0.75,
                    "payload": {
                        "doc_id": "a",
                        "text": "ta",
                        "metadata": {"kind": "logbook"},
                    },
                }
            ]
        },
    )

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
        await be.initialize(3)
        hits = await be.query([1.0, 0.0, 0.0], top_k=5, where={"kind": "logbook"})

    assert [h.doc_id for h in hits] == ["a"]
    # Qdrant returns cosine similarity; the Protocol wants distance.
    assert hits[0].distance == pytest.approx(0.25)

    search = [c for c in calls if c[1].endswith("/collections/mem/points/search")][0]
    assert search[2]["filter"] == {
        "must": [{"key": "metadata.kind", "match": {"value": "logbook"}}]
    }


async def test_unreachable_server_raises_without_leaking_api_key(
    hass: HomeAssistant,
) -> None:
    session = MagicMock()
    session.request = MagicMock(side_effect=OSError("cannot connect to secret-host"))

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://secret-host:6333", "mem", "hunter2", True)
        with pytest.raises(BackendInitError) as exc:
            await be.initialize(3)

    assert "hunter2" not in str(exc.value)
    assert be.is_available is False


async def test_initialize_raises_on_http_error_status(
    hass: HomeAssistant, session_and_calls
) -> None:
    """Initialize must raise on HTTP error status (401/500), not silently continue."""
    session, _calls, responses = session_and_calls
    responses["GET /collections/mem"] = _response(401, {})

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", "wrong-key", True)
        with pytest.raises(BackendInitError) as exc:
            await be.initialize(3)

    assert "wrong-key" not in str(exc.value)
    assert be.is_available is False


async def test_runtime_failure_leaves_backend_available(
    hass: HomeAssistant, session_and_calls
) -> None:
    """Runtime failures (query/upsert) must leave backend marked available."""
    import aiohttp

    session, _calls, responses = session_and_calls
    responses["GET /collections/mem"] = _response(404, {})
    responses["PUT /collections/mem"] = _response(200, {"result": {}})

    # Store the original request function
    original_request = session.request.side_effect

    def _fail_on_search(method, url, **kwargs):
        # Fail only on search requests
        if url.endswith("/points/search"):
            raise aiohttp.ClientError("network timeout")
        # Use the original fixture logic for other requests
        return original_request(method, url, **kwargs)

    session.request = MagicMock(side_effect=_fail_on_search)

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
        await be.initialize(3)
        assert be.is_available is True

        hits = await be.query([1.0, 0.0, 0.0], top_k=5, where=None)
        assert hits == []
        # Backend must remain available after a transient query failure
        assert be.is_available is True


async def _ready(hass: HomeAssistant, session, responses, api_key=None, url="http://q:6333"):
    """Build an initialized backend against the mocked session."""
    responses["GET /collections/mem"] = _response(404, {})
    responses["PUT /collections/mem"] = _response(200, {"result": {}})
    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, url, "mem", api_key, True)
        await be.initialize(3)
    return be


async def test_writes_wait_for_durability(hass: HomeAssistant, session_and_calls) -> None:
    """Without wait=true qdrant only acknowledges, so read-after-write races."""
    session, calls, responses = session_and_calls
    responses["POST /collections/mem/points/count"] = _response(200, {"result": {"count": 0}})
    be = await _ready(hass, session, responses)

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        await be.upsert([VectorRecord("a", [1.0, 0.0, 0.0], "ta", {"kind": "logbook"})])
        await be.delete_where({"kind": "logbook"})

    upsert_url = [c[1] for c in calls if c[0] == "PUT" and "/points" in c[1]][-1]
    delete_url = [c[1] for c in calls if "/points/delete" in c[1]][-1]
    assert upsert_url.endswith("?wait=true")
    assert delete_url.endswith("?wait=true")


async def test_retention_delete_waits_for_durability(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, calls, responses = session_and_calls
    responses["POST /collections/mem/points/scroll"] = _response(
        200,
        {
            "result": {
                "points": [
                    {"id": "p1", "payload": {"metadata": {"timestamp": "2020-01-01T00:00:00"}}}
                ],
                "next_page_offset": None,
            }
        },
    )
    be = await _ready(hass, session, responses)

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        assert await be.delete_older_than("2026-01-01T00:00:00") == 1

    delete_url = [c[1] for c in calls if "/points/delete" in c[1]][-1]
    assert delete_url.endswith("?wait=true")


async def test_upsert_raises_when_the_batch_is_rejected(
    hass: HomeAssistant, session_and_calls
) -> None:
    """A rejected write must not look like a success to MemoryStore."""
    session, _calls, responses = session_and_calls
    be = await _ready(hass, session, responses)
    responses["PUT /collections/mem/points?wait=true"] = _response(500, {})

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        with pytest.raises(QdrantError):
            await be.upsert([VectorRecord("a", [1.0, 0.0, 0.0], "ta", {})])


async def test_delete_where_returns_a_real_count_not_a_flag(
    hass: HomeAssistant, session_and_calls
) -> None:
    """The number is summed into smartchain_memory_cleared, so 0/1 is wrong."""
    session, _calls, responses = session_and_calls
    responses["POST /collections/mem/points/count"] = _response(200, {"result": {"count": 7}})
    responses["POST /collections/mem/points/delete?wait=true"] = _response(
        200, {"result": {"status": "acknowledged"}}
    )
    be = await _ready(hass, session, responses)

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        assert await be.delete_where({"kind": "logbook"}) == 7


async def test_delete_where_raises_when_qdrant_rejects_it(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, _calls, responses = session_and_calls
    responses["POST /collections/mem/points/count"] = _response(200, {"result": {"count": 2}})
    be = await _ready(hass, session, responses)
    responses["POST /collections/mem/points/delete?wait=true"] = _response(403, {})

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        with pytest.raises(QdrantError):
            await be.delete_where({"kind": "logbook"})


def test_strip_userinfo_removes_credentials() -> None:
    assert strip_userinfo("https://qu:s3cr3t@host:6333") == "https://host:6333"
    assert strip_userinfo("http://q:6333") == "http://q:6333"
    # A port that will not parse must not defeat the scrub.
    assert "URLSECRET" not in strip_userinfo("https://qu:URLSECRET@badhost.invalid:notaport")


async def test_url_password_never_reaches_the_log(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """aiohttp.InvalidURL.__str__ is the whole URL and it subclasses ClientError."""
    import aiohttp

    session = MagicMock()
    session.request = MagicMock(
        side_effect=aiohttp.InvalidURL("https://qu:URLSECRET@badhost.invalid:notaport")
    )

    caplog.set_level(logging.DEBUG)
    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        url = "https://qu:URLSECRET@badhost.invalid:6333"
        be = QdrantBackend(hass, url, "mem", "hunter2", True)
        with pytest.raises(BackendInitError) as exc:
            await be.initialize(3)

    assert "URLSECRET" not in caplog.text
    assert "hunter2" not in caplog.text
    assert "URLSECRET" not in str(exc.value)
    assert "hunter2" not in str(exc.value)
    # `from err` would keep the credentialed URL reachable on __cause__.
    assert exc.value.__cause__ is None


async def test_runtime_transport_failures_do_not_leak_the_url(
    hass: HomeAssistant, session_and_calls, caplog: pytest.LogCaptureFixture
) -> None:
    import aiohttp

    session, _calls, responses = session_and_calls
    be = await _ready(
        hass, session, responses, api_key="hunter2", url="https://qu:URLSECRET@h:6333"
    )

    session.request = MagicMock(
        side_effect=aiohttp.InvalidURL("https://qu:URLSECRET@badhost.invalid:notaport")
    )
    caplog.clear()
    caplog.set_level(logging.DEBUG)
    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        assert await be.query([1.0, 0.0, 0.0], top_k=3, where=None) == []
        with pytest.raises(QdrantError):
            await be.upsert([VectorRecord("a", [1.0, 0.0, 0.0], "ta", {})])
        with pytest.raises(QdrantError):
            await be.delete_where(None)
        with pytest.raises(QdrantError):
            await be.delete_older_than("2026-01-01T00:00:00")

    assert "URLSECRET" not in caplog.text
    assert "hunter2" not in caplog.text


async def test_dimension_mismatch_names_the_collection_to_delete(
    hass: HomeAssistant, session_and_calls
) -> None:
    """clear_memory cannot reach an unavailable store, so it must not be advised."""
    session, _calls, responses = session_and_calls
    responses["GET /collections/mem"] = _response(
        200, {"result": {"config": {"params": {"vectors": {"size": 768}}}}}
    )

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "https://qu:URLSECRET@h:6333", "mem", "hunter2", True)
        with pytest.raises(BackendInitError) as exc:
            await be.initialize(1536)

    message = str(exc.value)
    assert "Delete the collection mem" in message
    assert "smartchain.reload_tools" in message
    assert "clear_memory" not in message
    # The message reaches users and the LLM: no credential, and no server URL.
    assert "URLSECRET" not in message
    assert "hunter2" not in message
    assert "6333" not in message


async def test_query_raises_on_non_2xx_status(hass: HomeAssistant, session_and_calls) -> None:
    """A rejected search must not be indistinguishable from an empty result.

    Returning [] here made a broken server read to the LLM as "No memories
    matched the query". MemoryStore.search catches QdrantError, logs it and
    returns [], so the conversation survives and the cause lands in the log.
    """
    session, _calls, responses = session_and_calls
    responses["GET /collections/mem"] = _response(404, {})
    responses["PUT /collections/mem"] = _response(200, {"result": {}})
    responses["POST /collections/mem/points/search"] = _response(500, {})

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "https://qu:URLSECRET@h:6333", "mem", "hunter2", True)
        await be.initialize(3)
        with pytest.raises(QdrantError) as exc:
            await be.query([1.0, 0.0, 0.0], top_k=5, where=None)

    message = str(exc.value)
    assert "500" in message
    assert "URLSECRET" not in message
    assert "hunter2" not in message


async def test_list_metadata_follows_the_scroll_cursor(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, _calls, responses = session_and_calls
    be = await _ready(hass, session, responses)
    pages = [
        (
            200,
            {
                "result": {
                    "points": [{"payload": {"metadata": {"kind": "entity"}, "doc_id": "a"}}],
                    "next_page_offset": "cur1",
                }
            },
        ),
        (
            200,
            {
                "result": {
                    "points": [{"payload": {"metadata": {"kind": "entity"}, "doc_id": "b"}}],
                    "next_page_offset": None,
                }
            },
        ),
    ]
    with patch.object(be, "_request", new=AsyncMock(side_effect=pages)) as req:
        result = await be.list_metadata({"kind": "entity"})

    assert set(result) == {"a", "b"}
    assert req.await_count == 2
    assert req.await_args_list[1].args[2]["offset"] == "cur1"


async def test_update_metadata_sets_payload_and_waits(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, _calls, responses = session_and_calls
    be = await _ready(hass, session, responses)
    with patch.object(be, "_request", new=AsyncMock(return_value=(200, {}))) as req:
        assert await be.update_metadata("a", {"kind": "entity", "state": "on"}) is True

    path = req.await_args.args[1]
    assert "points/payload" in path
    assert "wait=true" in path


async def test_update_metadata_raises_on_a_bad_status(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, _calls, responses = session_and_calls
    be = await _ready(hass, session, responses)
    with (
        patch.object(be, "_request", new=AsyncMock(return_value=(500, {}))),
        pytest.raises(QdrantError),
    ):
        await be.update_metadata("a", {"kind": "entity"})


async def test_update_metadata_is_a_no_op_when_backend_is_unavailable(
    hass: HomeAssistant,
) -> None:
    """Carried forward from Task 1: the is_available guard must not be bypassed."""
    be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
    assert await be.update_metadata("a", {"kind": "entity"}) is False


async def test_list_metadata_is_a_no_op_when_backend_is_unavailable(
    hass: HomeAssistant,
) -> None:
    be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
    assert await be.list_metadata() == {}


async def test_store_search_degrades_to_empty_when_the_backend_raises(
    hass: HomeAssistant, caplog
) -> None:
    """The raise from `query` must stay inside MemoryStore, not reach the user."""
    from custom_components.smartchain.tools.memory.store import MemoryStore

    embeddings = MagicMock()
    embeddings.embed_query = AsyncMock(return_value=[1.0, 0.0, 0.0])
    backend = MagicMock()
    backend.name = "qdrant"
    backend.query = AsyncMock(side_effect=QdrantError("qdrant search failed with status 500"))

    store = MemoryStore(hass, embeddings, backend)
    store.is_available = True

    with caplog.at_level(logging.ERROR):
        assert await store.search("anything") == []
    assert "memory search failed" in caplog.text
