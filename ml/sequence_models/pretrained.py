"""Optional initialization from local Step 6 Word2Vec or GloVe vectors."""

from pathlib import Path

import numpy as np
import torch
from gensim.models import KeyedVectors, Word2Vec

from ml.sequence_models.vocabulary import Vocabulary


def load_local_vectors(source: str, project_root: Path) -> KeyedVectors | None:
    """Load an already-present Word2Vec/GloVe file without starting a download."""
    if source not in {"word2vec", "glove"}:
        raise ValueError("source must be 'word2vec' or 'glove'.")
    root = project_root / "models" / source
    candidates = (
        sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix in {".model", ".kv", ".vec", ".txt"}
        )
        if root.exists()
        else []
    )
    if not candidates:
        return None
    path = candidates[0]
    if path.suffix == ".model":
        try:
            return Word2Vec.load(str(path)).wv
        except (AttributeError, ValueError):
            return KeyedVectors.load(str(path))
    if path.suffix == ".kv":
        return KeyedVectors.load(str(path))
    return KeyedVectors.load_word2vec_format(
        str(path),
        binary=False,
        no_header=path.name.lower().startswith("glove"),
    )


def make_embedding_matrix(
    vocabulary: Vocabulary, vectors: KeyedVectors
) -> torch.Tensor:
    """Copy matching pretrained vectors and leave unmatched rows randomly initialized."""
    dimension = vectors.vector_size
    matrix = (
        np.random.default_rng(472)
        .normal(loc=0.0, scale=0.05, size=(len(vocabulary), dimension))
        .astype(np.float32)
    )
    matrix[0] = 0.0
    for token, index in vocabulary.token_to_id.items():
        if token in vectors:
            matrix[index] = vectors[token]
    return torch.from_numpy(matrix)
