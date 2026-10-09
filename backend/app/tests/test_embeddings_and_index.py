"""Offline embeddings, text helpers, retries, and the FAISS vector store."""

import numpy as np
import pytest

from app.rag.providers.base import ProviderError
from app.rag.providers.local import HashingEmbeddingProvider
from app.rag.retry import call_with_retries
from app.rag.text import coverage, split_sentences, stem, terms
from app.rag.vector_store import FaissVectorStore, VectorIndexMismatchError, VectorStoreError

# --------------------------------------------------------------------------- text helpers


@pytest.mark.parametrize(
    ("word", "expected"),
    [
        ("refunds", "refund"),
        ("refunded", "refund"),
        ("shipping", "ship"),
        ("shipped", "ship"),
        ("billing", "bill"),
        ("policies", "policy"),
        ("boxes", "box"),
        ("address", "address"),
        ("status", "status"),
    ],
)
def test_stemming(word, expected):
    assert stem(word) == expected


def test_terms_drop_stop_words():
    assert terms("How do I get a refund for my order?") == ["refund", "order"]


def test_coverage_measures_how_much_of_the_question_the_passages_mention():
    passages = ["Refunds are issued to the original payment method within 7 days."]

    assert coverage("When will my refund arrive on my payment card?", passages) == pytest.approx(2 / 4)
    assert coverage("Do you sell gift cards?", passages) == 0.0
    assert coverage("???", passages) == 0.0


def test_split_sentences_handles_lists_and_prose():
    text = "Returns are free. Exchanges too!\n- Item one\n* Item two"

    assert split_sentences(text) == ["Returns are free.", "Exchanges too!", "Item one", "Item two"]


# --------------------------------------------------------------------------- local embeddings


def test_local_embeddings_are_deterministic_and_unit_length():
    provider = HashingEmbeddingProvider(dimensions=256)

    first = provider.embed_documents(["Refunds are processed in 5 days", "Shipping is free"])
    second = provider.embed_documents(["Refunds are processed in 5 days", "Shipping is free"])

    assert first.shape == (2, 256)
    assert first.dtype == np.float32
    np.testing.assert_array_equal(first, second)
    np.testing.assert_allclose(np.linalg.norm(first, axis=1), 1.0, rtol=1e-5)


def test_related_texts_are_more_similar_than_unrelated_ones():
    provider = HashingEmbeddingProvider()
    query = provider.embed_query("How long do refunds take?")
    refund, shipping = provider.embed_documents(
        [
            "Refund timing: approved refunds are processed within 5-7 business days.",
            "We ship to over 40 countries; international delivery takes 10 days.",
        ]
    )

    assert float(query @ refund) > float(query @ shipping) + 0.1


def test_signature_identifies_the_vector_space():
    assert HashingEmbeddingProvider(dimensions=128).signature == "local:hashing-v1:128"


# --------------------------------------------------------------------------- retries


def test_retryable_errors_are_retried_then_succeed():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise ProviderError("busy", retryable=True)
        return "ok"

    assert call_with_retries(flaky, retries=2, base_delay=0, sleep=lambda _: None) == "ok"
    assert len(calls) == 3


def test_retries_are_bounded():
    calls = []

    def always_busy():
        calls.append(1)
        raise ProviderError("busy", retryable=True)

    with pytest.raises(ProviderError):
        call_with_retries(always_busy, retries=2, base_delay=0, sleep=lambda _: None)
    assert len(calls) == 3  # first attempt + 2 retries


def test_permanent_errors_are_not_retried():
    calls = []

    def bad_key():
        calls.append(1)
        raise ProviderError("unauthorized", retryable=False)

    with pytest.raises(ProviderError):
        call_with_retries(bad_key, retries=5, base_delay=0, sleep=lambda _: None)
    assert len(calls) == 1


def test_backoff_grows_exponentially():
    delays = []

    def always_busy():
        raise ProviderError("busy", retryable=True)

    with pytest.raises(ProviderError):
        call_with_retries(always_busy, retries=3, base_delay=1.0, max_delay=100, sleep=delays.append)
    # Each delay is base * 2**attempt scaled by jitter in [0.5, 1].
    for attempt, delay in enumerate(delays):
        assert 0.5 * 2**attempt <= delay <= 2**attempt


# --------------------------------------------------------------------------- vector store

SIGNATURE = "test:model:4"


def _unit(*values: float) -> np.ndarray:
    vector = np.array(values, dtype=np.float32)
    return vector / np.linalg.norm(vector)


@pytest.fixture
def store(tmp_path):
    return FaissVectorStore(tmp_path / "index")


def test_empty_store_returns_no_results(store):
    assert store.search(_unit(1, 0, 0, 0), k=5, signature=SIGNATURE) == []
    assert store.status().exists is False


def test_search_ranks_by_cosine_similarity(store):
    store.replace(
        remove_ids=[],
        add_ids=[10, 20, 30],
        vectors=np.stack([_unit(1, 0, 0, 0), _unit(1, 1, 0, 0), _unit(0, 0, 1, 0)]),
        signature=SIGNATURE,
    )

    results = store.search(_unit(1, 0.1, 0, 0), k=2, signature=SIGNATURE)

    assert [chunk_id for chunk_id, _ in results] == [10, 20]
    assert results[0][1] > results[1][1]


def test_replace_swaps_old_vectors_for_new_ones(store):
    store.replace(remove_ids=[], add_ids=[1, 2], vectors=np.stack([_unit(1, 0, 0, 0), _unit(0, 1, 0, 0)]), signature=SIGNATURE)

    store.replace(remove_ids=[1], add_ids=[3], vectors=np.stack([_unit(1, 0, 0, 0)]), signature=SIGNATURE)

    hits = dict(store.search(_unit(1, 0, 0, 0), k=5, signature=SIGNATURE))
    assert 1 not in hits and 3 in hits
    assert store.status().vector_count == 2


def test_index_persists_and_other_instances_see_updates(store, tmp_path):
    store.replace(remove_ids=[], add_ids=[7], vectors=np.stack([_unit(0, 0, 0, 1)]), signature=SIGNATURE)
    other = FaissVectorStore(tmp_path / "index")  # e.g. the worker process

    assert other.search(_unit(0, 0, 0, 1), k=1, signature=SIGNATURE)[0][0] == 7

    other.remove([7])
    assert store.search(_unit(0, 0, 0, 1), k=1, signature=SIGNATURE) == []


def test_searching_with_another_embedding_model_is_refused(store):
    store.replace(remove_ids=[], add_ids=[1], vectors=np.stack([_unit(1, 0, 0, 0)]), signature=SIGNATURE)

    with pytest.raises(VectorIndexMismatchError):
        store.search(_unit(1, 0, 0, 0), k=1, signature="other:model:4")
    with pytest.raises(VectorIndexMismatchError):
        store.replace(remove_ids=[], add_ids=[2], vectors=np.stack([_unit(1, 0, 0, 0)]), signature="other:model:4")


def test_reset_starts_a_new_index_for_a_new_model(store):
    store.replace(remove_ids=[], add_ids=[1], vectors=np.stack([_unit(1, 0, 0, 0)]), signature=SIGNATURE)

    store.reset("other:model:4", dimensions=4)

    assert store.status().vector_count == 0
    assert store.status().signature == "other:model:4"
    assert store.search(_unit(1, 0, 0, 0), k=1, signature="other:model:4") == []


def test_corrupted_index_file_gives_a_clear_error(store):
    store.replace(remove_ids=[], add_ids=[1], vectors=np.stack([_unit(1, 0, 0, 0)]), signature=SIGNATURE)
    store.index_path.write_bytes(b"not a faiss index")

    with pytest.raises(VectorStoreError, match="corrupted"):
        FaissVectorStore(store.directory).search(_unit(1, 0, 0, 0), k=1, signature=SIGNATURE)
