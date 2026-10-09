"""Interfaces every AI provider implements, plus the errors they may raise.

Nothing outside app/rag/providers imports a vendor SDK, so switching providers means
writing one new class here, not rewriting the application.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

import numpy as np


class ProviderError(Exception):
    """An AI provider call failed.

    ``retryable`` is True for temporary problems (timeouts, rate limits, 5xx) where
    trying again may succeed, and False for ones that will not fix themselves.
    The message is safe to log and to store: it never contains keys or prompts.
    """

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class ProviderNotConfiguredError(ProviderError):
    """The provider cannot be used at all, e.g. its API key is missing."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


@dataclass(frozen=True)
class ChatMessage:
    role: Literal["user", "assistant"]
    content: str


class EmbeddingProvider(ABC):
    """Turns text into unit-length vectors, so a dot product is cosine similarity."""

    name: str
    model: str
    dimensions: int
    # Similarity scales differ between embedding models, so each provider supplies
    # its own default thresholds (overridden by RETRIEVAL_MIN_SCORE and
    # ESCALATION_MIN_TOP_SCORE when those are set).
    default_min_score: float
    default_min_top_score: float

    @property
    def signature(self) -> str:
        """Identifies the vector space. Vectors with different signatures are incompatible."""
        return f"{self.name}:{self.model}:{self.dimensions}"

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> np.ndarray:
        """Return a float32 array of shape (len(texts), dimensions)."""

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray:
        """Return a float32 array of shape (dimensions,)."""


class ChatProvider(ABC):
    """Generates text from a system prompt and a list of conversation turns."""

    name: str
    model: str

    @abstractmethod
    def generate(self, system_prompt: str, messages: list[ChatMessage]) -> str:
        """Return the model's reply. Raises ProviderError on failure."""


def normalize_rows(vectors: np.ndarray) -> np.ndarray:
    """Scale each row to unit length (rows of zeros are left as zeros)."""
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms
