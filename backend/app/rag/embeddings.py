"""Chooses the embedding provider from settings (EMBEDDING_PROVIDER)."""

from functools import lru_cache

from app.core.config import get_settings
from app.rag.providers.base import EmbeddingProvider


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embedding_provider == "local":
        from app.rag.providers.local import HashingEmbeddingProvider

        return HashingEmbeddingProvider(settings.embedding_dimensions)

    from app.rag.providers.gemini import GeminiEmbeddingProvider

    return GeminiEmbeddingProvider(settings)


def retrieval_thresholds(provider: EmbeddingProvider) -> tuple[float, float]:
    """Return ``(min_score, min_top_score)``: settings if given, else provider defaults."""
    settings = get_settings()
    min_score = (
        settings.retrieval_min_score
        if settings.retrieval_min_score is not None
        else provider.default_min_score
    )
    min_top_score = (
        settings.escalation_min_top_score
        if settings.escalation_min_top_score is not None
        else provider.default_min_top_score
    )
    return min_score, max(min_top_score, min_score)
