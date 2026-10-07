import hashlib
from pathlib import Path

import numpy as np
import pytest

from ddr_rag.config import load_settings
from ddr_rag.embedder import write_embedding_artifact
from ddr_rag.schemas import ChunkRecord
from ddr_rag.vector_store import VectorStoreError, build_local_index, validate_local_index
from test_config import write_config


def make_record(index: int) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"TEST:{index:06d}:abc",
        doc_id="TEST",
        text=f"DDR layout rule {index}",
        title="Test guide",
        revision="R1",
        source_path=Path("data/raw/vendor/guide.pdf"),
        section="DDR",
        page_numbers=[index + 1],
        page_start=index + 1,
        page_end=index + 1,
        memory_types=["DDR4"],
        status="active",
        token_count=4,
    )


def write_chunks(settings, records: list[ChunkRecord]) -> None:
    output = settings.resolve_path(settings.paths.chunks)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8")


def test_qdrant_local_index_is_persistent_and_payload_is_traceable(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    records = [make_record(0), make_record(1)]
    write_chunks(settings, records)
    vectors = np.zeros((2, 1024), dtype=np.float32)
    vectors[0, 0] = 1.0
    vectors[1, 1] = 1.0
    chunk_hash = hashlib.sha256(settings.resolve_path(settings.paths.chunks).read_bytes()).hexdigest()
    write_embedding_artifact(settings, records, chunk_hash, vectors)

    report = build_local_index(settings)

    assert report["point_count"] == 2
    assert report["dimension"] == 1024
    assert validate_local_index(settings)["collection"] == "test"
    with pytest.raises(VectorStoreError, match="already exists"):
        build_local_index(settings)

    rebuilt = build_local_index(settings, replace=True)

    assert rebuilt["point_count"] == 2
    assert validate_local_index(settings)["point_count"] == 2
