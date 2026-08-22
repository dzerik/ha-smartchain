"""Qdrant backend over its REST API.

Deliberately avoids `qdrant-client`: Home Assistant already ships aiohttp, so
this backend costs no new dependency. Same reasoning as the MCP SSE transport.

Qdrant point IDs must be unsigned integers or UUIDs, while SmartChain document
IDs are strings such as `logbook_<sha1>` or `<uuid>_chunk0`. They are mapped
with uuid5, which is deterministic — so re-upserting the same document ID
overwrites rather than duplicates — and the original is kept in the payload.
"""

import asyncio
import logging
import uuid
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ....const import MEMORY_BACKEND_TIMEOUT_SECONDS
from .base import BackendInitError, Filter, VectorHit, VectorRecord

LOGGER = logging.getLogger(__name__)

_NAMESPACE = uuid.NAMESPACE_URL


def point_id_for(doc_id: str) -> str:
    """Map a SmartChain document ID onto a deterministic Qdrant point UUID."""
    return str(uuid.uuid5(_NAMESPACE, doc_id))


def build_qdrant_filter(where: Filter | None) -> dict[str, Any] | None:
    """Translate the neutral filter into Qdrant's filter object."""
    if not where:
        return None
    return {"must": [{"key": key, "match": {"value": value}} for key, value in where.items()]}


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

    async def initialize(self, dim: int) -> None:
        try:
            status, body = await self._request("GET", f"/collections/{self.collection}")
        except (aiohttp.ClientError, OSError, TimeoutError) as err:
            self.is_available = False
            LOGGER.exception("qdrant is unreachable")
            raise BackendInitError(
                "The configured Qdrant server is unreachable; see the Home "
                "Assistant log for details."
            ) from err

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
                    "readable vector size; the store may be corrupted. Clear this "
                    "store with smartchain.clear_memory, then call "
                    "smartchain.reload_tools."
                )
            if int(existing) != dim:
                self.is_available = False
                raise BackendInitError(
                    f"collection {self.collection} stores {existing}-dimensional "
                    f"vectors but the configured model produces {dim}. Clear this "
                    "store with smartchain.clear_memory, then call "
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
                LOGGER.exception("qdrant collection creation failed")
                raise BackendInitError(
                    "Could not create the Qdrant collection; see the Home "
                    "Assistant log for details."
                ) from err

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
            await self._request("PUT", f"/collections/{self.collection}/points", {"points": points})
        except (aiohttp.ClientError, OSError, TimeoutError):
            LOGGER.exception("qdrant upsert failed")

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
        except (aiohttp.ClientError, OSError, TimeoutError):
            LOGGER.exception("qdrant search failed")
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
                _status, body = await self._request(
                    "POST", f"/collections/{self.collection}/points/scroll", payload
                )
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
                await self._request(
                    "POST",
                    f"/collections/{self.collection}/points/delete",
                    {"points": to_delete},
                )
        except (aiohttp.ClientError, OSError, TimeoutError):
            LOGGER.exception("qdrant retention sweep failed")
            return 0
        return len(to_delete)

    async def delete_where(self, where: Filter | None) -> int:
        if not self.is_available:
            return 0
        flt = build_qdrant_filter(where)
        body_payload: dict[str, Any] = (
            {"filter": flt} if flt is not None else {"filter": {"must": []}}
        )
        try:
            _status, body = await self._request(
                "POST", f"/collections/{self.collection}/points/delete", body_payload
            )
        except (aiohttp.ClientError, OSError, TimeoutError):
            LOGGER.exception("qdrant delete failed")
            return 0
        # Qdrant does not report a deleted count; report the operation status.
        return int(bool((body.get("result") or {}).get("status") == "completed"))

    async def close(self) -> None:
        # The aiohttp session is owned by Home Assistant and must not be closed.
        self.is_available = False
