"""Command-line entry point for general-hardware RAG maintenance tasks."""

import json
import locale
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console

from ddr_rag.catalog import validate_catalog
from ddr_rag.catalog import load_catalog
from ddr_rag.config import load_settings
from ddr_rag.chunker import ChunkingError, chunk_documents
from ddr_rag.embedder import EmbeddingError, embed_chunks, load_chunk_records
from ddr_rag.evaluation import (
    EvaluationError,
    evaluate_offline_results,
    load_evaluation_dataset,
    retrieve_evaluation_results,
    retrieve_evaluation_results_with_routes,
    run_answer_evaluation,
    select_evaluation_questions,
    validate_evaluation_dataset,
    write_answer_evaluation_report,
    write_offline_evaluation_report,
)
from ddr_rag.vector_store import VectorStoreError, build_local_index
from ddr_rag.query_scope import QueryScope, QueryScopeError, resolve_query_scope
from ddr_rag.retriever import RetrievalError, dense_search, hybrid_search, retrieve_query
from ddr_rag.bm25 import SparseIndexError, build_sparse_index, sparse_search
from ddr_rag.citations import CitationError, build_citations, format_citation, format_source_location
from ddr_rag.ingest import IngestError, ingest_documents
from ddr_rag.answerer import AnsweringError, answer_question
from ddr_rag.parser import parse_documents


app = typer.Typer(help="Build and maintain the general-hardware knowledge base.")
catalog_app = typer.Typer(help="Manage the source-document catalog.")
evaluation_app = typer.Typer(help="Validate versioned local RAG evaluation datasets.")
app.add_typer(catalog_app, name="catalog")
app.add_typer(evaluation_app, name="eval")
console = Console()


def _console_safe(value: str) -> str:
    """Avoid Windows legacy-console encoding failures without changing stored evidence."""

    encoding = locale.getpreferredencoding(False) or "utf-8"
    return value.encode(encoding, errors="backslashreplace").decode(encoding)


def _resolve_cli_scope(
    settings,
    query: str,
    *,
    doc_id: str | None,
    domains: list[str],
    topics: list[str],
    interfaces: list[str],
    parts: list[str],
    memory_type: str | None,
    include_inactive: bool,
) -> QueryScope:
    return resolve_query_scope(
        settings,
        query,
        explicit_doc_id=doc_id,
        explicit_domains=domains,
        explicit_topics=topics,
        explicit_interfaces=interfaces,
        explicit_parts=parts,
        memory_type=memory_type,
        active_only=not include_inactive,
    )


def _emit_clarification(scope: QueryScope, output_format: str) -> None:
    if output_format == "json":
        typer.echo(
            json.dumps(
                {"route": scope.model_dump(mode="json"), "message": scope.clarification_message},
                ensure_ascii=True,
            )
        )
    else:
        console.print(f"[yellow]{scope.clarification_message}[/yellow]")


@catalog_app.command("validate")
def catalog_validate(
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Validate documents.yaml and every registered source file."""

    try:
        settings = load_settings(config)
    except (FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    report = validate_catalog(settings)
    for issue in report.issues:
        color = "red" if issue.level == "error" else "yellow"
        subject = f" [{issue.doc_id}]" if issue.doc_id else ""
        console.print(f"[{color}]{issue.level.upper()}[/{color}] {issue.code}{subject}: {issue.message}")

    console.print(
        f"Documents: {report.total_documents} | Errors: {report.error_count} | "
        f"Warnings: {report.warning_count}"
    )
    if not report.is_valid:
        raise typer.Exit(code=1)


@evaluation_app.command("validate")
def evaluation_validate(
    questions: Path | None = typer.Option(
        None,
        "--questions",
        help="Evaluation YAML; defaults to paths.evaluations/ddr_rag_v1_questions.yaml.",
    ),
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Validate question counts and anchors against existing local ChunkRecords."""

    try:
        settings = load_settings(config)
        dataset_path = (
            settings.resolve_path(questions)
            if questions is not None
            else settings.resolve_path(settings.paths.evaluations) / "ddr_rag_v1_questions.yaml"
        )
        dataset = load_evaluation_dataset(dataset_path)
        records, _ = load_chunk_records(settings)
        report = validate_evaluation_dataset(dataset, records)
    except (EvaluationError, EmbeddingError, FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]Evaluation dataset validation failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"Validated {report['total_questions']} questions | "
        f"answerable={report['answerable_questions']} | refusals={report['refusal_questions']}"
    )
    console.print(f"Answerable languages: {report['answerable_language_counts']}")
    console.print(f"Expected source documents: {report['expected_source_document_counts']}")


@evaluation_app.command("run")
def evaluation_run(
    top_k: int = typer.Option(5, "--top-k", min=1, help="Top-K local Hybrid results to evaluate."),
    min_hit_rate: float = typer.Option(
        0.9,
        "--min-hit-rate",
        min=0.0,
        max=1.0,
        help="Minimum all-expected-source hit rate required for a passing offline run.",
    ),
    with_answer_eval: bool = typer.Option(
        False,
        "--with-answer-eval",
        help="Call DeepSeek per question after the offline retrieval gate passes.",
    ),
    min_answerable_rate: float = typer.Option(
        0.9,
        "--min-answerable-rate",
        min=0.0,
        max=1.0,
        help="Minimum verified expected-source citation rate for answerable questions.",
    ),
    min_refusal_rate: float = typer.Option(
        0.9,
        "--min-refusal-rate",
        min=0.0,
        max=1.0,
        help="Minimum strict-refusal rate for the 10 unanswerable questions.",
    ),
    question_id: list[str] = typer.Option(
        [],
        "--question-id",
        help="Evaluate only this known question ID after validating the complete dataset; repeatable.",
    ),
    questions: Path | None = typer.Option(
        None,
        "--questions",
        help="Evaluation YAML; defaults to paths.evaluations/ddr_rag_v1_questions.yaml.",
    ),
    report_dir: Path | None = typer.Option(
        None,
        "--report-dir",
        help="Directory for timestamped JSON and Markdown reports.",
    ),
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Run offline evaluation, optionally followed by explicit DeepSeek answer evaluation."""

    try:
        settings = load_settings(config)
        dataset_path = (
            settings.resolve_path(questions)
            if questions is not None
            else settings.resolve_path(settings.paths.evaluations) / "ddr_rag_v1_questions.yaml"
        )
        dataset = load_evaluation_dataset(dataset_path)
        records, _ = load_chunk_records(settings)
        validate_evaluation_dataset(dataset, records)
        dataset = select_evaluation_questions(dataset, question_id)
        results_by_question, route_reports = retrieve_evaluation_results_with_routes(
            settings,
            dataset,
            top_k=top_k,
        )
        report = evaluate_offline_results(
            dataset,
            results_by_question,
            top_k=top_k,
            route_reports=route_reports,
        )
        output_dir = (
            settings.resolve_path(report_dir)
            if report_dir is not None
            else settings.resolve_path(settings.paths.evaluations) / "reports"
        )
        paths = write_offline_evaluation_report(report, output_dir)
    except (EvaluationError, EmbeddingError, RetrievalError, FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]Offline evaluation failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc

    summary = report["summary"]
    assert isinstance(summary, dict)
    hit_rate = float(summary["answerable_all_anchors_hit_rate"])
    if summary["answerable_questions"]:
        console.print(
            f"Offline retrieval evaluation | all-anchor hit@{top_k}={hit_rate:.1%} "
            f"({summary['answerable_all_anchors_hit']}/{summary['answerable_questions']})"
        )
        console.print(f"Expected-anchor recall@{top_k}={summary['expected_anchor_recall_at_k']:.1%}")
    else:
        console.print("Offline retrieval evaluation | refusal-only selection; answerable-anchor gate skipped")
    console.print(
        "Retrieval-insufficiency no-results="
        f"{summary['refusal_no_result']}/{summary['retrieval_refusal_questions']}"
    )
    if summary["clarification_questions"]:
        console.print(
            f"Clarification routing={summary['clarification_rate']:.1%} "
            f"({summary['clarification_pass']}/{summary['clarification_questions']})"
        )
    if summary["single_source_questions"]:
        console.print(
            f"Single-source anchor hit@5={summary['single_source_hit_rate_at_5']:.1%} "
            f"({summary['single_source_hit_at_5']}/{summary['single_source_questions']})"
        )
    if summary["cross_domain_questions"]:
        console.print(
            f"Cross-domain scope coverage@{top_k}="
            f"{summary['cross_domain_coverage_rate_at_k']:.1%} "
            f"({summary['cross_domain_covered']}/{summary['cross_domain_questions']})"
        )
    console.print(f"Reports: {paths['json']} | {paths['markdown']}")
    if summary["answerable_questions"] and hit_rate < min_hit_rate:
        console.print(f"[yellow]Offline acceptance not met:[/yellow] {hit_rate:.1%} < {min_hit_rate:.1%}")
        raise typer.Exit(code=1)
    if summary["clarification_rate"] < 1.0:
        console.print("[yellow]Offline acceptance not met:[/yellow] clarification routing must be 100%")
        raise typer.Exit(code=1)
    if not with_answer_eval:
        return

    console.print(
        f"DeepSeek answer evaluation enabled | questions={len(dataset.questions)} | "
        "only each question and its limited retrieved evidence will be sent"
    )

    def show_progress(current: int, total: int, question_id: str, status: str) -> None:
        console.print(f"[{current}/{total}] {question_id}: {status}")

    try:
        answer_report = run_answer_evaluation(
            settings,
            dataset,
            results_by_question,
            top_k=top_k,
            progress=show_progress,
        )
        answer_paths = write_answer_evaluation_report(answer_report, output_dir)
    except (EvaluationError, AnsweringError, FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]Answer evaluation failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc

    answer_summary = answer_report["summary"]
    assert isinstance(answer_summary, dict)
    answerable_rate = float(answer_summary["answerable_grounded_source_pass_rate"])
    refusal_rate = float(answer_summary["refusal_pass_rate"])
    console.print(
        f"Answer evaluation | grounded-source pass={answerable_rate:.1%} "
        f"({answer_summary['answerable_grounded_source_pass']}/{answer_summary['answerable_questions']}) | "
        f"strict refusals={refusal_rate:.1%} "
        f"({answer_summary['refusal_pass']}/{answer_summary['refusal_questions']})"
    )
    console.print(
        f"API calls attempted={answer_summary['api_calls_attempted']} | "
        f"question errors={answer_summary['question_errors']}"
    )
    console.print(f"Answer reports: {answer_paths['json']} | {answer_paths['markdown']}")
    answerable_gate_failed = (
        bool(answer_summary["answerable_questions"]) and answerable_rate < min_answerable_rate
    )
    refusal_gate_failed = bool(answer_summary["refusal_questions"]) and refusal_rate < min_refusal_rate
    if answerable_gate_failed or refusal_gate_failed:
        console.print(
            "[yellow]Answer acceptance not met:[/yellow] "
            f"answerable {answerable_rate:.1%}/{min_answerable_rate:.1%}, "
            f"refusal {refusal_rate:.1%}/{min_refusal_rate:.1%}"
        )
        raise typer.Exit(code=1)


@app.command("parse")
def parse(
    doc_id: str | None = typer.Option(None, "--doc-id", help="Parse one registered document."),
    all_documents: bool = typer.Option(False, "--all", help="Parse all active registered documents."),
    replace: bool = typer.Option(False, "--replace", help="Replace existing parsed outputs."),
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Parse registered PDF, DOCX, or PPTX sources into Markdown and Docling JSON."""

    if bool(doc_id) == all_documents:
        console.print("[red]Choose exactly one of --doc-id or --all.[/red]")
        raise typer.Exit(code=2)

    try:
        settings = load_settings(config)
        validation = validate_catalog(settings)
        if not validation.is_valid:
            console.print("[red]Catalog validation failed; parsing was not started.[/red]")
            raise typer.Exit(code=1)
        catalog = load_catalog(settings)
        documents = [document for document in catalog.documents if document.status == "active"]
        if doc_id:
            documents = [document for document in documents if document.doc_id == doc_id]
            if not documents:
                console.print(f"[red]Active document not found:[/red] {doc_id}")
                raise typer.Exit(code=2)

        reports = parse_documents(
            settings,
            documents,
            replace=replace,
            progress=lambda message: console.print(f"[cyan]{message}[/cyan]"),
        )
    except typer.Exit:
        raise
    except Exception as exc:
        console.print(f"[red]Parsing failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc

    for report in reports:
        console.print(
            f"{report['doc_id']}: {report['status']} | "
            f"format={report.get('source_format', '-')} | pages/slides={report.get('source_page_count', '-')} | "
            f"tables={report.get('table_count', '-')} | "
            f"seconds={report.get('duration_seconds', '-')}"
        )


@app.command("chunk")
def chunk(
    doc_id: str | None = typer.Option(None, "--doc-id", help="Chunk one active parsed document."),
    all_documents: bool = typer.Option(False, "--all", help="Chunk all active parsed documents."),
    replace: bool = typer.Option(False, "--replace", help="Replace chunks for the selected document(s)."),
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Create traceable HybridChunker JSONL records from parsed Docling JSON."""

    if bool(doc_id) == all_documents:
        console.print("[red]Choose exactly one of --doc-id or --all.[/red]")
        raise typer.Exit(code=2)

    try:
        settings = load_settings(config)
        validation = validate_catalog(settings)
        if not validation.is_valid:
            console.print("[red]Catalog validation failed; chunking was not started.[/red]")
            raise typer.Exit(code=1)
        catalog = load_catalog(settings)
        documents = [document for document in catalog.documents if document.status == "active"]
        if doc_id:
            documents = [document for document in documents if document.doc_id == doc_id]
            if not documents:
                console.print(f"[red]Active document not found:[/red] {doc_id}")
                raise typer.Exit(code=2)
        report = chunk_documents(settings, documents, replace=replace)
    except typer.Exit:
        raise
    except (ChunkingError, FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]Chunking failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc

    for document_report in report["documents"]:
        console.print(
            f"{document_report['doc_id']}: chunks={document_report['chunk_count']} | "
            f"tokens min/mean/p50/p95/max="
            f"{document_report['min_tokens']}/{document_report['mean_tokens']}/"
            f"{document_report['p50_tokens']}/{document_report['p95_tokens']}/"
            f"{document_report['max_tokens']}"
        )
    console.print(f"Wrote {report['total_chunks']} chunks to {report['output']}")


@app.command("embed")
def embed(
    replace: bool = typer.Option(False, "--replace", help="Replace existing local embedding artifacts."),
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Create offline BGE-M3 dense vectors for every published chunk."""

    try:
        settings = load_settings(config)
        report = embed_chunks(settings, replace=replace)
    except (EmbeddingError, FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]Embedding failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc

    validation = report["validation"]
    console.print(
        f"Embedded {validation['chunk_count']} chunks | dimension={validation['dimension']} | "
        f"norm min/max={validation['norm_min']:.6f}/{validation['norm_max']:.6f}"
    )
    console.print(f"Vectors: {report['paths']['vectors']}")


@app.command("index")
def index(
    replace: bool = typer.Option(False, "--replace", help="Replace the existing Qdrant Local collection."),
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Build a persistent local Qdrant collection from the validated BGE-M3 vectors."""

    try:
        settings = load_settings(config)
        report = build_local_index(settings, replace=replace)
    except (EmbeddingError, VectorStoreError, FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]Indexing failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"Indexed {report['point_count']} points | dimension={report['dimension']} | "
        f"distance={report['distance']} | collection={report['collection']}"
    )
    console.print(f"Qdrant Local path: {report['path']}")


@app.command("bm25")
def bm25(
    replace: bool = typer.Option(False, "--replace", help="Replace the existing local BM25 index."),
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Build the persistent local BM25 sparse index from published ChunkRecords."""

    try:
        settings = load_settings(config)
        report = build_sparse_index(settings, replace=replace)
    except (EmbeddingError, SparseIndexError, FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]BM25 build failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc
    console.print(
        f"BM25 indexed {report['chunk_count']} chunks | terms={report['term_count']} | "
        f"average length={report['average_document_length']:.2f}"
    )
    console.print(f"BM25 path: {report['path']}")


@app.command("ingest")
def ingest(
    doc_id: str | None = typer.Option(None, "--doc-id", help="Ingest one active registered document."),
    all_documents: bool = typer.Option(False, "--all", help="Ingest all active registered documents."),
    replace: bool = typer.Option(
        False,
        "--replace",
        help="Explicitly replace affected Chunk, embedding, Qdrant, and BM25 artifacts.",
    ),
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Run local parse, chunk, embedding, Qdrant, and BM25 for registered documents."""

    if bool(doc_id) == all_documents:
        console.print("[red]Choose exactly one of --doc-id or --all.[/red]")
        raise typer.Exit(code=2)
    try:
        settings = load_settings(config)
        validation = validate_catalog(settings)
        if not validation.is_valid:
            console.print("[red]Catalog validation failed; ingestion was not started.[/red]")
            raise typer.Exit(code=1)
        catalog = load_catalog(settings)
        documents = [document for document in catalog.documents if document.status == "active"]
        if doc_id:
            documents = [document for document in documents if document.doc_id == doc_id]
            if not documents:
                console.print(f"[red]Active document not found:[/red] {doc_id}")
                raise typer.Exit(code=2)
        report = ingest_documents(
            settings,
            documents,
            replace=replace,
            progress=lambda message: console.print(f"[cyan]{message}[/cyan]"),
        )
    except typer.Exit:
        raise
    except (IngestError, FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]Ingestion failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"Ingested document(s): {', '.join(report['doc_ids'])}")
    console.print(f"Chunks: {report['chunk']['total_chunks']} selected | {report['chunk']['output']}")
    console.print(
        f"Embedding: {report['embedding']['validation']['chunk_count']} chunks | "
        f"dimension={report['embedding']['validation']['dimension']}"
    )
    console.print(
        f"Qdrant: {report['vector_index']['point_count']} points | "
        f"BM25: {report['sparse_index']['chunk_count']} chunks"
    )


@app.command("route")
def route(
    query: str = typer.Argument(..., help="Hardware question to route locally without retrieval."),
    domain: list[str] = typer.Option([], "--domain", help="Explicit domain; repeat for cross-domain scope."),
    topic: list[str] = typer.Option([], "--topic", help="Controlled topic filter; repeatable."),
    interface: list[str] = typer.Option([], "--interface", help="Applicable interface filter; repeatable."),
    part: list[str] = typer.Option([], "--part", help="Applicable part filter; repeatable."),
    memory_type: str | None = typer.Option(None, "--memory-type", help="Compatible DDR type filter."),
    doc_id: str | None = typer.Option(None, "--doc-id", help="Filter by one registered document ID."),
    include_inactive: bool = typer.Option(False, "--include-inactive", help="Also scope non-active documents."),
    output_format: str = typer.Option("text", "--format", help="Output format: text or json."),
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Resolve and explain a query scope without retrieval, embeddings, or answer APIs."""

    if output_format not in {"text", "json"}:
        console.print("[red]--format must be 'text' or 'json'.[/red]")
        raise typer.Exit(code=2)
    try:
        settings = load_settings(config)
        scope = _resolve_cli_scope(
            settings,
            query,
            doc_id=doc_id,
            domains=domain,
            topics=topic,
            interfaces=interface,
            parts=part,
            memory_type=memory_type,
            include_inactive=include_inactive,
        )
    except (QueryScopeError, FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]Routing failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc

    if output_format == "json":
        typer.echo(json.dumps(scope.model_dump(mode="json"), ensure_ascii=True))
        return
    console.print(f"status: {scope.status}")
    console.print(f"domains: {', '.join(scope.domains) or '-'}")
    console.print(f"candidate_domains: {', '.join(scope.candidate_domains) or '-'}")
    console.print(f"topics: {', '.join(scope.topics) or '-'}")
    console.print(f"interfaces: {', '.join(scope.applicable_interfaces) or '-'}")
    console.print(f"parts: {', '.join(scope.applicable_parts) or '-'}")
    console.print(f"documents: {', '.join(scope.doc_ids or []) or '-'}")
    console.print(f"routing_source: {scope.routing_source}")
    console.print(
        _console_safe(
            "explicit_filters: " + json.dumps(scope.explicit_filters, ensure_ascii=False)
        )
    )
    for reason in scope.reasons:
        console.print(_console_safe(f"reason: {reason}"))
    if scope.status == "clarification_required":
        console.print(_console_safe(scope.clarification_message))


@app.command("search")
def search(
    query: str = typer.Argument(..., help="Natural-language hardware question to search locally."),
    domain: list[str] = typer.Option([], "--domain", help="Explicit domain; repeat for cross-domain search."),
    topic: list[str] = typer.Option([], "--topic", help="Controlled topic filter; repeatable."),
    interface: list[str] = typer.Option([], "--interface", help="Applicable interface filter; repeatable."),
    part: list[str] = typer.Option([], "--part", help="Applicable part filter; repeatable."),
    memory_type: str | None = typer.Option(None, "--memory-type", help="Compatible DDR type filter."),
    doc_id: str | None = typer.Option(None, "--doc-id", help="Filter by one registered document ID."),
    include_inactive: bool = typer.Option(False, "--include-inactive", help="Also search non-active documents."),
    mode: str = typer.Option("hybrid", "--mode", help="Retrieval mode: hybrid, dense, or sparse."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Maximum evidence records to return."),
    output_format: str = typer.Option("text", "--format", help="Output format: text or json."),
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Retrieve locally routed Dense/BM25 evidence without answer generation."""

    if output_format not in {"text", "json"} or mode not in {"hybrid", "dense", "sparse"}:
        console.print("[red]--format must be 'text' or 'json'; --mode must be hybrid, dense, or sparse.[/red]")
        raise typer.Exit(code=2)
    try:
        settings = load_settings(config)
        scope = _resolve_cli_scope(
            settings,
            query,
            doc_id=doc_id,
            domains=domain,
            topics=topic,
            interfaces=interface,
            parts=part,
            memory_type=memory_type,
            include_inactive=include_inactive,
        )
        if scope.status != "resolved":
            _emit_clarification(scope, output_format)
            raise typer.Exit(code=2)
        if mode == "hybrid":
            results = hybrid_search(settings, query, scope=scope, limit=limit)
        elif mode == "dense":
            results = dense_search(settings, query, scope=scope, limit=limit)
        elif len(scope.domains) > 1:
            results = retrieve_query(settings, query, scope=scope, mode="sparse", limit=limit)
        else:
            results = sparse_search(settings, query, scope=scope, limit=limit)
        citations = build_citations(results)
    except typer.Exit:
        raise
    except (QueryScopeError, RetrievalError, SparseIndexError, CitationError,
            FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]Search failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc

    if output_format == "json":
        payload = {
            "route": scope.model_dump(mode="json"),
            "results": [
                {"citation_id": citation.citation_id, **result.model_dump(mode="json")}
                for citation, result in zip(citations, results, strict=True)
            ],
            "citations": [citation.model_dump(mode="json") for citation in citations],
        }
        typer.echo(json.dumps(payload, ensure_ascii=True))
        return
    console.print(
        f"route: {', '.join(scope.domains)} | source={scope.routing_source} | "
        f"topics={', '.join(scope.topics) or '-'}"
    )
    if not results:
        console.print("No local evidence matched the query and selected filters.")
        return
    for citation, result in zip(citations, results, strict=True):
        chunk = result.chunk
        console.print(
            f"[bold][{citation.citation_id}][/bold] score={result.score:.6f} | {chunk.doc_id} | "
            f"{chunk.revision} | {chunk.document_type} | {chunk.source_format.upper()} | "
            f"{format_source_location(citation)}"
        )
        console.print(_console_safe(f"  domains: {', '.join(chunk.domains)}"))
        console.print(_console_safe(f"  topics: {', '.join(chunk.topics)}"))
        console.print(_console_safe(f"  section: {chunk.section}"))
        console.print(_console_safe(f"  source: {chunk.source_path}"))
        console.print(_console_safe(f"  citation: {format_citation(citation)}"))
        console.print(_console_safe(chunk.text))


@app.command("ask")
def ask(
    question: str = typer.Argument(..., help="Hardware question to answer from retrieved evidence."),
    domain: list[str] = typer.Option([], "--domain", help="Explicit domain; repeat for cross-domain search."),
    topic: list[str] = typer.Option([], "--topic", help="Controlled topic filter; repeatable."),
    interface: list[str] = typer.Option([], "--interface", help="Applicable interface filter; repeatable."),
    part: list[str] = typer.Option([], "--part", help="Applicable part filter; repeatable."),
    memory_type: str | None = typer.Option(None, "--memory-type", help="Compatible DDR type filter."),
    doc_id: str | None = typer.Option(None, "--doc-id", help="Filter by one registered document ID."),
    include_inactive: bool = typer.Option(False, "--include-inactive", help="Also search non-active documents."),
    limit: int | None = typer.Option(None, "--limit", min=1, help="Maximum evidence records to send to DeepSeek."),
    output_format: str = typer.Option("text", "--format", help="Output format: text or json."),
    config: Path = typer.Option(Path("config.yaml"), "--config", "-c", help="Configuration file."),
) -> None:
    """Answer from a locally routed scope using only retrieved, verified evidence."""

    if output_format not in {"text", "json"}:
        console.print("[red]--format must be 'text' or 'json'.[/red]")
        raise typer.Exit(code=2)
    try:
        settings = load_settings(config)
        scope = _resolve_cli_scope(
            settings,
            question,
            doc_id=doc_id,
            domains=domain,
            topics=topic,
            interfaces=interface,
            parts=part,
            memory_type=memory_type,
            include_inactive=include_inactive,
        )
        if scope.status != "resolved":
            _emit_clarification(scope, output_format)
            raise typer.Exit(code=2)
        answer = answer_question(settings, question, limit=limit, scope=scope)
    except typer.Exit:
        raise
    except (QueryScopeError, AnsweringError, RetrievalError, SparseIndexError, CitationError,
            FileNotFoundError, OSError, ValidationError) as exc:
        console.print(f"[red]Answering failed:[/red] {type(exc).__name__}: {exc}")
        raise typer.Exit(code=1) from exc

    if output_format == "json":
        retrieval_citations = build_citations(answer.retrieved)
        payload = {
            "route": scope.model_dump(mode="json"),
            "answer": answer.answer,
            "citations": [citation.model_dump(mode="json") for citation in answer.citations],
            "retrieved": [
                {"citation_id": citation.citation_id, **result.model_dump(mode="json")}
                for citation, result in zip(retrieval_citations, answer.retrieved, strict=True)
            ],
        }
        typer.echo(json.dumps(payload, ensure_ascii=True))
        return

    console.print(
        f"route: {', '.join(scope.domains)} | source={scope.routing_source} | "
        f"topics={', '.join(scope.topics) or '-'}"
    )
    console.print(_console_safe(answer.answer))
    if answer.citations:
        console.print("\n答案来源：")
        for citation in answer.citations:
            console.print(_console_safe(f"  {format_citation(citation)}"))
    else:
        console.print("\n本次没有可用于作答的引用来源。")


if __name__ == "__main__":
    app()
