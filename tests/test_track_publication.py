"""P4: three tracks, publication after testing, and per-PR identity."""

from __future__ import annotations

import json

from review_ticket.policy import (
    TRACK_COMPLETE_LOCALLY,
    TRACK_IN_PROGRESS,
    TRACK_NOT_STARTED,
    TRACK_PUBLICATION_PENDING,
    TRACK_RETURNED,
    TRACK_STALE,
    classify_track_status,
    disposition_checklist,
    functional_testing_passed,
    publication_event_allowed,
)
from review_ticket.storage import read_json, read_jsonl, write_json
from review_ticket.workflow import (
    _build_checklist,
    prepare_profile,
    publish_review,
    read_track_status,
    record_tests,
    run_review,
)
from tests.support import ISSUE, SHA1, SHA2, make_app, posts
from tests.test_acceptance import _commit, _normalized_pr, _ready_issue, _run, _seed_pr, _seed_publishable


def test_resume_reaches_virtualization_without_publication(tmp_path):
    app, _runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    _ready_issue(world)
    world.reviewer_output = {
        "summary": "Looks good.",
        "approval_recommendation": "approve",
        "findings": [],
    }
    assert _run(app, [ISSUE, "notes", "--accept"]) == 0
    assert _run(app, [ISSUE, "run-review"]) == 0
    review = _commit(tmp_path, SHA1) / "review"
    assert (review / "findings.json").is_file()
    assert not (review / "human-review.json").exists()
    assert not (review / "publication.json").exists()

    code = _run(app, [ISSUE])
    output = app.stdout.getvalue()
    assert code == 0
    assert "step: virtualization" in output
    assert f"next: review-ticket {ISSUE} test prepare" in output
    assert "publish-review" not in output
    assert not (review / "publication.json").exists()


def test_saved_human_curation_resumes_to_testing_not_publish(tmp_path):
    app, _runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    _ready_issue(world)
    world.reviewer_output = {
        "summary": "Looks good.",
        "approval_recommendation": "approve",
        "findings": [],
    }
    assert _run(app, [ISSUE, "notes", "--accept"]) == 0
    assert _run(app, [ISSUE, "run-review"]) == 0
    human_path = tmp_path / "human-review.json"
    write_json(
        human_path,
        {
            "rejected_review": False,
            "findings": {},
            "added": [],
            "event": "COMMENT",
            "summary": "No blocking findings.",
        },
    )
    code = _run(app, [ISSUE, "review", "apply", "--file", str(human_path)])
    output = app.stdout.getvalue()
    review = _commit(tmp_path, SHA1) / "review"
    assert code == 0, app.stderr.getvalue()
    assert (review / "human-review.json").is_file()
    assert not (review / "publication.json").exists()
    assert f"next: review-ticket {ISSUE} test prepare" in output
    assert "publish-review" not in output


def _seed_approvable(tmp_path, sha: str) -> None:
    _seed_publishable(tmp_path, sha)
    review = _commit(tmp_path, sha) / "review"
    write_json(
        review / "findings.json",
        {"summary": "Looks good.", "approval_recommendation": "approve", "findings": []},
    )
    write_json(
        review / "human-review.json",
        {
            "rejected_review": False,
            "findings": {},
            "added": [],
            "event": "COMMENT",
            "summary": "Looks good.",
        },
    )


def test_approve_is_rejected_before_functional_pass(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_approvable(tmp_path, SHA1)
    world.head_sha = SHA1
    code = _run(app, [ISSUE, "publish-review", "--yes", "--event", "APPROVE"])
    assert code == 2
    assert "passing functional test" in app.stderr.getvalue()
    assert posts(runner) == []
    review = _commit(tmp_path, SHA1) / "review"
    assert not (review / "publication.json").exists()
    assert not (review / "publications.jsonl").exists()


def test_approve_after_functional_pass_is_idempotent(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_approvable(tmp_path, SHA1)
    world.head_sha = SHA1
    review = _commit(tmp_path, SHA1) / "review"
    testing = _commit(tmp_path, SHA1) / "testing"
    write_json(
        review / "manual-review.json",
        {
            "sha": SHA1,
            "completed": True,
            "notes": "Inspected the quantity check.",
            "findings": [],
            "disposition": "APPROVE",
            "recorded_at": "2026-10-18T00:00:00Z",
        },
    )
    digest = "sha256:" + "a" * 64
    write_json(testing / "environment.json", {"sha": SHA1, "digest": digest})
    write_json(
        testing / "test-results.json",
        {"sha": SHA1, "result": "pass", "digest": digest, "recorded_at": "2026-10-18T00:00:00Z"},
    )
    assert _run(app, [ISSUE, "publish-review", "--yes", "--event", "APPROVE"]) == 0
    assert len(posts(runner)) == 1
    receipt = read_json(review / "publication.json")
    history = read_jsonl(review / "publications.jsonl")
    assert receipt["event"] == "APPROVE"
    assert receipt["status"] == "success"
    assert history == [receipt]
    assert _run(app, [ISSUE, "publish-review", "--yes", "--event", "APPROVE"]) == 0
    assert len(posts(runner)) == 1
    assert "already published" in app.stdout.getvalue()
    assert read_jsonl(review / "publications.jsonl") == [receipt]


def test_approve_still_requires_manual_review_after_functional_pass(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_approvable(tmp_path, SHA1)
    world.head_sha = SHA1
    digest = "sha256:" + "a" * 64
    testing = _commit(tmp_path, SHA1) / "testing"
    write_json(testing / "environment.json", {"sha": SHA1, "digest": digest})
    write_json(
        testing / "test-results.json",
        {"sha": SHA1, "result": "pass", "digest": digest, "recorded_at": "2026-10-18T00:00:00Z"},
    )
    code = _run(app, [ISSUE, "publish-review", "--yes", "--event", "APPROVE"])
    assert code == 2
    assert "manual code review" in app.stderr.getvalue()
    assert posts(runner) == []


def test_second_pr_is_addressable_without_narrowing_scope(tmp_path):
    app, runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    _ready_issue(world)
    world.reviewer_output = {
        "summary": "Other repository.",
        "approval_recommendation": "comment",
        "findings": [],
    }
    assert _run(app, [ISSUE, "notes", "--accept"]) == 0
    root = tmp_path / "reviews" / ISSUE
    session = read_json(root / "session.json")
    session["pr_scope"] = "all"
    session["active_prs"] = ["acme/widgets#87", "acme/other#88"]
    session["pr_shas"] = {"acme/widgets#87": SHA1, "acme/other#88": SHA1}
    write_json(root / "session.json", session)
    other_pr = {
        **_normalized_pr(SHA1),
        "owner": "acme",
        "repo": "other",
        "number": 88,
        "url": "https://github.com/acme/other/pull/88",
    }
    write_json(root / "prs" / "acme-other-pr-88" / "pr.json", other_pr)
    other_commit = root / "prs" / "acme-other-pr-88" / "commits" / SHA1

    prepare_profile(app, ISSUE, identity=("acme", "other", 88), sha=SHA1)
    profile = other_commit / "testing" / "profile" / "profile.json"
    assert read_json(profile)["repository"] == "acme/other"
    assert not (_commit(tmp_path, SHA1) / "testing" / "profile" / "profile.json").exists()

    record_tests(
        app,
        ISSUE,
        result="pass",
        kind=None,
        notes="Cart rejected a negative quantity.",
        scenarios=["quantity"],
        evidence=[],
        revise=False,
        identity=("acme", "other", 88),
        sha=SHA1,
    )
    stored = read_json(other_commit / "testing" / "test-results.json")
    assert stored["sha"] == SHA1
    assert stored["result"] == "pass"
    saved = read_json(root / "session.json")
    assert saved["pr_scope"] == "all"
    assert saved["active_pr"] == "acme/widgets#87"
    assert saved["active_prs"] == ["acme/widgets#87", "acme/other#88"]

    result = run_review(app, ISSUE, revise=False, identity=("acme", "other", 88), sha=SHA1)
    assert result.step == "human-review"
    other_findings = other_commit / "review" / "findings.json"
    assert other_findings.is_file()
    assert not (_commit(tmp_path, SHA1) / "review" / "findings.json").exists()
    saved = read_json(root / "session.json")
    assert saved["pr_scope"] == "all"
    assert saved["active_pr"] == "acme/widgets#87"
    assert not any(call[:3] == ["review-ticket", ISSUE, "pr"] for call in runner.calls)


def test_old_human_review_still_loads_as_automated_curation(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    review = _commit(tmp_path, SHA1) / "review"
    human = json.loads((review / "human-review.json").read_text(encoding="utf-8"))
    assert human["findings"]["F001"]["decision"] == "accept"
    assert "completed" not in human
    status = read_track_status(app, ISSUE, ("acme", "widgets", 87), SHA1, current_sha=SHA1)
    assert status["automated"] == TRACK_COMPLETE_LOCALLY
    assert status["manual"] == TRACK_NOT_STARTED
    assert status["publication"] == TRACK_PUBLICATION_PENDING
    checklist = _build_checklist(app, read_json(tmp_path / "reviews" / ISSUE / "session.json"))
    human_item = next(item for item in checklist if item["id"] == "human")
    assert human_item["ok"] is False
    assert "Manual code review" in human_item["detail"]

    write_json(
        review / "manual-review.json",
        {"sha": SHA1, "completed": True, "notes": "", "findings": [], "disposition": "COMMENT"},
    )
    checklist = _build_checklist(app, read_json(tmp_path / "reviews" / ISSUE / "session.json"))
    assert next(item for item in checklist if item["id"] == "human")["ok"] is True


def test_track_status_vocabulary_and_approve_predicate():
    stale = classify_track_status(
        sha=SHA1,
        current_sha=SHA2,
        findings={"findings": []},
        human_review={"rejected_review": False, "findings": {}},
        manual_review={"completed": True, "sha": SHA1},
        test_results={"sha": SHA1, "result": "pass"},
        publication={"status": "success", "event": "COMMENT", "sha": SHA1},
    )
    assert set(stale.values()) == {TRACK_STALE}

    current = classify_track_status(
        sha=SHA1,
        current_sha=SHA1,
        findings={"findings": []},
        human_review=None,
        manual_review={"completed": False, "notes": "partial"},
        test_results={"sha": SHA1, "result": "blocked", "failure_kind": "environment"},
        publication=None,
    )
    assert current["automated"] == TRACK_IN_PROGRESS
    assert current["manual"] == TRACK_IN_PROGRESS
    assert current["functional"] == "blocked"
    assert current["publication"] == TRACK_NOT_STARTED

    allowed, reason = publication_event_allowed(
        "APPROVE",
        sha=SHA1,
        manual_review=None,
        test_results=None,
    )
    assert allowed is False
    assert "functional" in reason
    allowed, _reason = publication_event_allowed(
        "REQUEST_CHANGES",
        sha=SHA1,
        manual_review=None,
        test_results=None,
    )
    assert allowed is True
    allowed, reason = publication_event_allowed(
        "COMMENT",
        sha=SHA1,
        manual_review=None,
        test_results=None,
    )
    assert allowed is False
    assert "manual" in reason.lower()


def test_digest_mismatch_blocks_approve_even_when_result_pass(tmp_path):
    digest_a = "sha256:" + "a" * 64
    digest_b = "sha256:" + "b" * 64
    results = {"sha": SHA1, "result": "pass", "digest": digest_a}
    environment = {"sha": SHA1, "digest": digest_b}
    assert functional_testing_passed(results, SHA1, environment) is False
    allowed, reason = publication_event_allowed(
        "APPROVE",
        sha=SHA1,
        manual_review={"sha": SHA1, "completed": True},
        test_results=results,
        environment=environment,
    )
    assert allowed is False
    assert "functional" in reason
    status = classify_track_status(
        sha=SHA1,
        current_sha=SHA1,
        findings={"findings": []},
        human_review=None,
        manual_review=None,
        test_results=results,
        publication=None,
        environment=environment,
    )
    assert status["functional"] == TRACK_IN_PROGRESS


def test_comment_rejected_without_manual_review(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_approvable(tmp_path, SHA1)
    world.head_sha = SHA1
    code = _run(app, [ISSUE, "publish-review", "--yes", "--event", "COMMENT"])
    assert code == 2
    assert "manual" in app.stderr.getvalue().lower()
    assert posts(runner) == []
    review = _commit(tmp_path, SHA1) / "review"
    assert not (review / "publication.json").exists()

    items = disposition_checklist(
        {
            "sha_matches": True,
            "checks_passed": True,
            "analyzers_clear": True,
            "open_must_fix": False,
            "manual_review": False,
            "testing_passed": True,
            "evidence_matches": True,
        }
    )
    assert next(item for item in items if item["id"] == "human")["ok"] is False


def test_request_changes_without_functional_when_blocker_confirmed(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_approvable(tmp_path, SHA1)
    review = _commit(tmp_path, SHA1) / "review"
    human = read_json(review / "human-review.json")
    human["disposition"] = "REQUEST_CHANGES"
    human["blocker_confirmed"] = True
    human["event"] = "REQUEST_CHANGES"
    write_json(review / "human-review.json", human)
    world.head_sha = SHA1
    assert _run(app, [ISSUE, "publish-review", "--yes", "--event", "REQUEST_CHANGES"]) == 0
    assert len(posts(runner)) == 1
    receipt = read_json(review / "publication.json")
    assert receipt["event"] == "REQUEST_CHANGES"
    assert len(read_jsonl(review / "publications.jsonl")) == 1


def test_publish_review_identity_writes_the_named_pr(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    root = tmp_path / "reviews" / ISSUE
    session = read_json(root / "session.json")
    session["pr_scope"] = "all"
    session["active_prs"] = ["acme/widgets#87", "acme/other#88"]
    session["pr_shas"] = {"acme/widgets#87": SHA1, "acme/other#88": SHA2}
    write_json(root / "session.json", session)
    other = root / "prs" / "acme-other-pr-88"
    write_json(
        other / "pr.json",
        {**_normalized_pr(SHA2), "owner": "acme", "repo": "other", "number": 88},
    )
    review = other / "commits" / SHA2 / "review"
    write_json(
        review / "findings.json",
        {"summary": "Other PR.", "approval_recommendation": "comment", "findings": []},
    )
    write_json(
        review / "human-review.json",
        {
            "rejected_review": False,
            "findings": {},
            "added": [],
            "event": "COMMENT",
            "summary": "Other PR.",
        },
    )
    write_json(review / "diff-lines.json", [])
    write_json(
        review / "manual-review.json",
        {
            "sha": SHA2,
            "completed": True,
            "notes": "Reviewed other PR.",
            "findings": [],
            "disposition": "COMMENT",
            "recorded_at": "2026-10-18T00:00:00Z",
        },
    )
    world.head_sha = SHA2
    result = publish_review(
        app,
        ISSUE,
        yes=True,
        event="COMMENT",
        skip=False,
        identity=("acme", "other", 88),
        sha=SHA2,
    )
    assert result.outcome.value == "READY"
    assert read_json(review / "publication.json")["event"] == "COMMENT"
    assert len(read_jsonl(review / "publications.jsonl")) == 1
    assert not (_commit(tmp_path, SHA1) / "review" / "publication.json").exists()
    saved = read_json(root / "session.json")
    assert saved["pr_scope"] == "all"
    assert saved["active_pr"] == "acme/widgets#87"
    assert len(posts(runner)) == 1
