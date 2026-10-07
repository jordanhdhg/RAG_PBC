from pathlib import Path
from types import SimpleNamespace

import pytest

from ddr_rag.answerer import AnsweringError, answer_question
from ddr_rag.config import load_settings
from ddr_rag.schemas import ChunkRecord, SearchResult
from test_config import write_config


def make_result(index: int = 0) -> SearchResult:
    return SearchResult(
        chunk=ChunkRecord(
            chunk_id=f"TEST:{index:06d}:abc",
            doc_id="TEST_GUIDE",
            text="DDR4 CLKP CLKN routing must be controlled.",
            title="Test guide",
            revision="R1",
            source_path=Path("data/raw/vendor/test-guide.pdf"),
            section="DDR routing",
            document_type="hardware_design_guide",
            authority="vendor_design_guide",
            applicable_parts=["TEST_SOC"],
            page_numbers=[10],
            page_start=10,
            page_end=10,
            memory_types=["DDR4"],
            status="active",
            token_count=8,
        ),
        score=0.9,
        retrieval_sources=["dense", "sparse"],
    )


class FakeCompletions:
    def __init__(self, content: str | list[str]) -> None:
        self.contents = [content] if isinstance(content, str) else content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.contents[min(len(self.calls) - 1, len(self.contents) - 1)]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class FakeClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


def configured_settings(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    settings.generation.enabled = True
    settings.generation.provider = "deepseek"
    settings.generation.model = "deepseek-flash"
    settings.generation.max_evidence_chunks = 2
    return settings


def test_answerer_sends_only_retrieved_evidence_and_returns_verified_citation(tmp_path: Path, monkeypatch) -> None:
    settings = configured_settings(tmp_path)
    completions = FakeCompletions("CLKP/CLKN must be controlled. [C1]")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("ddr_rag.answerer.hybrid_search", lambda *args, **kwargs: [make_result()])
    monkeypatch.setattr("ddr_rag.answerer.OpenAI", lambda **kwargs: FakeClient(completions))

    answer = answer_question(settings, "DDR4 CLK requirement?", memory_type="DDR4")

    assert answer.citations[0].citation_id == "C1"
    assert answer.citations[0].chunk_id == make_result().chunk.chunk_id
    assert answer.generation_attempts == 1
    prompt = completions.calls[0]["messages"][1]["content"]
    assert "允许引用：[C1]" in prompt
    assert "资料类别：hardware_design_guide" in prompt
    assert "来源身份：vendor_design_guide" in prompt
    assert "适用型号：TEST_SOC" in prompt
    assert "原文位置：PDF 第 10 页" in prompt
    assert "DDR4 CLKP CLKN routing must be controlled." in prompt
    assert "DEEPSEEK_API_KEY" not in prompt
    assert completions.calls[0]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_answerer_rejects_forged_or_missing_citations(tmp_path: Path, monkeypatch) -> None:
    settings = configured_settings(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("ddr_rag.answerer.hybrid_search", lambda *args, **kwargs: [make_result()])

    forged = FakeCompletions("Invented rule. [C9]")
    monkeypatch.setattr("ddr_rag.answerer.OpenAI", lambda **kwargs: FakeClient(forged))
    with pytest.raises(AnsweringError, match="invalid citation"):
        answer_question(settings, "Question")
    assert len(forged.calls) == 1

    uncited = FakeCompletions("Uncited conclusion.")
    monkeypatch.setattr("ddr_rag.answerer.OpenAI", lambda **kwargs: FakeClient(uncited))
    with pytest.raises(AnsweringError, match="contained no allowed") as error:
        answer_question(settings, "Question")
    assert len(uncited.calls) == 2
    assert error.value.generation_attempts == 2


def test_answerer_refuses_without_local_evidence_without_calling_api(tmp_path: Path, monkeypatch) -> None:
    settings = configured_settings(tmp_path)
    monkeypatch.setattr("ddr_rag.answerer.hybrid_search", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "ddr_rag.answerer.OpenAI",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("API must not be called")),
    )

    answer = answer_question(settings, "Unknown DDR rule")

    assert "不足以判断" in answer.answer
    assert answer.citations == []
    assert answer.retrieved == []


def test_answerer_accepts_strict_refusal_when_retrieved_evidence_is_insufficient(tmp_path: Path, monkeypatch) -> None:
    settings = configured_settings(tmp_path)
    completions = FakeCompletions("当前知识库不足以判断。")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("ddr_rag.answerer.hybrid_search", lambda *args, **kwargs: [make_result()])
    monkeypatch.setattr("ddr_rag.answerer.OpenAI", lambda **kwargs: FakeClient(completions))

    answer = answer_question(settings, "Unsupported question")

    assert answer.answer == "当前知识库不足以判断。"
    assert answer.citations == []
    assert len(answer.retrieved) == 1
    assert answer.generation_attempts == 1


def test_answerer_retries_one_uncited_response_then_accepts_strict_refusal(tmp_path: Path, monkeypatch) -> None:
    settings = configured_settings(tmp_path)
    completions = FakeCompletions([
        "现有资料没有明确说明。",
        "当前知识库不足以判断。",
    ])
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("ddr_rag.answerer.hybrid_search", lambda *args, **kwargs: [make_result()])
    monkeypatch.setattr("ddr_rag.answerer.OpenAI", lambda **kwargs: FakeClient(completions))

    answer = answer_question(settings, "Unsupported question")

    assert answer.answer == "当前知识库不足以判断。"
    assert answer.generation_attempts == 2
    assert len(completions.calls) == 2
    assert "严格格式纠正" in completions.calls[1]["messages"][1]["content"]


def test_answerer_validates_citations_in_refusal_explanations(tmp_path: Path, monkeypatch) -> None:
    settings = configured_settings(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    monkeypatch.setattr("ddr_rag.answerer.hybrid_search", lambda *args, **kwargs: [make_result()])
    monkeypatch.setattr(
        "ddr_rag.answerer.OpenAI",
        lambda **kwargs: FakeClient(FakeCompletions("当前知识库不足以判断。证据范围不包含该内容。[C1]")),
    )

    answer = answer_question(settings, "Unsupported question")

    assert answer.citations[0].citation_id == "C1"

    monkeypatch.setattr(
        "ddr_rag.answerer.OpenAI",
        lambda **kwargs: FakeClient(FakeCompletions("当前知识库不足以判断。这里还有一段无引用解释。")),
    )
    with pytest.raises(AnsweringError, match="explanation without allowed"):
        answer_question(settings, "Unsupported question")
