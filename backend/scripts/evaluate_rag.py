"""Evaluate the RAG pipeline on eval/dataset.json using the sample knowledge base.

Everything runs in a temporary database and index; your real data is never touched.

Usage (from backend/, virtual environment active):
    python scripts/evaluate_rag.py                     # offline: demo answers + local embeddings
    python scripts/evaluate_rag.py --providers gemini  # real Gemini (needs GEMINI_API_KEY)
    python scripts/evaluate_rag.py --sweep             # threshold calibration table
    python scripts/evaluate_rag.py --json report.json  # also save the full report
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def _configure_environment(providers: str, workdir: Path, thresholds: dict[str, float | None]) -> None:
    # Must run before any "app" import: settings are read once at import time.
    os.environ.update(
        {
            "DATABASE_URL": f"sqlite:///{(workdir / 'eval.db').as_posix()}",
            "UPLOAD_DIR": str(workdir / "uploads"),
            "VECTOR_INDEX_DIR": str(workdir / "index"),
            "LOG_LEVEL": "WARNING",
        }
    )
    os.environ.setdefault("SECRET_KEY", "evaluation-only-secret-key-not-used-for-tokens-123")
    if providers == "offline":
        # Offline runs ignore backend/.env, so thresholds tuned for Gemini cannot leak in.
        os.environ.update({"APP_ENV_FILE": "none", "LLM_PROVIDER": "demo", "EMBEDDING_PROVIDER": "local"})
    else:
        os.environ.update({"LLM_PROVIDER": "gemini", "EMBEDDING_PROVIDER": "gemini"})
    for name, value in thresholds.items():
        if value is not None:
            os.environ[name] = str(value)


def _print_metrics(metrics: dict) -> None:
    print("\nMetrics")
    for key, value in metrics.items():
        shown = f"{value:.1%}" if isinstance(value, float) and key.endswith(("rate", "accuracy", "precision", "detection")) else value
        print(f"  {key:<26} {shown}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--providers", choices=["offline", "gemini"], default="offline")
    parser.add_argument("--sweep", action="store_true", help="print a threshold calibration table")
    parser.add_argument("--json", type=Path, help="write the full report to this file")
    parser.add_argument("--min-score", type=float, help="override RETRIEVAL_MIN_SCORE")
    parser.add_argument("--min-top-score", type=float, help="override ESCALATION_MIN_TOP_SCORE")
    parser.add_argument("--min-coverage", type=float, help="override ESCALATION_MIN_COVERAGE")
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="rag-eval-"))
    _configure_environment(
        args.providers,
        workdir,
        {
            "RETRIEVAL_MIN_SCORE": args.min_score,
            "ESCALATION_MIN_TOP_SCORE": args.min_top_score,
            "ESCALATION_MIN_COVERAGE": args.min_coverage,
        },
    )
    sys.path.insert(0, str(BACKEND))

    from app.core.logging import setup_logging
    from app.db.base import Base
    from app.db.session import SessionLocal, engine
    from app.rag.benchmark import (
        compute_metrics,
        load_dataset,
        load_sample_knowledge_base,
        run_cases,
        sweep_thresholds,
    )
    from app.rag.embeddings import get_embedding_provider, retrieval_thresholds
    from app.rag.generation import get_answer_generator

    setup_logging("WARNING")
    try:
        Base.metadata.create_all(engine)
        with SessionLocal() as db:
            documents = load_sample_knowledge_base(db)
            failed = [d.original_filename for d in documents if d.status.value != "indexed"]
            if failed:
                print(f"Could not index: {failed}. Check provider configuration.")
                return 1
            embedder, generator = get_embedding_provider(), get_answer_generator()
            min_score, min_top = retrieval_thresholds(embedder)
            print(f"Embeddings: {embedder.signature} | Answers: {generator.name}:{generator.model}")
            print(f"Thresholds: min_score={min_score} min_top_score={min_top}")
            print(f"Indexed {len(documents)} sample documents")

            cases = load_dataset()
            results = run_cases(db, cases)
            metrics = compute_metrics(results)

            wrong = [r for r in results if not r.correct_decision or (r.answered and not r.facts_present)]
            print(f"\nCases needing attention ({len(wrong)} of {len(results)}):")
            for r in wrong:
                verdict = "answered" if r.answered else f"escalated ({r.reason})"
                issue = "wrong decision" if not r.correct_decision else "missing facts"
                print(f"  [{r.case.kind}] {r.case.id}: {verdict}, expected {r.case.expected} - {issue}")
            _print_metrics(metrics)

            report = {"metrics": metrics, "cases": [
                {"id": r.case.id, "kind": r.case.kind, "expected": r.case.expected, "answered": r.answered,
                 "reason": r.reason, "cited": r.cited_documents, "retrieved": r.retrieved_documents,
                 "groundedness": r.groundedness, "answer": r.answer}
                for r in results
            ]}
            if args.sweep:
                grid = [round(x * 0.01, 2) for x in range(4, 61, 2)]
                rows = sweep_thresholds(
                    db, cases, min_scores=grid, min_top_scores=grid, coverages=[0.0, 0.2, 0.3, 0.4, 0.5]
                )
                print("\nThreshold sweep (retrieval-stage decision only), best first:")
                print("  min_score  min_top  coverage  correct_esc  false_esc  balanced")
                for row in rows[:12]:
                    marker = "  <- current" if row["current"] else ""
                    print(
                        f"  {row['min_score']:<9}  {row['min_top_score']:<7}  {row['min_coverage']:<8}  "
                        f"{row['correct_escalation_rate']:<11.1%}  {row['false_escalation_rate']:<9.1%}  "
                        f"{row['balanced_accuracy']:.1%}{marker}"
                    )
                current = [r for r in rows if r["current"]]
                if current and current[0] not in rows[:12]:
                    row = current[0]
                    print(f"  current settings: balanced {row['balanced_accuracy']:.1%} "
                          f"(correct {row['correct_escalation_rate']:.1%}, false {row['false_escalation_rate']:.1%})")
                report["sweep"] = rows[:50]
            if args.json:
                args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(f"\nReport written to {args.json}")
        return 0
    finally:
        engine.dispose()
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
