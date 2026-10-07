from pathlib import Path

from ddr_rag.catalog import validate_catalog
from ddr_rag.config import load_settings
from test_config import write_config


def prepare_project(tmp_path: Path, catalog_text: str) -> Path:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    catalog_path = tmp_path / "data/catalog/documents.yaml"
    catalog_path.parent.mkdir(parents=True)
    catalog_path.write_text(catalog_text, encoding="utf-8")
    return config_path


def document_yaml(file_path: str, doc_id: str = "TEST_DDR4_R1") -> str:
    return f"""
documents:
  - doc_id: {doc_id}
    title: Test DDR4 Guide
    revision: R1
    vendor: Test Vendor
    file: {file_path}
    document_type: hardware_design_guide
    language: en
    memory_types: [ddr4]
    applicable_parts: []
    authority: vendor_design_guide
    authority_score: 90
    status: active
    confidentiality: public
""".strip()


def test_empty_catalog_is_valid_with_warning(tmp_path: Path) -> None:
    config_path = prepare_project(tmp_path, "documents: []")
    report = validate_catalog(load_settings(config_path))
    assert report.is_valid
    assert report.warning_count == 1
    assert report.issues[0].code == "catalog_empty"


def test_existing_pdf_under_raw_is_valid(tmp_path: Path) -> None:
    pdf_path = tmp_path / "data/raw/vendor/guide.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4 test")
    config_path = prepare_project(tmp_path, document_yaml("data/raw/vendor/guide.pdf"))
    report = validate_catalog(load_settings(config_path))
    assert report.is_valid
    assert report.error_count == 0
    assert report.total_documents == 1


def test_missing_pdf_is_reported(tmp_path: Path) -> None:
    config_path = prepare_project(tmp_path, document_yaml("data/raw/vendor/missing.pdf"))
    report = validate_catalog(load_settings(config_path))
    assert not report.is_valid
    assert any(issue.code == "file_missing" for issue in report.issues)


def test_duplicate_doc_id_is_schema_error(tmp_path: Path) -> None:
    record = document_yaml("data/raw/vendor/one.pdf").splitlines()[1:]
    second = document_yaml("data/raw/vendor/two.pdf").splitlines()[1:]
    catalog_text = "documents:\n" + "\n".join(record + second)
    config_path = prepare_project(tmp_path, catalog_text)
    report = validate_catalog(load_settings(config_path))
    assert not report.is_valid
    assert report.issues[0].code == "catalog_schema"
