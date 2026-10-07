from pathlib import Path

import hashlib
import numpy as np

from ddr_rag.config import load_settings
from ddr_rag.embedder import write_embedding_artifact
from ddr_rag.schemas import ChunkRecord
from ddr_rag.retriever import search_vector
from ddr_rag.vector_store import build_local_index
from test_config import write_config


def make_record(index: int, memory_type: str, status: str = "active") -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"TEST:{index:06d}:abc",
        doc_id=f"TEST_{memory_type}",
        text=f"{memory_type} layout evidence {index}",
        title="Test guide",
        revision="R1",
        source_path=Path("data/raw/vendor/guide.pdf"),
        section="DDR",
        page_numbers=[index + 1],
        page_start=index + 1,
        page_end=index + 1,
        memory_types=[memory_type],
        status=status,
        token_count=4,
    )


def test_dense_vector_search_preserves_filters_and_citations(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    records = [make_record(0, "DDR4"), make_record(1, "LPDDR4"), make_record(2, "DDR4", "archived")]
    chunk_path = settings.resolve_path(settings.paths.chunks)
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_path.write_text("".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8")
    vectors = np.zeros((3, 1024), dtype=np.float32)
    vectors[0, 0] = 1.0
    vectors[1, 1] = 1.0
    vectors[2, 2] = 1.0
    chunk_hash = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
    write_embedding_artifact(settings, records, chunk_hash, vectors)
    build_local_index(settings)

    results = search_vector(settings, vectors[0], memory_type="DDR4")

    assert [result.chunk.chunk_id for result in results] == [records[0].chunk_id]
    assert results[0].score == 1.0
    assert results[0].chunk.page_numbers == [1]
    assert results[0].retrieval_sources == ["dense"]


def test_ddr4_filter_excludes_lpddr4_specific_chunk_in_mixed_document(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    records = [
        make_record(0, "DDR4"),
        make_record(1, "LPDDR4"),
    ]
    for record in records:
        record.memory_types = ["DDR4", "LPDDR4"]
    chunk_path = settings.resolve_path(settings.paths.chunks)
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_path.write_text("".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8")
    vectors = np.zeros((2, 1024), dtype=np.float32)
    vectors[0, 0] = 1.0
    vectors[1, 1] = 1.0
    chunk_hash = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
    write_embedding_artifact(settings, records, chunk_hash, vectors)
    build_local_index(settings)

    results = search_vector(settings, vectors[0], memory_type="DDR4")

    assert [result.chunk.chunk_id for result in results] == [records[0].chunk_id]


def test_ddr4_filter_excludes_incidental_ddr4_in_lpddr_specific_chunk(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    records = [
        make_record(0, "DDR4"),
        make_record(1, "LPDDR4"),
    ]
    records[1].text = "DDR4 VTT support; LPDDR4 topology; LPDDR4 ODT; LPDDR4 routing"
    for record in records:
        record.memory_types = ["DDR4", "LPDDR4"]
    chunk_path = settings.resolve_path(settings.paths.chunks)
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_path.write_text("".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8")
    vectors = np.zeros((2, 1024), dtype=np.float32)
    vectors[0, 0] = 1.0
    vectors[1, 1] = 1.0
    chunk_hash = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
    write_embedding_artifact(settings, records, chunk_hash, vectors)
    build_local_index(settings)

    results = search_vector(settings, vectors[0], memory_type="DDR4")

    assert [result.chunk.chunk_id for result in results] == [records[0].chunk_id]


def test_dense_vector_search_accepts_multiple_documents_for_one_part(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    records = [make_record(0, "DDR4"), make_record(1, "DDR4"), make_record(2, "DDR4")]
    records[0].doc_id = "RK_GUIDE"
    records[1].doc_id = "RK_NOTE"
    records[2].doc_id = "TI_GUIDE"
    chunk_path = settings.resolve_path(settings.paths.chunks)
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_path.write_text("".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8")
    vectors = np.zeros((3, 1024), dtype=np.float32)
    vectors[:, 0] = 1.0
    chunk_hash = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
    write_embedding_artifact(settings, records, chunk_hash, vectors)
    build_local_index(settings)

    results = search_vector(settings, vectors[0], doc_ids=("RK_GUIDE", "RK_NOTE"), limit=3)

    assert {result.chunk.doc_id for result in results} == {"RK_GUIDE", "RK_NOTE"}
