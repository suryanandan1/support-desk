"""The Gemini provider, tested against a fake SDK client (no network, no API key)."""

from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from google.genai import errors as genai_errors

from app.core.config import get_settings
from app.rag.providers.base import ChatMessage, ProviderError, ProviderNotConfiguredError
from app.rag.providers.gemini import GeminiChatProvider, GeminiEmbeddingProvider


class FakeModels:
    def __init__(self, embed_results=None, generate_results=None):
        self.embed_results = list(embed_results or [])
        self.generate_results = list(generate_results or [])
        self.embed_calls = []
        self.generate_calls = []

    @staticmethod
    def _next(results):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def embed_content(self, *, model, contents, config):
        self.embed_calls.append({"model": model, "contents": contents, "config": config})
        return self._next(self.embed_results)

    def generate_content(self, *, model, contents, config):
        self.generate_calls.append({"model": model, "contents": contents, "config": config})
        return self._next(self.generate_results)


def fake_client(**kwargs):
    return SimpleNamespace(models=FakeModels(**kwargs))


def embed_response(count, dims):
    return SimpleNamespace(embeddings=[SimpleNamespace(values=[1.0] * dims) for _ in range(count)])


def api_error(code):
    return genai_errors.APIError(code, {"error": {"code": code, "message": "x", "status": "STATUS"}})


@pytest.fixture
def settings(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_dimensions", 8)
    monkeypatch.setattr(settings, "embedding_batch_size", 2)
    monkeypatch.setattr(settings, "llm_max_retries", 2)
    monkeypatch.setattr(settings, "llm_retry_base_delay_seconds", 0)
    return settings


def test_embeddings_are_batched_typed_and_normalised(settings):
    client = fake_client(embed_results=[embed_response(2, 8), embed_response(1, 8)])
    provider = GeminiEmbeddingProvider(settings, client=client)

    vectors = provider.embed_documents(["a", "b", "c"])

    calls = client.models.embed_calls
    assert [c["contents"] for c in calls] == [["a", "b"], ["c"]]
    assert calls[0]["config"].task_type == "RETRIEVAL_DOCUMENT"
    assert calls[0]["config"].output_dimensionality == 8
    assert vectors.shape == (3, 8)
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1.0, rtol=1e-5)


def test_query_embeddings_use_the_query_task_type(settings):
    client = fake_client(embed_results=[embed_response(1, 8)])

    GeminiEmbeddingProvider(settings, client=client).embed_query("question")

    assert client.models.embed_calls[0]["config"].task_type == "RETRIEVAL_QUERY"


def test_wrong_embedding_size_is_reported(settings):
    client = fake_client(embed_results=[embed_response(1, 4)])

    with pytest.raises(ProviderError, match="EMBEDDING_DIMENSIONS"):
        GeminiEmbeddingProvider(settings, client=client).embed_documents(["a"])


def test_rate_limits_are_retried(settings):
    client = fake_client(embed_results=[api_error(429), api_error(503), embed_response(1, 8)])

    GeminiEmbeddingProvider(settings, client=client).embed_documents(["a"])

    assert len(client.models.embed_calls) == 3


def test_retries_stop_after_the_configured_limit(settings):
    client = fake_client(generate_results=[httpx.ReadTimeout("slow")] * 5)

    with pytest.raises(ProviderError, match="timed out") as raised:
        GeminiChatProvider(settings, client=client).generate("system", [ChatMessage("user", "hi")])

    assert raised.value.retryable is True
    assert len(client.models.generate_calls) == 3  # 1 + LLM_MAX_RETRIES


def test_authentication_errors_are_not_retried(settings):
    client = fake_client(generate_results=[api_error(403), "never reached"])

    with pytest.raises(ProviderError, match="GEMINI_API_KEY") as raised:
        GeminiChatProvider(settings, client=client).generate("system", [ChatMessage("user", "hi")])

    assert raised.value.retryable is False
    assert len(client.models.generate_calls) == 1


def test_chat_maps_roles_and_passes_generation_settings(settings):
    client = fake_client(generate_results=[SimpleNamespace(text="Answer [1]")])

    reply = GeminiChatProvider(settings, client=client).generate(
        "Be grounded.", [ChatMessage("user", "Q1"), ChatMessage("assistant", "A1"), ChatMessage("user", "Q2")]
    )

    call = client.models.generate_calls[0]
    assert reply == "Answer [1]"
    assert [c.role for c in call["contents"]] == ["user", "model", "user"]
    assert call["config"].system_instruction == "Be grounded."
    assert call["config"].temperature == settings.llm_temperature


def test_empty_replies_are_errors(settings):
    client = fake_client(generate_results=[SimpleNamespace(text=None)])

    with pytest.raises(ProviderError, match="empty"):
        GeminiChatProvider(settings, client=client).generate("s", [ChatMessage("user", "hi")])


def test_missing_api_key_is_a_clear_configuration_error(settings, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", None)

    with pytest.raises(ProviderNotConfiguredError, match="GEMINI_API_KEY"):
        GeminiEmbeddingProvider(settings).embed_query("question")
