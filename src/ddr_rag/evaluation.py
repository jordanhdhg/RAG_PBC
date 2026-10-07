"""Versioned, local-only evaluation-question dataset validation."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ddr_rag.schemas import AnswerResult, ChunkRecord, Citation, SearchResult
from ddr_rag.taxonomy import (
    normalize_domains,
    normalize_interfaces,
    normalize_memory_types,
    normalize_topics,
    validate_domain_topic_relationship,
)


class EvaluationError(RuntimeError):
    """Raised when a versioned RAG evaluation dataset is unusable."""


def _normalized_section(value: str) -> str:
    """Compare Docling headings without treating formatting-only whitespace as meaning."""

    return re.sub(r"\s+", " ", value).strip().casefold()


def _matches_source(record: ChunkRecord, source: "ExpectedSource") -> bool:
    if record.doc_id != source.doc_id:
        return False
    if _normalized_section(source.section_contains) not in _normalized_section(record.section):
        return False
    if source.page_numbers:
        return bool(set(source.page_numbers).intersection(record.page_numbers))
    location = record.source_location
    if location is None:
        return False
    if source.slide_numbers:
        return bool(set(source.slide_numbers).intersection(location.slide_numbers))
    return bool(set(source.element_refs).intersection(location.element_refs))


class ExpectedSource(BaseModel):
    """One format-aware source anchor required by an answerable question."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    section_contains: str = Field(min_length=1)
    page_numbers: list[int] = Field(default_factory=list)
    slide_numbers: list[int] = Field(default_factory=list)
    element_refs: list[str] = Field(default_factory=list)

    @field_validator("page_numbers", "slide_numbers")
    @classmethod
    def normalize_pages(cls, values: list[int]) -> list[int]:
        normalized = sorted(set(values))
        if any(page < 1 for page in normalized):
            raise ValueError("page_numbers must contain only positive page numbers")
        return normalized

    @field_validator("element_refs")
    @classmethod
    def normalize_element_refs(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def require_one_locator(self) -> "ExpectedSource":
        locator_count = sum(bool(values) for values in (self.page_numbers, self.slide_numbers, self.element_refs))
        if locator_count != 1:
            raise ValueError(
                "expected source requires exactly one of page_numbers, slide_numbers, or element_refs"
            )
        return self

    def locator_summary(self) -> dict[str, list[int] | list[str]]:
        if self.page_numbers:
            return {"page_numbers": self.page_numbers}
        if self.slide_numbers:
            return {"slide_numbers": self.slide_numbers}
        return {"element_refs": self.element_refs}


class EvaluationQuestion(BaseModel):
    """Ground truth for one retrieval or grounded-answering evaluation case."""

    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    question: str = Field(min_length=5)
    language: str = Field(min_length=2)
    category: str = Field(min_length=1)
    domains: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    applicable_interfaces: list[str] = Field(default_factory=list)
    memory_type: str | None = None
    expected_route_status: Literal["resolved", "clarification_required"] = "resolved"
    answerable: bool
    expected_sources: list[ExpectedSource] = Field(default_factory=list)
    expected_key_facts: list[str] = Field(default_factory=list)
    refusal_reason: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_domain(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if payload.get("memory_type") and "domains" not in payload:
            payload["domains"] = ["memory"]
        return payload

    @field_validator("domains")
    @classmethod
    def normalize_question_domains(cls, values: list[str]) -> list[str]:
        return normalize_domains(values) if values else []

    @field_validator("topics")
    @classmethod
    def normalize_question_topics(cls, values: list[str]) -> list[str]:
        return normalize_topics(values) if values else []

    @field_validator("applicable_interfaces")
    @classmethod
    def normalize_question_interfaces(cls, values: list[str]) -> list[str]:
        return normalize_interfaces(values)

    @field_validator("memory_type")
    @classmethod
    def normalize_memory_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = normalize_memory_types([value])
        return normalized[0] if normalized else None

    @field_validator("expected_key_facts")
    @classmethod
    def strip_key_facts(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values if value.strip()]
        return list(dict.fromkeys(normalized))

    @model_validator(mode="after")
    def validate_expected_outcome(self) -> "EvaluationQuestion":
        if self.topics and not self.domains:
            raise ValueError("question topics require at least one domain")
        if self.topics:
            validate_domain_topic_relationship(self.domains, self.topics)
        if self.memory_type and self.domains and "memory" not in self.domains:
            raise ValueError("question memory_type requires the memory domain")
        if self.expected_route_status == "clarification_required":
            if self.answerable:
                raise ValueError("clarification-required questions must be unanswerable")
            if self.domains or self.topics or self.applicable_interfaces or self.memory_type:
                raise ValueError(
                    "clarification-required questions cannot define routing hints"
                )
        if self.answerable:
            if not self.expected_sources:
                raise ValueError("answerable questions require expected_sources")
            if not self.expected_key_facts:
                raise ValueError("answerable questions require expected_key_facts")
            if self.refusal_reason is not None:
                raise ValueError("answerable questions cannot define refusal_reason")
        else:
            if self.expected_sources or self.expected_key_facts:
                raise ValueError("refusal questions cannot define answer evidence")
            if not self.refusal_reason or not self.refusal_reason.strip():
                raise ValueError("refusal questions require refusal_reason")
        return self


class EvaluationRequirements(BaseModel):
    """Dataset-defined validation contract; no quota is hard-coded in the evaluator."""

    model_config = ConfigDict(extra="forbid")

    total_questions: int | None = Field(default=None, ge=1)
    answerable_questions: int | None = Field(default=None, ge=0)
    refusal_questions: int | None = Field(default=None, ge=0)
    min_answerable_by_language: dict[str, int] = Field(default_factory=dict)
    required_source_doc_ids: list[str] = Field(default_factory=list)

    @field_validator("min_answerable_by_language")
    @classmethod
    def validate_language_minima(cls, values: dict[str, int]) -> dict[str, int]:
        normalized = {key.strip(): value for key, value in values.items() if key.strip()}
        if any(value < 0 for value in normalized.values()):
            raise ValueError("language minimum counts cannot be negative")
        return normalized

    @field_validator("required_source_doc_ids")
    @classmethod
    def normalize_required_sources(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_totals(self) -> "EvaluationRequirements":
        if (
            self.total_questions is not None
            and self.answerable_questions is not None
            and self.refusal_questions is not None
            and self.answerable_questions + self.refusal_questions != self.total_questions
        ):
            raise ValueError("answerable_questions + refusal_questions must equal total_questions")
        return self


class EvaluationDataset(BaseModel):
    """A versioned, hardware-domain-neutral evaluation dataset."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1, 2]
    dataset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    description: str = Field(min_length=1)
    validation_requirements: EvaluationRequirements = Field(default_factory=EvaluationRequirements)
    questions: list[EvaluationQuestion] = Field(min_length=1)

    @model_validator(mode="before")
    @classmethod
    def populate_v1_requirements(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        payload = dict(value)
        if (
            payload.get("schema_version") == 1
            and payload.get("dataset_id") == "ddr_rag_v1"
        ):
            if "validation_requirements" not in payload:
                payload["validation_requirements"] = {
                    "total_questions": 40,
                    "answerable_questions": 30,
                    "refusal_questions": 10,
                    "min_answerable_by_language": {"zh-CN": 10, "en": 10},
                    "required_source_doc_ids": [
                        "ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2",
                        "TI_AM62X_AM62LX_DDR_LAYOUT_GUIDE_SPRAD06C",
                        "NXP_IMX8MP_HARDWARE_DEVELOPERS_GUIDE_REV1",
                    ],
                }
            questions = payload.get("questions")
            if isinstance(questions, list):
                payload["questions"] = [
                    (
                        {**question, "domains": ["memory"]}
                        if isinstance(question, dict) and "domains" not in question
                        else question
                    )
                    for question in questions
                ]
        return payload

    @model_validator(mode="after")
    def ensure_unique_question_ids(self) -> "EvaluationDataset":
        question_ids = [question.question_id for question in self.questions]
        duplicates = sorted({question_id for question_id in question_ids if question_ids.count(question_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate question_id values: {', '.join(duplicates)}")
        return self


def load_evaluation_dataset(path: Path) -> EvaluationDataset:
    """Load a UTF-8 YAML dataset without accessing models, indexes, or APIs."""

    if not path.is_file():
        raise EvaluationError(f"Evaluation dataset is missing: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("top-level YAML value must be a mapping")
        return EvaluationDataset.model_validate(payload)
    except Exception as exc:
        raise EvaluationError(f"Invalid evaluation dataset {path}: {exc}") from exc


def select_evaluation_questions(
    dataset: EvaluationDataset,
    question_ids: list[str] | None = None,
) -> EvaluationDataset:
    """Return an explicitly selected subset after the full dataset has been validated."""

    requested = [question_id.strip() for question_id in (question_ids or []) if question_id.strip()]
    if not requested:
        return dataset
    duplicates = sorted({question_id for question_id in requested if requested.count(question_id) > 1})
    if duplicates:
        raise EvaluationError("Repeated --question-id values: " + ", ".join(duplicates))
    by_id = {question.question_id: question for question in dataset.questions}
    missing = [question_id for question_id in requested if question_id not in by_id]
    if missing:
        raise EvaluationError("Unknown --question-id values: " + ", ".join(missing))
    return dataset.model_copy(update={"questions": [by_id[question_id] for question_id in requested]})


def validate_evaluation_dataset(
    dataset: EvaluationDataset,
    records: list[ChunkRecord],
) -> dict[str, object]:
    """Check the dataset-defined coverage contract and all local source anchors."""

    errors: list[str] = []
    answerable = [question for question in dataset.questions if question.answerable]
    refusals = [question for question in dataset.questions if not question.answerable]
    requirements = dataset.validation_requirements
    expected_counts = (
        ("answerable", requirements.answerable_questions, len(answerable)),
        ("refusal", requirements.refusal_questions, len(refusals)),
        ("total", requirements.total_questions, len(dataset.questions)),
    )
    for label, expected, actual in expected_counts:
        if expected is not None and actual != expected:
            errors.append(f"expected {expected} {label} questions, found {actual}")

    language_counts = Counter(question.language for question in answerable)
    for language, minimum in requirements.min_answerable_by_language.items():
        if language_counts[language] < minimum:
            errors.append(f"expected at least {minimum} answerable {language} questions")

    expected_doc_ids = set(requirements.required_source_doc_ids)
    source_doc_ids = {
        source.doc_id
        for question in answerable
        for source in question.expected_sources
    }
    missing_doc_ids = sorted(expected_doc_ids.difference(source_doc_ids))
    if missing_doc_ids:
        errors.append("missing answerable coverage for: " + ", ".join(missing_doc_ids))

    for question in answerable:
        for source in question.expected_sources:
            matches = [record for record in records if _matches_source(record, source)]
            if not matches:
                errors.append(
                    f"{question.question_id}: no Chunk matches {source.doc_id}, "
                    f"section containing {source.section_contains!r}, locator {source.locator_summary()}"
                )
                continue
            memory_matches = [record for record in matches if "memory" in record.domains]
            if question.memory_type and memory_matches and not any(
                question.memory_type in record.memory_types for record in memory_matches
            ):
                errors.append(
                    f"{question.question_id}: matching Chunk lacks memory type {question.memory_type}"
                )

    if errors:
        raise EvaluationError("Evaluation dataset validation failed:\n- " + "\n- ".join(errors))

    category_counts = Counter(question.category for question in dataset.questions)
    document_counts = Counter(
        source.doc_id for question in answerable for source in question.expected_sources
    )
    return {
        "dataset_id": dataset.dataset_id,
        "schema_version": dataset.schema_version,
        "validation_requirements": requirements.model_dump(mode="json"),
        "total_questions": len(dataset.questions),
        "answerable_questions": len(answerable),
        "refusal_questions": len(refusals),
        "answerable_language_counts": dict(sorted(language_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "expected_source_document_counts": dict(sorted(document_counts.items())),
    }


def _result_summary(result: SearchResult, rank: int) -> dict[str, object]:
    """Persist only traceability metadata, never full retrieved source text."""

    chunk = result.chunk
    return {
        "rank": rank,
        "chunk_id": chunk.chunk_id,
        "doc_id": chunk.doc_id,
        "section": chunk.section,
        "page_numbers": chunk.page_numbers,
        "source_location": (
            chunk.source_location.model_dump(mode="json") if chunk.source_location else None
        ),
        "domains": chunk.domains,
        "topics": chunk.topics,
        "memory_types": chunk.memory_types,
        "applicable_interfaces": chunk.applicable_interfaces,
        "score": result.score,
        "retrieval_sources": result.retrieval_sources,
    }


def evaluate_offline_results(
    dataset: EvaluationDataset,
    results_by_question: dict[str, list[SearchResult]],
    *,
    top_k: int,
    route_reports: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    """Score precomputed local retrieval rankings; this function has no model or API calls."""

    if top_k < 1:
        raise EvaluationError("top_k must be at least 1")

    question_reports: list[dict[str, object]] = []
    answerable_all_hit = 0
    answerable_any_hit = 0
    expected_anchor_total = 0
    expected_anchor_hit = 0
    refusal_no_result = 0
    clarification_questions = 0
    clarification_pass = 0
    single_source_questions = 0
    single_source_hit_at_5 = 0
    single_source_by_document: dict[str, dict[str, int]] = {}
    cross_domain_questions = 0
    cross_domain_covered = 0
    route_reports = route_reports or {}

    for question in dataset.questions:
        results = results_by_question.get(question.question_id, [])[:top_k]
        compact_results = [_result_summary(result, rank) for rank, result in enumerate(results, start=1)]
        base: dict[str, object] = {
            "question_id": question.question_id,
            "question": question.question,
            "language": question.language,
            "category": question.category,
            "domains": question.domains,
            "topics": question.topics,
            "applicable_interfaces": question.applicable_interfaces,
            "memory_type": question.memory_type,
            "expected_route_status": question.expected_route_status,
            "answerable": question.answerable,
            "top_k_results": compact_results,
        }
        route_report = route_reports.get(question.question_id)
        if route_report is not None:
            base["route"] = route_report
        if question.expected_route_status == "clarification_required":
            clarification_questions += 1
            actual_route_status = (
                str(route_report.get("status")) if route_report is not None else "not_recorded"
            )
            passed = actual_route_status == "clarification_required" and not results
            clarification_pass += int(passed)
            base.update(
                {
                    "offline_status": "route_pass" if passed else "route_miss",
                    "actual_route_status": actual_route_status,
                    "refusal_reason": question.refusal_reason,
                    "note": (
                        "The local router requested clarification and retrieval was not run."
                        if passed
                        else "The expected clarification route was not observed, or retrieval results were returned."
                    ),
                }
            )
            question_reports.append(base)
            continue
        if not question.answerable:
            no_result = not results
            if no_result:
                refusal_no_result += 1
            base.update(
                {
                    "offline_status": "no_results" if no_result else "manual_review_required",
                    "refusal_reason": question.refusal_reason,
                    "note": (
                        "No local candidate was returned. This is retrieval evidence only; "
                        "final refusal wording is evaluated later with the optional answer mode."
                        if no_result
                        else "Candidates were returned, but offline retrieval alone cannot decide "
                        "whether they support a final refusal."
                    ),
                }
            )
            question_reports.append(base)
            continue

        source_reports: list[dict[str, object]] = []
        for source in question.expected_sources:
            rank = next(
                (
                    result_rank
                    for result_rank, result in enumerate(results, start=1)
                    if _matches_source(result.chunk, source)
                ),
                None,
            )
            expected_anchor_total += 1
            if rank is not None:
                expected_anchor_hit += 1
            source_reports.append(
                {
                    "doc_id": source.doc_id,
                    "section_contains": source.section_contains,
                    **source.locator_summary(),
                    "rank": rank,
                }
            )
        all_hit = bool(source_reports) and all(item["rank"] is not None for item in source_reports)
        any_hit = any(item["rank"] is not None for item in source_reports)
        single_hit_at_5 = False
        if len(question.expected_sources) == 1:
            single_source_questions += 1
            source_rank = source_reports[0]["rank"]
            single_hit_at_5 = source_rank is not None and int(source_rank) <= min(5, top_k)
            single_source_hit_at_5 += int(single_hit_at_5)
            source_doc_id = question.expected_sources[0].doc_id
            document_summary = single_source_by_document.setdefault(
                source_doc_id,
                {"questions": 0, "hit_at_5": 0},
            )
            document_summary["questions"] += 1
            document_summary["hit_at_5"] += int(single_hit_at_5)
        retrieved_domains = sorted(
            {
                domain
                for result in results
                for domain in result.chunk.domains
            }
        )
        cross_domain_coverage = None
        if len(question.domains) > 1:
            cross_domain_questions += 1
            cross_domain_coverage = set(question.domains).issubset(retrieved_domains)
            cross_domain_covered += int(cross_domain_coverage)
        answerable_all_hit += int(all_hit)
        answerable_any_hit += int(any_hit)
        base.update(
            {
                "offline_status": "pass" if all_hit else "miss",
                "expected_sources": source_reports,
                "expected_key_facts": question.expected_key_facts,
                "all_expected_sources_in_top_k": all_hit,
                "any_expected_source_in_top_k": any_hit,
                "single_source_hit_at_5": single_hit_at_5 if len(question.expected_sources) == 1 else None,
                "retrieved_domains": retrieved_domains,
                "all_expected_domains_in_top_k": cross_domain_coverage,
            }
        )
        question_reports.append(base)

    answerable_count = sum(question.answerable for question in dataset.questions)
    refusal_count = len(dataset.questions) - answerable_count
    retrieval_refusal_count = refusal_count - clarification_questions
    return {
        "evaluation_mode": "offline_retrieval_only",
        "answer_model_called": False,
        "dataset_id": dataset.dataset_id,
        "dataset_schema_version": dataset.schema_version,
        "validation_requirements": dataset.validation_requirements.model_dump(mode="json"),
        "top_k": top_k,
        "summary": {
            "total_questions": len(dataset.questions),
            "answerable_questions": answerable_count,
            "answerable_all_anchors_hit": answerable_all_hit,
            "answerable_all_anchors_hit_rate": answerable_all_hit / answerable_count if answerable_count else 1.0,
            "answerable_any_anchor_hit": answerable_any_hit,
            "answerable_any_anchor_hit_rate": answerable_any_hit / answerable_count if answerable_count else 1.0,
            "expected_anchor_total": expected_anchor_total,
            "expected_anchor_hit": expected_anchor_hit,
            "expected_anchor_recall_at_k": expected_anchor_hit / expected_anchor_total if expected_anchor_total else 1.0,
            "refusal_questions": refusal_count,
            "retrieval_refusal_questions": retrieval_refusal_count,
            "refusal_no_result": refusal_no_result,
            "refusal_manual_review_required": retrieval_refusal_count - refusal_no_result,
            "clarification_questions": clarification_questions,
            "clarification_pass": clarification_pass,
            "clarification_rate": (
                clarification_pass / clarification_questions if clarification_questions else 1.0
            ),
            "single_source_questions": single_source_questions,
            "single_source_hit_at_5": single_source_hit_at_5,
            "single_source_hit_rate_at_5": (
                single_source_hit_at_5 / single_source_questions if single_source_questions else 1.0
            ),
            "single_source_by_document": dict(sorted(single_source_by_document.items())),
            "cross_domain_questions": cross_domain_questions,
            "cross_domain_covered": cross_domain_covered,
            "cross_domain_coverage_rate_at_k": (
                cross_domain_covered / cross_domain_questions if cross_domain_questions else 1.0
            ),
        },
        "questions": question_reports,
    }


def retrieve_evaluation_results(
    settings: Any,
    dataset: EvaluationDataset,
    *,
    top_k: int = 5,
) -> dict[str, list[SearchResult]]:
    """Run the routed local Dense/BM25 path for every evaluation question once."""

    results, route_reports = retrieve_evaluation_results_with_routes(
        settings,
        dataset,
        top_k=top_k,
    )
    unexpected_clarifications = [
        question.question_id
        for question in dataset.questions
        if question.expected_route_status == "resolved"
        and route_reports[question.question_id]["status"] != "resolved"
    ]
    if unexpected_clarifications:
        raise EvaluationError(
            "Questions unexpectedly require routing clarification: "
            + ", ".join(unexpected_clarifications)
        )
    return results


def retrieve_evaluation_results_with_routes(
    settings: Any,
    dataset: EvaluationDataset,
    *,
    top_k: int = 5,
) -> tuple[dict[str, list[SearchResult]], dict[str, dict[str, object]]]:
    """Route every question and retrieve only questions whose local scope is resolved."""

    if top_k < 1:
        raise EvaluationError("top_k must be at least 1")
    try:
        from ddr_rag.embedder import _encode_texts
        from ddr_rag.query_scope import QueryScopeError, enrich_query, resolve_query_scope
        from ddr_rag.retriever import RetrievalError, retrieve_with_vector
        from ddr_rag.vector_store import VectorStoreError, validate_local_index

        validate_local_index(settings)
        routed_questions = []
        route_reports: dict[str, dict[str, object]] = {}
        for question in dataset.questions:
            scope = resolve_query_scope(
                settings,
                question.question,
                explicit_domains=question.domains,
                explicit_topics=question.topics,
                explicit_interfaces=question.applicable_interfaces,
                memory_type=question.memory_type,
                active_only=True,
            )
            route_reports[question.question_id] = scope.model_dump(mode="json")
            if scope.status == "resolved":
                routed_questions.append((question, scope))

        enriched_questions = [
            enrich_query(question.question) for question, _scope in routed_questions
        ]
        vectors = _encode_texts(settings, enriched_questions) if enriched_questions else []
        if len(vectors) != len(routed_questions):
            raise EvaluationError("BGE-M3 returned a vector count different from the question count")
        results_by_question: dict[str, list[SearchResult]] = {
            question.question_id: [] for question in dataset.questions
        }
        for (question, scope), vector in zip(routed_questions, vectors, strict=True):
            results_by_question[question.question_id] = retrieve_with_vector(
                settings,
                question.question,
                vector,
                scope=scope,
                mode="hybrid",
                limit=top_k,
            )
    except (EvaluationError, QueryScopeError, RetrievalError, VectorStoreError) as exc:
        raise EvaluationError(str(exc)) from exc
    except Exception as exc:
        raise EvaluationError(f"Offline retrieval evaluation failed: {type(exc).__name__}: {exc}") from exc
    return results_by_question, route_reports


def run_offline_evaluation(
    settings: Any,
    dataset: EvaluationDataset,
    *,
    top_k: int = 5,
) -> dict[str, object]:
    """Retrieve and score local evidence without calling an answer model or API."""

    results, route_reports = retrieve_evaluation_results_with_routes(
        settings,
        dataset,
        top_k=top_k,
    )
    return evaluate_offline_results(
        dataset,
        results,
        top_k=top_k,
        route_reports=route_reports,
    )


def _citation_matches_source(citation: Citation, source: ExpectedSource) -> bool:
    if citation.doc_id != source.doc_id:
        return False
    if _normalized_section(source.section_contains) not in _normalized_section(citation.section):
        return False
    if source.page_numbers:
        return bool(set(source.page_numbers).intersection(citation.page_numbers))
    location = citation.source_location
    if location is None:
        return False
    if source.slide_numbers:
        return bool(set(source.slide_numbers).intersection(location.slide_numbers))
    return bool(set(source.element_refs).intersection(location.element_refs))


def evaluate_answer_results(
    dataset: EvaluationDataset,
    answers_by_question: dict[str, AnswerResult],
    errors_by_question: dict[str, str],
    *,
    top_k: int,
    api_attempted_question_ids: set[str] | None = None,
    api_request_counts: dict[str, int] | None = None,
) -> dict[str, object]:
    """Score verified answers and strict refusals without making additional model calls."""

    from ddr_rag.answerer import is_refusal_answer

    attempted = api_attempted_question_ids or set()
    request_counts = api_request_counts or {}
    question_reports: list[dict[str, object]] = []
    answerable_pass = 0
    refusal_pass = 0
    verified_citation_questions = 0
    for question in dataset.questions:
        answer = answers_by_question.get(question.question_id)
        error = errors_by_question.get(question.question_id)
        base: dict[str, object] = {
            "question_id": question.question_id,
            "question": question.question,
            "language": question.language,
            "category": question.category,
            "domains": question.domains,
            "topics": question.topics,
            "applicable_interfaces": question.applicable_interfaces,
            "memory_type": question.memory_type,
            "answerable": question.answerable,
            "api_call_attempted": question.question_id in attempted,
            "api_request_count": request_counts.get(
                question.question_id,
                answer.generation_attempts if answer is not None else 0,
            ),
            "error": error,
        }
        if answer is None:
            base.update(
                {
                    "answer_status": "error",
                    "generated_answer": None,
                    "citations": [],
                    "pass": False,
                    "failure_reason": error or "No answer result was produced.",
                }
            )
            question_reports.append(base)
            continue

        refused = is_refusal_answer(answer.answer)
        citations = [citation.model_dump(mode="json") for citation in answer.citations]
        if answer.citations:
            verified_citation_questions += 1
        base.update(
            {
                "generated_answer": answer.answer,
                "citations": citations,
                "refused": refused,
            }
        )
        if not question.answerable:
            passed = refused
            refusal_pass += int(passed)
            base.update(
                {
                    "answer_status": "pass" if passed else "fail",
                    "pass": passed,
                    "expected_refusal_reason": question.refusal_reason,
                    "failure_reason": None if passed else "The answer did not start with the strict no-knowledge refusal.",
                }
            )
            question_reports.append(base)
            continue

        source_reports: list[dict[str, object]] = []
        for source in question.expected_sources:
            matching_ids = [
                citation.citation_id
                for citation in answer.citations
                if _citation_matches_source(citation, source)
            ]
            source_reports.append(
                {
                    "doc_id": source.doc_id,
                    "section_contains": source.section_contains,
                    **source.locator_summary(),
                    "matching_citation_ids": matching_ids,
                    "cited": bool(matching_ids),
                }
            )
        all_sources_cited = bool(source_reports) and all(item["cited"] for item in source_reports)
        passed = not refused and bool(answer.citations) and all_sources_cited
        answerable_pass += int(passed)
        if refused:
            failure_reason = "The model refused an answerable question."
        elif not answer.citations:
            failure_reason = "The answer contained no verified citations."
        elif not all_sources_cited:
            failure_reason = "The answer did not cite every expected source anchor."
        else:
            failure_reason = None
        base.update(
            {
                "answer_status": "pass" if passed else "fail",
                "pass": passed,
                "expected_sources": source_reports,
                "all_expected_sources_cited": all_sources_cited,
                "expected_key_facts": question.expected_key_facts,
                "semantic_fact_review": "manual_review_required",
                "failure_reason": failure_reason,
            }
        )
        question_reports.append(base)

    answerable_count = sum(question.answerable for question in dataset.questions)
    refusal_count = len(dataset.questions) - answerable_count
    return {
        "evaluation_mode": "deepseek_answer_evaluation",
        "answer_model_called": bool(attempted),
        "dataset_id": dataset.dataset_id,
        "dataset_schema_version": dataset.schema_version,
        "validation_requirements": dataset.validation_requirements.model_dump(mode="json"),
        "top_k": top_k,
        "summary": {
            "total_questions": len(dataset.questions),
            "api_calls_attempted": len(attempted),
            "answerable_questions": answerable_count,
            "answerable_grounded_source_pass": answerable_pass,
            "answerable_grounded_source_pass_rate": answerable_pass / answerable_count if answerable_count else 1.0,
            "refusal_questions": refusal_count,
            "refusal_pass": refusal_pass,
            "refusal_pass_rate": refusal_pass / refusal_count if refusal_count else 1.0,
            "verified_citation_questions": verified_citation_questions,
            "question_errors": len(errors_by_question),
            "api_requests_attempted": sum(
                request_counts.get(
                    question.question_id,
                    answers_by_question[question.question_id].generation_attempts
                    if question.question_id in answers_by_question else 0,
                )
                for question in dataset.questions
            ),
        },
        "scoring_note": (
            "Pass/fail checks strict refusal behavior and verified citations to every expected source. "
            "Expected key facts are included beside each answer for human semantic review; they are not leaked to the answer model."
        ),
        "questions": question_reports,
    }


def run_answer_evaluation(
    settings: Any,
    dataset: EvaluationDataset,
    results_by_question: dict[str, list[SearchResult]],
    *,
    top_k: int = 5,
    progress: Callable[[int, int, str, str], None] | None = None,
) -> dict[str, object]:
    """Call DeepSeek once per question with evidence and continue after per-question failures."""

    from ddr_rag.answerer import answer_from_results

    if not settings.generation.enabled or settings.generation.provider != "deepseek":
        raise EvaluationError("DeepSeek generation must be enabled for answer evaluation.")
    if not os.getenv(settings.generation.api_key_env, "").strip():
        raise EvaluationError(
            f"{settings.generation.api_key_env} is missing; answer evaluation was not started."
        )
    answers: dict[str, AnswerResult] = {}
    errors: dict[str, str] = {}
    attempted: set[str] = set()
    request_counts: dict[str, int] = {}
    evidence_limit = min(top_k, settings.generation.max_evidence_chunks)
    total = len(dataset.questions)
    for index, question in enumerate(dataset.questions, start=1):
        results = results_by_question.get(question.question_id, [])[:evidence_limit]
        if results:
            attempted.add(question.question_id)
        try:
            answers[question.question_id] = answer_from_results(settings, question.question, results)
            request_counts[question.question_id] = answers[question.question_id].generation_attempts
            status = "answered" if answers[question.question_id].citations else "refused"
        except Exception as exc:
            errors[question.question_id] = f"{type(exc).__name__}: {exc}"
            request_counts[question.question_id] = int(getattr(exc, "generation_attempts", 0))
            status = "error"
        if progress is not None:
            progress(index, total, question.question_id, status)
    return evaluate_answer_results(
        dataset,
        answers,
        errors,
        top_k=evidence_limit,
        api_attempted_question_ids=attempted,
        api_request_counts=request_counts,
    )


def regrade_answer_report(
    dataset: EvaluationDataset,
    prior_report: dict[str, object],
) -> dict[str, object]:
    """Reapply deterministic scoring to saved answers without another API call."""

    if prior_report.get("dataset_id") != dataset.dataset_id:
        raise EvaluationError("Saved answer report belongs to a different evaluation dataset.")
    raw_questions = prior_report.get("questions")
    if not isinstance(raw_questions, list):
        raise EvaluationError("Saved answer report has no question results.")
    answers: dict[str, AnswerResult] = {}
    errors: dict[str, str] = {}
    attempted: set[str] = set()
    request_counts: dict[str, int] = {}
    seen: set[str] = set()
    for raw in raw_questions:
        if not isinstance(raw, dict) or not isinstance(raw.get("question_id"), str):
            raise EvaluationError("Saved answer report contains an invalid question result.")
        question_id = raw["question_id"]
        if question_id in seen:
            raise EvaluationError(f"Saved answer report repeats question {question_id}.")
        seen.add(question_id)
        if raw.get("api_call_attempted"):
            attempted.add(question_id)
        request_counts[question_id] = int(raw.get("api_request_count", 0))
        generated_answer = raw.get("generated_answer")
        if isinstance(generated_answer, str) and generated_answer.strip():
            citations = [Citation.model_validate(item) for item in raw.get("citations", [])]
            answers[question_id] = AnswerResult(
                answer=generated_answer,
                citations=citations,
                retrieved=[],
                generation_attempts=int(raw.get("api_request_count", 0)),
            )
        else:
            errors[question_id] = str(raw.get("error") or "No answer result was produced.")
    expected_ids = {question.question_id for question in dataset.questions}
    if seen != expected_ids:
        missing = sorted(expected_ids.difference(seen))
        extra = sorted(seen.difference(expected_ids))
        raise EvaluationError(f"Saved answer report question mismatch; missing={missing}, extra={extra}")
    return evaluate_answer_results(
        dataset,
        answers,
        errors,
        top_k=int(prior_report.get("top_k", 5)),
        api_attempted_question_ids=attempted,
        api_request_counts=request_counts,
    )


def _atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _report_citation_location(citation: dict[str, Any]) -> str:
    location = citation.get("source_location") or {}
    kind = location.get("kind")
    if kind == "pdf_pages":
        return "PDF pages " + ", ".join(str(value) for value in location.get("page_numbers", []))
    if kind == "pptx_slides":
        return "PowerPoint slides " + ", ".join(
            str(value) for value in location.get("slide_numbers", [])
        )
    if kind == "docx_elements":
        return "Word elements " + ", ".join(location.get("element_refs", []))
    return "source location unavailable"


def write_offline_evaluation_report(report: dict[str, object], output_dir: Path) -> dict[str, Path]:
    """Write timestamped JSON and Markdown reports without overwriting prior runs."""

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    prefix = f"{report['dataset_id']}_offline_{timestamp}"
    json_path = output_dir / f"{prefix}.json"
    markdown_path = output_dir / f"{prefix}.md"
    summary = report["summary"]
    assert isinstance(summary, dict)
    question_reports = report["questions"]
    assert isinstance(question_reports, list)
    misses = [
        question for question in question_reports
        if question["answerable"] and question["offline_status"] == "miss"
    ]
    refusal_diagnostics = [
        question for question in question_reports
        if not question["answerable"]
        and question["expected_route_status"] == "resolved"
    ]
    clarification_diagnostics = [
        question for question in question_reports
        if question["expected_route_status"] == "clarification_required"
    ]
    markdown_lines = [
        f"# Hardware RAG offline retrieval evaluation: {report['dataset_id']}",
        "",
        "- Answer model: not called",
        f"- Top-K: {report['top_k']}",
        "- Answerable all-anchor hit rate: " + (
            "N/A (0/0)" if not summary["answerable_questions"] else
            f"{summary['answerable_all_anchors_hit_rate']:.1%} "
            f"({summary['answerable_all_anchors_hit']}/{summary['answerable_questions']})"
        ),
        "- Expected-anchor recall@K: " + (
            "N/A (0/0)" if not summary["expected_anchor_total"] else
            f"{summary['expected_anchor_recall_at_k']:.1%} "
            f"({summary['expected_anchor_hit']}/{summary['expected_anchor_total']})"
        ),
        "- Retrieval-insufficiency questions with no results: "
        f"{summary['refusal_no_result']}/{summary['retrieval_refusal_questions']}",
        "- Clarification routing pass: "
        f"{summary['clarification_rate']:.1%} "
        f"({summary['clarification_pass']}/{summary['clarification_questions']})",
        "- Single-source anchor hit@5: "
        f"{summary['single_source_hit_rate_at_5']:.1%} "
        f"({summary['single_source_hit_at_5']}/{summary['single_source_questions']})",
        "- Cross-domain scope coverage@K: "
        f"{summary['cross_domain_coverage_rate_at_k']:.1%} "
        f"({summary['cross_domain_covered']}/{summary['cross_domain_questions']})",
        "",
        "## Answerable misses",
    ]
    if misses:
        markdown_lines.extend(
            f"- `{question['question_id']}`: {question['question']}" for question in misses
        )
    else:
        markdown_lines.append("- None")
    markdown_lines.extend(("", "## Refusal retrieval diagnostics"))
    markdown_lines.extend(
        f"- `{question['question_id']}`: {question['offline_status']}"
        for question in refusal_diagnostics
    )
    markdown_lines.extend(("", "## Clarification routing diagnostics"))
    if clarification_diagnostics:
        markdown_lines.extend(
            f"- `{question['question_id']}`: {question['offline_status']}"
            for question in clarification_diagnostics
        )
    else:
        markdown_lines.append("- None")
    _atomic_write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _atomic_write_text(markdown_path, "\n".join(markdown_lines) + "\n")
    return {"json": json_path, "markdown": markdown_path}


def write_answer_evaluation_report(report: dict[str, object], output_dir: Path) -> dict[str, Path]:
    """Write answer-evaluation results without source Chunk text or credentials."""

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    prefix = f"{report['dataset_id']}_answers_{timestamp}"
    json_path = output_dir / f"{prefix}.json"
    markdown_path = output_dir / f"{prefix}.md"
    summary = report["summary"]
    assert isinstance(summary, dict)
    questions = report["questions"]
    assert isinstance(questions, list)
    failures = [question for question in questions if not question["pass"]]
    lines = [
        f"# Hardware RAG answer evaluation: {report['dataset_id']}",
        "",
        "- Answer model: DeepSeek called only for questions with retrieved evidence",
        f"- Top-K evidence: {report['top_k']}",
        f"- API calls attempted: {summary['api_calls_attempted']}",
        f"- API requests attempted: {summary['api_requests_attempted']}",
        "- Answerable grounded-source pass: " + (
            "N/A (0/0)" if not summary["answerable_questions"] else
            f"{summary['answerable_grounded_source_pass_rate']:.1%} "
            f"({summary['answerable_grounded_source_pass']}/{summary['answerable_questions']})"
        ),
        "- Refusal pass: " + (
            "N/A (0/0)" if not summary["refusal_questions"] else
            f"{summary['refusal_pass_rate']:.1%} "
            f"({summary['refusal_pass']}/{summary['refusal_questions']})"
        ),
        f"- Per-question errors: {summary['question_errors']}",
        "- Semantic fact check: manual review; expected facts were not sent to the answer model",
        "",
        "## Automatic failures",
    ]
    if failures:
        lines.extend(
            f"- `{question['question_id']}`: {question.get('failure_reason') or question.get('error')}"
            for question in failures
        )
    else:
        lines.append("- None")
    lines.extend(("", "## Per-question answers"))
    for question in questions:
        lines.extend(
            (
                "",
                f"### {question['question_id']} — {question['answer_status']}",
                "",
                f"Question: {question['question']}",
                "",
            )
        )
        answer = question.get("generated_answer")
        if answer:
            lines.extend(f"> {line}" if line else ">" for line in str(answer).splitlines())
        else:
            lines.append(f"> ERROR: {question.get('error') or 'No answer produced.'}")
        citations = question.get("citations") or []
        if citations:
            lines.extend(("", "Citations:"))
            for citation in citations:
                lines.append(
                    f"- [{citation['citation_id']}] `{citation['doc_id']}` — "
                    f"{citation['section']}, {_report_citation_location(citation)}"
                )
        expected_facts = question.get("expected_key_facts") or []
        if expected_facts:
            lines.extend(("", "Expected facts for human review:"))
            lines.extend(f"- {fact}" for fact in expected_facts)
    _atomic_write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _atomic_write_text(markdown_path, "\n".join(lines) + "\n")
    return {"json": json_path, "markdown": markdown_path}
