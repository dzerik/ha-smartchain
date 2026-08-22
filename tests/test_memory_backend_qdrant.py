"""Tests for the Qdrant REST backend against a mocked aiohttp session."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.smartchain.tools.memory.backends.base import (
    BackendInitError,
    VectorRecord,
)
from custom_components.smartchain.tools.memory.backends.qdrant import (
    QdrantBackend,
    build_qdrant_filter,
    point_id_for,
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
            {"key": "kind", "match": {"value": "logbook"}},
            {"key": "agent_id", "match": {"value": "a1"}},
        ]
    }


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
    responses["/collections/mem"] = _response(404, {})

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
    responses["/collections/mem"] = _response(
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
    responses["/collections/mem"] = _response(404, {})

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
    responses["/collections/mem"] = _response(404, {})

    with patch(
        "custom_components.smartchain.tools.memory.backends.qdrant.async_get_clientsession",
        return_value=session,
    ):
        be = QdrantBackend(hass, "http://q:6333", "mem", None, True)
        await be.initialize(3)
        await be.upsert([VectorRecord("logbook_abc", [1.0, 0.0, 0.0], "ta", {"kind": "logbook"})])

    points_calls = [c for c in calls if c[1].endswith("/points") and c[0] == "PUT"]
    assert points_calls
    point = points_calls[0][2]["points"][0]
    assert point["id"] == point_id_for("logbook_abc")
    assert point["payload"]["doc_id"] == "logbook_abc"
    assert point["payload"]["text"] == "ta"


async def test_query_translates_filter_and_maps_score(
    hass: HomeAssistant, session_and_calls
) -> None:
    session, calls, responses = session_and_calls
    responses["/collections/mem"] = _response(404, {})
    responses["/points/search"] = _response(
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

    search = [c for c in calls if c[1].endswith("/points/search")][0]
    assert search[2]["filter"] == {"must": [{"key": "kind", "match": {"value": "logbook"}}]}


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
