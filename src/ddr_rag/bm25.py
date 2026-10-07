"""Persistent, dependency-free BM25 sparse retrieval over ChunkRecords."""

from __future__ import annotations

import json
import math
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from ddr_rag.config import AppSettings
from ddr_rag.embedder import load_chunk_records
from ddr_rag.query_scope import (
    QueryScope,
    QueryScopeError,
    enrich_query,
    resolve_document_scope,
    resolve_query_scope,
)
from ddr_rag.schemas import ChunkRecord, SearchResult
from ddr_rag.vector_store import chunk_memory_types

_SPARSE_SCHEMA_VERSION = 5


class SparseIndexError(RuntimeError):
    """Raised when the local BM25 artifact cannot be built or safely queried."""


def sparse_index_dir(settings: AppSettings) -> Path:
    return settings.resolve_path(settings.sparse.path)


def tokenize(text: str, *, decompose_compounds: bool = True) -> list[str]:
    """Tokenize engineering text, optionally decomposing natural-language compounds."""

    normalized = unicodedata.normalize("NFKC", text).upper()
    raw_identifiers = re.findall(r"[A-Z][A-Z0-9_+.-]*|\d+(?:\.\d+)?(?:[A-ZΩ]+)?", normalized)
    tokens: list[str] = []
    for identifier in raw_identifiers:
        tokens.append(identifier)
        if not decompose_compounds:
            continue
        # Keep exact product and signal identifiers intact. Only a hyphenated
        # natural-language signal relation needs components, e.g. L2a-to-L2b
        # and CLK-to-DQS. Units with a space are normalized by enrich_query.
        if "-" in identifier:
            components = re.findall(r"[A-Z][A-Z0-9_]*|\d+(?:\.\d+)?(?:[A-ZΩ]+)?", identifier)
            tokens.extend(component for component in components if component != identifier)
    for run in re.findall(r"[\u4E00-\u9FFF]+", normalized):
        tokens.extend(run)
        tokens.extend(run[index:index + 2] for index in range(len(run) - 1))
    return tokens


def _searchable_text(record: ChunkRecord) -> str:
    """Return the published Chunk body without distorting corpus-wide BM25 scores.

    Section and title remain available in every retrieved result for tracing. The
    published body retains V1's original index representation; query-side aliases
    and compound splitting provide targeted matching without perturbing corpus-wide
    BM25 statistics.
    """

    return record.text


def _atomic_write(path: Path, payload: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def _artifact_paths(settings: AppSettings) -> dict[str, Path]:
    root = sparse_index_dir(settings)
    return {
        "root": root,
        "index": root / "index.json",
        "chunk_ids": root / "chunk_ids.jsonl",
        "manifest": root / "manifest.json",
    }


def build_sparse_index(settings: AppSettings, *, replace: bool = False) -> dict[str, int | float | Path]:
    """Build a durable BM25 inverted index from the current immutable Chunk JSONL."""

    if settings.sparse.provider != "bm25_local":
        raise SparseIndexError("Only sparse.provider='bm25_local' is supported by local indexing.")
    records, chunk_hash = load_chunk_records(settings)
    paths = _artifact_paths(settings)
    paths["root"].mkdir(parents=True, exist_ok=True)
    existing = [path for name, path in paths.items() if name != "root" and path.exists()]
    if existing and not replace:
        raise SparseIndexError(
            f"BM25 index already exists in {paths['root']}. Re-run with --replace to rebuild it."
        )

    postings: dict[str, list[list[int]]] = {}
    document_lengths: list[int] = []
    for position, record in enumerate(records):
        frequencies = Counter(tokenize(_searchable_text(record), decompose_compounds=False))
        document_lengths.append(sum(frequencies.values()))
        for token, frequency in frequencies.items():
            postings.setdefault(token, []).append([position, frequency])
    if not any(document_lengths):
        raise SparseIndexError("BM25 input contains no searchable tokens.")

    average_document_length = sum(document_lengths) / len(document_lengths)
    index_payload = {
        "schema_version": _SPARSE_SCHEMA_VERSION,
        "document_lengths": document_lengths,
        "average_document_length": average_document_length,
        "postings": postings,
    }
    manifest = {
        "artifact_type": "bm25_sparse_index",
        "provider": settings.sparse.provider,
        "chunk_count": len(records),
        "chunk_file_sha256": chunk_hash,
        "k1": settings.sparse.k1,
        "b": settings.sparse.b,
        "tokenizer": "unicode_engineering_v5_v1_document_tokens_query_expansion",
        "search_fields": {"title_weight": 0, "section_weight": 0, "text_weight": 1},
        "chunk_classification_fields": [
            "domains", "topics", "memory_types", "applicable_interfaces"
        ],
    }
    identifiers = "".join(
        json.dumps({"position": position, "chunk_id": record.chunk_id}, ensure_ascii=False) + "\n"
        for position, record in enumerate(records)
    )
    _atomic_write(paths["index"], json.dumps(index_payload, ensure_ascii=False, separators=(",", ":")))
    _atomic_write(paths["chunk_ids"], identifiers)
    _atomic_write(paths["manifest"], json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    validation = validate_sparse_index(settings)
    return {"path": paths["root"], **validation}


def _load_sparse_index(settings: AppSettings) -> tuple[list[ChunkRecord], dict[str, Any]]:
    records, chunk_hash = load_chunk_records(settings)
    paths = _artifact_paths(settings)
    if not all(paths[name].is_file() for name in ("index", "chunk_ids", "manifest")):
        raise SparseIndexError(f"BM25 index is incomplete: {paths['root']}")
    try:
        index_payload = json.loads(paths["index"].read_text(encoding="utf-8"))
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        identifiers = [
            json.loads(line)["chunk_id"]
            for line in paths["chunk_ids"].read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SparseIndexError(f"Could not read BM25 index: {exc}") from exc
    if manifest.get("chunk_file_sha256") != chunk_hash:
        raise SparseIndexError("Chunk JSONL changed after BM25 build; rebuild the sparse index.")
    if index_payload.get("schema_version") != _SPARSE_SCHEMA_VERSION:
        raise SparseIndexError("BM25 schema is older than the current tokenizer; rebuild the sparse index.")
    if manifest.get("chunk_count") != len(records) or identifiers != [record.chunk_id for record in records]:
        raise SparseIndexError("BM25 Chunk ID mapping does not match the current Chunk JSONL.")
    return records, {"index": index_payload, "manifest": manifest}


def validate_sparse_index(settings: AppSettings) -> dict[str, int | float]:
    records, artifact = _load_sparse_index(settings)
    index_payload = artifact["index"]
    lengths = index_payload.get("document_lengths")
    postings = index_payload.get("postings")
    if not isinstance(lengths, list) or len(lengths) != len(records):
        raise SparseIndexError("BM25 document lengths do not match Chunk count.")
    if not isinstance(postings, dict) or not postings:
        raise SparseIndexError("BM25 postings are missing or empty.")
    if any(not isinstance(length, int) or length < 0 for length in lengths):
        raise SparseIndexError("BM25 document lengths are invalid.")
    return {
        "chunk_count": len(records),
        "term_count": len(postings),
        "average_document_length": float(index_payload["average_document_length"]),
    }


def _matches_filters(
    record: ChunkRecord,
    *,
    scope: QueryScope,
) -> bool:
    if scope.active_only and record.status != "active":
        return False
    if scope.doc_ids is not None and record.doc_id not in scope.doc_ids:
        return False
    if scope.domains and not set(scope.domains).intersection(record.domains):
        return False
    if scope.topics and not set(scope.topics).intersection(record.topics):
        return False
    if scope.applicable_interfaces and not set(scope.applicable_interfaces).intersection(
        record.applicable_interfaces
    ):
        return False
    if scope.applicable_parts and not set(scope.applicable_parts).intersection(record.applicable_parts):
        return False
    if scope.memory_types and not set(scope.memory_types).intersection(chunk_memory_types(record)):
        return False
    return True


def _is_navigation_chunk(record: ChunkRecord) -> bool:
    """Exclude table-of-contents style navigation text from sparse evidence."""

    opening = f"{record.section}\n{record.text[:200]}".upper()
    return any(marker in opening for marker in ("目录", "TABLE OF CONTENTS", "LIST OF FIGURES", "LIST OF TABLES"))


def sparse_search(
    settings: AppSettings,
    query: str,
    *,
    memory_type: str | None = None,
    doc_id: str | None = None,
    doc_ids: tuple[str, ...] | None = None,
    active_only: bool | None = None,
    limit: int | None = None,
    domains: list[str] | tuple[str, ...] | None = None,
    topics: list[str] | tuple[str, ...] | None = None,
    interfaces: list[str] | tuple[str, ...] | None = None,
    parts: list[str] | tuple[str, ...] | None = None,
    scope: QueryScope | None = None,
) -> list[SearchResult]:
    """Return BM25-ranked local evidence with the same filters as dense retrieval."""

    if settings.sparse.provider != "bm25_local":
        raise SparseIndexError("Only sparse.provider='bm25_local' is supported by local retrieval.")
    normalized_query = query.strip()
    query_tokens = list(dict.fromkeys(tokenize(enrich_query(normalized_query))))
    if not query_tokens:
        raise SparseIndexError("Search query contains no searchable terms.")
    if scope is not None and any(
        value is not None
        for value in (memory_type, doc_id, doc_ids, active_only, domains, topics, interfaces, parts)
    ):
        raise SparseIndexError("Pass either a resolved scope or query filter arguments, not both.")
    if doc_id and doc_ids:
        raise SparseIndexError("Use either doc_id or doc_ids, not both.")
    if scope is None:
        try:
            scope = resolve_query_scope(
                settings,
                normalized_query,
                explicit_doc_id=doc_id,
                explicit_domains=domains,
                explicit_topics=topics,
                explicit_interfaces=interfaces,
                explicit_parts=parts,
                memory_type=memory_type,
                active_only=(
                    settings.retrieval.active_documents_only
                    if active_only is None
                    else active_only
                ),
            )
        except QueryScopeError as exc:
            raise SparseIndexError(str(exc)) from exc
        legacy_doc_ids = doc_ids if doc_ids is not None else resolve_document_scope(
            settings, normalized_query, doc_id
        )
        if legacy_doc_ids is not None:
            scope = scope.model_copy(update={"doc_ids": list(legacy_doc_ids)})
    if scope.status != "resolved":
        raise SparseIndexError(scope.clarification_message)
    if len(scope.domains) > 1:
        raise SparseIndexError("Multi-domain sparse retrieval must use the balanced retrieval entry point.")
    if scope.doc_ids == []:
        return []
    records, artifact = _load_sparse_index(settings)
    index_payload = artifact["index"]
    postings: dict[str, list[list[int]]] = index_payload["postings"]
    lengths: list[int] = index_payload["document_lengths"]
    trust_classification = settings.classification.mapping is not None
    effective_records = [
        record.model_copy(
            update={
                "memory_types": chunk_memory_types(
                    record,
                    trust_classification=trust_classification,
                )
            }
        )
        for record in records
    ]
    eligible = {
        position
        for position, record in enumerate(effective_records)
        if _matches_filters(record, scope=scope) and not _is_navigation_chunk(record)
    }
    if not eligible:
        return []
    document_count = len(eligible)
    average_length = sum(lengths[position] for position in eligible) / document_count
    scores: dict[int, float] = {}
    for token in query_tokens:
        entries = [entry for entry in postings.get(token, []) if entry[0] in eligible]
        if not entries:
            continue
        document_frequency = len(entries)
        idf = math.log(1 + (document_count - document_frequency + 0.5) / (document_frequency + 0.5))
        for position, frequency in entries:
            denominator = frequency + settings.sparse.k1 * (
                1 - settings.sparse.b + settings.sparse.b * lengths[position] / average_length
            )
            scores[position] = scores.get(position, 0.0) + idf * frequency * (settings.sparse.k1 + 1) / denominator
    ranked = sorted(
        (
            (position, score)
            for position, score in scores.items()
            if position in eligible
        ),
        key=lambda item: (-item[1], effective_records[item[0]].chunk_id),
    )
    result_limit = limit if limit is not None else settings.retrieval.sparse_candidates
    return [
        SearchResult(
            chunk=effective_records[position],
            score=float(score),
            retrieval_sources=["sparse"],
        )
        for position, score in ranked[:result_limit]
    ]
