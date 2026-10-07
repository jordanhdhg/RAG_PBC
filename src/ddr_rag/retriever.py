"""Domain-isolated local Dense/BM25 retrieval and balanced result fusion."""

from __future__ import annotations

from typing import Any

import numpy as np

from ddr_rag.config import AppSettings
from ddr_rag.embedder import _encode_texts
from ddr_rag.bm25 import SparseIndexError, sparse_search
from ddr_rag.query_scope import (
    QueryScope,
    QueryScopeError,
    enrich_query,
    resolve_query_scope,
    scope_for_domain,
)
from ddr_rag.schemas import ChunkRecord, SearchResult
from ddr_rag.vector_store import VectorStoreError, _close, _qdrant_client, qdrant_path, validate_local_index


class RetrievalError(RuntimeError):
    """Raised when an offline dense query cannot produce traceable evidence."""


def _query_filter(
    settings: AppSettings,
    *,
    scope: QueryScope,
) -> Any | None:
    """Build the exact Qdrant side of a shared Dense/BM25 query scope."""

    try:
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue
    except ImportError as exc:
        raise RetrievalError("qdrant-client is not installed in the project virtual environment.") from exc

    must: list[Any] = []
    if scope.memory_types:
        match = (
            MatchValue(value=scope.memory_types[0])
            if len(scope.memory_types) == 1
            else MatchAny(any=scope.memory_types)
        )
        must.append(FieldCondition(key="memory_types", match=match))
    if scope.doc_ids:
        match = (
            MatchValue(value=scope.doc_ids[0])
            if len(scope.doc_ids) == 1
            else MatchAny(any=scope.doc_ids)
        )
        must.append(FieldCondition(key="doc_id", match=match))
    if scope.active_only:
        must.append(FieldCondition(key="status", match=MatchValue(value="active")))
    if scope.applicable_parts:
        must.append(
            FieldCondition(key="applicable_parts", match=MatchAny(any=scope.applicable_parts))
        )

    has_v2_payload = settings.classification.mapping is not None
    if has_v2_payload:
        if scope.domains:
            domain_match = (
                MatchValue(value=scope.domains[0])
                if len(scope.domains) == 1
                else MatchAny(any=scope.domains)
            )
            must.append(FieldCondition(key="domains", match=domain_match))
        if scope.topics:
            must.append(FieldCondition(key="topics", match=MatchAny(any=scope.topics)))
        if scope.applicable_interfaces:
            must.append(
                FieldCondition(
                    key="applicable_interfaces",
                    match=MatchAny(any=scope.applicable_interfaces),
                )
            )
    return Filter(must=must) if must else None


def search_vector(
    settings: AppSettings,
    vector: np.ndarray,
    *,
    memory_type: str | None = None,
    doc_id: str | None = None,
    doc_ids: tuple[str, ...] | None = None,
    active_only: bool | None = None,
    limit: int | None = None,
    scope: QueryScope | None = None,
) -> list[SearchResult]:
    """Search a supplied local BGE-M3 vector and return evidence-rich ChunkRecords."""

    if settings.vector_store.provider != "qdrant_local":
        raise RetrievalError("Only vector_store.provider='qdrant_local' is supported by local retrieval.")
    query = np.asarray(vector, dtype=np.float32)
    if query.shape != (1024,) or not np.isfinite(query).all():
        raise RetrievalError("Dense query vector must be finite with shape (1024,).")
    result_limit = limit if limit is not None else settings.retrieval.final_top_k
    if result_limit <= 0:
        raise RetrievalError("Search limit must be greater than zero.")
    use_active_only = settings.retrieval.active_documents_only if active_only is None else active_only
    if scope is not None and any(value is not None for value in (memory_type, doc_id, doc_ids, active_only)):
        raise RetrievalError("Pass either a resolved scope or legacy filter arguments, not both.")
    if doc_id and doc_ids:
        raise RetrievalError("Use either doc_id or doc_ids, not both.")
    effective_scope = scope or QueryScope(
        query="legacy-vector-search",
        status="resolved",
        domains=[],
        memory_types=[memory_type.strip().upper()] if memory_type else [],
        doc_ids=(
            list(doc_ids)
            if doc_ids is not None
            else ([doc_id.strip()] if doc_id else None)
        ),
        active_only=use_active_only,
        routing_source="explicit_filters",
    )
    if effective_scope.status != "resolved":
        raise RetrievalError(effective_scope.clarification_message)
    if effective_scope.doc_ids == []:
        return []
    if (
        settings.classification.mapping is None
        and effective_scope.domains
        and any(domain != "memory" for domain in effective_scope.domains)
    ):
        return []
    filters = _query_filter(settings, scope=effective_scope)
    collection_name = settings.knowledge_base.collection_name
    client = _qdrant_client(qdrant_path(settings))
    try:
        response = client.query_points(
            collection_name=collection_name,
            query=query.tolist(),
            query_filter=filters,
            limit=result_limit,
            with_payload=True,
            with_vectors=False,
        )
        points = response.points
    except Exception as exc:
        raise RetrievalError(f"Qdrant Local query failed: {exc}") from exc
    finally:
        _close(client)

    results: list[SearchResult] = []
    for point in points:
        try:
            results.append(
                SearchResult(
                    chunk=ChunkRecord.model_validate(point.payload),
                    score=float(point.score),
                    retrieval_sources=["dense"],
                )
            )
        except Exception as exc:
            raise RetrievalError(f"Qdrant returned an invalid payload: {exc}") from exc
    return results


def _resolve_scope_or_raise(
    settings: AppSettings,
    query: str,
    *,
    scope: QueryScope | None,
    memory_type: str | None,
    doc_id: str | None,
    active_only: bool | None,
    domains: list[str] | tuple[str, ...] | None,
    topics: list[str] | tuple[str, ...] | None,
    interfaces: list[str] | tuple[str, ...] | None,
    parts: list[str] | tuple[str, ...] | None,
) -> QueryScope:
    if scope is not None:
        if any((memory_type, doc_id, domains, topics, interfaces, parts)) or active_only is not None:
            raise RetrievalError("Pass either a resolved scope or query filter arguments, not both.")
        resolved = scope
    else:
        try:
            resolved = resolve_query_scope(
                settings,
                query,
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
            raise RetrievalError(str(exc)) from exc
    if resolved.status != "resolved":
        raise RetrievalError(resolved.clarification_message)
    return resolved


def dense_search(
    settings: AppSettings,
    query: str,
    *,
    memory_type: str | None = None,
    doc_id: str | None = None,
    active_only: bool | None = None,
    limit: int | None = None,
    domains: list[str] | tuple[str, ...] | None = None,
    topics: list[str] | tuple[str, ...] | None = None,
    interfaces: list[str] | tuple[str, ...] | None = None,
    parts: list[str] | tuple[str, ...] | None = None,
    scope: QueryScope | None = None,
) -> list[SearchResult]:
    """Resolve one hardware scope, encode locally, and retrieve Dense evidence."""

    normalized_query = query.strip()
    if not normalized_query:
        raise RetrievalError("Search query cannot be empty.")
    effective_scope = _resolve_scope_or_raise(
        settings,
        normalized_query,
        scope=scope,
        memory_type=memory_type,
        doc_id=doc_id,
        active_only=active_only,
        domains=domains,
        topics=topics,
        interfaces=interfaces,
        parts=parts,
    )
    return retrieve_query(
        settings,
        normalized_query,
        scope=effective_scope,
        mode="dense",
        limit=limit,
    )


def rrf_fuse(
    dense_results: list[SearchResult],
    sparse_results: list[SearchResult],
    *,
    limit: int,
    rrf_k: int,
) -> list[SearchResult]:
    """Fuse ranked dense and sparse evidence by Reciprocal Rank Fusion."""

    fused: dict[str, tuple[SearchResult, float, list[str]]] = {}
    for source, results in (("dense", dense_results), ("sparse", sparse_results)):
        for rank, result in enumerate(results, start=1):
            chunk_id = result.chunk.chunk_id
            existing = fused.get(chunk_id)
            contribution = 1.0 / (rrf_k + rank)
            if existing is None:
                fused[chunk_id] = (result, contribution, [source])
            else:
                original, score, sources = existing
                fused[chunk_id] = (original, score + contribution, sources + [source])
    ranked = sorted(fused.values(), key=lambda item: (-item[1], item[0].chunk.chunk_id))
    return [
        SearchResult(chunk=result.chunk, score=score, retrieval_sources=sources)
        for result, score, sources in ranked[:limit]
    ]


def balanced_domain_merge(
    results_by_domain: dict[str, list[SearchResult]],
    domains: list[str],
    *,
    limit: int,
) -> list[SearchResult]:
    """Round-robin domain rankings while removing multi-domain duplicate chunks."""

    if limit < len(domains):
        raise RetrievalError(
            f"Evidence limit {limit} is smaller than requested domain count {len(domains)}."
        )
    merged: list[SearchResult] = []
    seen: set[str] = set()
    offsets = {domain: 0 for domain in domains}
    while len(merged) < limit:
        added = False
        for domain in domains:
            results = results_by_domain.get(domain, [])
            while offsets[domain] < len(results):
                result = results[offsets[domain]]
                offsets[domain] += 1
                if result.chunk.chunk_id in seen:
                    continue
                seen.add(result.chunk.chunk_id)
                merged.append(result)
                added = True
                break
            if len(merged) >= limit:
                break
        if not added:
            break
    return merged


def retrieve_with_vector(
    settings: AppSettings,
    query: str,
    vector: np.ndarray | None,
    *,
    scope: QueryScope,
    mode: str,
    limit: int,
) -> list[SearchResult]:
    """Apply one scope to Dense and BM25, independently per requested domain."""

    if scope.status != "resolved":
        raise RetrievalError(scope.clarification_message)
    if mode not in {"hybrid", "dense", "sparse"}:
        raise RetrievalError("Retrieval mode must be hybrid, dense, or sparse.")
    if limit < 1:
        raise RetrievalError("Search limit must be greater than zero.")
    if len(scope.domains) > 1 and limit < len(scope.domains):
        raise RetrievalError(
            f"Evidence limit {limit} is smaller than requested domain count {len(scope.domains)}."
        )
    if mode in {"hybrid", "dense"} and vector is None:
        raise RetrievalError("Dense and hybrid retrieval require a local query vector.")

    domains = scope.domains or [""]
    results_by_domain: dict[str, list[SearchResult]] = {}
    for domain in domains:
        domain_scope = scope_for_domain(scope, domain) if domain else scope
        dense_results: list[SearchResult] = []
        sparse_results: list[SearchResult] = []
        if mode in {"hybrid", "dense"}:
            assert vector is not None
            dense_results = search_vector(
                settings,
                vector,
                scope=domain_scope,
                limit=settings.retrieval.dense_candidates,
            )
        if mode in {"hybrid", "sparse"}:
            try:
                sparse_results = sparse_search(
                    settings,
                    query,
                    scope=domain_scope,
                    limit=settings.retrieval.sparse_candidates,
                )
            except SparseIndexError as exc:
                raise RetrievalError(str(exc)) from exc
        if mode == "hybrid":
            ranked = rrf_fuse(
                dense_results,
                sparse_results,
                limit=max(limit, settings.retrieval.final_top_k),
                rrf_k=settings.retrieval.rrf_k,
            )
        else:
            ranked = dense_results if mode == "dense" else sparse_results
        results_by_domain[domain] = ranked

    if len(domains) == 1:
        return results_by_domain[domains[0]][:limit]
    return balanced_domain_merge(results_by_domain, domains, limit=limit)


def retrieve_query(
    settings: AppSettings,
    query: str,
    *,
    scope: QueryScope,
    mode: str = "hybrid",
    limit: int | None = None,
) -> list[SearchResult]:
    """Execute a previously audited route without any answer-model call."""

    final_limit = limit if limit is not None else settings.retrieval.final_top_k
    if len(scope.domains) > 1 and final_limit < len(scope.domains):
        raise RetrievalError(
            f"Evidence limit {final_limit} is smaller than requested domain count "
            f"{len(scope.domains)}."
        )
    vector: np.ndarray | None = None
    if mode in {"hybrid", "dense"}:
        try:
            validate_local_index(settings)
            vector = _encode_texts(settings, [enrich_query(query)])[0]
        except VectorStoreError as exc:
            raise RetrievalError(str(exc)) from exc
        except Exception as exc:
            raise RetrievalError(f"Could not create a local BGE-M3 query vector: {exc}") from exc
    return retrieve_with_vector(
        settings,
        query,
        vector,
        scope=scope,
        mode=mode,
        limit=final_limit,
    )


def hybrid_search(
    settings: AppSettings,
    query: str,
    *,
    memory_type: str | None = None,
    doc_id: str | None = None,
    active_only: bool | None = None,
    limit: int | None = None,
    domains: list[str] | tuple[str, ...] | None = None,
    topics: list[str] | tuple[str, ...] | None = None,
    interfaces: list[str] | tuple[str, ...] | None = None,
    parts: list[str] | tuple[str, ...] | None = None,
    scope: QueryScope | None = None,
) -> list[SearchResult]:
    """Resolve one hardware scope and fuse local Dense/BM25 evidence."""

    normalized_query = query.strip()
    if not normalized_query:
        raise RetrievalError("Search query cannot be empty.")
    effective_scope = _resolve_scope_or_raise(
        settings,
        normalized_query,
        scope=scope,
        memory_type=memory_type,
        doc_id=doc_id,
        active_only=active_only,
        domains=domains,
        topics=topics,
        interfaces=interfaces,
        parts=parts,
    )
    return retrieve_query(
        settings,
        normalized_query,
        scope=effective_scope,
        mode="hybrid",
        limit=limit,
    )
