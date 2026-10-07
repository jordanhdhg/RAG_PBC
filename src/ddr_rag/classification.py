"""Versioned document/section classification mappings for hardware V2 chunks."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ddr_rag.schemas import DocumentRecord
from ddr_rag.taxonomy import TAXONOMY_VERSION, validate_classification


class ClassificationError(RuntimeError):
    """Raised when a classification mapping is invalid or ambiguous."""


class ClassificationAssignment(BaseModel):
    """One complete, controlled classification attached to a document or chunk."""

    model_config = ConfigDict(extra="forbid")

    domains: list[str] = Field(min_length=1)
    topics: list[str] = Field(min_length=1)
    memory_types: list[str] = Field(default_factory=list)
    applicable_interfaces: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_controlled_values(self) -> "ClassificationAssignment":
        domains, topics, memory_types, interfaces = validate_classification(
            domains=self.domains,
            topics=self.topics,
            memory_types=self.memory_types,
            applicable_interfaces=self.applicable_interfaces,
        )
        self.domains = domains
        self.topics = topics
        self.memory_types = memory_types
        self.applicable_interfaces = interfaces
        return self


class SectionMatcher(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["exact", "prefix", "contains", "regex"]
    pattern: str = Field(min_length=1)
    case_sensitive: bool = False

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, value: str) -> str:
        pattern = value.strip()
        if not pattern:
            raise ValueError("section match pattern cannot be empty")
        return pattern

    @model_validator(mode="after")
    def validate_regex(self) -> "SectionMatcher":
        if self.kind == "regex":
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError(f"invalid section regex: {exc}") from exc
        return self

    def matches(self, section: str) -> bool:
        if self.kind == "regex":
            flags = 0 if self.case_sensitive else re.IGNORECASE
            return re.search(self.pattern, section, flags=flags) is not None
        candidate = section if self.case_sensitive else section.casefold()
        pattern = self.pattern if self.case_sensitive else self.pattern.casefold()
        if self.kind == "exact":
            return candidate == pattern
        if self.kind == "prefix":
            return candidate.startswith(pattern)
        return pattern in candidate


class SectionClassificationRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    priority: int = Field(default=0, ge=0, le=1000)
    match: SectionMatcher
    classification: ClassificationAssignment


class DocumentClassificationMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    default: ClassificationAssignment | None = None
    section_overrides: list[SectionClassificationRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_unique_rule_ids(self) -> "DocumentClassificationMap":
        rule_ids = [rule.rule_id for rule in self.section_overrides]
        duplicates = sorted({rule_id for rule_id in rule_ids if rule_ids.count(rule_id) > 1})
        if duplicates:
            raise ValueError("duplicate classification rule_id values: " + ", ".join(duplicates))
        return self


class ClassificationMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    mapping_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    taxonomy_version: Literal[TAXONOMY_VERSION]
    documents: list[DocumentClassificationMap] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_unique_document_ids(self) -> "ClassificationMap":
        doc_ids = [document.doc_id for document in self.documents]
        duplicates = sorted({doc_id for doc_id in doc_ids if doc_ids.count(doc_id) > 1})
        if duplicates:
            raise ValueError("duplicate classification doc_id values: " + ", ".join(duplicates))
        return self


def load_classification_map(path: Path) -> ClassificationMap:
    if not path.is_file():
        raise ClassificationError(f"Classification mapping is missing: {path}")
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("top-level YAML value must be a mapping")
        return ClassificationMap.model_validate(payload)
    except Exception as exc:
        raise ClassificationError(f"Invalid classification mapping {path}: {exc}") from exc


def document_assignment(document: DocumentRecord) -> ClassificationAssignment:
    return ClassificationAssignment(
        domains=document.domains,
        topics=document.topics,
        memory_types=document.memory_types,
        applicable_interfaces=document.applicable_interfaces,
    )


def resolve_chunk_classification(
    document: DocumentRecord,
    section: str,
    mapping: ClassificationMap | None = None,
    *,
    require_document_mapping: bool = False,
) -> ClassificationAssignment:
    """Resolve one chunk deterministically, using the highest-priority matching rule."""

    fallback = document_assignment(document)
    if mapping is None:
        if require_document_mapping:
            raise ClassificationError("A classification mapping is required but was not loaded.")
        return fallback
    mapped = next((item for item in mapping.documents if item.doc_id == document.doc_id), None)
    if mapped is None:
        if require_document_mapping:
            raise ClassificationError(
                f"Classification mapping has no document entry for {document.doc_id}."
            )
        return fallback
    default = mapped.default or fallback
    matches = [rule for rule in mapped.section_overrides if rule.match.matches(section)]
    if not matches:
        return default
    highest_priority = max(rule.priority for rule in matches)
    winners = [rule for rule in matches if rule.priority == highest_priority]
    if len(winners) > 1:
        rule_ids = ", ".join(rule.rule_id for rule in winners)
        raise ClassificationError(
            f"Section {section!r} in {document.doc_id} matches equal-priority rules: {rule_ids}"
        )
    return winners[0].classification
