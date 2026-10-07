import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from typer.testing import CliRunner

from ddr_rag.answerer import _system_prompt
from ddr_rag.bm25 import build_sparse_index
from ddr_rag.cli import app
from ddr_rag.config import load_settings
from ddr_rag.embedder import write_embedding_artifact
from ddr_rag.query_scope import QueryScopeError, resolve_query_scope, scope_for_domain
from ddr_rag.retriever import RetrievalError, retrieve_with_vector
from ddr_rag.schemas import ChunkRecord
from ddr_rag.vector_store import build_local_index
from test_config import write_config


def _record(
    index: int,
    *,
    domain: str,
    topic: str,
    text: str,
    part: str = "TEST_SOC",
) -> ChunkRecord:
    memory_types = ["DDR4"] if domain == "memory" else []
    return ChunkRecord(
        chunk_id=f"ROUTE:{index:06d}:abc",
        doc_id=f"DOC_{index}",
        text=text,
        title=f"Fixture {domain}",
        revision="R1",
        source_path=Path(f"data/raw/fixture/{index}.pdf"),
        section=f"{domain} section",
        domains=[domain],
        topics=[topic],
        memory_types=memory_types,
        applicable_parts=[part],
        page_numbers=[index + 1],
        page_start=index + 1,
        page_end=index + 1,
        status="active",
        token_count=6,
    )


def _retrieval_fixture(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    # A non-null mapping marks this disposable index as a V2 payload collection.
    settings.classification.mapping = Path("fixture-classification.yaml")
    records = [
        _record(
            0,
            domain="memory",
            topic="ddr4",
            text="shared hardware guidance DDR4 termination",
        ),
        _record(
            1,
            domain="power_management",
            topic="ldo",
            text="shared hardware guidance LDO power supply",
        ),
        _record(
            2,
            domain="signal_integrity",
            topic="eye_diagram",
            text="shared hardware guidance eye diagram jitter",
        ),
    ]
    chunk_path = settings.resolve_path(settings.paths.chunks)
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_path.write_text(
        "".join(record.model_dump_json() + "\n" for record in records),
        encoding="utf-8",
    )
    vectors = np.zeros((len(records), 1024), dtype=np.float32)
    vectors[:, 0] = 1.0
    chunk_hash = hashlib.sha256(chunk_path.read_bytes()).hexdigest()
    write_embedding_artifact(settings, records, chunk_hash, vectors)
    build_local_index(settings)
    build_sparse_index(settings)
    return settings, vectors[0]


def test_local_router_is_conservative_and_explicit_domains_take_priority(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)

    assert resolve_query_scope(settings, "DDR4 clock routing").domains == ["memory"]
    assert resolve_query_scope(settings, "LDO stability").domains == ["power_management"]
    assert resolve_query_scope(settings, "layout", explicit_topics=["ldo"]).domains == [
        "power_management"
    ]
    assert resolve_query_scope(settings, "layout", explicit_interfaces=["usb"]).domains == [
        "high_speed_interface"
    ]

    ambiguous = resolve_query_scope(settings, "DDR4 rail supplied by an LDO")
    assert ambiguous.status == "clarification_required"
    assert ambiguous.candidate_domains == ["memory", "power_management"]

    explicit = resolve_query_scope(
        settings,
        "DDR4 rail supplied by an LDO",
        explicit_domains=["memory", "power_management"],
    )
    assert explicit.status == "resolved"
    assert explicit.domains == ["memory", "power_management"]
    assert explicit.routing_source == "explicit_domains"


def test_explicit_memory_scope_infers_named_types_and_cross_domain_scope_isolates_them(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)

    scope = resolve_query_scope(
        settings,
        "Compare DDR4 timing with LPDDR4 timing",
        explicit_domains=["memory", "signal_integrity"],
    )

    assert scope.memory_types == ["DDR4", "LPDDR4"]
    assert scope_for_domain(scope, "memory").memory_types == ["DDR4", "LPDDR4"]
    assert scope_for_domain(scope, "signal_integrity").memory_types == []


def test_incompatible_explicit_filters_are_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)

    with pytest.raises(QueryScopeError, match="do not share"):
        resolve_query_scope(
            settings,
            "layout",
            explicit_topics=["ldo"],
            explicit_interfaces=["usb"],
        )
    with pytest.raises(QueryScopeError, match="not valid"):
        resolve_query_scope(
            settings,
            "layout",
            explicit_domains=["power_management"],
            explicit_interfaces=["usb"],
        )


def test_part_scope_keeps_every_registered_document_for_the_same_part(monkeypatch) -> None:
    catalog = SimpleNamespace(
        documents=[
            SimpleNamespace(doc_id="RK_GUIDE", applicable_parts=["RK3568"], status="active"),
            SimpleNamespace(doc_id="RK_NOTE", applicable_parts=["RK3568"], status="active"),
            SimpleNamespace(doc_id="TI_GUIDE", applicable_parts=["AM62x"], status="active"),
        ]
    )
    monkeypatch.setattr("ddr_rag.query_scope.load_catalog", lambda settings: catalog)

    scope = resolve_query_scope(
        object(),
        "clock routing",
        explicit_domains=["memory"],
        explicit_parts=["rk3568"],
    )

    assert scope.doc_ids == ["RK_GUIDE", "RK_NOTE"]
    assert scope.applicable_parts == ["RK3568"]


@pytest.mark.parametrize("mode", ["dense", "sparse", "hybrid"])
def test_cross_domain_retrieval_is_isolated_and_balanced(
    tmp_path: Path,
    mode: str,
) -> None:
    settings, vector = _retrieval_fixture(tmp_path)
    scope = resolve_query_scope(
        settings,
        "shared hardware guidance",
        explicit_domains=["memory", "power_management"],
    )

    results = retrieve_with_vector(
        settings,
        "shared hardware guidance",
        vector if mode != "sparse" else None,
        scope=scope,
        mode=mode,
        limit=4,
    )

    result_domains = [result.chunk.domains[0] for result in results]
    assert set(result_domains) == {"memory", "power_management"}
    assert set(result_domains[:2]) == {"memory", "power_management"}
    assert len({result.chunk.chunk_id for result in results}) == len(results)
    assert "signal_integrity" not in result_domains


def test_cross_domain_limit_smaller_than_domain_count_is_rejected(tmp_path: Path) -> None:
    settings, vector = _retrieval_fixture(tmp_path)
    scope = resolve_query_scope(
        settings,
        "shared hardware guidance",
        explicit_domains=["memory", "power_management"],
    )

    with pytest.raises(RetrievalError, match="smaller than requested domain count"):
        retrieve_with_vector(
            settings,
            "shared hardware guidance",
            vector,
            scope=scope,
            mode="hybrid",
            limit=1,
        )


def test_route_cli_is_read_only_and_accepts_repeated_domains(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("route must not retrieve or call an answer model")

    monkeypatch.setattr("ddr_rag.cli.hybrid_search", forbidden)
    monkeypatch.setattr("ddr_rag.cli.dense_search", forbidden)
    monkeypatch.setattr("ddr_rag.cli.sparse_search", forbidden)
    monkeypatch.setattr("ddr_rag.cli.retrieve_query", forbidden)
    monkeypatch.setattr("ddr_rag.cli.answer_question", forbidden)

    response = CliRunner().invoke(
        app,
        [
            "route",
            "power and memory review",
            "--domain",
            "memory",
            "--domain",
            "power_management",
            "--format",
            "json",
            "--config",
            str(config_path),
        ],
    )
    payload = json.loads(response.stdout)

    assert response.exit_code == 0
    assert payload["status"] == "resolved"
    assert payload["domains"] == ["memory", "power_management"]


def test_search_cli_passes_the_audited_cross_domain_scope(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    captured = {}

    def fake_hybrid(settings, query, *, scope, limit):
        captured["scope"] = scope
        return []

    monkeypatch.setattr("ddr_rag.cli.hybrid_search", fake_hybrid)
    response = CliRunner().invoke(
        app,
        [
            "search",
            "combined review",
            "--domain",
            "memory",
            "--domain",
            "power_management",
            "--format",
            "json",
            "--config",
            str(config_path),
        ],
    )
    payload = json.loads(response.stdout)

    assert response.exit_code == 0
    assert captured["scope"].domains == ["memory", "power_management"]
    assert payload["route"]["domains"] == ["memory", "power_management"]
    assert payload["results"] == []


def test_answer_prompt_is_general_hardware_and_preserves_scope_rules() -> None:
    prompt = _system_prompt()

    assert "基于硬件资料的证据助手" in prompt
    assert "特定器件规则和标准要求" in prompt
    assert "DDR 硬件设计资料助手" not in prompt


def test_ambiguous_ask_requests_clarification_before_any_api(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)

    monkeypatch.setattr(
        "ddr_rag.cli.answer_question",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("ambiguous ask must not reach answer generation")
        ),
    )
    response = CliRunner().invoke(
        app,
        ["ask", "这个要求是什么？", "--config", str(config_path)],
    )

    assert response.exit_code == 2
    assert "需要澄清领域" in response.stdout
