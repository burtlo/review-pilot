"""P4: three-track helpers, publication eligibility, and PR/SHA targeting."""

from review_ticket.policy import disposition_checklist
from review_ticket.storage import read_json, read_jsonl, write_json
from review_ticket.tracks import (
    publication_eligibility,
    track_status_snapshot,
    TRACK_COMPLETE_LOCALLY,
    TRACK_PUBLICATION_PENDING,
)
from review_ticket.workflow import resume
from tests.support import ISSUE, SHA1, SHA2, make_app
from tests.test_acceptance import _commit, _run, _seed_publishable


def test_disposition_checklist_human_is_manual_track():
    items = disposition_checklist({"manual_review": True, "sha_matches": True})
    human = next(item for item in items if item["id"] == "human")
    assert human["ok"] is True
    assert "Manual code review" in human["detail"]


def test_publication_eligibility_blocks_approve_without_manual_and_tests(tmp_path):
    commit = _commit(tmp_path, SHA1)
    _seed_publishable(tmp_path, SHA1)
    allowed, reason = publication_eligibility("APPROVE", commit, expected_sha=SHA1)
    assert not allowed
    assert "manual" in reason.casefold()
    write_json(
        commit / "review" / "manual-review.json",
        {"completed": True, "notes": "looked at diff", "findings": []},
    )
    allowed, reason = publication_eligibility("APPROVE", commit, expected_sha=SHA1)
    assert not allowed
    assert "functional" in reason.casefold()
    write_json(
        commit / "testing" / "test-results.json",
        {"sha": SHA1, "result": "pass", "digest": "sha256:abc"},
    )
    allowed, _ = publication_eligibility("APPROVE", commit, expected_sha=SHA1)
    assert allowed


def test_track_status_snapshot_marks_publication_pending_after_curation(tmp_path):
    commit = _commit(tmp_path, SHA1)
    _seed_publishable(tmp_path, SHA1)
    snapshot = track_status_snapshot(commit, expected_sha=SHA1)
    assert snapshot["automated"] == TRACK_COMPLETE_LOCALLY
    assert snapshot["publication"] == TRACK_PUBLICATION_PENDING


def test_resume_reaches_virtualization_without_publication(tmp_path):
    from review_ticket.util import sha256_text
    from review_ticket.workflow import (
        CACHE_STEP_ANALYZERS,
        CACHE_STEP_CHECKS,
        CACHE_STEP_PULL_REQUEST,
        _mark_step_cached,
    )
    from tests.support import jira_document

    app, _runner, world = make_app(tmp_path)
    doc = jira_document("Ran the cart tests and recorded the result.")
    world.issue = doc
    _seed_publishable(tmp_path, SHA1)
    root = tmp_path / "reviews" / ISSUE
    from review_ticket.adapters import normalize_issue

    normalized = normalize_issue(ISSUE, doc, [], app.config)
    write_json(root / "issue.json", normalized)
    session = read_json(root / "session.json")
    session["decisions"] = {
        "testing_notes": {
            "choice": "accept",
            "notes_hash": sha256_text(normalized.get("testing_notes") or ""),
        },
        "analyzers": {SHA1: {"choice": "accept_dispositions"}},
    }
    _mark_step_cached(session, "jira-issue", CACHE_STEP_PULL_REQUEST, CACHE_STEP_CHECKS, CACHE_STEP_ANALYZERS)
    write_json(root / "session.json", session)
    write_json(_commit(tmp_path, SHA1) / "github-checks.json", {"outcome": "READY"})
    result = resume(app, ISSUE)
    output = app.stdout.getvalue()
    assert result.step == "virtualization"
    assert result.outcome.value == "READY"
    assert "test prepare" in (result.next_command or "")
    assert not (_commit(tmp_path, SHA1) / "review" / "publication.json").exists()
    assert "publish-review" not in output.split("next:")[-1]


def test_run_review_targets_non_active_pr_without_single_scope(tmp_path):
    app, runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    doc = __import__("tests.support", fromlist=["jira_document"]).jira_document("notes")
    doc["fields"]["description"] += (
        "\nhttps://github.com/acme/widgets/pull/87\n"
        "https://github.com/acme/other/pull/88\n"
    )
    world.issue = doc
    world.head_sha = SHA1
    _run(app, [ISSUE, "notes", "--accept"])
    other_commit = tmp_path / "reviews" / ISSUE / "prs" / "acme-other-pr-88" / "commits" / SHA2
    write_json(other_commit / "snapshot.json", {"sha": SHA2})
    write_json(
        other_commit.parent.parent / "pr.json",
        {
            "owner": "acme",
            "repo": "other",
            "number": 88,
            "title": "Other",
            "url": "https://github.com/acme/other/pull/88",
            "state": "OPEN",
            "draft": False,
            "head_branch": "feature",
            "head_sha": SHA2,
            "base_branch": "main",
            "base_sha": "b" * 40,
            "body": "",
        },
    )
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    session["pr_shas"]["acme/other#88"] = SHA2
    write_json(tmp_path / "reviews" / ISSUE / "session.json", session)
    world.reviewer_output = {"summary": "Other PR", "approval_recommendation": "approve", "findings": []}
    world.head_sha = SHA2
    code = _run(app, [ISSUE, "run-review", "--pr", "acme/other#88", "--sha", SHA2])
    assert code == 0
    assert (other_commit / "review" / "findings.json").exists()
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    assert session["active_pr"] == "acme/widgets#87"


def test_request_changes_requires_confirmed_blocker(tmp_path):
    commit = _commit(tmp_path, SHA1)
    _seed_publishable(tmp_path, SHA1)
    allowed, reason = publication_eligibility("REQUEST_CHANGES", commit, expected_sha=SHA1)
    assert allowed
    human = read_json(commit / "review" / "human-review.json")
    human.pop("track_disposition_confirmed", None)
    write_json(commit / "review" / "human-review.json", human)
    allowed, reason = publication_eligibility("REQUEST_CHANGES", commit, expected_sha=SHA1)
    assert not allowed
    assert "blocker" in reason.casefold()


def test_comment_requires_completed_manual_review(tmp_path):
    commit = _commit(tmp_path, SHA1)
    _seed_publishable(tmp_path, SHA1)
    allowed, reason = publication_eligibility("COMMENT", commit, expected_sha=SHA1)
    assert not allowed
    assert "manual" in reason.casefold()
    write_json(
        commit / "review" / "manual-review.json",
        {"completed": True, "notes": "looked at diff", "findings": []},
    )
    allowed, _ = publication_eligibility("COMMENT", commit, expected_sha=SHA1)
    assert allowed


def test_request_changes_allowed_without_functional_pass(tmp_path):
    commit = _commit(tmp_path, SHA1)
    _seed_publishable(tmp_path, SHA1)
    assert not (commit / "testing" / "test-results.json").exists()
    allowed, _ = publication_eligibility("REQUEST_CHANGES", commit, expected_sha=SHA1)
    assert allowed


def test_failed_create_review_journals_without_success_receipt(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    world.head_sha = SHA1
    world.review_code = 1
    code = _run(app, [ISSUE, "publish-review", "--yes"])
    assert code == 2
    assert "outcome: BLOCKED" in app.stdout.getvalue()
    review_dir = _commit(tmp_path, SHA1) / "review"
    assert not (review_dir / "publication.json").exists()
    actions = read_jsonl(tmp_path / "reviews" / ISSUE / "actions.jsonl")
    assert any(entry.get("status") == "failure" and entry.get("kind") == "github.review" for entry in actions)


def test_disposition_leave_and_override_still_work(tmp_path, monkeypatch):
    app, _runner, world = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    world.head_sha = SHA1
    for name in ("step_jira", "step_pull_request", "step_checks", "step_analyzers"):
        monkeypatch.setattr(f"review_ticket.workflow.{name}", lambda app, session: None)
    assert _run(app, [ISSUE, "disposition", "--choice", "leave"]) == 0
    assert "Left the issue in Peer Review" in app.stdout.getvalue()
    app.stdout.seek(0)
    app.stdout.truncate()
    assert _run(app, [ISSUE, "disposition", "--choice", "approve"]) != 0
    assert (
        _run(
            app,
            [ISSUE, "disposition", "--choice", "approve", "--override", "--notes", "Ship with known gaps.", "--revise"],
        )
        == 0
    )
    stored = read_json(_commit(tmp_path, SHA1) / "disposition.json")
    assert stored["choice"] == "approve"
    assert stored["override"] is True


def test_publish_appends_publications_jsonl(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    world.head_sha = SHA1
    assert _run(app, [ISSUE, "publish-review", "--yes"]) == 0
    review_dir = _commit(tmp_path, SHA1) / "review"
    history = (review_dir / "publications.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(history) == 1
    assert read_json(review_dir / "publication.json")["status"] == "success"
