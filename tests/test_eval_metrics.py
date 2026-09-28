from docwiki.contracts import Evidence, Location, SourceContext
from docwiki.eval import coverage, summarize


def test_context_matches_its_actual_location_without_borrowing_child_paths():
    item = Evidence(
        source_id="child",
        text="A record about an alert.",
        kind="json",
        method="json-record",
        location=Location(json_path="$.alerts[0]"),
        context=[
            SourceContext(
                block_id="$",
                role="json_parent",
                text='{"owner":"Archive team"}',
                location=Location(json_path="$"),
            )
        ],
    )
    requirements = [
        {"json_path": "$", "contains": ["Archive team"]},
        {"json_path": "$.alerts[0]", "contains": ["Archive team"]},
    ]
    assert coverage([item], requirements) == [True, False]


def test_added_context_does_not_inflate_dense_hit_at_six():
    summary = summarize(
        [
            {
                "required_evidence_count": 2,
                "retrieval_seed_any_required": False,
                "retrieval_seed_all_required": False,
                "retrieval_any_required": True,
                "retrieval_all_required": True,
            }
        ],
        live=False,
    )
    assert summary["retrieval_evidence_hit_at_6"] == 0
    assert summary["retrieval_seed_all_required_coverage"] == 0
    assert summary["retrieval_all_required_coverage"] == 1
