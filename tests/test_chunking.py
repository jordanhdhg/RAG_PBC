from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from ddr_rag.chunker import ChunkingError, build_chunk_records, write_chunk_records
from ddr_rag.config import load_settings
from ddr_rag.schemas import ChunkRecord, DocumentRecord
from test_config import write_config


def make_document() -> DocumentRecord:
    return DocumentRecord(
        doc_id="TEST_DDR4_R1",
        title="Test DDR4 Guide",
        revision="R1",
        vendor="Test Vendor",
        file=Path("data/raw/vendor/guide.pdf"),
        document_type="hardware_design_guide",
        memory_types=["DDR4"],
        authority="vendor_design_guide",
        authority_score=90,
        status="active",
        confidentiality="public",
    )


class FakeTokenizer:
    def count_tokens(self, text: str) -> int:
        return len(text.split())


class FakeHybridChunker:
    tokenizer = FakeTokenizer()

    def __init__(self, chunks: list[SimpleNamespace]) -> None:
        self._chunks = chunks

    def chunk(self, *, dl_doc: object):
        return iter(self._chunks)

    def contextualize(self, *, chunk: SimpleNamespace) -> str:
        return chunk.text


def fake_chunk(text: str, pages: list[int], headings: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        meta=SimpleNamespace(
            headings=headings,
            doc_items=[SimpleNamespace(prov=[SimpleNamespace(page_no=page) for page in pages])],
        ),
    )


def test_build_chunk_records_preserves_required_metadata() -> None:
    document = make_document()
    chunker = FakeHybridChunker(
        [
            fake_chunk("DDR4 layout rule", [3, 4], ["3 DDR", "3.2 Layout"]),
            fake_chunk("DDR4 termination rule", [4], ["3 DDR", "3.3 Termination"]),
        ]
    )

    records = build_chunk_records(document, object(), chunker, max_tokens=600)

    assert len(records) == 2
    assert len({record.chunk_id for record in records}) == 2
    assert records[0].doc_id == document.doc_id
    assert records[0].title == document.title
    assert records[0].revision == document.revision
    assert records[0].source_path == document.file
    assert records[0].document_type == "hardware_design_guide"
    assert records[0].authority == "vendor_design_guide"
    assert records[0].source_format == "pdf"
    assert records[0].section == "3 DDR > 3.2 Layout"
    assert records[0].page_numbers == [3, 4]
    assert records[0].page_start == 3
    assert records[0].page_end == 4
    assert records[0].source_location.kind == "pdf_pages"
    assert records[0].memory_types == ["DDR4"]
    assert records[0].status == "active"


def test_build_chunk_records_rejects_missing_page_provenance() -> None:
    chunker = FakeHybridChunker([fake_chunk("layout rule", [], ["DDR"])])

    with pytest.raises(ChunkingError, match="no PDF page provenance"):
        build_chunk_records(make_document(), object(), chunker, max_tokens=600)


def test_build_chunk_records_splits_token_overflow_with_section_context() -> None:
    chunker = FakeHybridChunker([fake_chunk("one two three", [1], ["DDR"])])

    records = build_chunk_records(make_document(), object(), chunker, max_tokens=2)

    assert len(records) == 3
    assert all(record.token_count <= 2 for record in records)
    assert all(record.text.startswith("DDR") for record in records)


def test_chunk_record_page_range_must_match_pages() -> None:
    with pytest.raises(ValidationError, match="page range"):
        ChunkRecord(
            chunk_id="chunk",
            doc_id="DOC",
            text="text",
            title="title",
            revision="R1",
            source_path=Path("source.pdf"),
            section="section",
            page_numbers=[2, 3],
            page_start=1,
            page_end=3,
            memory_types=["DDR4"],
            status="active",
            token_count=1,
        )


def test_write_chunks_requires_replace_for_existing_output(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    record = ChunkRecord(
        chunk_id="TEST:000000:abc",
        doc_id="TEST",
        text="text",
        title="title",
        revision="R1",
        source_path=Path("data/raw/vendor/guide.pdf"),
        section="section",
        page_numbers=[1],
        page_start=1,
        page_end=1,
        memory_types=["DDR4"],
        status="active",
        token_count=1,
    )

    write_chunk_records(settings, [record])
    with pytest.raises(ChunkingError, match="already exists"):
        write_chunk_records(settings, [record])
