"""Qdrant backend over its REST API.

Deliberately avoids `qdrant-client`: Home Assistant already ships aiohttp, so
this backend costs no new dependency. Same reasoning as the MCP SSE transport.

Qdrant point IDs must be unsigned integers or UUIDs, while SmartChain document
IDs are strings such as `logbook_<sha1>` or `<uuid>_chunk0`. They are mapped
with uuid5, which is deterministic — so re-upserting the same document ID
overwrites rather than duplicates — and the original is kept in the payload.

The configured URL may embed credentials (`https://user:pass@host`), and
`aiohttp.InvalidURL.__str__` is the whole URL. Nothing here may therefore log
an exception object or chain a cause: every message uses `_safe_url`, which has
the userinfo stripped, and reports only the exception's class name.
"""

import asyncio
import logging
import uuid
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ....const import MEMORY_BACKEND_TIMEOUT_SECONDS
from .base import BackendInitError, Filter, VectorHit, VectorRecord

LOGGER = logging.getLogger(__name__)

_NAMESPACE = uuid.NAMESPACE_URL

# Qdrant nests the neutral metadata one level down inside the point payload
# (see `upsert`), and its filter keys are JSON paths — so every filter key
# needs this prefix or the condition matches nothing at all.
_PAYLOAD_PREFIX = "metadata."


class QdrantError(RuntimeError):
    """A Qdrant request failed at runtime.

    Distinct from BackendInitError: the store stays available and MemoryStore
    logs this and degrades the single operation. Never carries the server URL.
    """


def strip_userinfo(url: str) -> str:
    """Return `url` without any `user:password@`, safe to log or surface."""
    try:
        parts = urlsplit(url)
        netloc = parts.netloc
    except ValueError:
        return "<the configured Qdrant server>"
    if not netloc or "@" not in netloc:
        return url
    return urlunsplit(
        (parts.scheme, netloc.rsplit("@", 1)[1], parts.path, parts.query, parts.fragment)
    )


def point_id_for(doc_id: str) -> str:
    """Map a SmartChain document ID onto a deterministic Qdrant point UUID."""
    return str(uuid.uuid5(_NAMESPACE, doc_id))


def build_qdrant_filter(where: Filter | None) -> dict[str, Any] | None:
    """Translate the neutral filter into Qdrant's filter object.

    Keys are payload JSON paths, so each neutral key is prefixed with
    `metadata.` to match the nesting `upsert` writes.
    """
    if not where:
        return None
    return {
        "must": [
            {"key": f"{_PAYLOAD_PREFIX}{key}", "match": {"value": value}}
            for key, value in where.items()
        ]
    }


class QdrantBackend:
    """Vectors in a Qdrant collection, addressed over REST."""

    name = "qdrant"

    def __init__(
        self,
        hass: HomeAssistant,
        url: str,
        collection: str,
        api_key: str | None,
        verify_ssl: bool,
    ) -> None:
        self.hass = hass
        self.url = url.rstrip("/")
        self._safe_url = strip_userinfo(self.url)
        self.collection = collection
        self._api_key = api_key
        self.verify_ssl = verify_ssl
        self.is_available = False
        self._dim: int | None = None

    @property
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["api-key"] = self._api_key
        return headers

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        session = async_get_clientsession(self.hass, verify_ssl=self.verify_ssl)
        async with asyncio.timeout(MEMORY_BACKEND_TIMEOUT_SECONDS):
            async with session.request(
                method,
                f"{self.url}{path}",
                json=payload,
                headers=self._headers,
            ) as resp:
                if resp.status >= 400 and resp.status != 404:
                    body = await resp.text()
                    LOGGER.warning("qdrant %s %s -> %s: %s", method, path, resp.status, body)
                    return resp.status, {}
                if resp.status == 404:
                    return 404, {}
                return resp.status, await resp.json()

    @staticmethod
    def _check_status(status: int, operation: str) -> None:
        """Raise unless the response status is 2xx.

        Without this a rejected batch looks identical to a successful one, and
        MemoryStore reports document IDs for a write that never landed.
        """
        if not 200 <= status < 300:
            raise QdrantError(f"qdrant {operation} failed with status {status}")

    def _log_transport_failure(self, operation: str, err: BaseException) -> None:
        """Log a transport failure without ever rendering the exception.

        `aiohttp.InvalidURL.__str__` is the full URL, credentials included, so
        only the exception's class name may be logged.
        """
        LOGGER.error(
            "qdrant %s failed against %s: %s", operation, self._safe_url, type(err).__name__
        )

    async def initialize(self, dim: int) -> None:
        try:
            status, body = await self._request("GET", f"/collections/{self.collection}")
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            self.is_available = False
            self._log_transport_failure("collection lookup", err)
            raise BackendInitError(
                f"The Qdrant server at {self._safe_url} is unreachable; see the "
                "Home Assistant log for details."
            ) from None

        if status == 200:
            existing = (
                body.get("result", {})
                .get("config", {})
                .get("params", {})
                .get("vectors", {})
                .get("size")
            )
            if existing is None:
                self.is_available = False
                raise BackendInitError(
                    f"Qdrant collection {self.collection} exists but has no "
                    "readable vector size; the store may be corrupted. Delete the "
                    f"collection {self.collection} on the Qdrant server, then call "
                    "smartchain.reload_tools."
                )
            if int(existing) != dim:
                self.is_available = False
                raise BackendInitError(
                    f"collection {self.collection} stores {existing}-dimensional "
                    f"vectors but the configured model produces {dim}. Delete the "
                    f"collection {self.collection} on the Qdrant server, then call "
                    "smartchain.reload_tools."
                )
        elif status == 404:
            try:
                create_status, _body = await self._request(
                    "PUT",
                    f"/collections/{self.collection}",
                    {"vectors": {"size": dim, "distance": "Cosine"}},
                )
            except (aiohttp.ClientError, OSError, TimeoutError) as err:
                self.is_available = False
                self._log_transport_failure("collection creation", err)
                raise BackendInitError(
                    "Could not create the Qdrant collection; see the Home "
                    "Assistant log for details."
                ) from None

            if create_status < 200 or create_status >= 300:
                self.is_available = False
                raise BackendInitError(
                    f"Qdrant collection creation failed with status {create_status}; "
                    "see the Home Assistant log for details."
                )
        else:
            self.is_available = False
            raise BackendInitError(
                f"Qdrant server returned status {status} when querying collection "
                f"{self.collection}; see the Home Assistant log for details."
            )

        self._dim = dim
        self.is_available = True

    async def upsert(self, records: list[VectorRecord]) -> None:
        if not self.is_available or not records:
            return
        points = [
            {
                "id": point_id_for(r.doc_id),
                "vector": list(r.vector),
                "payload": {"doc_id": r.doc_id, "text": r.text, "metadata": r.metadata},
            }
            for r in records
        ]
        try:
            # wait=true makes the write durable before we return, so a search
            # issued right afterwards sees it. Without it Qdrant only
            # acknowledges the request and read-after-write is a race.
            status, _body = await self._request(
                "PUT",
                f"/collections/{self.collection}/points?wait=true",
                {"points": points},
            )
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            self._log_transport_failure("upsert", err)
            raise QdrantError("qdrant upsert failed to reach the server") from None
        self._check_status(status, "upsert")

    async def query(self, vector: list[float], top_k: int, where: Filter | None) -> list[VectorHit]:
        if not self.is_available:
            return []
        payload: dict[str, Any] = {
            "vector": list(vector),
            "limit": top_k,
            "with_payload": True,
        }
        flt = build_qdrant_filter(where)
        if flt is not None:
            payload["filter"] = flt

        try:
            _status, body = await self._request(
                "POST", f"/collections/{self.collection}/points/search", payload
            )
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            self._log_transport_failure("search", err)
            return []

        hits: list[VectorHit] = []
        for item in body.get("result") or []:
            data = item.get("payload") or {}
            hits.append(
                VectorHit(
                    doc_id=data.get("doc_id", ""),
                    text=data.get("text", ""),
                    metadata=data.get("metadata") or {},
                    # Qdrant reports cosine similarity; the Protocol wants distance.
                    distance=1.0 - float(item.get("score", 0.0)),
                )
            )
        return hits

    async def delete_older_than(self, cutoff_iso: str) -> int:
        if not self.is_available:
            return 0
        # Qdrant range matching works on numbers, not ISO strings, so the
        # timestamp filter is applied by scrolling and comparing client-side.
        # Home-scale stores make this acceptable; pgvector is the documented
        # choice when retention volume grows.
        to_delete: list[str] = []
        offset: Any = None
        try:
            while True:
                payload: dict[str, Any] = {"limit": 256, "with_payload": True}
                if offset is not None:
                    payload["offset"] = offset
                status, body = await self._request(
                    "POST", f"/collections/{self.collection}/points/scroll", payload
                )
                self._check_status(status, "retention scroll")
                result = body.get("result") or {}
                for point in result.get("points") or []:
                    meta = (point.get("payload") or {}).get("metadata") or {}
                    ts = str(meta.get("timestamp", ""))
                    if ts and ts < cutoff_iso:
                        to_delete.append(point["id"])
                offset = result.get("next_page_offset")
                if offset is None:
                    break

            if to_delete:
                status, _body = await self._request(
                    "POST",
                    f"/collections/{self.collection}/points/delete?wait=true",
                    {"points": to_delete},
                )
                self._check_status(status, "retention delete")
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            self._log_transport_failure("retention sweep", err)
            raise QdrantError("qdrant retention sweep failed to reach the server") from None
        return len(to_delete)

    async def delete_where(self, where: Filter | None) -> int:
        """Delete every point matching `where` and return how many went.

        Qdrant's delete API reports only an operation status, never a count, so
        the matching points are counted first with an exact `points/count`
        request. That is one extra round trip per clear, which is acceptable
        for a user-invoked service, and it keeps the number that reaches the
        `smartchain_memory_cleared` event a real count.
        """
        if not self.is_available:
            return 0
        flt = build_qdrant_filter(where)
        count_payload: dict[str, Any] = {"exact": True}
        delete_payload: dict[str, Any] = {"filter": flt if flt is not None else {"must": []}}
        if flt is not None:
            count_payload["filter"] = flt

        try:
            status, body = await self._request(
                "POST", f"/collections/{self.collection}/points/count", count_payload
            )
            self._check_status(status, "count")
            matched = int((body.get("result") or {}).get("count", 0))

            status, _body = await self._request(
                "POST",
                f"/collections/{self.collection}/points/delete?wait=true",
                delete_payload,
            )
            self._check_status(status, "delete")
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            self._log_transport_failure("delete", err)
            raise QdrantError("qdrant delete failed to reach the server") from None
        return matched

    async def close(self) -> None:
        # The aiohttp session is owned by Home Assistant and must not be closed.
        self.is_available = False
