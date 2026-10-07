"""Persistent Qdrant Local index construction for validated local embeddings."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import Path
from typing import Any

import numpy as np

from ddr_rag.config import AppSettings
from ddr_rag.embedder import EmbeddingError, embedding_output_dir, load_chunk_records
from ddr_rag.schemas import ChunkRecord


class VectorStoreError(RuntimeError):
    """Raised when a Qdrant Local collection cannot be safely built or checked."""


def qdrant_path(settings: AppSettings) -> Path:
    """Return the D/RAG-local persistent Qdrant data directory."""

    return settings.resolve_path(settings.vector_store.path)


def _point_id(chunk_id: str) -> str:
    """Map a stable Chunk ID to a Qdrant-supported UUID without losing the ID."""

    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ddr-rag:{chunk_id}"))


def chunk_memory_types(
    record: ChunkRecord,
    *,
    trust_classification: bool = False,
) -> list[str]:
    """Return mapped V2 types, or derive legacy V1 types from Chunk text."""

    if trust_classification:
        return record.memory_types

    text = record.text.upper()
    patterns = {
        "LPDDR5X": r"(?<![A-Z0-9])LPDDR5X(?![A-Z0-9])",
        "LPDDR5": r"(?<![A-Z0-9])LPDDR5(?![A-Z0-9])",
        "LPDDR4X": r"(?<![A-Z0-9])LPDDR4X(?![A-Z0-9])",
        "LPDDR4": r"(?<![A-Z0-9])LPDDR4(?![A-Z0-9])",
        "LPDDR3": r"(?<![A-Z0-9])LPDDR3(?![A-Z0-9])",
        "DDR4": r"(?<![A-Z0-9])DDR4(?![A-Z0-9])",
        "DDR3L": r"(?<![A-Z0-9])DDR3L(?![A-Z0-9])",
        "DDR3": r"(?<![A-Z0-9])DDR3(?![A-Z0-9])",
    }
    counts = {
        memory_type: len(re.findall(pattern, text))
        for memory_type, pattern in patterns.items()
    }
    found = [memory_type for memory_type in patterns if counts[memory_type]]
    if not found:
        return record.memory_types

    lpddr_peak = max(
        (count for memory_type, count in counts.items() if memory_type.startswith("LPDDR")),
        default=0,
    )
    # A mixed overview can mention DDR4 once (for example, a shared VTT supply)
    # while the actual rule is an LPDDR-specific topology. Prefer precision for
    # --memory-type DDR4 by withholding the incidental DDR4 tag in that case.
    return [
        memory_type
        for memory_type in found
        if not (memory_type.startswith("DDR") and counts[memory_type] < lpddr_peak)
    ]


def _payload(record: ChunkRecord, *, trust_classification: bool = False) -> dict[str, Any]:
    """Preserve every retrieval/citation field in the Qdrant point payload."""

    return {
        "chunk_id": record.chunk_id,
        "doc_id": record.doc_id,
        "text": record.text,
        "title": record.title,
        "revision": record.revision,
        "source_path": str(record.source_path),
        "section": record.section,
        "document_type": record.document_type,
        "authority": record.authority,
        "source_format": record.source_format,
        "domains": record.domains,
        "topics": record.topics,
        "applicable_interfaces": record.applicable_interfaces,
        "applicable_parts": record.applicable_parts,
        "source_file_hash": record.source_file_hash,
        "parser_version": record.parser_version,
        "source_location": record.source_location.model_dump(mode="json") if record.source_location else None,
        "page_numbers": record.page_numbers,
        "page_start": record.page_start,
        "page_end": record.page_end,
        "memory_types": chunk_memory_types(
            record,
            trust_classification=trust_classification,
        ),
        "status": record.status,
        "token_count": record.token_count,
    }


def _load_index_inputs(settings: AppSettings) -> tuple[list[ChunkRecord], np.ndarray, dict[str, Any]]:
    """Ensure vectors, IDs, manifest, and current Chunk JSONL have identical order."""

    records, current_chunk_hash = load_chunk_records(settings)
    artifact_dir = embedding_output_dir(settings)
    vector_path = artifact_dir / "vectors.npy"
    ids_path = artifact_dir / "chunk_ids.jsonl"
    manifest_path = artifact_dir / "manifest.json"
    if not all(path.is_file() for path in (vector_path, ids_path, manifest_path)):
        raise VectorStoreError(f"Embedding artifact is incomplete: {artifact_dir}")
    try:
        vectors = np.load(vector_path, allow_pickle=False)
        identifiers = [
            json.loads(line)["chunk_id"]
            for line in ids_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise VectorStoreError(f"Could not read embedding artifact {artifact_dir}: {exc}") from exc

    expected_ids = [record.chunk_id for record in records]
    if manifest.get("chunk_file_sha256") != current_chunk_hash:
        raise VectorStoreError("Chunk JSONL changed after embedding; rebuild embeddings before indexing.")
    if identifiers != expected_ids:
        raise VectorStoreError("Embedding chunk_ids.jsonl does not match the current Chunk JSONL order.")
    if vectors.ndim != 2 or vectors.shape != (len(records), 1024):
        raise VectorStoreError(
            f"Expected vectors with shape ({len(records)}, 1024), got {tuple(vectors.shape)}."
        )
    if vectors.dtype != np.float32 or not np.isfinite(vectors).all():
        raise VectorStoreError("Vectors must be finite float32 values.")
    if manifest.get("dimension") != 1024 or manifest.get("chunk_count") != len(records):
        raise VectorStoreError("Embedding manifest dimension or count does not match the current input.")
    return records, vectors, manifest


def _qdrant_client(path: Path) -> Any:
    try:
        from qdrant_client import QdrantClient
    except ImportError as exc:
        raise VectorStoreError("qdrant-client is not installed in the project virtual environment.") from exc
    path.mkdir(parents=True, exist_ok=True)
    return QdrantClient(path=str(path))


def _close(client: Any) -> None:
    close = getattr(client, "close", None)
    if close is not None:
        close()


def _collection_exists(client: Any, collection_name: str) -> bool:
    return bool(client.collection_exists(collection_name))


def validate_local_index(settings: AppSettings) -> dict[str, int | str]:
    """Validate collection configuration, count, metadata and a fresh client reopen."""

    if settings.vector_store.provider != "qdrant_local":
        raise VectorStoreError(
            "Only vector_store.provider='qdrant_local' is supported by local index validation."
        )
    if settings.vector_store.distance != "cosine":
        raise VectorStoreError("V1 BGE-M3 index requires vector_store.distance='cosine'.")

    records, _, _ = _load_index_inputs(settings)
    collection_name = settings.knowledge_base.collection_name
    database_path = qdrant_path(settings)
    client = _qdrant_client(database_path)
    try:
        if not _collection_exists(client, collection_name):
            raise VectorStoreError(f"Qdrant collection is missing: {collection_name}")
        info = client.get_collection(collection_name)
        vector_params = info.config.params.vectors
        if vector_params.size != 1024 or str(vector_params.distance).upper() != "COSINE":
            raise VectorStoreError("Qdrant collection vector configuration is not 1024-dimensional Cosine.")
        count = int(client.count(collection_name, exact=True).count)
        if count != len(records):
            raise VectorStoreError(f"Qdrant count {count} does not match {len(records)} input chunks.")
        sample = records[0]
        point = client.retrieve(collection_name, ids=[_point_id(sample.chunk_id)], with_payload=True)
        if len(point) != 1 or point[0].payload.get("chunk_id") != sample.chunk_id:
            raise VectorStoreError("Qdrant sample payload does not map back to its Chunk ID.")
        required_payload_fields = {
            "chunk_id", "doc_id", "text", "title", "revision", "source_path", "section",
            "document_type", "authority", "source_format", "applicable_parts",
            "source_file_hash", "parser_version", "source_location",
            "page_numbers", "page_start", "page_end", "memory_types", "status", "token_count",
        }
        # The published V1.2 collection remains readable without an in-place
        # payload rewrite.  V2 configurations that enable a classification map
        # must carry the complete unified metadata in every point.
        if settings.classification.mapping is not None:
            required_payload_fields.update({"domains", "topics", "applicable_interfaces"})
        missing_fields = sorted(required_payload_fields - set(point[0].payload))
        if missing_fields:
            raise VectorStoreError(
                f"Qdrant sample payload is missing required fields: {', '.join(missing_fields)}"
            )
    finally:
        _close(client)

    reopened = _qdrant_client(database_path)
    try:
        reopened_count = int(reopened.count(collection_name, exact=True).count)
    finally:
        _close(reopened)
    if reopened_count != len(records):
        raise VectorStoreError("Qdrant collection was not readable after reopening the local database.")
    return {
        "collection": collection_name,
        "point_count": len(records),
        "dimension": 1024,
        "distance": "cosine",
    }


def build_local_index(settings: AppSettings, *, replace: bool = False) -> dict[str, int | str | Path]:
    """Create a durable Qdrant Local collection from the existing embedding artifact."""

    if settings.vector_store.provider != "qdrant_local":
        raise VectorStoreError(
            "Only vector_store.provider='qdrant_local' is supported by local index building."
        )
    if settings.vector_store.distance != "cosine":
        raise VectorStoreError("V1 BGE-M3 index requires vector_store.distance='cosine'.")
    records, vectors, _ = _load_index_inputs(settings)
    collection_name = settings.knowledge_base.collection_name
    database_path = qdrant_path(settings)
    client = _qdrant_client(database_path)
    try:
        if _collection_exists(client, collection_name):
            if not replace:
                raise VectorStoreError(
                    f"Qdrant collection already exists: {collection_name}. Re-run with --replace to rebuild it."
                )
            client.delete_collection(collection_name)

        from qdrant_client.models import Distance, PointStruct, VectorParams

        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
        )
        for start in range(0, len(records), settings.vector_store.batch_size):
            stop = min(start + settings.vector_store.batch_size, len(records))
            points = [
                PointStruct(
                    id=_point_id(record.chunk_id),
                    vector=vectors[index].tolist(),
                    payload=_payload(
                        record,
                        trust_classification=settings.classification.mapping is not None,
                    ),
                )
                for index, record in enumerate(records[start:stop], start=start)
            ]
            client.upsert(collection_name=collection_name, points=points, wait=True)
    except VectorStoreError:
        raise
    except Exception as exc:
        raise VectorStoreError(f"Could not build Qdrant Local collection: {exc}") from exc
    finally:
        _close(client)

    validation = validate_local_index(settings)
    return {"path": database_path, **validation}
