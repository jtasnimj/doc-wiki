import argparse
import hashlib
import html
import json
from collections import Counter
from pathlib import Path

from docwiki.contracts import Evidence
from docwiki.eval import coverage


def review(baseline, manifest):
    for key in ("source_sha256", "workbook_sha256"):
        if baseline[key] != manifest[key]:
            raise ValueError(f"{key} mismatch; source review is required")
    if baseline["commit"] != manifest["baseline_commit"]:
        raise ValueError("The judgments apply only to the captured baseline commit")
    expected = manifest["cases"]
    captured = baseline["cases"]
    if len(expected) != 19 or [c["case"] for c in captured] != list(range(1, 20)):
        raise ValueError("The baseline must contain exactly 19 ordered workbook cases")
    rows = []
    for actual, gold in zip(captured, expected, strict=True):
        digest = hashlib.sha256(actual["question"].encode()).hexdigest()
        if digest != gold["question_sha256"] or actual["case"] != gold["case"]:
            raise ValueError("Question mismatch; review cannot be applied to this baseline")
        evidence = [Evidence.model_validate(item) for item in actual["retrieved"]]
        required = coverage(evidence, gold["required_evidence"])
        allowed = {e.source_id: e for e in evidence}
        result = actual["actual"]
        citations = result["citations"] + [
            citation
            for item in result.get("related_information", [])
            for citation in item["citations"]
        ]
        valid = all(
            citation["source_id"] in allowed
            and citation["excerpt"] == allowed[citation["source_id"]].text
            and citation["kind"] == allowed[citation["source_id"]].kind
            and citation["derived"] == (allowed[citation["source_id"]].kind == "vision")
            and citation["locations"]
            == [allowed[citation["source_id"]].location.model_dump(mode="json")]
            for citation in citations
        ) and (bool(result["citations"]) == (result["status"] in {"answered", "partial"}))
        rows.append(
            {
                **gold,
                **actual,
                "status_agreement": result["status"] == gold["expected_status"],
                "citation_structural_validity": valid,
                "required_evidence_coverage": required,
            }
        )
    eligible = [r for r in rows if r["required_evidence"]]
    summary = {
        "cases": len(rows),
        "baseline_statuses": dict(Counter(r["actual"]["status"] for r in rows)),
        "target_statuses": dict(Counter(r["expected_status"] for r in rows)),
        "status_agreement": sum(r["status_agreement"] for r in rows),
        "structurally_valid_citations": sum(r["citation_structural_validity"] for r in rows),
        "evidence_eligible_cases": len(eligible),
        "evidence_hit_at_6": sum(any(r["required_evidence_coverage"]) for r in eligible),
        "all_required_evidence_at_6": sum(all(r["required_evidence_coverage"]) for r in eligible),
        "required_evidence_groups": sum(len(r["required_evidence"]) for r in eligible),
        "retrieved_required_groups": sum(sum(r["required_evidence_coverage"]) for r in eligible),
        "baseline_not_found": sum(r["actual"]["status"] == "not_found" for r in rows),
        "target_not_found": sum(r["expected_status"] == "not_found" for r in rows),
        "latency_ms": baseline["latency_ms"],
        "estimated_actual_cost_usd": baseline["estimated_actual_cost_usd"],
        "post_change_live_retest": "Not run; separate paid approval required.",
        "interpretation": "Status agreement and citation structure are not factual accuracy. "
        "Evidence coverage uses reviewed positive text/location groups; it is not entailment. "
        "Offline fixtures verify contracts, not model quality or semantic relevance.",
    }
    return {
        "summary": summary,
        "source_sha256": baseline["source_sha256"],
        "workbook_sha256": baseline["workbook_sha256"],
        "baseline_commit": baseline["commit"],
        "prompt_sha256": baseline["prompt_sha256"],
        "configuration": baseline["configuration"],
        "warnings": baseline["batch"]["warnings"],
        "usage": baseline["usage"],
        "cases": rows,
    }


def render_html(report):
    def esc(value):
        return html.escape(str(value))

    headings = [
        "Case / question",
        "Workbook reference",
        "Baseline answer",
        "Source-supported target",
        "Evidence / retrieval",
        "Reference alignment / grounding review",
        "Diagnosis / fix",
        "Retest",
    ]
    parts = [
        "<!doctype html><html lang='en'><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>DocWiki: 19-case baseline review</title>",
        "<style>body{font:14px/1.5 system-ui;margin:28px;color:#193732}"
        "table{border-collapse:collapse;min-width:1800px}th,td{border:1px solid #ccd8d0;"
        "padding:12px;vertical-align:top;min-width:200px}th{background:#e9f0e9;text-align:left}"
        "td p{white-space:pre-wrap}pre{white-space:pre-wrap;overflow-wrap:anywhere}"
        "details{margin-top:12px}summary{cursor:pointer}.scroll{overflow:auto}"
        "h1{font-size:28px}code{overflow-wrap:anywhere}</style>",
        "<h1>19-case baseline review</h1>",
        "<p>The SOC 2 PDF is the sole runtime source. Workbook answers are evaluation references. "
        "Comments and confidence are ignored. All inspected cases are development cases.</p>",
        "<p>Each row separates reference alignment from source correctness. "
        "The baseline predates the changes. No post-change live evaluation has been run.</p>",
        f"<pre>{esc(json.dumps(report['summary'], indent=2))}</pre>",
        "<details><summary>Configuration, provenance, warnings and usage</summary><pre>",
        esc(
            json.dumps({k: v for k, v in report.items() if k not in {"cases", "summary"}}, indent=2)
        ),
        "</pre></details><div class='scroll'><table><thead><tr>",
        "".join(f"<th>{esc(h)}</th>" for h in headings),
        "</tr></thead><tbody>",
    ]
    for row in report["cases"]:
        actual = row["actual"]
        passages = "".join(
            f"<details><summary>Rank {rank} · page {esc(e['location']['page'])}</summary>"
            f"<pre>{esc(e['source_id'])}\n{esc(e['text'])}</pre></details>"
            for rank, e in enumerate(row["retrieved"], 1)
        )
        cells = [
            f"<b>{row['case']} · {esc(row['topic'])}</b><p>{esc(row['question'])}</p>"
            f"<small>Sheet1 row {row['workbook_row']}</small>",
            f"<p>{esc(row['reference_answer'])}</p>",
            f"<b>{esc(actual['status'])}</b><p>{esc(actual['answer'])}</p>"
            f"<details><summary>Citations / raw result</summary>"
            f"<pre>{esc(json.dumps(actual, indent=2))}</pre></details>"
            f"<small>Retrieval {row['retrieval_latency_ms']} ms; "
            f"generation {row['generation_latency_ms']} ms</small>",
            f"<b>{esc(row['expected_status'])}</b><p>{esc(row['source_supported_target'])}</p>",
            f"<p>Reviewed pages: {esc(row['evidence_pages']) or 'none'}</p>"
            f"<p>{esc(row['retrieval_review'])}</p>"
            f"<p>Required-group coverage: {esc(row['required_evidence_coverage'])}</p>{passages}",
            f"<p>{esc(row['reference_alignment'])}</p><p>{esc(row['baseline_claim_review'])}</p>",
            f"<p>{esc(', '.join(row['diagnoses']))}</p><p>{esc(row['proposed_fix'])}</p>",
            f"<p>{esc(row['retest_outcome'])}</p><code>{esc(row['regression_pattern'])}</code>",
        ]
        parts.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    parts.append("</tbody></table></div></html>")
    return "".join(parts)


def main():
    parser = argparse.ArgumentParser(
        description="Review a captured baseline without provider calls"
    )
    parser.add_argument(
        "--baseline", type=Path, default=Path("evaluation/runs/workbook-baseline.json")
    )
    parser.add_argument("--manifest", type=Path, default=Path("evaluation/workbook_cases.json"))
    parser.add_argument("--output", type=Path, default=Path("evaluation/runs/workbook-review"))
    args = parser.parse_args()
    report = review(json.loads(args.baseline.read_text()), json.loads(args.manifest.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.with_suffix(".json").write_text(json.dumps(report, indent=2) + "\n")
    args.output.with_suffix(".html").write_text(render_html(report))
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
