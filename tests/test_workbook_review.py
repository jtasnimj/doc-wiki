import copy
import hashlib
import json
from pathlib import Path

import pytest

from doc_wiki.workbook_review import render_html, review


@pytest.fixture
def captured():
    manifest = json.loads(Path("evaluation/workbook_cases.json").read_text())
    cases = []
    for gold in manifest["cases"]:
        question = f"Question {gold['case']} <script>alert(1)</script>"
        gold["question_sha256"] = hashlib.sha256(question.encode()).hexdigest()
        cases.append(
            {
                "case": gold["case"],
                "workbook_row": gold["workbook_row"],
                "question": question,
                "reference_answer": "<img src=x onerror=alert(1)>",
                "retrieved": [],
                "retrieval_latency_ms": 1,
                "generation_latency_ms": 2,
                "actual": {"status": "not_found", "answer": "Missing detail.", "citations": []},
            }
        )
    baseline = {
        "source_sha256": manifest["source_sha256"],
        "workbook_sha256": manifest["workbook_sha256"],
        "commit": manifest["baseline_commit"],
        "prompt_sha256": "test-prompt",
        "configuration": {},
        "usage": [],
        "batch": {"warnings": []},
        "cases": cases,
        "latency_ms": 50,
        "estimated_actual_cost_usd": 0,
    }
    return baseline, manifest


@pytest.mark.parametrize("change", ["source", "workbook", "commit", "question", "missing"])
def test_review_rejects_mismatched_capture(captured, change):
    baseline, manifest = captured
    if change in {"source", "workbook"}:
        baseline[f"{change}_sha256"] = "different"
    elif change == "commit":
        baseline["commit"] = "different"
    elif change == "question":
        baseline["cases"][0]["question"] = "different"
    else:
        baseline["cases"].pop()
    with pytest.raises(ValueError):
        review(baseline, manifest)


def test_report_keeps_all_cases_escapes_content_and_does_not_score_unrun_quality(captured):
    baseline, manifest = captured
    report = review(baseline, manifest)
    rendered = render_html(report)
    assert rendered.count("<tr>") == 20
    assert "<script>" not in rendered
    assert "<img" not in rendered
    assert "&lt;script&gt;" in rendered
    assert report["summary"]["status_agreement"] == 11
    assert report["summary"]["evidence_hit_at_6"] == 0
    assert "Not run" in report["summary"]["post_change_live_retest"]
    assert len(report["cases"]) == 19
    changed = copy.deepcopy(baseline)
    changed["cases"][0]["reference_answer"] = "Entirely different reference"
    assert review(changed, manifest)["summary"] == report["summary"]


def test_every_review_pattern_has_a_separate_authored_scenario():
    manifest = json.loads(Path("evaluation/workbook_cases.json").read_text())
    scenarios = json.loads(Path("evaluation/grounding_cases.json").read_text())["cases"]
    assert {c["regression_pattern"] for c in manifest["cases"]} <= {c["id"] for c in scenarios}
    assert {c["split"] for c in manifest["cases"] + scenarios} == {"dev"}
    assert {"explicit_negative", "explicit_nonapplicability", "explicit_threshold"} <= {
        c["id"] for c in scenarios
    }
