from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from pydantic import ValidationError

from ddr_rag.evaluation import (
    EvaluationDataset,
    EvaluationError,
    EvaluationQuestion,
    ExpectedSource,
    evaluate_answer_results,
    evaluate_offline_results,
    load_evaluation_dataset,
    regrade_answer_report,
    run_answer_evaluation,
    select_evaluation_questions,
    validate_evaluation_dataset,
    write_answer_evaluation_report,
    write_offline_evaluation_report,
)
from ddr_rag.citations import build_citations
from ddr_rag.schemas import AnswerResult, ChunkRecord, SearchResult


DOC_IDS = (
    "ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2",
    "TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C",
    "NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1",
)


def make_source(index: int = 0) -> ExpectedSource:
    return ExpectedSource(doc_id=DOC_IDS[index % len(DOC_IDS)], section_contains="DDR routing", page_numbers=[10])


def make_answerable(index: int) -> EvaluationQuestion:
    return EvaluationQuestion(
        question_id=f"DDR_ANS_TEST_{index:02d}",
        question=f"What is DDR test rule {index}?",
        language="zh-CN" if index % 2 else "en",
        category="routing_limit",
        memory_type="DDR4",
        answerable=True,
        expected_sources=[make_source(index)],
        expected_key_facts=["A verified fact"],
    )


def make_refusal(index: int) -> EvaluationQuestion:
    return EvaluationQuestion(
        question_id=f"DDR_REFUSE_TEST_{index:02d}",
        question=f"What is unavailable DDR rule {index}?",
        language="zh-CN" if index % 2 else "en",
        category="refusal_scope",
        memory_type="DDR5",
        answerable=False,
        refusal_reason="The source is outside the local knowledge-base scope.",
    )


def make_dataset() -> EvaluationDataset:
    return EvaluationDataset(
        schema_version=1,
        dataset_id="ddr_rag_v1",
        description="Test dataset",
        questions=[*(make_answerable(index) for index in range(1, 31)), *(make_refusal(index) for index in range(1, 11))],
    )


def make_record(doc_id: str) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=f"{doc_id}:000001:abc",
        doc_id=doc_id,
        text="A verified DDR4 routing rule.",
        title="Test guide",
        revision="R1",
        source_path=Path("data/raw/vendor/test.pdf"),
        section="DDR   routing",
        page_numbers=[10],
        page_start=10,
        page_end=10,
        memory_types=["DDR4"],
        status="active",
        token_count=5,
    )


def test_evaluation_question_requires_evidence_or_refusal_reason() -> None:
    with pytest.raises(ValidationError, match="expected_sources"):
        EvaluationQuestion(
            question_id="DDR_ANS_BAD",
            question="What is the rule?",
            language="en",
            category="routing_limit",
            answerable=True,
            expected_key_facts=["fact"],
        )
    with pytest.raises(ValidationError, match="refusal_reason"):
        EvaluationQuestion(
            question_id="DDR_REFUSE_BAD",
            question="What is unavailable?",
            language="en",
            category="refusal_scope",
            answerable=False,
        )


def test_clarification_question_requires_no_routing_hints() -> None:
    question = EvaluationQuestion(
        question_id="V2_AMBIG_TEST_01",
        question="这个要求应该怎么处理？",
        language="zh-CN",
        category="ambiguity_route",
        expected_route_status="clarification_required",
        answerable=False,
        refusal_reason="领域不明确，必须先向用户澄清。",
    )

    assert question.expected_route_status == "clarification_required"
    with pytest.raises(ValidationError, match="cannot define routing hints"):
        question.model_copy(update={"domains": ["memory"]}).__class__.model_validate(
            {**question.model_dump(mode="json"), "domains": ["memory"]}
        )


def test_load_and_validate_complete_dataset_against_local_anchors(tmp_path: Path) -> None:
    path = tmp_path / "questions.yaml"
    path.write_text(yaml.safe_dump(make_dataset().model_dump(mode="json"), sort_keys=False), encoding="utf-8")

    dataset = load_evaluation_dataset(path)
    report = validate_evaluation_dataset(dataset, [make_record(doc_id) for doc_id in DOC_IDS])

    assert report["total_questions"] == 40
    assert report["answerable_questions"] == 30
    assert report["refusal_questions"] == 10
    assert report["answerable_language_counts"] == {"en": 15, "zh-CN": 15}


def test_validation_rejects_anchor_missing_from_chunk_records() -> None:
    dataset = make_dataset()
    missing_anchor = make_source().model_copy(update={"page_numbers": [11]})
    dataset.questions[0] = dataset.questions[0].model_copy(update={"expected_sources": [missing_anchor]})

    with pytest.raises(EvaluationError, match="no Chunk matches"):
        validate_evaluation_dataset(dataset, [make_record(doc_id) for doc_id in DOC_IDS])


def test_cross_domain_validation_checks_memory_type_only_on_memory_sources() -> None:
    memory_record = make_record(DOC_IDS[0])
    si_record = ChunkRecord(
        chunk_id="SI_DOC:000001:abc",
        doc_id="SI_DOC",
        text="Impedance mismatch causes reflection.",
        title="SI fixture",
        revision="R1",
        source_path=Path("data/raw/fixture/si.pptx"),
        source_format="pptx",
        section="Reflection",
        source_location={"kind": "pptx_slides", "slide_numbers": [8]},
        domains=["signal_integrity"],
        topics=["signal_integrity", "impedance"],
        status="active",
        token_count=5,
    )
    question = EvaluationQuestion(
        question_id="V2_CROSS_TEST_01",
        question="How do DDR4 termination and reflection relate?",
        language="en",
        category="cross_domain_synthesis",
        domains=["memory", "signal_integrity"],
        topics=["ddr4", "impedance"],
        memory_type="DDR4",
        answerable=True,
        expected_sources=[
            make_source(0),
            ExpectedSource(doc_id="SI_DOC", section_contains="Reflection", slide_numbers=[8]),
        ],
        expected_key_facts=["Termination controls reflections."],
    )
    dataset = EvaluationDataset(
        schema_version=2,
        dataset_id="hardware_v2_cross_validation",
        description="Cross-domain memory-type fixture",
        questions=[question],
    )

    report = validate_evaluation_dataset(dataset, [memory_record, si_record])

    assert report["answerable_questions"] == 1


def test_select_evaluation_question_requires_a_known_unique_id() -> None:
    dataset = make_dataset()
    selected = select_evaluation_questions(dataset, ["DDR_REFUSE_TEST_05"])

    assert [question.question_id for question in selected.questions] == ["DDR_REFUSE_TEST_05"]
    with pytest.raises(EvaluationError, match="Repeated"):
        select_evaluation_questions(dataset, ["DDR_REFUSE_TEST_05", "DDR_REFUSE_TEST_05"])
    with pytest.raises(EvaluationError, match="Unknown"):
        select_evaluation_questions(dataset, ["DDR_REFUSE_UNKNOWN"])


def test_offline_evaluation_scores_all_anchors_and_writes_traceable_reports(tmp_path: Path) -> None:
    dataset = make_dataset()
    results = {
        question.question_id: [
            SearchResult(
                chunk=make_record(question.expected_sources[0].doc_id),
                score=0.9,
                retrieval_sources=["dense", "sparse"],
            )
        ]
        if question.answerable
        else []
        for question in dataset.questions
    }

    report = evaluate_offline_results(dataset, results, top_k=5)
    paths = write_offline_evaluation_report(report, tmp_path)

    assert report["answer_model_called"] is False
    assert report["summary"]["answerable_all_anchors_hit_rate"] == 1.0
    assert report["summary"]["single_source_hit_at_5"] == 30
    assert report["summary"]["single_source_hit_rate_at_5"] == 1.0
    assert report["summary"]["cross_domain_questions"] == 0
    assert report["summary"]["cross_domain_coverage_rate_at_k"] == 1.0
    assert report["summary"]["refusal_no_result"] == 10
    assert paths["json"].is_file()
    assert "Answer model: not called" in paths["markdown"].read_text(encoding="utf-8")

    refusal_only = select_evaluation_questions(dataset, ["DDR_REFUSE_TEST_01"])
    refusal_report = evaluate_offline_results(refusal_only, {"DDR_REFUSE_TEST_01": []}, top_k=5)
    assert refusal_report["summary"]["answerable_all_anchors_hit_rate"] == 1.0
    assert refusal_report["summary"]["expected_anchor_recall_at_k"] == 1.0


def test_offline_evaluation_scores_clarification_without_retrieval() -> None:
    question = EvaluationQuestion(
        question_id="V2_AMBIG_TEST_01",
        question="这个要求应该怎么处理？",
        language="zh-CN",
        category="ambiguity_route",
        expected_route_status="clarification_required",
        answerable=False,
        refusal_reason="领域不明确，必须先向用户澄清。",
    )
    dataset = EvaluationDataset(
        schema_version=2,
        dataset_id="hardware_v2_route_test",
        description="Clarification routing fixture",
        questions=[question],
    )
    report = evaluate_offline_results(
        dataset,
        {question.question_id: []},
        top_k=5,
        route_reports={
            question.question_id: {
                "status": "clarification_required",
                "candidate_domains": [],
                "reasons": ["no deterministic domain hint"],
            }
        },
    )

    assert report["summary"]["clarification_questions"] == 1
    assert report["summary"]["clarification_pass"] == 1
    assert report["summary"]["clarification_rate"] == 1.0
    assert report["summary"]["refusal_no_result"] == 0
    assert report["questions"][0]["offline_status"] == "route_pass"


def test_answer_evaluation_scores_verified_sources_and_strict_refusals(tmp_path: Path) -> None:
    dataset = make_dataset()
    answers: dict[str, AnswerResult] = {}
    for question in dataset.questions:
        if question.answerable:
            result = SearchResult(
                chunk=make_record(question.expected_sources[0].doc_id),
                score=0.9,
                retrieval_sources=["dense", "sparse"],
            )
            answers[question.question_id] = AnswerResult(
                answer="Verified answer. [C1]",
                citations=build_citations([result]),
                retrieved=[result],
                generation_attempts=1,
            )
        else:
            answers[question.question_id] = AnswerResult(
                answer="当前知识库不足以判断。",
                citations=[],
                retrieved=[],
            )

    attempted = {question.question_id for question in dataset.questions if question.answerable}
    report = evaluate_answer_results(
        dataset,
        answers,
        {},
        top_k=5,
        api_attempted_question_ids=attempted,
    )
    paths = write_answer_evaluation_report(report, tmp_path)

    assert report["answer_model_called"] is True
    assert report["summary"]["answerable_grounded_source_pass_rate"] == 1.0
    assert report["summary"]["refusal_pass_rate"] == 1.0
    assert report["summary"]["api_requests_attempted"] == 30
    assert paths["json"].is_file()
    assert "Semantic fact check: manual review" in paths["markdown"].read_text(encoding="utf-8")

    regraded = regrade_answer_report(dataset, report)
    assert regraded["summary"] == report["summary"]


def test_answer_evaluation_caps_evidence_at_generation_limit(monkeypatch) -> None:
    dataset = make_dataset()
    settings = SimpleNamespace(
        generation=SimpleNamespace(
            enabled=True,
            provider="deepseek",
            api_key_env="DEEPSEEK_API_KEY",
            max_evidence_chunks=2,
        )
    )
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test")
    seen_lengths: list[int] = []

    def fake_answer_from_results(settings, question, results):
        seen_lengths.append(len(results))
        return AnswerResult(answer="当前知识库不足以判断。", citations=[], retrieved=results)

    monkeypatch.setattr("ddr_rag.answerer.answer_from_results", fake_answer_from_results)
    candidate = SearchResult(
        chunk=make_record(DOC_IDS[0]),
        score=0.9,
        retrieval_sources=["dense", "sparse"],
    )
    results = {question.question_id: [candidate] * 8 for question in dataset.questions}

    report = run_answer_evaluation(settings, dataset, results, top_k=8)

    assert report["top_k"] == 2
    assert seen_lengths == [2] * 40


def test_answer_evaluation_records_requests_for_generation_errors() -> None:
    dataset = select_evaluation_questions(make_dataset(), ["DDR_REFUSE_TEST_01"])
    report = evaluate_answer_results(
        dataset,
        {},
        {"DDR_REFUSE_TEST_01": "AnsweringError: rejected after generation"},
        top_k=5,
        api_attempted_question_ids={"DDR_REFUSE_TEST_01"},
        api_request_counts={"DDR_REFUSE_TEST_01": 2},
    )

    assert report["questions"][0]["api_request_count"] == 2
    assert report["summary"]["api_requests_attempted"] == 2
