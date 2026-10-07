from pathlib import Path

import pytest

from ddr_rag.citations import (
    CitationError,
    build_citations,
    format_citation,
    resolve_citation_ids,
    validate_citations,
)
from ddr_rag.schemas import ChunkRecord, SearchResult, SourceLocation


def make_result(index: int) -> SearchResult:
    chunk = ChunkRecord(
        chunk_id=f"TEST:{index:06d}:abc",
        doc_id="TEST_GUIDE",
        text="DDR4 CLKP CLKN routing evidence",
        title="DDR test guide",
        revision="Rev. 1",
        source_path=Path("data/raw/test-guide.pdf"),
        section=f"DDR routing {index}",
        page_numbers=[index + 10, index + 11],
        page_start=index + 10,
        page_end=index + 11,
        memory_types=["DDR4"],
        status="active",
        token_count=6,
    )
    return SearchResult(chunk=chunk, score=0.9 - index / 10, retrieval_sources=["dense"])


def test_citations_copy_complete_retrieval_traceability_metadata() -> None:
    results = [make_result(0), make_result(1)]

    citations = build_citations(results)

    assert [citation.citation_id for citation in citations] == ["C1", "C2"]
    assert citations[0].chunk_id == results[0].chunk.chunk_id
    assert citations[0].source_path == results[0].chunk.source_path
    assert citations[0].section == results[0].chunk.section
    assert citations[0].page_numbers == [10, 11]
    validate_citations(results, citations)


def test_citations_reject_foreign_ids_and_forged_pages() -> None:
    results = [make_result(0), make_result(1)]
    citations = build_citations(results)

    assert resolve_citation_ids(results, ["C2"]) == [citations[1]]
    with pytest.raises(CitationError, match="not present"):
        resolve_citation_ids(results, ["C3"])
    with pytest.raises(CitationError, match="must not repeat"):
        resolve_citation_ids(results, ["C1", "C1"])

    forged = citations[0].model_copy(update={"page_numbers": [999], "page_start": 999, "page_end": 999})
    with pytest.raises(CitationError, match="metadata does not match"):
        validate_citations(results, [forged])


def test_citations_reject_duplicate_retrieved_chunks() -> None:
    result = make_result(0)

    with pytest.raises(CitationError, match="duplicate retrieved chunk IDs"):
        build_citations([result, result])


def test_word_experience_citation_preserves_and_formats_source_identity() -> None:
    chunk = ChunkRecord(
        chunk_id="NOTE:000000:abc",
        doc_id="NOTE",
        text="RK3568 project experience",
        title="RK3568 调试记录",
        revision="2026-01",
        source_path=Path("data/raw/internal/note.docx"),
        section="问题分析",
        document_type="engineering_experience",
        authority="unverified_note",
        source_format="docx",
        applicable_parts=["RK3568"],
        source_location=SourceLocation(
            kind="docx_elements", element_refs=["#/texts/3"], excerpt="RK3568 project experience"
        ),
        memory_types=["DDR4"],
        status="active",
        token_count=4,
    )
    citation = build_citations([SearchResult(chunk=chunk, score=1.0)])[0]

    rendered = format_citation(citation)
    assert citation.document_type == "engineering_experience"
    assert citation.authority == "unverified_note"
    assert "工程经验 · 未审核 · Word" in rendered
    assert "结构元素 #/texts/3" in rendered
    assert "原文摘录" in rendered

    forged = citation.model_copy(update={"authority": "vendor_design_guide"})
    with pytest.raises(CitationError, match="metadata does not match"):
        validate_citations([SearchResult(chunk=chunk, score=1.0)], [forged])
