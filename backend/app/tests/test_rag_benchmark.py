"""Regression guard: the offline RAG pipeline must keep its measured quality.

Runs the full evaluation dataset (eval/dataset.json) against the sample knowledge base
with the offline providers. If a change lowers these numbers, this test fails; run
`python scripts/evaluate_rag.py` to see which questions changed.
"""

from app.rag.benchmark import compute_metrics, load_dataset, load_sample_knowledge_base, run_cases


def test_offline_pipeline_quality_does_not_regress(db):
    documents = load_sample_knowledge_base(db)
    assert {d.status.value for d in documents} == {"indexed"}

    metrics = compute_metrics(run_cases(db, load_dataset()))

    assert metrics["cases"] >= 30
    assert metrics["retrieval_hit_rate"] >= 0.95
    assert metrics["citation_precision"] >= 0.95
    assert metrics["correct_escalation_rate"] == 1.0  # never answer what the documents don't cover
    assert metrics["false_escalation_rate"] <= 0.1
    assert metrics["human_request_detection"] == 1.0
    assert metrics["decision_accuracy"] >= 0.9
    assert metrics["fact_match_rate"] >= 0.85
    assert metrics["provider_failure_rate"] == 0.0
