from pathlib import Path

import pytest

from ddr_rag.catalog import load_catalog
from ddr_rag.config import load_settings
from ddr_rag.ingest import IngestError, ingest_documents
from test_config import write_config


def make_document(tmp_path: Path):
    catalog_path = tmp_path / "data/catalog/documents.yaml"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(
        """
documents:
  - doc_id: TEST_GUIDE
    title: Test guide
    revision: R1
    vendor: Test
    file: data/raw/test.pdf
    document_type: hardware_design_guide
    memory_types: [DDR4]
    authority: vendor_design_guide
    authority_score: 90
    status: active
""".strip(),
        encoding="utf-8",
    )
    return load_catalog(load_settings(tmp_path / "config.yaml")).documents[0]


def test_ingest_requires_replace_before_any_stage_when_artifacts_exist(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    document = make_document(tmp_path)
    chunk_path = settings.resolve_path(settings.paths.chunks)
    chunk_path.parent.mkdir(parents=True)
    chunk_path.write_text("existing evidence", encoding="utf-8")
    called = []
    monkeypatch.setattr("ddr_rag.ingest.parse_documents", lambda *args, **kwargs: called.append("parse"))

    with pytest.raises(IngestError, match="require --replace"):
        ingest_documents(settings, [document])

    assert called == []


def test_ingest_runs_all_local_stages_in_order_and_forwards_replace(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    document = make_document(tmp_path)
    calls = []

    def fake_parse(*args, **kwargs):
        calls.append(("parse", kwargs["replace"]))
        return [{"doc_id": "TEST_GUIDE", "status": "success"}]

    def fake_chunk(*args, **kwargs):
        calls.append(("chunk", kwargs["replace"]))
        return {"total_chunks": 2, "output": tmp_path / "chunks.jsonl"}

    def fake_embed(*args, **kwargs):
        calls.append(("embed", kwargs["replace"]))
        return {"validation": {"chunk_count": 2, "dimension": 1024}}

    def fake_index(*args, **kwargs):
        calls.append(("index", kwargs["replace"]))
        return {"point_count": 2}

    def fake_bm25(*args, **kwargs):
        calls.append(("bm25", kwargs["replace"]))
        return {"chunk_count": 2}

    monkeypatch.setattr("ddr_rag.ingest.parse_documents", fake_parse)
    monkeypatch.setattr("ddr_rag.ingest.chunk_documents", fake_chunk)
    monkeypatch.setattr("ddr_rag.ingest.embed_chunks", fake_embed)
    monkeypatch.setattr("ddr_rag.ingest.build_local_index", fake_index)
    monkeypatch.setattr("ddr_rag.ingest.build_sparse_index", fake_bm25)

    report = ingest_documents(settings, [document], replace=True)

    assert calls == [("parse", True), ("chunk", True), ("embed", True), ("index", True), ("bm25", True)]
    assert report["doc_ids"] == ["TEST_GUIDE"]
    assert report["vector_index"]["point_count"] == 2


def test_ingest_stops_before_later_stages_after_failure(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    document = make_document(tmp_path)
    calls = []

    monkeypatch.setattr("ddr_rag.ingest.parse_documents", lambda *args, **kwargs: calls.append("parse") or [])

    def fail_chunk(*args, **kwargs):
        calls.append("chunk")
        raise RuntimeError("synthetic chunk failure")

    monkeypatch.setattr("ddr_rag.ingest.chunk_documents", fail_chunk)
    monkeypatch.setattr("ddr_rag.ingest.embed_chunks", lambda *args, **kwargs: calls.append("embed"))

    with pytest.raises(IngestError, match="stopped at chunk.*synthetic chunk failure"):
        ingest_documents(settings, [document], replace=True)

    assert calls == ["parse", "chunk"]
