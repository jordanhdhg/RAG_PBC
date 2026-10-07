from pathlib import Path

import pytest

from ddr_rag.bm25 import SparseIndexError, build_sparse_index, sparse_search, tokenize, validate_sparse_index
from ddr_rag.config import load_settings
from ddr_rag.retriever import rrf_fuse
from ddr_rag.schemas import ChunkRecord, SearchResult
from test_config import write_config


def make_record(index: int, text: str, memory_type: str = "DDR4", status: str = "active") -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"TEST:{index:06d}:abc",
        doc_id="TEST",
        text=text,
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


def write_chunks(settings, records: list[ChunkRecord]) -> None:
    chunk_path = settings.resolve_path(settings.paths.chunks)
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_path.write_text("".join(record.model_dump_json() + "\n" for record in records), encoding="utf-8")


def test_bm25_exact_signal_search_filters_status_and_memory_type(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    records = [
        make_record(0, "DDR4 CLKP CLKN differential impedance 100ohm 1500mil"),
        make_record(1, "LPDDR4 CLKP topology", "LPDDR4"),
        make_record(2, "DDR4 CLKP archived", "DDR4", "archived"),
    ]
    write_chunks(settings, records)

    report = build_sparse_index(settings)
    results = sparse_search(settings, "CLKP CLKN 1500mil", memory_type="DDR4")

    assert report["chunk_count"] == 3
    assert validate_sparse_index(settings)["chunk_count"] == 3
    assert [result.chunk.chunk_id for result in results] == [records[0].chunk_id]
    assert results[0].retrieval_sources == ["sparse"]
    with pytest.raises(SparseIndexError, match="already exists"):
        build_sparse_index(settings)


def test_rrf_fusion_deduplicates_and_records_both_sources() -> None:
    first = make_record(0, "DDR4 CLKP")
    second = make_record(1, "DDR4 CLKN")
    dense = [
        SearchResult(chunk=first, score=0.9, retrieval_sources=["dense"]),
        SearchResult(chunk=second, score=0.8, retrieval_sources=["dense"]),
    ]
    sparse = [
        SearchResult(chunk=second, score=8.0, retrieval_sources=["sparse"]),
        SearchResult(chunk=first, score=6.0, retrieval_sources=["sparse"]),
    ]

    fused = rrf_fuse(dense, sparse, limit=2, rrf_k=60)

    assert {result.chunk.chunk_id for result in fused} == {first.chunk_id, second.chunk_id}
    assert all(set(result.retrieval_sources) == {"dense", "sparse"} for result in fused)


def test_bm25_excludes_navigation_chunk_with_matching_signal_names(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    records = [
        make_record(0, "DDR4 CLKP CLKN impedance 1500mil"),
        make_record(1, "目录\n图 1 CLKP CLKN 1500mil ........ 169"),
    ]
    write_chunks(settings, records)
    build_sparse_index(settings)

    results = sparse_search(settings, "CLKP CLKN 1500mil", memory_type="DDR4")

    assert [result.chunk.chunk_id for result in results] == [records[0].chunk_id]


def test_bm25_decomposes_hyphenated_signals_and_matches_chinese_routing_terms(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    target = make_record(0, "DDR4 CLK和DQS之间等长要求。L2a和L2b之间的等长要求。")
    distractor = make_record(1, "DDR4 device overview.")
    write_chunks(settings, [target, distractor])
    build_sparse_index(settings)

    results = sparse_search(settings, "DDR4 clock L2a-to-L2b mismatch")

    assert {"L2A", "L2B", "CLK", "DQS"}.issubset(tokenize("L2a-to-L2b CLK-to-DQS"))
    assert "L2A" not in tokenize("L2a-to-L2b", decompose_compounds=False)
    assert tokenize("i.MX") == ["I.MX"]
    assert results[0].chunk.chunk_id == target.chunk_id


def test_bm25_accepts_multiple_documents_for_one_part(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    records = [
        make_record(0, "RK3568 DDR4 CLKP guide"),
        make_record(1, "RK3568 DDR4 CLKP experience"),
        make_record(2, "AM62x DDR4 CLKP guide"),
    ]
    records[0].doc_id = "RK_GUIDE"
    records[1].doc_id = "RK_NOTE"
    records[2].doc_id = "TI_GUIDE"
    write_chunks(settings, records)
    build_sparse_index(settings)
    monkeypatch.setattr(
        "ddr_rag.bm25.resolve_document_scope",
        lambda *args, **kwargs: ("RK_GUIDE", "RK_NOTE"),
    )

    results = sparse_search(settings, "RK3568 DDR4 CLKP", limit=3)

    assert {result.chunk.doc_id for result in results} == {"RK_GUIDE", "RK_NOTE"}
