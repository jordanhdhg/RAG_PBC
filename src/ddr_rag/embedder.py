"""Offline dense embedding with the local BAAI BGE-M3 model.

This module intentionally does not import or call OpenAI, Qdrant, or any
generation model.  It turns the already validated chunk JSONL into a small,
portable NumPy artifact that a later index-building phase may consume.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ddr_rag.config import AppSettings
from ddr_rag.schemas import ChunkRecord


class EmbeddingError(RuntimeError):
    """Raised when local embedding cannot safely produce a usable artifact."""


def embedding_output_dir(settings: AppSettings) -> Path:
    """Return the model-specific D/RAG index artifact directory."""

    return settings.resolve_path(settings.paths.index) / settings.embedding.output_subdir


def _chunk_file_hash(chunk_path: Path) -> str:
    return hashlib.sha256(chunk_path.read_bytes()).hexdigest()


def load_chunk_records(settings: AppSettings) -> tuple[list[ChunkRecord], str]:
    """Load and validate every already-published ChunkRecord."""

    chunk_path = settings.resolve_path(settings.paths.chunks)
    if not chunk_path.is_file():
        raise EmbeddingError(f"Chunk input is missing: {chunk_path}")

    records: list[ChunkRecord] = []
    for line_number, line in enumerate(chunk_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(ChunkRecord.model_validate_json(line))
        except Exception as exc:
            raise EmbeddingError(f"Invalid chunk JSON at {chunk_path}:{line_number}: {exc}") from exc

    if not records:
        raise EmbeddingError(f"Chunk input is empty: {chunk_path}")
    chunk_ids = [record.chunk_id for record in records]
    if len(chunk_ids) != len(set(chunk_ids)):
        raise EmbeddingError("Chunk input has duplicate chunk_id values.")
    return records, _chunk_file_hash(chunk_path)


def _configure_huggingface_cache(cache_dir: Path) -> None:
    """Keep all future Hub downloads on the configured project drive."""

    cache_dir.mkdir(parents=True, exist_ok=True)
    os.environ["HF_HOME"] = str(cache_dir)
    os.environ["HF_HUB_CACHE"] = str(cache_dir / "hub")
    os.environ["HF_XET_CACHE"] = str(cache_dir / "xet")


def _load_local_model(settings: AppSettings) -> tuple[Any, Any, Any]:
    """Load BGE-M3 with the installed local CUDA runtime; never use an API."""

    if settings.embedding.provider != "local_bge_m3":
        raise EmbeddingError(
            "Local embedding requires embedding.provider to be 'local_bge_m3'."
        )
    if settings.embedding.device != "cuda:0":
        raise EmbeddingError(
            "V1 local BGE-M3 is intentionally pinned to cuda:0; change this only "
            "after adding and testing a CPU fallback."
        )

    cache_dir = settings.resolve_path(settings.embedding.model_cache)
    _configure_huggingface_cache(cache_dir)
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:
        raise EmbeddingError(
            "Local BGE-M3 dependencies are missing. Install CUDA PyTorch in the project .venv."
        ) from exc

    if not torch.cuda.is_available():
        raise EmbeddingError(
            "CUDA is unavailable in the project virtual environment. "
            "Install the CUDA build of PyTorch; the CPU build is not accepted for this stage."
        )
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            settings.embedding.model, cache_dir=cache_dir, local_files_only=True
        )
        model = AutoModel.from_pretrained(
            settings.embedding.model, cache_dir=cache_dir, local_files_only=True
        )
        model = model.to(settings.embedding.device).eval()
        if settings.embedding.use_fp16:
            model = model.half()
    except Exception as exc:
        raise EmbeddingError(f"Could not load local model {settings.embedding.model!r}: {exc}") from exc
    return torch, tokenizer, model


def _encode_texts(settings: AppSettings, texts: list[str]) -> Any:
    """Return normalized float32 BGE-M3 dense vectors in input order."""

    torch, tokenizer, model = _load_local_model(settings)
    batches: list[Any] = []
    start = 0
    batch_size = settings.embedding.batch_size
    while start < len(texts):
        batch = texts[start:start + batch_size]
        try:
            encoded = tokenizer(
                batch,
                max_length=settings.embedding.max_length,
                padding=True,
                truncation=True,
                return_tensors="pt",
            )
            encoded = {name: tensor.to(settings.embedding.device) for name, tensor in encoded.items()}
            with torch.inference_mode():
                output = model(**encoded).last_hidden_state[:, 0]
                output = output.float()
                if settings.embedding.normalize_vectors:
                    output = torch.nn.functional.normalize(output, p=2, dim=1)
            batches.append(output.cpu())
            start += len(batch)
        except torch.cuda.OutOfMemoryError as exc:
            torch.cuda.empty_cache()
            if batch_size == 1:
                raise EmbeddingError("CUDA ran out of memory even at batch_size=1.") from exc
            batch_size = max(1, batch_size // 2)
    return torch.cat(batches, dim=0).numpy()


def _atomic_write_text(path: Path, text: str) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(text, encoding="utf-8")
    os.replace(temporary_path, path)


def _atomic_save_npy(path: Path, values: Any) -> None:
    import numpy as np

    temporary_path = path.with_suffix(path.suffix + ".tmp")
    with temporary_path.open("wb") as stream:
        np.save(stream, values, allow_pickle=False)
    os.replace(temporary_path, path)


def write_embedding_artifact(
    settings: AppSettings,
    records: list[ChunkRecord],
    chunk_hash: str,
    vectors: Any,
    *,
    replace: bool = False,
) -> dict[str, Path]:
    """Atomically publish vector data and its traceability manifest."""

    import numpy as np

    if vectors.ndim != 2 or vectors.shape[0] != len(records) or vectors.shape[1] != 1024:
        raise EmbeddingError(
            "Expected BGE-M3 vectors with shape (chunk_count, 1024); "
            f"got {tuple(vectors.shape)} for {len(records)} chunks."
        )
    if not np.isfinite(vectors).all():
        raise EmbeddingError("Embedding output contains NaN or infinite values.")

    output_dir = embedding_output_dir(settings)
    output_dir.mkdir(parents=True, exist_ok=True)
    vector_path = output_dir / "vectors.npy"
    ids_path = output_dir / "chunk_ids.jsonl"
    manifest_path = output_dir / "manifest.json"
    existing = [path for path in (vector_path, ids_path, manifest_path) if path.exists()]
    if existing and not replace:
        raise EmbeddingError(
            f"Embedding output already exists in {output_dir}. Re-run with --replace to rebuild it."
        )

    ids_payload = "".join(
        json.dumps({"position": index, "chunk_id": record.chunk_id}, ensure_ascii=False) + "\n"
        for index, record in enumerate(records)
    )
    norms = np.linalg.norm(vectors, axis=1)
    manifest = {
        "artifact_type": "local_dense_embeddings",
        "provider": settings.embedding.provider,
        "model": settings.embedding.model,
        "device": settings.embedding.device,
        "dimension": int(vectors.shape[1]),
        "chunk_count": len(records),
        "chunk_file_sha256": chunk_hash,
        "normalize_vectors": settings.embedding.normalize_vectors,
        "dtype": str(vectors.dtype),
        "vector_norm_min": float(norms.min()),
        "vector_norm_max": float(norms.max()),
    }
    _atomic_save_npy(vector_path, vectors)
    _atomic_write_text(ids_path, ids_payload)
    _atomic_write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return {"vectors": vector_path, "chunk_ids": ids_path, "manifest": manifest_path}


def validate_embedding_artifact(settings: AppSettings) -> dict[str, int | float]:
    """Verify count, dimensionality, finiteness, ID order, and vector normalization."""

    import numpy as np

    output_dir = embedding_output_dir(settings)
    vector_path = output_dir / "vectors.npy"
    ids_path = output_dir / "chunk_ids.jsonl"
    manifest_path = output_dir / "manifest.json"
    if not all(path.is_file() for path in (vector_path, ids_path, manifest_path)):
        raise EmbeddingError(f"Incomplete embedding artifact in {output_dir}")
    vectors = np.load(vector_path, allow_pickle=False)
    ids = [json.loads(line)["chunk_id"] for line in ids_path.read_text(encoding="utf-8").splitlines() if line]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if vectors.ndim != 2 or vectors.shape[1] != 1024:
        raise EmbeddingError(f"Expected 1024-dimensional vectors, got {tuple(vectors.shape)}")
    if len(ids) != vectors.shape[0] or len(ids) != manifest["chunk_count"]:
        raise EmbeddingError("Embedding vectors, IDs, and manifest counts do not match.")
    if len(ids) != len(set(ids)) or not np.isfinite(vectors).all():
        raise EmbeddingError("Embedding artifact has duplicate IDs or non-finite vector values.")
    norms = np.linalg.norm(vectors, axis=1)
    if manifest["normalize_vectors"] and not np.allclose(norms, 1.0, atol=1e-4):
        raise EmbeddingError("Normalized embedding vectors do not all have unit norm.")
    return {
        "chunk_count": int(vectors.shape[0]),
        "dimension": int(vectors.shape[1]),
        "norm_min": float(norms.min()),
        "norm_max": float(norms.max()),
    }


def embed_chunks(settings: AppSettings, *, replace: bool = False) -> dict[str, Any]:
    """Create and validate offline BGE-M3 dense vectors for every ChunkRecord."""

    records, chunk_hash = load_chunk_records(settings)
    vectors = _encode_texts(settings, [record.text for record in records])
    paths = write_embedding_artifact(settings, records, chunk_hash, vectors, replace=replace)
    return {"paths": paths, "validation": validate_embedding_artifact(settings)}
