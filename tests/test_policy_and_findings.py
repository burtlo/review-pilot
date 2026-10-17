from review_ticket.findings import build_review_payload, reconcile
from review_ticket.policy import Check, evaluate_analyzers, evaluate_readiness
from review_ticket.models import Outcome
from review_ticket.textutil import parse_unified_diff
from tests.support import DIFF


def test_diff_index_marks_added_lines_and_ignores_unrelated_lines():
    index = parse_unified_diff(DIFF)
    assert ("src/Example.cs", 142, "RIGHT") in index
    assert ("src/Example.cs", 10, "RIGHT") not in index


def test_inline_and_general_findings_are_split():
    index = parse_unified_diff(DIFF)
    findings = [
        {
            "id": "F001",
            "priority": "high",
            "must_fix": True,
            "path": "src/Example.cs",
            "line": 142,
            "side": "RIGHT",
            "title": "Missing validation",
            "explanation": "This path permits an invalid state.",
            "suggested_change": "if (item.Quantity < 0) throw new InvalidOperationException();",
            "decision": "accept",
        },
        {
            "id": "F002",
            "priority": "medium",
            "must_fix": False,
            "path": "src/Example.cs",
            "line": 10,
            "side": "RIGHT",
            "title": "Unrelated helper",
            "explanation": "This behavior lives outside the diff.",
            "decision": "accept",
        },
        {
            "id": "F003",
            "priority": "low",
            "must_fix": False,
            "title": "Release note",
            "explanation": "Mention the validation in the changelog.",
            "decision": "accept",
        },
    ]
    payload = build_review_payload(
        sha="a" * 40,
        event="REQUEST_CHANGES",
        summary="Please validate quantity.",
        findings=findings,
        diff_index=index,
    )
    assert len(payload["comments"]) == 1
    assert payload["comments"][0]["path"] == "src/Example.cs"
    assert payload["comments"][0]["line"] == 142
    assert "```suggestion" in payload["comments"][0]["body"]
    assert "Unrelated helper" in payload["body"]
    assert "Release note" in payload["body"]
    assert all(comment["line"] != 10 for comment in payload["comments"])


def test_pending_checks_wait_and_failed_checks_recommend_progress():
    pending = evaluate_readiness(
        [Check(name="build", bucket="pending", required=True)],
        missing_analyzers=[],
        service_unavailable=None,
        accepted_missing_checks=False,
        accepted_missing_analyzers=False,
        in_progress_status="In Progress",
    )
    failed = evaluate_readiness(
        [Check(name="build", bucket="fail", required=True)],
        missing_analyzers=[],
        service_unavailable=None,
        accepted_missing_checks=False,
        accepted_missing_analyzers=False,
        in_progress_status="In Progress",
    )
    assert pending.outcome == Outcome.WAITING
    assert pending.recommendation is None
    assert failed.outcome == Outcome.ACTION_REQUIRED
    assert failed.recommendation == "In Progress"


def test_unaddressed_analyzer_recommends_progress_and_disposition_can_continue():
    unaddressed = [{"id": "bugbot:1", "attention": "unaddressed"}]
    dispositioned = [{"id": "bugbot:1", "attention": "dispositioned"}]
    blocked, _, recommendation = evaluate_analyzers(unaddressed, None, in_progress_status="In Progress")
    waiting, _, _ = evaluate_analyzers(dispositioned, None, in_progress_status="In Progress")
    ready, _, _ = evaluate_analyzers(dispositioned, "accept_dispositions", in_progress_status="In Progress")
    assert blocked == Outcome.ACTION_REQUIRED
    assert recommendation == "In Progress"
    assert waiting == Outcome.REVIEW_DECISION
    assert ready == Outcome.READY


def test_reconciliation_keeps_unmentioned_findings_unverified():
    rows = reconcile(
        [{"id": "F001", "title": "Missing validation"}, {"id": "F002", "title": "Old note"}],
        [
            {
                "id": "F010",
                "title": "Still missing",
                "reconciles": "F001",
                "reconciliation_status": "partially_resolved",
            }
        ],
    )
    assert rows[0]["status"] == "partially_resolved"
    assert rows[0]["current_id"] == "F010"
    assert rows[1]["status"] == "requires_additional_verification"
