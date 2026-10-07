"""Shared data models for the versioned hardware RAG knowledge bases."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from ddr_rag.taxonomy import (
    normalize_domains,
    normalize_interfaces,
    normalize_memory_types,
    normalize_topics,
    topics_for_memory_types,
    validate_domain_topic_relationship,
)


def _populate_legacy_memory_classification(value: Any) -> Any:
    """Read unchanged V1.2 DDR records without weakening V2 non-memory validation."""

    if not isinstance(value, dict):
        return value
    payload = dict(value)
    memory_types = payload.get("memory_types") or []
    if memory_types and "domains" not in payload:
        payload["domains"] = ["memory"]
    if memory_types and "topics" not in payload:
        payload["topics"] = topics_for_memory_types(memory_types)
    return payload


def _populate_legacy_citation_classification(value: Any) -> Any:
    """Keep saved V1/V1.2 answer reports locally regradable."""

    if not isinstance(value, dict):
        return value
    payload = dict(value)
    if "domains" not in payload:
        payload["domains"] = ["memory"]
    if "topics" not in payload:
        payload["topics"] = ["ddr_design"]
    return payload


class DocumentRecord(BaseModel):
    """A source document registered in the knowledge-base catalog."""

    model_config = ConfigDict(extra="forbid")
    doc_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    title: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    vendor: str = Field(min_length=1)
    file: Path
    document_type: Literal[
        "standard", "datasheet", "hardware_design_guide", "application_note",
        "company_spec", "fab_capability", "engineering_experience",
        "approved_experience", "technical_whitepaper", "training_material", "other",
    ]
    source_format: Literal["pdf", "docx", "pptx"] | None = None
    language: str = "en"
    domains: list[str] = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    memory_types: list[str] = Field(default_factory=list)
    applicable_interfaces: list[str] = Field(default_factory=list)
    applicable_parts: list[str] = Field(default_factory=list)
    authority: Literal[
        "standard", "vendor_datasheet", "vendor_design_guide", "company_spec",
        "fab_capability", "approved_experience", "unverified_note",
    ]
    authority_score: int = Field(ge=0, le=100)
    status: Literal["active", "superseded", "draft", "archived"] = "active"
    published_date: date | None = None
    confidentiality: Literal["public", "internal", "confidential", "restricted"] = "public"
    source_url: HttpUrl | None = None
    source_access: Literal["official", "official_community", "public_mirror", "local"] = "local"
    supersedes: str | None = None
    notes: str | None = None
    file_hash: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_memory_classification(cls, value: Any) -> Any:
        return _populate_legacy_memory_classification(value)

    @model_validator(mode="after")
    def validate_source_format(self) -> "DocumentRecord":
        suffix = self.file.suffix.lower().lstrip(".")
        if suffix not in {"pdf", "docx", "pptx"}:
            raise ValueError("file must use one of the supported formats: .pdf, .docx, .pptx")
        if self.source_format is not None and self.source_format != suffix:
            raise ValueError("source_format must match the source file extension")
        self.source_format = suffix
        return self

    @field_validator("domains")
    @classmethod
    def normalize_document_domains(cls, values: list[str]) -> list[str]:
        return normalize_domains(values)

    @field_validator("topics")
    @classmethod
    def normalize_document_topics(cls, values: list[str]) -> list[str]:
        return normalize_topics(values)

    @field_validator("memory_types")
    @classmethod
    def normalize_memory_types(cls, values: list[str]) -> list[str]:
        return normalize_memory_types(values)

    @field_validator("applicable_interfaces")
    @classmethod
    def normalize_document_interfaces(cls, values: list[str]) -> list[str]:
        return normalize_interfaces(values)

    @field_validator("applicable_parts")
    @classmethod
    def normalize_parts(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @field_validator("file_hash")
    @classmethod
    def validate_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower().strip()
        if len(normalized) != 64 or any(char not in "0123456789abcdef" for char in normalized):
            raise ValueError("file_hash must be a 64-character SHA-256 hexadecimal value")
        return normalized

    @model_validator(mode="after")
    def validate_document_classification(self) -> "DocumentRecord":
        validate_domain_topic_relationship(self.domains, self.topics)
        if self.memory_types and "memory" not in self.domains:
            raise ValueError("memory_types may only be set when domains includes memory")
        return self


class DocumentCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: list[DocumentRecord] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_unique_ids(self) -> "DocumentCatalog":
        ids = [document.doc_id for document in self.documents]
        duplicates = sorted({doc_id for doc_id in ids if ids.count(doc_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate doc_id values: {', '.join(duplicates)}")
        return self


class SourceLocation(BaseModel):
    """Format-aware location that can be checked against the original source."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["pdf_pages", "pptx_slides", "docx_elements"]
    page_numbers: list[int] = Field(default_factory=list)
    slide_numbers: list[int] = Field(default_factory=list)
    element_refs: list[str] = Field(default_factory=list)
    excerpt: str | None = None

    @field_validator("page_numbers", "slide_numbers")
    @classmethod
    def normalize_positive_numbers(cls, values: list[int]) -> list[int]:
        normalized = sorted(set(values))
        if any(value < 1 for value in normalized):
            raise ValueError("source location numbers must be positive")
        return normalized

    @field_validator("element_refs")
    @classmethod
    def normalize_element_refs(cls, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value.strip() for value in values if value.strip()))

    @model_validator(mode="after")
    def validate_kind_fields(self) -> "SourceLocation":
        if self.kind == "pdf_pages" and not self.page_numbers:
            raise ValueError("pdf_pages source locations require page_numbers")
        if self.kind == "pptx_slides" and not self.slide_numbers:
            raise ValueError("pptx_slides source locations require slide_numbers")
        if self.kind == "docx_elements" and (not self.element_refs or not (self.excerpt or "").strip()):
            raise ValueError("docx_elements source locations require element_refs and excerpt")
        return self


class ChunkRecord(BaseModel):
    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    title: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    source_path: Path
    section: str = Field(min_length=1)
    document_type: str = "other"
    authority: str = "unverified_note"
    source_format: Literal["pdf", "docx", "pptx"] = "pdf"
    domains: list[str] = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    applicable_interfaces: list[str] = Field(default_factory=list)
    applicable_parts: list[str] = Field(default_factory=list)
    source_file_hash: str | None = None
    parser_version: str | None = None
    source_location: SourceLocation | None = None
    page_numbers: list[int] = Field(default_factory=list)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    memory_types: list[str] = Field(default_factory=list)
    status: str = Field(min_length=1)
    token_count: int = Field(ge=1)

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_memory_classification(cls, value: Any) -> Any:
        return _populate_legacy_memory_classification(value)

    @field_validator("domains")
    @classmethod
    def normalize_chunk_domains(cls, values: list[str]) -> list[str]:
        return normalize_domains(values)

    @field_validator("topics")
    @classmethod
    def normalize_chunk_topics(cls, values: list[str]) -> list[str]:
        return normalize_topics(values)

    @field_validator("memory_types")
    @classmethod
    def normalize_chunk_memory_types(cls, values: list[str]) -> list[str]:
        return normalize_memory_types(values)

    @field_validator("applicable_interfaces")
    @classmethod
    def normalize_chunk_interfaces(cls, values: list[str]) -> list[str]:
        return normalize_interfaces(values)

    @field_validator("page_numbers")
    @classmethod
    def normalize_page_numbers(cls, values: list[int]) -> list[int]:
        normalized = sorted(set(values))
        if any(page < 1 for page in normalized):
            raise ValueError("page_numbers must contain only positive page numbers")
        return normalized

    @model_validator(mode="after")
    def validate_page_range(self) -> "ChunkRecord":
        if self.source_format == "pdf":
            if not self.page_numbers or self.page_start is None or self.page_end is None:
                raise ValueError("PDF chunks require page_numbers, page_start, and page_end")
            if self.page_start > self.page_end:
                raise ValueError("page_start cannot exceed page_end")
            if self.page_start != self.page_numbers[0] or self.page_end != self.page_numbers[-1]:
                raise ValueError("page range must match page_numbers")
            if self.source_location is None:
                self.source_location = SourceLocation(kind="pdf_pages", page_numbers=self.page_numbers)
        else:
            if self.page_numbers or self.page_start is not None or self.page_end is not None:
                raise ValueError("non-PDF chunks must not contain PDF page fields")
            expected_kind = "docx_elements" if self.source_format == "docx" else "pptx_slides"
            if self.source_location is None or self.source_location.kind != expected_kind:
                raise ValueError(f"{self.source_format.upper()} chunks require a {expected_kind} source location")
        return self

    @model_validator(mode="after")
    def validate_chunk_classification(self) -> "ChunkRecord":
        validate_domain_topic_relationship(self.domains, self.topics)
        if self.memory_types and "memory" not in self.domains:
            raise ValueError("memory_types may only be set when domains includes memory")
        return self


class Citation(BaseModel):
    """A stable, verifiable reference to one retrieved source chunk."""

    model_config = ConfigDict(extra="forbid")
    citation_id: str = Field(pattern=r"^C[1-9][0-9]*$")
    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    source_path: Path
    section: str = Field(min_length=1)
    document_type: str = "other"
    authority: str = "unverified_note"
    source_format: Literal["pdf", "docx", "pptx"] = "pdf"
    domains: list[str] = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    memory_types: list[str] = Field(default_factory=list)
    applicable_interfaces: list[str] = Field(default_factory=list)
    applicable_parts: list[str] = Field(default_factory=list)
    source_file_hash: str | None = None
    parser_version: str | None = None
    source_location: SourceLocation | None = None
    page_numbers: list[int] = Field(default_factory=list)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_classification(cls, value: Any) -> Any:
        return _populate_legacy_citation_classification(value)

    @field_validator("domains")
    @classmethod
    def normalize_citation_domains(cls, values: list[str]) -> list[str]:
        return normalize_domains(values)

    @field_validator("topics")
    @classmethod
    def normalize_citation_topics(cls, values: list[str]) -> list[str]:
        return normalize_topics(values)

    @field_validator("memory_types")
    @classmethod
    def normalize_citation_memory_types(cls, values: list[str]) -> list[str]:
        return normalize_memory_types(values)

    @field_validator("applicable_interfaces")
    @classmethod
    def normalize_citation_interfaces(cls, values: list[str]) -> list[str]:
        return normalize_interfaces(values)

    @field_validator("page_numbers")
    @classmethod
    def normalize_citation_pages(cls, values: list[int]) -> list[int]:
        normalized = sorted(set(values))
        if any(page < 1 for page in normalized):
            raise ValueError("page_numbers must contain only positive page numbers")
        return normalized

    @model_validator(mode="after")
    def validate_citation_page_range(self) -> "Citation":
        if self.source_format == "pdf":
            if not self.page_numbers or self.page_start is None or self.page_end is None:
                raise ValueError("PDF citations require page_numbers, page_start, and page_end")
            if self.page_start > self.page_end:
                raise ValueError("page_start cannot exceed page_end")
            if self.page_start != self.page_numbers[0] or self.page_end != self.page_numbers[-1]:
                raise ValueError("page range must match page_numbers")
            if self.source_location is None:
                self.source_location = SourceLocation(kind="pdf_pages", page_numbers=self.page_numbers)
        else:
            if self.page_numbers or self.page_start is not None or self.page_end is not None:
                raise ValueError("non-PDF citations must not contain PDF page fields")
            expected_kind = "docx_elements" if self.source_format == "docx" else "pptx_slides"
            if self.source_location is None or self.source_location.kind != expected_kind:
                raise ValueError(f"{self.source_format.upper()} citations require a {expected_kind} source location")
        return self

    @model_validator(mode="after")
    def validate_citation_classification(self) -> "Citation":
        validate_domain_topic_relationship(self.domains, self.topics)
        if self.memory_types and "memory" not in self.domains:
            raise ValueError("memory_types may only be set when domains includes memory")
        return self


class SearchResult(BaseModel):
    chunk: ChunkRecord
    score: float
    retrieval_sources: list[Literal["dense", "sparse"]] = Field(default_factory=list)


class AnswerResult(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    retrieved: list[SearchResult] = Field(default_factory=list)
    generation_attempts: int = Field(default=0, ge=0, le=2)


class ValidationIssue(BaseModel):
    level: Literal["error", "warning"]
    code: str
    message: str
    doc_id: str | None = None


class CatalogValidationReport(BaseModel):
    total_documents: int = 0
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(issue.level == "error" for issue in self.issues)

    @property
    def warning_count(self) -> int:
        return sum(issue.level == "warning" for issue in self.issues)

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0
