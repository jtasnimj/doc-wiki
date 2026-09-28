"""Source-verified extraction/retrieval evaluation and opt-in live answer review.

Reference answers are used only after retrieval/generation, never by the providers.
Offline hash embeddings exercise plumbing, not OpenAI retrieval or answer quality.
"""

import argparse
import asyncio
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

from doc_wiki.config import Settings
from doc_wiki.contracts import Extraction, ModelAnswer, Question
from doc_wiki.errors import AppError
from doc_wiki.offline import FakeProvider
from doc_wiki.providers import OpenAIProvider
from doc_wiki.service import QAService, validate_answer


def normalize(text):
    return " ".join(text.replace("\u200b", "").lower().split())


def matches(evidence, requirement):
    passages = [(evidence.text, evidence.location)] + [
        (context.text, context.location) for context in evidence.context
    ]
    for text, loc in passages:
        if "pages" in requirement and loc.page not in requirement["pages"]:
            continue
        if "json_path" in requirement and loc.json_path != requirement["json_path"]:
            continue
        if all(normalize(term) in normalize(text) for term in requirement["contains"]):
            return True
    return False


def coverage(evidence, requirements):
    return [any(matches(item, requirement) for item in evidence) for requirement in requirements]


def usage_cost(records):
    """Documented text-only standard rates; estimates, not account-balance evidence."""
    total = 0.0
    for record in records:
        usage = record.get("usage") or {}
        if record["operation"] == "embedding":
            total += usage.get("total_tokens", 0) * 0.02 / 1_000_000
        else:
            total += (
                usage.get("input_tokens", 0) * 0.15 + usage.get("output_tokens", 0) * 0.60
            ) / 1_000_000
    return round(total, 6)


def summarize(rows, live):
    eligible = [row for row in rows if row.get("required_evidence_count", 0)]
    completed = [row for row in rows if "answer" in row]
    positives = [row for row in completed if row["expected_status"] != "not_found"]
    negatives = [row for row in completed if row["expected_status"] == "not_found"]

    def rate(items, key):
        return sum(bool(row.get(key)) for row in items) / len(items) if items else None

    return {
        "cases": len(rows),
        "skipped": sum("skipped" in r for r in rows),
        "extraction_all_required_coverage": rate(eligible, "extraction_all_required"),
        "retrieval_evidence_hit_at_6": rate(eligible, "retrieval_seed_any_required"),
        "retrieval_seed_all_required_coverage": rate(eligible, "retrieval_seed_all_required"),
        "retrieval_all_required_coverage": rate(eligible, "retrieval_all_required"),
        "citation_validity": rate(completed, "citation_valid"),
        "status_accuracy": rate(completed, "status_correct") if live else None,
        "not_found_accuracy": rate(negatives, "status_correct") if live else None,
        "false_abstention_rate": rate(positives, "false_abstention") if live else None,
        "factual_correctness": "manual review pending"
        if live
        else "not measured with fake provider",
        "citation_support": "manual review pending" if live else "not measured with fake provider",
    }


async def evaluate(args):
    config = Settings()
    root = Path(args.source_root).resolve()
    all_cases = json.loads((root / "evaluation/cases.json").read_text())
    cases = [c for c in all_cases if args.split == "all" or c["split"] == args.split]
    live = args.mode == "live"
    source_names = {c["source"] for c in cases} | {
        c["distractor_source"] for c in cases if "distractor_source" in c
    }
    # Worst configured chunk count for every source, full text context/output, and one retry.
    estimate = 2 * (
        len(source_names) * 2000 * 700 * 0.02 / 1_000_000
        + len(cases) * (2000 * 0.02 + 8000 * 0.15 + 1200 * 0.60) / 1_000_000
    )
    if config.question_planning:
        estimate += 2 * len(cases) * (2400 * 0.15 + 1600 * 0.60) / 1_000_000
    if args.mode == "estimate":
        return {
            "case_count": len(cases),
            "unique_sources": len(source_names),
            "conservative_text_cost_ceiling_usd": round(estimate, 4),
            "vision": False,
            "question_planning": config.question_planning,
            "calls_made": 0,
            "note": "Includes one retry; verify current rates before approval.",
        }
    if live and (os.getenv("DOCWIKI_LIVE_APPROVED") != "1" or args.budget_usd < estimate):
        raise SystemExit(
            "Live run requires explicit approval, DOCWIKI_LIVE_APPROVED=1 "
            f"and --budget-usd >= {estimate:.4f}. No calls made."
        )
    rows = []
    with tempfile.TemporaryDirectory(prefix="docwiki-eval-") as folder:
        settings = Settings(
            data_dir=Path(folder) / "data",
            embedding_dimensions=1536 if live else 64,
            vision_enabled=False,
        )
        provider = OpenAIProvider(settings, record_usage=True) if live else FakeProvider()
        if live and not settings.openai_api_key:
            raise SystemExit("OPENAI_API_KEY is required for an approved live run.")
        service = QAService(settings, provider)
        await service.start()
        try:
            for case in cases:
                source = root / case["source"]
                row = {
                    "id": case["id"],
                    "split": case["split"],
                    "source": case["source"],
                    "source_sha256": case["source_sha256"],
                    "expected_status": case["expected_status"],
                }
                rows.append(row)
                if not source.exists():
                    row["skipped"] = (
                        "Source unavailable locally; no third-party samples are distributed."
                    )
                    continue
                raw = source.read_bytes()
                if hashlib.sha256(raw).hexdigest() != case["source_sha256"]:
                    row["skipped"] = "Source hash mismatch; gold references require source review."
                    continue
                started = time.monotonic()
                try:
                    doc = await service.ingest(raw, "pdf" if source.suffix == ".pdf" else "json")
                    if "distractor_source" in case:
                        distractor = (root / case["distractor_source"]).read_bytes()
                        if hashlib.sha256(distractor).hexdigest() != case["distractor_sha256"]:
                            raise ValueError("Distractor source hash mismatch")
                        await service.ingest(distractor, "json")
                    extraction = Extraction.model_validate_json(
                        (service.store.directory(doc.document_id) / "extraction.json").read_text()
                    )
                    plan = (
                        await provider.plan(case["question"])
                        if settings.question_planning
                        else None
                    )
                    vector = await service.store.embedder.aget_query_embedding(case["question"])
                    evidence = await service.store.run(
                        service.store.retrieve, doc.document_id, case["question"], vector
                    )
                    required = case["required_evidence"]
                    extracted_coverage = coverage(extraction.blocks, required)
                    retrieved_coverage = coverage(evidence, required)
                    seeds = [e for e in evidence if e.retrieval_role == "seed"][:6]
                    seed_coverage = coverage(seeds, required)
                    row.update(
                        required_evidence_count=len(required),
                        extraction_all_required=all(extracted_coverage) if required else None,
                        retrieval_seed_any_required=any(seed_coverage) if required else None,
                        retrieval_seed_all_required=all(seed_coverage) if required else None,
                        retrieval_any_required=any(retrieved_coverage) if required else None,
                        retrieval_all_required=all(retrieved_coverage) if required else None,
                        retrieved=[e.model_dump() for e in evidence],
                        warnings=doc.warnings,
                    )
                    if "figure_evidence" in case:
                        labels = case["figure_evidence"]["visible_facts"]
                        row["figure_gate"] = {
                            "source_image_reviewed": True,
                            "labels_missing_from_baseline": [
                                label
                                for label in labels
                                if not any(
                                    normalize(label) in normalize(b.text) for b in extraction.blocks
                                )
                            ],
                            "candidate_detected": any(
                                loc.page == case["figure_evidence"]["page"]
                                for loc in extraction.visual_candidates
                            ),
                        }
                    model = (
                        await provider.answer(case["question"], evidence, doc.warnings, plan=plan)
                        if evidence
                        else ModelAnswer(
                            answer="Not found in the provided document.",
                            status="not_found",
                            source_ids=[],
                        )
                    )
                    result = validate_answer(
                        Question(id=case["id"], question=case["question"]), model, evidence
                    )
                    row.update(
                        answer=result.model_dump(),
                        citation_valid=True,
                        status_correct=result.status == case["expected_status"],
                        false_abstention=result.status == "not_found"
                        and case["expected_status"] != "not_found",
                    )
                    if live:
                        row["human_review"] = {
                            "required_facts": case["required_facts"],
                            "forbidden_claims": case["forbidden_claims"],
                            "factual_correctness": None,
                            "citation_support": None,
                            "notes": "",
                        }
                    row["diagnosis"] = (
                        "extraction_miss"
                        if required and not all(extracted_coverage)
                        else "retrieval_miss"
                        if required and not all(retrieved_coverage)
                        else "answer_review_required"
                        if live
                        else "offline_plumbing_only"
                    )
                except AppError as exc:
                    row["error"] = {"code": exc.code, "message": exc.message}
                    if exc.code in {"provider_quota", "provider_auth"}:
                        break
                row["latency_ms"] = round((time.monotonic() - started) * 1000)
        finally:
            await service.close()
        records = getattr(provider, "usage_records", [])
    return {
        "mode": args.mode,
        "split": args.split,
        "configuration": {
            "generation_model": settings.generation_model,
            "embedding_model": settings.embedding_model,
            "context_neighbors": settings.context_neighbors,
            "contextual_embeddings": settings.contextual_embeddings,
            "question_planning": settings.question_planning,
            "top_k": settings.top_k,
            "evidence_tokens": settings.evidence_tokens,
        },
        "interpretation": "Live answers require human entailment review."
        if live
        else (
            "Fake hash embeddings and stub answers. "
            "These are NOT OpenAI quality or performance measurements."
        ),
        "summary": summarize(rows, live),
        "usage": records,
        "estimated_actual_cost_usd": usage_cost(records),
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["offline", "estimate", "live"], default="offline")
    parser.add_argument("--split", choices=["dev", "heldout", "all"], default="all")
    parser.add_argument("--source-root", default=".")
    parser.add_argument("--budget-usd", type=float, default=0)
    parser.add_argument("--output", default="evaluation/runs/latest.json")
    args = parser.parse_args()
    result = asyncio.run(evaluate(args))
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "report": str(path),
                **{k: v for k, v in result.items() if k not in {"cases", "usage"}},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
