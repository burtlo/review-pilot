from pathlib import Path

from review_ticket.findings import build_review_payload, reconcile
from review_ticket.runner import SubprocessRunner
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


def test_cache_step_skip_requires_matching_fingerprint():
    from review_ticket.config import Config
    from review_ticket.workflow import (
        App,
        _cache_fingerprint,
        _invalidate_step_cache,
        _mark_step_cached,
        _should_skip_cached_step,
    )

    session = {
        "pr_scope": "all",
        "active_prs": ["acme/widgets#87"],
        "pr_shas": {"acme/widgets#87": "a" * 40},
        "cached_step_ids": [],
    }
    config = Config(reviews_dir=Path("."), cache_dir=Path("."), cache_steps=True)
    app = App(config=config, runner=SubprocessRunner(), refresh=False)
    assert not _should_skip_cached_step(app, session, "github-readiness")
    _mark_step_cached(session, "github-readiness")
    assert _should_skip_cached_step(app, session, "github-readiness")
    session["pr_shas"]["acme/widgets#87"] = "b" * 40
    assert not _should_skip_cached_step(app, session, "github-readiness")
    _invalidate_step_cache(session)
    session["pr_shas"]["acme/widgets#87"] = "a" * 40
    _mark_step_cached(session, "github-readiness")
    app.refresh = True
    assert not _should_skip_cached_step(app, session, "github-readiness")


def test_multi_pr_analyzer_report_lists_every_pull_request():
    from review_ticket.reports import multi_pr_analyzer_report

    report = multi_pr_analyzer_report(
        [
            {
                "pr_ref": "acme/widgets#87",
                "pr_url": "https://github.com/acme/widgets/pull/87",
                "outcome": "READY",
                "checks_summary": "all 1 required check(s) passed",
                "findings_summary": "no Bugbot or CodeQL threads",
                "readiness_summary": "Required checks passed.",
                "checks_table": "| Check | Required | Status | State | Link |\n| --- | --- | --- | --- | --- |",
                "detail_markdown": "_No Bugbot or CodeQL findings were collected._",
            },
            {
                "pr_ref": "acme/other#88",
                "pr_url": "https://github.com/acme/other/pull/88",
                "outcome": "REVIEW_DECISION",
                "checks_summary": "all 1 required check(s) passed",
                "findings_summary": "2 dispositioned",
                "readiness_summary": "Required checks passed.",
                "checks_table": "| Check | Required | Status | State | Link |\n| --- | --- | --- | --- | --- |",
                "detail_markdown": "## bugbot:1 (bugbot, dispositioned)",
            },
        ]
    )
    assert "acme/widgets#87" in report
    assert "acme/other#88" in report
    assert "https://github.com/acme/widgets/pull/87" in report
    assert "Needs attention" not in report
    assert "### CI checks" in report


def test_iris_pr19_fixture_classifies_unaddressed_bugbot():
    import json
    from pathlib import Path

    from review_ticket.config import Config
    from review_ticket.workflow import classify_analyzer_findings

    path = Path(__file__).resolve().parent / "fixtures" / "iris-pr-19-review-thread-nodes.json"
    nodes = json.loads(path.read_text(encoding="utf-8"))
    config = Config(reviews_dir=Path("."), cache_dir=Path("."))
    bugbot, codeql = classify_analyzer_findings(nodes, [], config)
    assert not codeql
    assert len(bugbot) == 1
    assert bugbot[0]["attention"] == "unaddressed"
    assert bugbot[0]["source"] == "bugbot"
    assert "Docker settings file never loaded" in bugbot[0]["body"]


def test_normalize_checks_uses_github_required_status(tmp_path):
    from pathlib import Path

    from review_ticket.config import Config
    from review_ticket.workflow import normalize_checks

    required_raw = [{"name": "build / build", "bucket": "pass", "state": "SUCCESS"}]
    all_raw = [
        {"name": "build / build", "bucket": "pass", "state": "SUCCESS"},
        {"name": "QA / deploy", "bucket": "pending", "state": "WAITING"},
    ]
    config = Config(reviews_dir=tmp_path, cache_dir=tmp_path)
    checks, missing = normalize_checks(required_raw, all_raw, config)
    build = next(item for item in checks if item.name == "build / build")
    qa = next(item for item in checks if item.name == "QA / deploy")
    assert build.required is True
    assert qa.required is False
    assert qa.bucket == "pending"
    assert missing == []


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
