"""Safe local orchestration for ingesting registered DDR source documents."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from ddr_rag.bm25 import build_sparse_index, sparse_index_dir
from ddr_rag.chunker import chunk_documents
from ddr_rag.config import AppSettings
from ddr_rag.embedder import embed_chunks, embedding_output_dir
from ddr_rag.parser import parse_documents
from ddr_rag.schemas import DocumentRecord
from ddr_rag.vector_store import build_local_index, qdrant_path


class IngestError(RuntimeError):
    """Raised when a local ingestion pipeline cannot safely complete."""


def existing_derived_artifacts(settings: AppSettings) -> list[Path]:
    """List artifacts that would be replaced by an end-to-end ingestion run."""

    chunks_path = settings.resolve_path(settings.paths.chunks)
    embedding_root = embedding_output_dir(settings)
    sparse_root = sparse_index_dir(settings)
    candidates = [
        chunks_path,
        embedding_root / "vectors.npy",
        embedding_root / "chunk_ids.jsonl",
        embedding_root / "manifest.json",
        sparse_root / "index.json",
        sparse_root / "chunk_ids.jsonl",
        sparse_root / "manifest.json",
    ]
    existing = [path for path in candidates if path.exists()]

    # Qdrant owns an internal directory structure rather than a single output
    # file. Treat any content as a derived artifact conservatively: a caller
    # must explicitly approve replacing it with --replace.
    local_qdrant_path = qdrant_path(settings)
    if local_qdrant_path.is_dir() and any(local_qdrant_path.iterdir()):
        existing.append(local_qdrant_path)
    return existing


def ingest_documents(
    settings: AppSettings,
    documents: list[DocumentRecord],
    *,
    replace: bool = False,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run parse, chunk, dense embedding, Qdrant, and BM25 in safe order.

    The dense, Qdrant, and BM25 stages are global artifacts. Therefore a run
    that changes any document always regenerates every current Chunk vector and
    both indexes. Existing derived artifacts require the caller to consciously
    supply ``replace=True`` before the first stage can modify anything.
    """

    if not documents:
        raise IngestError("No active documents were selected for ingestion.")
    duplicate_ids = sorted({document.doc_id for document in documents if [
        item.doc_id for item in documents
    ].count(document.doc_id) > 1})
    if duplicate_ids:
        raise IngestError("Selected documents are not unique: " + ", ".join(duplicate_ids))

    existing = existing_derived_artifacts(settings)
    if existing and not replace:
        rendered = ", ".join(str(path) for path in existing)
        raise IngestError(
            "Existing derived artifacts require --replace before ingestion: " + rendered
        )

    stage = "parse"
    try:
        parse_reports = parse_documents(
            settings,
            documents,
            replace=replace,
            progress=progress,
        )
        stage = "chunk"
        chunk_report = chunk_documents(settings, documents, replace=replace)
        stage = "embed"
        embedding_report = embed_chunks(settings, replace=replace)
        stage = "index"
        vector_index_report = build_local_index(settings, replace=replace)
        stage = "bm25"
        sparse_index_report = build_sparse_index(settings, replace=replace)
    except Exception as exc:
        raise IngestError(f"Ingestion stopped at {stage}: {type(exc).__name__}: {exc}") from exc

    return {
        "doc_ids": [document.doc_id for document in documents],
        "replace": replace,
        "parse": parse_reports,
        "chunk": chunk_report,
        "embedding": embedding_report,
        "vector_index": vector_index_report,
        "sparse_index": sparse_index_report,
    }
