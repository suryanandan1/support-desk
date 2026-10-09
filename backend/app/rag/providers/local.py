"""Offline embedding provider: no network, no API key, fully deterministic.

Each text becomes a bag of its content words, word pairs, and four-letter word pieces,
hashed into a fixed-size vector (the "hashing trick"). Texts that share vocabulary get
similar vectors. It does not understand synonyms the way a neural model does, so it is
meant for demo mode and tests, not as a substitute for a real embedding model.
"""

import hashlib
import math
from collections import Counter

import numpy as np

from app.rag.providers.base import EmbeddingProvider, normalize_rows
from app.rag.text import terms


def _features(text: str) -> Counter[str]:
    words = terms(text)
    features: Counter[str] = Counter(f"w:{w}" for w in words)
    features.update(f"b:{a}_{b}" for a, b in zip(words, words[1:], strict=False))
    # Word pieces make "shipping" and "shipped" partially match even when stemming misses.
    for word in words:
        padded = f"<{word}>"
        features.update(f"c:{padded[i:i + 4]}" for i in range(len(padded) - 3))
    return features


_WEIGHTS = {"w": 1.0, "b": 0.7, "c": 0.3}


class HashingEmbeddingProvider(EmbeddingProvider):
    name = "local"
    model = "hashing-v1"
    # Calibrated with `scripts/evaluate_rag.py --sweep` on the sample knowledge base:
    # 100% of should-escalate questions escalated, 3.6% false escalations (retrieval stage).
    default_min_score = 0.10
    default_min_top_score = 0.22

    def __init__(self, dimensions: int = 768) -> None:
        self.dimensions = dimensions

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimensions, dtype=np.float32)
        for feature, count in _features(text).items():
            digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            sign = 1.0 if value >> 63 else -1.0
            weight = _WEIGHTS[feature[0]] * (1.0 + math.log(count))
            vector[value % self.dimensions] += sign * weight
        return vector

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        return normalize_rows(np.stack([self._vector(t) for t in texts]))

    def embed_query(self, text: str) -> np.ndarray:
        return self.embed_documents([text])[0]
