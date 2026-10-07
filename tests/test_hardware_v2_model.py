import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typer.testing import CliRunner

from ddr_rag.classification import load_classification_map, resolve_chunk_classification
from ddr_rag.answerer import _evidence_prompt
from ddr_rag.bm25 import build_sparse_index, sparse_search
from ddr_rag.cli import app
from ddr_rag.config import load_settings
from ddr_rag.citations import build_citations
from ddr_rag.evaluation import (
    EvaluationDataset,
    EvaluationQuestion,
    EvaluationRequirements,
    ExpectedSource,
    evaluate_offline_results,
    validate_evaluation_dataset,
)
from ddr_rag.schemas import ChunkRecord, DocumentRecord, SearchResult, SourceLocation
from ddr_rag.taxonomy import (
    CONTROLLED_DOMAINS,
    CONTROLLED_INTERFACES,
    CONTROLLED_MEMORY_TYPES,
    DOMAIN_TOPICS,
    TAXONOMY_VERSION,
)
from ddr_rag.vector_store import _payload, chunk_memory_types
from test_config import write_config


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_document(**updates) -> DocumentRecord:
    values = {
        "doc_id": "TEST_POWER_GUIDE",
        "title": "Power guide",
        "revision": "R1",
        "vendor": "Test Vendor",
        "file": Path("data/raw/vendor/power.pdf"),
        "document_type": "technical_whitepaper",
        "domains": ["power_management"],
        "topics": ["ldo", "power_supply"],
        "memory_types": [],
        "authority": "vendor_design_guide",
        "authority_score": 90,
    }
    values.update(updates)
    return DocumentRecord(**values)


def test_non_memory_document_is_valid_without_fake_memory_type() -> None:
    document = make_document(applicable_interfaces=[])

    assert document.domains == ["power_management"]
    assert document.topics == ["ldo", "power_supply"]
    assert document.memory_types == []
    assert document.applicable_interfaces == []
    assert document.document_type == "technical_whitepaper"


def test_missing_or_uncontrolled_classification_is_rejected() -> None:
    with pytest.raises(ValidationError, match="domains"):
        make_document(domains=[])
    with pytest.raises(ValidationError, match="unknown domains"):
        make_document(domains=["software"])
    with pytest.raises(ValidationError, match="not valid for the selected domains"):
        make_document(topics=["ddr4"])
    with pytest.raises(ValidationError, match="memory_types may only"):
        make_document(memory_types=["DDR4"])


def test_unchanged_v1_memory_metadata_gets_deterministic_compatibility_fields() -> None:
    document = DocumentRecord(
        doc_id="LEGACY_DDR4",
        title="Legacy DDR guide",
        revision="R1",
        vendor="Test Vendor",
        file=Path("data/raw/vendor/ddr.pdf"),
        document_type="hardware_design_guide",
        memory_types=["ddr4"],
        authority="vendor_design_guide",
        authority_score=90,
    )

    assert document.domains == ["memory"]
    assert document.topics == ["ddr4"]
    assert document.memory_types == ["DDR4"]


def test_versioned_taxonomy_yaml_matches_runtime_vocabulary() -> None:
    payload = yaml.safe_load(
        (PROJECT_ROOT / "data/taxonomy/hardware_v2_taxonomy.v1.yaml").read_text(encoding="utf-8")
    )

    assert payload["taxonomy_version"] == TAXONOMY_VERSION
    assert set(payload["domains"]) == set(CONTROLLED_DOMAINS)
    assert {
        domain: set(settings["topics"])
        for domain, settings in payload["domains"].items()
    } == {domain: set(topics) for domain, topics in DOMAIN_TOPICS.items()}
    assert set(payload["memory_types"]) == set(CONTROLLED_MEMORY_TYPES)
    assert set(payload["interfaces"]) == set(CONTROLLED_INTERFACES)


def test_section_mapping_overrides_document_default_and_is_traceable() -> None:
    mapping = load_classification_map(
        PROJECT_ROOT / "data/classification/hardware_v2_classification.v1.yaml"
    )
    document = make_document(
        doc_id="ROCKCHIP_RK3568_HARDWARE_DESIGN_GUIDE_CN_V1_2",
        title="RK3568 Hardware Design Guide",
        topics=["power_supply"],
    )

    default = resolve_chunk_classification(document, "1.1 概述", mapping)
    ddr_power = resolve_chunk_classification(document, "2.1.7.5 DDR电源设计和上电时序要求", mapping)
    usb = resolve_chunk_classification(document, "2.2.2.9 USB2.0 PHY电源", mapping)
    ddr4 = resolve_chunk_classification(document, "3.2.3.5 DDR4 PCB设计", mapping)
    lpddr3 = resolve_chunk_classification(document, "3.2.3.4 LPDDR3 PCB设计", mapping)
    lpddr4 = resolve_chunk_classification(document, "3.2.3.7 LPDDR4 PCB设计", mapping)
    lpddr4x = resolve_chunk_classification(document, "3.2.3.8 LPDDR4x PCB设计", mapping)

    assert default.domains == ["hardware_general"]
    assert default.memory_types == []
    assert ddr_power.domains == ["memory", "power_management"]
    assert ddr_power.memory_types == ["DDR3", "DDR3L", "LPDDR3", "DDR4", "LPDDR4", "LPDDR4X"]
    assert usb.domains == ["high_speed_interface"]
    assert usb.applicable_interfaces == ["usb"]
    assert ddr4.memory_types == ["DDR4"]
    assert lpddr3.memory_types == ["LPDDR3"]
    assert lpddr4.memory_types == ["LPDDR4"]
    assert lpddr4x.memory_types == ["LPDDR4X"]


def test_classification_reaches_chunk_citation_and_search_json_models() -> None:
    chunk = ChunkRecord(
        chunk_id="POWER:000001:abc",
        doc_id="POWER",
        text="An LDO regulates the rail.",
        title="Power guide",
        revision="R1",
        source_path=Path("data/raw/vendor/power.pdf"),
        section="LDO basics",
        document_type="training_material",
        domains=["power_management"],
        topics=["ldo"],
        applicable_interfaces=[],
        memory_types=[],
        page_numbers=[3],
        page_start=3,
        page_end=3,
        status="active",
        token_count=6,
    )
    result = SearchResult(chunk=chunk, score=0.9, retrieval_sources=["sparse"])
    citation = build_citations([result])[0]
    evidence = _evidence_prompt("What is the rule?", [result], [citation], [])
    payload = _payload(chunk)

    assert result.model_dump(mode="json")["chunk"]["domains"] == ["power_management"]
    assert payload["domains"] == ["power_management"]
    assert payload["topics"] == ["ldo"]
    assert payload["applicable_interfaces"] == []
    assert citation.domains == ["power_management"]
    assert citation.topics == ["ldo"]
    assert citation.memory_types == []
    assert "领域：power_management" in evidence
    assert "主题：ldo" in evidence
    assert "内存类型：不适用" in evidence


def test_v2_index_trusts_versioned_memory_classification_over_incidental_text() -> None:
    chunk = ChunkRecord(
        chunk_id="MEMORY:000001:abc",
        doc_id="MEMORY",
        text="LPDDR3 section followed by a DDR4 table after a parser heading boundary.",
        title="Memory guide",
        revision="R1",
        source_path=Path("data/raw/vendor/memory.pdf"),
        section="LPDDR3 PCB design",
        domains=["memory"],
        topics=["lpddr3", "ddr_design"],
        memory_types=["LPDDR3"],
        page_numbers=[10],
        page_start=10,
        page_end=10,
        status="active",
        token_count=12,
    )

    assert set(chunk_memory_types(chunk)) == {"LPDDR3", "DDR4"}
    assert chunk_memory_types(chunk, trust_classification=True) == ["LPDDR3"]
    assert _payload(chunk, trust_classification=True)["memory_types"] == ["LPDDR3"]


def test_non_memory_classification_survives_bm25_and_cli_json(
    tmp_path: Path, monkeypatch
) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    chunk = ChunkRecord(
        chunk_id="POWER:000002:abc",
        doc_id="POWER",
        text="LDO power supply regulation",
        title="Power guide",
        revision="R1",
        source_path=Path("data/raw/vendor/power.pdf"),
        section="LDO basics",
        domains=["power_management"],
        topics=["ldo", "power_supply"],
        memory_types=[],
        page_numbers=[4],
        page_start=4,
        page_end=4,
        status="active",
        token_count=4,
    )
    chunks_path = settings.resolve_path(settings.paths.chunks)
    chunks_path.parent.mkdir(parents=True, exist_ok=True)
    chunks_path.write_text(chunk.model_dump_json() + "\n", encoding="utf-8")
    build_sparse_index(settings)

    result = sparse_search(settings, "LDO", limit=1)[0]
    monkeypatch.setattr("ddr_rag.cli.hybrid_search", lambda *args, **kwargs: [result])
    response = CliRunner().invoke(
        app,
        ["search", "LDO", "--format", "json", "--config", str(config_path)],
    )
    payload = json.loads(response.stdout)

    assert result.chunk.domains == ["power_management"]
    assert result.chunk.memory_types == []
    assert response.exit_code == 0
    assert payload["results"][0]["chunk"]["domains"] == ["power_management"]
    assert payload["citations"][0]["topics"] == ["ldo", "power_supply"]


def test_generic_evaluation_contract_supports_non_pdf_non_ddr_dataset() -> None:
    question = EvaluationQuestion(
        question_id="POWER_ANS_LDO_01",
        question="What does the slide say about the LDO?",
        language="en",
        category="power_basics",
        domains=["power_management"],
        topics=["ldo"],
        answerable=True,
        expected_sources=[
            ExpectedSource(
                doc_id="POWER_TRAINING",
                section_contains="LDO",
                slide_numbers=[4],
            )
        ],
        expected_key_facts=["The LDO regulates the rail."],
    )
    dataset = EvaluationDataset(
        schema_version=2,
        dataset_id="hardware_power_fixture_v1",
        description="Small configurable non-DDR fixture",
        validation_requirements=EvaluationRequirements(
            total_questions=1,
            answerable_questions=1,
            refusal_questions=0,
            min_answerable_by_language={"en": 1},
            required_source_doc_ids=["POWER_TRAINING"],
        ),
        questions=[question],
    )
    chunk = ChunkRecord(
        chunk_id="POWER_TRAINING:000001:abc",
        doc_id="POWER_TRAINING",
        text="The LDO regulates the rail.",
        title="Power training",
        revision="R1",
        source_path=Path("data/raw/experience/power.pptx"),
        section="LDO basics",
        source_format="pptx",
        source_location=SourceLocation(kind="pptx_slides", slide_numbers=[4]),
        domains=["power_management"],
        topics=["ldo"],
        memory_types=[],
        status="active",
        token_count=6,
    )
    result = SearchResult(chunk=chunk, score=1.0, retrieval_sources=["dense"])

    validation = validate_evaluation_dataset(dataset, [chunk])
    report = evaluate_offline_results(dataset, {question.question_id: [result]}, top_k=1)

    assert validation["total_questions"] == 1
    assert validation["validation_requirements"]["answerable_questions"] == 1
    assert report["dataset_schema_version"] == 2
    assert report["questions"][0]["domains"] == ["power_management"]
    assert report["questions"][0]["top_k_results"][0]["topics"] == ["ldo"]
