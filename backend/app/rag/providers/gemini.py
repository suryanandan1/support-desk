"""Google Gemini implementation of the chat and embedding interfaces (google-genai SDK).

Every SDK error is translated into ProviderError, so callers never handle vendor
exceptions. Retries are done here with our own bounded backoff; the SDK's built-in
retries stay off so the two never multiply.
"""

import logging
from collections.abc import Iterator
from typing import Any

import httpx
import numpy as np
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import Settings
from app.rag.providers.base import (
    ChatMessage,
    ChatProvider,
    EmbeddingProvider,
    ProviderError,
    ProviderNotConfiguredError,
    normalize_rows,
)
from app.rag.retry import call_with_retries

logger = logging.getLogger(__name__)

# Rate limits, timeouts and server-side failures can succeed on a later attempt.
_RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def _translate_error(exc: Exception) -> ProviderError:
    """Map an SDK or transport exception to ProviderError without leaking details."""
    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, genai_errors.APIError):
        status = f" {exc.status}" if getattr(exc, "status", None) else ""
        message = f"Gemini API error {exc.code}{status}"
        if exc.code in (401, 403):
            message += " (check GEMINI_API_KEY)"
        elif exc.code == 404:
            message += " (model not found; run scripts/check_provider.py)"
        return ProviderError(message, retryable=exc.code in _RETRYABLE_STATUS_CODES)
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError("Gemini request timed out", retryable=True)
    if isinstance(exc, httpx.TransportError):
        return ProviderError("Could not connect to the Gemini API", retryable=True)
    return ProviderError(f"Unexpected Gemini error ({type(exc).__name__})", retryable=False)


def _batches(items: list[str], size: int) -> Iterator[list[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class _GeminiBase:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client  # tests inject a fake client here

    def _get_client(self) -> Any:
        if self._client is None:
            key = self._settings.gemini_api_key
            if key is None or not key.get_secret_value().strip():
                raise ProviderNotConfiguredError(
                    "GEMINI_API_KEY is not set. Add it to backend/.env, or use "
                    "LLM_PROVIDER=demo and EMBEDDING_PROVIDER=local to run offline."
                )
            self._client = genai.Client(
                api_key=key.get_secret_value().strip(),
                http_options=types.HttpOptions(
                    timeout=int(self._settings.llm_timeout_seconds * 1000)
                ),
            )
        return self._client

    def _with_retries(self, func: Any, description: str) -> Any:
        def attempt() -> Any:
            try:
                return func()
            except Exception as exc:  # noqa: BLE001 - translated below, never swallowed
                raise _translate_error(exc) from exc

        return call_with_retries(
            attempt,
            retries=self._settings.llm_max_retries,
            base_delay=self._settings.llm_retry_base_delay_seconds,
            description=description,
        )


class GeminiEmbeddingProvider(_GeminiBase, EmbeddingProvider):
    name = "gemini"
    # Starting points only: gemini-embedding-001 scores were not calibrated on this
    # knowledge base. Run scripts/evaluate_rag.py --sweep with a key to tune them.
    default_min_score = 0.50
    default_min_top_score = 0.60

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        super().__init__(settings, client)
        self.model = settings.gemini_embedding_model
        self.dimensions = settings.embedding_dimensions

    def _embed(self, texts: list[str], task_type: str) -> np.ndarray:
        vectors: list[list[float]] = []
        for batch in _batches(texts, self._settings.embedding_batch_size):

            def call(batch: list[str] = batch) -> list[list[float]]:
                response = self._get_client().models.embed_content(
                    model=self.model,
                    contents=batch,
                    config=types.EmbedContentConfig(
                        task_type=task_type, output_dimensionality=self.dimensions
                    ),
                )
                embeddings = response.embeddings or []
                if len(embeddings) != len(batch):
                    raise ProviderError("Gemini returned the wrong number of embeddings")
                return [list(e.values or []) for e in embeddings]

            vectors.extend(self._with_retries(call, "Gemini embedding"))

        array = np.asarray(vectors, dtype=np.float32)
        if array.shape != (len(texts), self.dimensions):
            raise ProviderError(
                f"Gemini returned embeddings of shape {array.shape}; expected "
                f"({len(texts)}, {self.dimensions}). Check EMBEDDING_DIMENSIONS."
            )
        # Reduced-dimension Gemini embeddings are not unit length; normalise them.
        return normalize_rows(array)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_query(self, text: str) -> np.ndarray:
        return self._embed([text], "RETRIEVAL_QUERY")[0]


class GeminiChatProvider(_GeminiBase, ChatProvider):
    name = "gemini"

    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        super().__init__(settings, client)
        self.model = settings.gemini_chat_model

    def generate(self, system_prompt: str, messages: list[ChatMessage]) -> str:
        contents = [
            types.Content(
                role="user" if message.role == "user" else "model",
                parts=[types.Part(text=message.content)],
            )
            for message in messages
        ]
        config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=self._settings.llm_temperature,
            max_output_tokens=self._settings.llm_max_output_tokens,
        )

        def call() -> str:
            response = self._get_client().models.generate_content(
                model=self.model, contents=contents, config=config
            )
            text = response.text
            if not text or not text.strip():
                # Typically a safety block or the token limit being used up by "thinking".
                raise ProviderError("Gemini returned an empty response", retryable=False)
            return text

        return self._with_retries(call, "Gemini generation")
