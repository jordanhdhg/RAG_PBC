"""Document catalog loading and pre-ingestion validation."""

from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import ValidationError

from ddr_rag.config import AppSettings
from ddr_rag.schemas import CatalogValidationReport, DocumentCatalog, ValidationIssue


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_catalog(settings: AppSettings) -> DocumentCatalog:
    with settings.catalog_path.open("r", encoding="utf-8") as stream:
        raw_catalog = yaml.safe_load(stream) or {}
    return DocumentCatalog.model_validate(raw_catalog)


def _issue(
    report: CatalogValidationReport,
    level: str,
    code: str,
    message: str,
    doc_id: str | None = None,
) -> None:
    report.issues.append(
        ValidationIssue(level=level, code=code, message=message, doc_id=doc_id)
    )


def validate_catalog(settings: AppSettings) -> CatalogValidationReport:
    """Validate catalog structure, source locations, supported files, and optional hashes."""

    report = CatalogValidationReport()
    try:
        catalog = load_catalog(settings)
    except FileNotFoundError:
        _issue(report, "error", "catalog_missing", f"Catalog not found: {settings.catalog_path}")
        return report
    except yaml.YAMLError as exc:
        _issue(report, "error", "catalog_yaml", f"Invalid YAML: {exc}")
        return report
    except ValidationError as exc:
        _issue(report, "error", "catalog_schema", f"Catalog schema validation failed: {exc}")
        return report

    report.total_documents = len(catalog.documents)
    if not catalog.documents:
        _issue(report, "warning", "catalog_empty", "The catalog is valid but contains no documents yet.")
        return report

    raw_root = settings.raw_path.resolve()
    seen_paths: dict[Path, str] = {}
    known_ids = {document.doc_id for document in catalog.documents}

    for document in catalog.documents:
        source_path = settings.resolve_path(document.file)
        try:
            source_path.relative_to(raw_root)
        except ValueError:
            _issue(
                report, "error", "file_outside_raw",
                f"Source must be stored under {raw_root}: {source_path}", document.doc_id,
            )

        if source_path.suffix.lower() not in {".pdf", ".docx", ".pptx"}:
            _issue(
                report, "error", "unsupported_file_format",
                f"Only PDF, DOCX, and PPTX source documents are accepted: {source_path}", document.doc_id,
            )

        if not source_path.is_file():
            _issue(report, "error", "file_missing", f"Source file does not exist: {source_path}", document.doc_id)
        elif document.file_hash:
            actual_hash = compute_sha256(source_path)
            if actual_hash != document.file_hash:
                _issue(
                    report, "warning", "hash_mismatch",
                    "The registered SHA-256 does not match the current file.", document.doc_id,
                )

        if source_path in seen_paths:
            _issue(
                report, "error", "duplicate_file",
                f"The same file is also registered by {seen_paths[source_path]}.", document.doc_id,
            )
        else:
            seen_paths[source_path] = document.doc_id

        if document.supersedes and document.supersedes not in known_ids:
            _issue(
                report, "warning", "unknown_superseded_document",
                f"supersedes references an unknown doc_id: {document.supersedes}", document.doc_id,
            )

    return report
