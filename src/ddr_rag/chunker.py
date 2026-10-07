"""Structure-aware, traceable chunking of parsed Docling documents."""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Iterable
from pathlib import Path
from statistics import mean
from typing import Any
from importlib.metadata import version

from ddr_rag.catalog import compute_sha256
from ddr_rag.classification import (
    ClassificationError,
    ClassificationMap,
    load_classification_map,
    resolve_chunk_classification,
)
from ddr_rag.config import AppSettings
from ddr_rag.parser import parsed_output_paths
from ddr_rag.schemas import ChunkRecord, DocumentRecord, SourceLocation


class ChunkingError(RuntimeError):
    """Raised when parsed documents cannot produce valid traceable chunks."""


def _parsed_json_path(settings: AppSettings, document: DocumentRecord) -> Path:
    return parsed_output_paths(settings, document)[1]


def _build_hybrid_chunker(settings: AppSettings, *, merge_peers: bool | None = None) -> Any:
    """Create the explicit local tokenizer used for Chunk size control."""

    import tiktoken
    from docling.chunking import HybridChunker
    from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer

    try:
        encoding = tiktoken.get_encoding(settings.chunking.tokenizer_encoding)
    except (KeyError, ValueError) as exc:
        raise ChunkingError(
            f"No local tiktoken encoding is registered for chunking "
            f"tokenizer_encoding={settings.chunking.tokenizer_encoding!r}."
        ) from exc

    tokenizer = OpenAITokenizer(
        tokenizer=encoding,
        max_tokens=settings.chunking.max_tokens,
    )
    return HybridChunker(
        tokenizer=tokenizer,
        merge_peers=settings.chunking.merge_peers if merge_peers is None else merge_peers,
        repeat_table_header=settings.chunking.repeat_table_header,
    )


def _load_docling_document(json_path: Path) -> Any:
    if not json_path.is_file():
        raise ChunkingError(f"Parsed Docling JSON is missing: {json_path}")

    from docling_core.types.doc import DoclingDocument

    try:
        return DoclingDocument.load_from_json(json_path)
    except Exception as exc:
        raise ChunkingError(f"Could not load parsed Docling JSON {json_path}: {exc}") from exc


def _section_path(headings: Iterable[str] | None, fallback: str) -> str:
    normalized = [heading.strip() for heading in headings or [] if heading and heading.strip()]
    return " > ".join(normalized) if normalized else fallback


def _page_numbers(chunk: Any) -> list[int]:
    pages = {
        int(provenance.page_no)
        for item in getattr(chunk.meta, "doc_items", [])
        for provenance in (getattr(item, "prov", None) or [])
        if getattr(provenance, "page_no", None) is not None and int(provenance.page_no) >= 1
    }
    return sorted(pages)


def _doc_item_refs(chunk: Any) -> list[str]:
    refs = []
    for item in getattr(chunk.meta, "doc_items", []):
        self_ref = getattr(item, "self_ref", None)
        if self_ref is not None:
            refs.append(str(self_ref))
    return list(dict.fromkeys(refs))


def _contains_excluded_content(chunk: Any) -> bool:
    """Exclude comments/notes that are outside V1.2's supported source scope."""

    for item in getattr(chunk.meta, "doc_items", []):
        layer = getattr(item, "content_layer", None)
        rendered = str(getattr(layer, "value", layer) or "").casefold()
        if "note" in rendered or "comment" in rendered:
            return True
    return False


def _excerpt(text: str, limit: int = 180) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized if len(normalized) <= limit else normalized[: limit - 1].rstrip() + "…"


def _hidden_slides_from_log(settings: AppSettings, doc_id: str) -> set[int]:
    log_path = settings.resolve_path(settings.paths.logs) / "ingestion" / f"{doc_id}.parse.json"
    try:
        payload = json.loads(log_path.read_text(encoding="utf-8"))
        return {int(number) for number in payload.get("hidden_slide_numbers", []) if int(number) >= 1}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return set()


def _chunk_id(document: DocumentRecord, index: int, text: str) -> str:
    digest_input = f"{document.doc_id}\x00{index}\x00{text}".encode("utf-8")
    digest = hashlib.sha256(digest_input).hexdigest()[:16]
    return f"{document.doc_id}:{index:06d}:{digest}"


def _split_overflow_text(text: str, section: str, tokenizer: Any, max_tokens: int) -> list[str]:
    """Apply a character-safe final guard only when HybridChunker exceeds its budget.

    HybridChunker is deliberately preferred for all structural boundaries. This
    fallback is only needed for an indivisible oversized item (commonly a table
    with a repeated header). Each emitted fragment repeats its section context.
    """

    prefix = f"{section}\n"
    prefix_tokens = int(tokenizer.count_tokens(prefix))
    if prefix_tokens >= max_tokens:
        raise ChunkingError(
            f"Section context alone has {prefix_tokens} tokens and cannot fit the "
            f"configured chunk limit of {max_tokens}."
        )

    fragments: list[str] = []
    remaining = text.strip()
    while remaining:
        low, high = 1, len(remaining)
        best = 0
        while low <= high:
            midpoint = (low + high) // 2
            candidate = prefix + remaining[:midpoint].rstrip()
            if tokenizer.count_tokens(candidate) <= max_tokens:
                best = midpoint
                low = midpoint + 1
            else:
                high = midpoint - 1

        if best == 0:
            raise ChunkingError(
                f"Could not split an oversized chunk into the configured {max_tokens}-token limit."
            )

        boundary = best
        for delimiter in ("\n", "。", ".", ";", "；", ",", "，", " "):
            found = remaining.rfind(delimiter, 0, best)
            if found > max(0, best // 2):
                boundary = found + len(delimiter)
                break

        fragment = (prefix + remaining[:boundary].strip()).strip()
        if tokenizer.count_tokens(fragment) > max_tokens:
            boundary = best
            fragment = (prefix + remaining[:boundary].strip()).strip()
        fragments.append(fragment)
        remaining = remaining[boundary:].lstrip()

    return fragments


def build_chunk_records(
    document: DocumentRecord,
    docling_document: Any,
    hybrid_chunker: Any,
    max_tokens: int,
    *,
    hidden_slide_numbers: set[int] | None = None,
    source_file_hash: str | None = None,
    parser_version: str | None = None,
    classification_map: ClassificationMap | None = None,
    require_document_mapping: bool = False,
) -> list[ChunkRecord]:
    """Build validated records from one Docling document without writing output."""

    records: list[ChunkRecord] = []
    record_index = 0
    source_format = document.source_format or document.file.suffix.lower().lstrip(".")
    hidden_slides = hidden_slide_numbers or set()
    for hybrid_index, docling_chunk in enumerate(hybrid_chunker.chunk(dl_doc=docling_document)):
        if _contains_excluded_content(docling_chunk):
            continue
        text = hybrid_chunker.contextualize(chunk=docling_chunk).strip()
        if not text:
            raise ChunkingError(f"{document.doc_id} produced an empty chunk at index {hybrid_index}")

        token_count = int(hybrid_chunker.tokenizer.count_tokens(text))
        pages = _page_numbers(docling_chunk)
        element_refs = _doc_item_refs(docling_chunk)
        if source_format == "pdf" and not pages:
            raise ChunkingError(
                f"{document.doc_id} chunk {hybrid_index} has no PDF page provenance and cannot be indexed."
            )
        if source_format == "pptx":
            if not pages:
                raise ChunkingError(
                    f"{document.doc_id} chunk {hybrid_index} has no original slide provenance."
                )
            if any(page in hidden_slides for page in pages):
                continue
            if len(pages) != 1:
                raise ChunkingError(
                    f"{document.doc_id} chunk {hybrid_index} spans multiple slides {pages}; "
                    "PPTX chunks must remain on one original slide."
                )
        if source_format == "docx" and not element_refs:
            raise ChunkingError(
                f"{document.doc_id} chunk {hybrid_index} has no DOCX structure element references."
            )

        section = _section_path(getattr(docling_chunk.meta, "headings", None), document.title)
        try:
            classification = resolve_chunk_classification(
                document,
                section,
                classification_map,
                require_document_mapping=require_document_mapping,
            )
        except ClassificationError as exc:
            raise ChunkingError(str(exc)) from exc
        texts = [text] if token_count <= max_tokens else _split_overflow_text(
            text,
            section,
            hybrid_chunker.tokenizer,
            max_tokens,
        )
        for chunk_text in texts:
            chunk_token_count = int(hybrid_chunker.tokenizer.count_tokens(chunk_text))
            if chunk_token_count > max_tokens:
                raise ChunkingError(
                    f"{document.doc_id} chunk {hybrid_index} still has {chunk_token_count} tokens "
                    f"after overflow splitting."
                )
            if source_format == "pdf":
                source_location = SourceLocation(kind="pdf_pages", page_numbers=pages)
                pdf_pages, page_start, page_end = pages, pages[0], pages[-1]
            elif source_format == "pptx":
                source_location = SourceLocation(kind="pptx_slides", slide_numbers=pages)
                pdf_pages, page_start, page_end = [], None, None
            else:
                source_location = SourceLocation(
                    kind="docx_elements",
                    element_refs=element_refs,
                    excerpt=_excerpt(chunk_text),
                )
                pdf_pages, page_start, page_end = [], None, None

            records.append(
                ChunkRecord(
                    chunk_id=_chunk_id(document, record_index, chunk_text),
                    doc_id=document.doc_id,
                    text=chunk_text,
                    title=document.title,
                    revision=document.revision,
                    source_path=document.file,
                    section=section,
                    document_type=document.document_type,
                    authority=document.authority,
                    source_format=source_format,
                    domains=classification.domains,
                    topics=classification.topics,
                    applicable_interfaces=classification.applicable_interfaces,
                    applicable_parts=document.applicable_parts,
                    source_file_hash=source_file_hash or document.file_hash,
                    parser_version=parser_version,
                    source_location=source_location,
                    page_numbers=pdf_pages,
                    page_start=page_start,
                    page_end=page_end,
                    memory_types=classification.memory_types,
                    status=document.status,
                    token_count=chunk_token_count,
                )
            )
            record_index += 1

    if not records:
        raise ChunkingError(f"{document.doc_id} produced no chunks")
    return records


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    position = (len(values) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    if lower == upper:
        return values[lower]
    return round(values[lower] + (values[upper] - values[lower]) * (position - lower))


def _statistics(records: list[ChunkRecord]) -> dict[str, int | float]:
    tokens = sorted(record.token_count for record in records)
    return {
        "chunk_count": len(records),
        "min_tokens": tokens[0],
        "mean_tokens": round(mean(tokens), 2),
        "p50_tokens": _percentile(tokens, 0.5),
        "p95_tokens": _percentile(tokens, 0.95),
        "max_tokens": tokens[-1],
    }


def _read_existing_records(output_path: Path) -> list[ChunkRecord]:
    records: list[ChunkRecord] = []
    for line_number, line in enumerate(output_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            records.append(ChunkRecord.model_validate_json(line))
        except Exception as exc:
            raise ChunkingError(
                f"Existing chunk output is invalid at {output_path}:{line_number}: {exc}"
            ) from exc
    return records


def write_chunk_records(
    settings: AppSettings,
    records: list[ChunkRecord],
    replace: bool = False,
    replace_doc_ids: set[str] | None = None,
) -> Path:
    """Atomically write JSONL records without silently discarding other documents."""

    output_path = settings.resolve_path(settings.paths.chunks)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and not replace:
        raise ChunkingError(
            f"Chunk output already exists: {output_path}. Re-run with --replace to update it."
        )

    retained: list[ChunkRecord] = []
    if output_path.exists() and replace and replace_doc_ids is not None:
        retained = [
            record for record in _read_existing_records(output_path)
            if record.doc_id not in replace_doc_ids
        ]

    combined = retained + records
    ids = [record.chunk_id for record in combined]
    if len(ids) != len(set(ids)):
        raise ChunkingError("Chunk IDs are not globally unique; no output was written.")

    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    payload = "".join(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True) + "\n"
        for record in combined
    )
    temp_path.write_text(payload, encoding="utf-8")
    os.replace(temp_path, output_path)
    return output_path


def chunk_documents(
    settings: AppSettings,
    documents: list[DocumentRecord],
    replace: bool = False,
) -> dict[str, Any]:
    """Chunk selected parsed documents and atomically publish their JSONL records."""

    if settings.chunking.strategy != "docling_hybrid":
        raise ChunkingError(f"Unsupported chunking strategy: {settings.chunking.strategy}")
    if not documents:
        raise ChunkingError("No active documents were selected for chunking.")

    hybrid_chunker = _build_hybrid_chunker(settings)
    pptx_chunker = _build_hybrid_chunker(settings, merge_peers=False)
    classification_map = None
    if settings.classification.mapping is not None:
        mapping_path = settings.resolve_path(settings.classification.mapping)
        try:
            classification_map = load_classification_map(mapping_path)
        except ClassificationError as exc:
            raise ChunkingError(str(exc)) from exc
        if classification_map.taxonomy_version != settings.classification.taxonomy_version:
            raise ChunkingError(
                "Classification mapping taxonomy version does not match configuration: "
                f"{classification_map.taxonomy_version} != {settings.classification.taxonomy_version}"
            )
    all_records: list[ChunkRecord] = []
    reports: list[dict[str, Any]] = []
    for document in documents:
        docling_document = _load_docling_document(_parsed_json_path(settings, document))
        records = build_chunk_records(
            document,
            docling_document,
            pptx_chunker if document.source_format == "pptx" else hybrid_chunker,
            settings.chunking.max_tokens,
            hidden_slide_numbers=_hidden_slides_from_log(settings, document.doc_id),
            source_file_hash=compute_sha256(settings.resolve_path(document.file)),
            parser_version=version("docling"),
            classification_map=classification_map,
            require_document_mapping=settings.classification.require_document_mapping,
        )
        all_records.extend(records)
        reports.append({"doc_id": document.doc_id, **_statistics(records)})

    output_path = write_chunk_records(
        settings,
        all_records,
        replace=replace,
        replace_doc_ids={document.doc_id for document in documents},
    )
    return {
        "output": output_path,
        "documents": reports,
        "total_chunks": len(all_records),
    }
