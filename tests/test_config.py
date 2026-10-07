from pathlib import Path

import pytest
from pydantic import ValidationError

from ddr_rag.config import load_settings


def write_config(path: Path, max_tokens: int = 600) -> None:
    path.write_text(
        f"""
knowledge_base:
  name: test
  collection_name: test
paths:
  raw: data/raw
  catalog: data/catalog/documents.yaml
  parsed: data/parsed
  chunks: data/chunks/chunks.jsonl
  index: data/index
  prompts: prompts
  logs: logs
  evaluations: evals
parser:
  engine: docling
  enable_ocr: false
  enable_table_structure: true
  device: cpu
  num_threads: 4
  document_timeout_seconds: 1800
  page_batch_size: 8
  export_markdown: true
  export_json: true
chunking:
  strategy: docling_hybrid
  max_tokens: {max_tokens}
  tokenizer_encoding: cl100k_base
  merge_peers: true
  repeat_table_header: true
embedding:
  provider: openai
  model: text-embedding-3-small
  device: cuda:0
  batch_size: 8
  max_length: 1024
  normalize_vectors: true
  use_fp16: true
  model_cache: data/models/bge-m3
  output_subdir: bge-m3
vector_store:
  provider: qdrant_local
  path: data/index/qdrant
  distance: cosine
  batch_size: 64
sparse:
  provider: bm25_local
  path: data/index/bm25
  k1: 1.5
  b: 0.75
retrieval:
  mode: hybrid
  dense_candidates: 20
  sparse_candidates: 20
  final_top_k: 6
  rrf_k: 60
  active_documents_only: true
generation:
  enabled: false
  provider: openai
  model: gpt-5.6-luna
  reasoning_effort: none
  max_output_tokens: 1800
logging:
  save_retrieved_chunks: true
  save_answers: true
""".strip(),
        encoding="utf-8",
    )


def test_load_settings_resolves_project_paths(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    assert settings.project_root == tmp_path.resolve()
    assert settings.raw_path == (tmp_path / "data/raw").resolve()
    assert settings.catalog_path == (tmp_path / "data/catalog/documents.yaml").resolve()


def test_invalid_chunk_size_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path, max_tokens=10)
    with pytest.raises(ValidationError):
        load_settings(config_path)


def test_invalid_parser_device_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("device: cpu", "device: gpu"),
        encoding="utf-8",
    )
    with pytest.raises(ValidationError):
        load_settings(config_path)
