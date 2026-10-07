"""Build and validate citations that are bound to the current retrieval evidence."""

from __future__ import annotations

from collections.abc import Sequence

from ddr_rag.schemas import Citation, SearchResult


class CitationError(RuntimeError):
    """Raised when a citation does not exactly correspond to retrieved evidence."""


def build_citations(results: Sequence[SearchResult]) -> list[Citation]:
    """Assign rank-stable ``C1``, ``C2`` IDs and copy source metadata exactly.

    A citation is intentionally derived only from the supplied result list.  This
    makes a later answer-generation layer unable to invent a document, page, or
    chunk that was not returned by the active retrieval request.
    """

    chunk_ids = [result.chunk.chunk_id for result in results]
    duplicates = sorted({chunk_id for chunk_id in chunk_ids if chunk_ids.count(chunk_id) > 1})
    if duplicates:
        raise CitationError(
            "Cannot assign citations to duplicate retrieved chunk IDs: " + ", ".join(duplicates)
        )

    return [
        Citation(
            citation_id=f"C{rank}",
            chunk_id=result.chunk.chunk_id,
            doc_id=result.chunk.doc_id,
            title=result.chunk.title,
            revision=result.chunk.revision,
            source_path=result.chunk.source_path,
            section=result.chunk.section,
            document_type=result.chunk.document_type,
            authority=result.chunk.authority,
            source_format=result.chunk.source_format,
            domains=result.chunk.domains,
            topics=result.chunk.topics,
            memory_types=result.chunk.memory_types,
            applicable_interfaces=result.chunk.applicable_interfaces,
            applicable_parts=result.chunk.applicable_parts,
            source_file_hash=result.chunk.source_file_hash,
            parser_version=result.chunk.parser_version,
            source_location=result.chunk.source_location,
            page_numbers=result.chunk.page_numbers,
            page_start=result.chunk.page_start,
            page_end=result.chunk.page_end,
        )
        for rank, result in enumerate(results, start=1)
    ]


def resolve_citation_ids(
    results: Sequence[SearchResult], citation_ids: Sequence[str]
) -> list[Citation]:
    """Resolve LLM-selected IDs while rejecting IDs outside this result set."""

    requested = list(citation_ids)
    duplicates = sorted({citation_id for citation_id in requested if requested.count(citation_id) > 1})
    if duplicates:
        raise CitationError("Citation IDs must not repeat: " + ", ".join(duplicates))

    allowed = {citation.citation_id: citation for citation in build_citations(results)}
    unknown = [citation_id for citation_id in requested if citation_id not in allowed]
    if unknown:
        raise CitationError(
            "Citation IDs are not present in the active retrieved evidence: " + ", ".join(unknown)
        )
    return [allowed[citation_id] for citation_id in requested]


def validate_citations(results: Sequence[SearchResult], citations: Sequence[Citation]) -> None:
    """Reject forged or stale citation metadata against current retrieval results."""

    allowed = {citation.citation_id: citation for citation in build_citations(results)}
    seen: set[str] = set()
    for citation in citations:
        if citation.citation_id in seen:
            raise CitationError(f"Citation ID must not repeat: {citation.citation_id}")
        seen.add(citation.citation_id)
        expected = allowed.get(citation.citation_id)
        if expected is None:
            raise CitationError(
                f"Citation ID is not present in the active retrieved evidence: {citation.citation_id}"
            )
        if citation.model_dump(mode="json") != expected.model_dump(mode="json"):
            raise CitationError(
                f"Citation metadata does not match active retrieved evidence: {citation.citation_id}"
            )


def format_citation(citation: Citation) -> str:
    """Render a format-aware Chinese source entry from verified citation metadata."""

    document_labels = {
        "standard": "标准",
        "datasheet": "数据手册",
        "hardware_design_guide": "硬件设计指南",
        "application_note": "应用笔记",
        "company_spec": "企业规范",
        "fab_capability": "板厂能力资料",
        "engineering_experience": "工程经验",
        "approved_experience": "工程经验",
        "technical_whitepaper": "技术白皮书",
        "training_material": "培训资料",
        "other": "其他资料",
    }
    authority_labels = {
        "standard": "标准组织",
        "vendor_datasheet": "原厂",
        "vendor_design_guide": "原厂",
        "company_spec": "企业已发布",
        "fab_capability": "板厂",
        "approved_experience": "已审核",
        "unverified_note": "未审核",
    }
    format_labels = {"pdf": "PDF", "docx": "Word", "pptx": "PowerPoint"}
    location = citation.source_location
    if location is None:
        rendered_location = citation.section
    elif location.kind == "pdf_pages":
        first, last = location.page_numbers[0], location.page_numbers[-1]
        pages = str(first) if first == last else f"{first}–{last}"
        rendered_location = f"{citation.section}，第 {pages} 页"
    elif location.kind == "pptx_slides":
        slides = "、".join(str(number) for number in location.slide_numbers)
        rendered_location = f"{citation.section}，第 {slides} 张幻灯片"
    else:
        refs = "、".join(location.element_refs)
        rendered_location = (
            f"{citation.section}，结构元素 {refs}\n"
            f"     原文摘录：“{location.excerpt}”"
        )
    header = " · ".join(
        (
            document_labels.get(citation.document_type, citation.document_type),
            authority_labels.get(citation.authority, citation.authority),
            format_labels[citation.source_format],
        )
    )
    return (
        f"[{citation.citation_id}] {header}\n"
        f"     《{citation.title}》，{citation.revision}\n"
        f"     领域：{', '.join(citation.domains)}；主题：{', '.join(citation.topics)}\n"
        f"     {rendered_location}\n"
        f"     原文件：{citation.source_path}"
    )


def format_source_location(citation: Citation) -> str:
    """Render only the source locator for prompts and compact search output."""

    location = citation.source_location
    if location is None:
        return citation.section
    if location.kind == "pdf_pages":
        first, last = location.page_numbers[0], location.page_numbers[-1]
        return f"PDF 第 {first} 页" if first == last else f"PDF 第 {first}-{last} 页"
    if location.kind == "pptx_slides":
        slides = "、".join(str(number) for number in location.slide_numbers)
        return f"PowerPoint 第 {slides} 张幻灯片"
    refs = "、".join(location.element_refs)
    return f"Word 结构元素 {refs}；原文摘录：{location.excerpt}"
