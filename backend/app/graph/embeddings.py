"""EmbeddingProvider interface (rule 6) + implementations.

- HashingEmbedder: deterministic, dependency-free token-hashing embeddings.
  Dev/test default; behaves like a bag-of-words similarity. NOT for prod chat
  quality (tech-spec debt #1).
- FastEmbedProvider: local ONNX model (bge-small class) when the optional
  `fastembed` package + model weights are available.
`embed_model` is persisted with every vector so mixed corpora are detectable
and re-embeddable (spec S3).
"""
import hashlib
import math
from typing import Protocol

from app.core.config import get_settings


class EmbeddingProvider(Protocol):
    model_id: str
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    model_id = "hashing-384-v1"

    def __init__(self, dim: int = 384) -> None:
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vec = [0.0] * self._dim
            for token in text.lower().split():
                token = token.strip(".,;:()[]\"'")
                if len(token) < 2:
                    continue
                h = int.from_bytes(hashlib.md5(token.encode()).digest()[:4], "big")
                vec[h % self._dim] += 1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class FastEmbedProvider:
    model_id = "bge-small-en-v1.5"

    def __init__(self) -> None:
        from fastembed import TextEmbedding  # optional dependency
        self._model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))  # vectors are pre-normalized


def build_embedder() -> EmbeddingProvider:
    s = get_settings()
    if s.embedding_provider == "fastembed":
        return FastEmbedProvider()
    return HashingEmbedder(dim=s.embedding_dim)
