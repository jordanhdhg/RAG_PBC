from pathlib import Path

import numpy as np
import pytest

from ddr_rag.embedder import EmbeddingError, validate_embedding_artifact, write_embedding_artifact
from ddr_rag.config import load_settings
from ddr_rag.schemas import ChunkRecord
from test_config import write_config


def make_record() -> ChunkRecord:
    return ChunkRecord(
        chunk_id="TEST:000000:abc",
        doc_id="TEST",
        text="DDR layout rule",
        title="Test guide",
        revision="R1",
        source_path=Path("data/raw/vendor/guide.pdf"),
        section="DDR",
        page_numbers=[1],
        page_start=1,
        page_end=1,
        memory_types=["DDR4"],
        status="active",
        token_count=3,
    )


def test_embedding_artifact_preserves_vector_to_chunk_mapping(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    vectors = np.zeros((1, 1024), dtype=np.float32)
    vectors[0, 0] = 1.0

    paths = write_embedding_artifact(settings, [make_record()], "a" * 64, vectors)
    validation = validate_embedding_artifact(settings)

    assert paths["vectors"].is_file()
    assert validation == {"chunk_count": 1, "dimension": 1024, "norm_min": 1.0, "norm_max": 1.0}


def test_embedding_artifact_requires_explicit_replace(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    write_config(config_path)
    settings = load_settings(config_path)
    vectors = np.zeros((1, 1024), dtype=np.float32)
    vectors[0, 0] = 1.0
    write_embedding_artifact(settings, [make_record()], "a" * 64, vectors)

    with pytest.raises(EmbeddingError, match="already exists"):
        write_embedding_artifact(settings, [make_record()], "a" * 64, vectors)
