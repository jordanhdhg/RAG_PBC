from pathlib import Path

from typer.testing import CliRunner

from ddr_rag.citations import build_citations
from ddr_rag.cli import app
from ddr_rag.schemas import AnswerResult, ChunkRecord, SearchResult
from test_config import write_config


def result() -> SearchResult:
    return SearchResult(
        chunk=ChunkRecord(
            chunk_id="GUIDE:000000:abc",
            doc_id="GUIDE",
            text="DDR4 clock evidence",
            title="DDR4 Hardware Guide",
            revision="R1",
            source_path=Path("data/raw/vendor/guide.pdf"),
            section="Clock routing",
            document_type="hardware_design_guide",
            authority="vendor_design_guide",
            applicable_parts=["TEST_SOC"],
            page_numbers=[10],
            page_start=10,
            page_end=10,
            memory_types=["DDR4"],
            status="active",
            token_count=4,
        ),
        score=0.9,
        retrieval_sources=["dense", "sparse"],
    )


def test_ask_text_appends_only_verified_answer_sources(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    evidence = result()
    citation = build_citations([evidence])[0]
    monkeypatch.setattr(
        "ddr_rag.cli.answer_question",
        lambda *args, **kwargs: AnswerResult(
            answer="时钟需要受控。[C1]", citations=[citation], retrieved=[evidence]
        ),
    )

    response = CliRunner().invoke(app, ["ask", "DDR4 clock?", "--config", str(config_path)])

    assert response.exit_code == 0
    assert "答案来源：" in response.stdout
    assert "硬件设计指南 · 原厂 · PDF" in response.stdout
    assert "DDR4 Hardware Guide" in response.stdout
    assert "第 10 页" in response.stdout


def test_ask_text_marks_refusal_as_having_no_answer_source(tmp_path: Path, monkeypatch) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    monkeypatch.setattr(
        "ddr_rag.cli.answer_question",
        lambda *args, **kwargs: AnswerResult(
            answer="当前知识库不足以判断。", citations=[], retrieved=[]
        ),
    )

    response = CliRunner().invoke(app, ["ask", "DDR5 rule?", "--config", str(config_path)])

    assert response.exit_code == 0
    assert "当前知识库不足以判断。" in response.stdout
    assert "本次没有可用于作答的引用来源。" in response.stdout
