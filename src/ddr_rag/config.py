"""Project configuration loading and path resolution."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator


class KnowledgeBaseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    collection_name: str


class PathSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw: Path
    catalog: Path
    parsed: Path
    chunks: Path
    index: Path
    prompts: Path
    logs: Path
    evaluations: Path


class ParserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    engine: str = "docling"
    enable_ocr: bool = False
    enable_table_structure: bool = True
    device: str = Field(default="cpu", pattern=r"^(auto|cpu|cuda(?::\d+)?)$")
    num_threads: int = Field(default=4, ge=1, le=64)
    document_timeout_seconds: int = Field(default=1800, ge=60, le=7200)
    page_batch_size: int = Field(default=8, ge=1, le=50)
    export_markdown: bool = True
    export_json: bool = True


class ChunkingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: str = "docling_hybrid"
    max_tokens: int = Field(default=600, ge=50, le=8192)
    tokenizer_encoding: str = Field(default="cl100k_base", min_length=1)
    merge_peers: bool = True
    repeat_table_header: bool = True


class EmbeddingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str
    device: str = "cuda:0"
    batch_size: int = Field(default=8, ge=1, le=128)
    max_length: int = Field(default=1024, ge=1, le=8192)
    normalize_vectors: bool = True
    use_fp16: bool = True
    model_cache: Path = Path("data/models/bge-m3")
    output_subdir: str = Field(default="bge-m3", pattern=r"^[A-Za-z0-9._-]+$")


class VectorStoreSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = "qdrant_local"
    path: Path = Path("data/index/qdrant")
    distance: str = "cosine"
    batch_size: int = Field(default=64, ge=1, le=512)


class SparseSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str = "bm25_local"
    path: Path = Path("data/index/bm25")
    k1: float = Field(default=1.5, gt=0, le=5)
    b: float = Field(default=0.75, ge=0, le=1)


class RetrievalSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = "hybrid"
    dense_candidates: int = Field(default=20, gt=0)
    sparse_candidates: int = Field(default=20, gt=0)
    final_top_k: int = Field(default=6, gt=0)
    rrf_k: int = Field(default=60, gt=0, le=500)
    active_documents_only: bool = True

    @model_validator(mode="after")
    def check_candidate_count(self) -> "RetrievalSettings":
        if self.final_top_k > self.dense_candidates + self.sparse_candidates:
            raise ValueError("final_top_k cannot exceed the total candidate count")
        return self


class GenerationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    provider: str
    model: str
    base_url: str = "https://api.deepseek.com"
    api_key_env: str = Field(default="DEEPSEEK_API_KEY", pattern=r"^[A-Z][A-Z0-9_]*$")
    reasoning_effort: str = "none"
    max_output_tokens: int = Field(default=1800, gt=0)
    max_evidence_chunks: int = Field(default=6, ge=1, le=20)
    request_timeout_seconds: int = Field(default=60, ge=1, le=600)


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    save_retrieved_chunks: bool = True
    save_answers: bool = True


class ClassificationSettings(BaseModel):
    """Optional V2 mapping; legacy V1.2 configs intentionally leave it disabled."""

    model_config = ConfigDict(extra="forbid")
    taxonomy_version: str = "hardware-v2-taxonomy-v1"
    mapping: Path | None = None
    require_document_mapping: bool = False


class AppSettings(BaseModel):
    """Validated application settings plus an absolute project root."""

    model_config = ConfigDict(extra="forbid")
    project_root: Path = Field(exclude=True)
    knowledge_base: KnowledgeBaseSettings
    paths: PathSettings
    parser: ParserSettings
    chunking: ChunkingSettings
    embedding: EmbeddingSettings
    vector_store: VectorStoreSettings
    sparse: SparseSettings
    retrieval: RetrievalSettings
    generation: GenerationSettings
    logging: LoggingSettings
    classification: ClassificationSettings = Field(default_factory=ClassificationSettings)

    def resolve_path(self, value: Path) -> Path:
        return value.resolve() if value.is_absolute() else (self.project_root / value).resolve()

    @property
    def raw_path(self) -> Path:
        return self.resolve_path(self.paths.raw)

    @property
    def catalog_path(self) -> Path:
        return self.resolve_path(self.paths.catalog)


def _default_project_root() -> Path:
    configured_root = os.getenv("DDR_RAG_PROJECT_ROOT")
    if configured_root:
        return Path(configured_root).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def load_settings(config_path: Path | str | None = None) -> AppSettings:
    """Load YAML configuration and optional values from the project .env file."""

    if config_path is None:
        project_root = _default_project_root()
        resolved_config = project_root / "config.yaml"
    else:
        resolved_config = Path(config_path).expanduser().resolve()
        project_root = resolved_config.parent

    load_dotenv(project_root / ".env", override=False)
    with resolved_config.open("r", encoding="utf-8") as stream:
        raw_config = yaml.safe_load(stream) or {}
    return AppSettings(project_root=project_root, **raw_config)
