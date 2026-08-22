"""Tests for the VectorBackend shared types."""

import pytest

from custom_components.smartchain.tools.memory.backends.base import (
    BackendInitError,
    VectorHit,
    VectorRecord,
)


def test_vector_record_fields() -> None:
    rec = VectorRecord(
        doc_id="d1",
        vector=[0.1, 0.2],
        text="hello",
        metadata={"kind": "conversation"},
    )
    assert rec.doc_id == "d1"
    assert rec.vector == [0.1, 0.2]
    assert rec.text == "hello"
    assert rec.metadata["kind"] == "conversation"


def test_vector_hit_fields() -> None:
    hit = VectorHit(doc_id="d1", text="hello", metadata={"kind": "logbook"}, distance=0.25)
    assert hit.doc_id == "d1"
    assert hit.distance == 0.25
    assert hit.metadata["kind"] == "logbook"


def test_records_are_frozen() -> None:
    rec = VectorRecord(doc_id="d1", vector=[0.0], text="t", metadata={})
    with pytest.raises(AttributeError):
        rec.doc_id = "other"  # type: ignore[misc]


def test_backend_init_error_is_exception() -> None:
    assert issubclass(BackendInitError, Exception)
