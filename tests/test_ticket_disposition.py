"""P12: ticket disposition predicate and return draft."""

from __future__ import annotations

import json
from pathlib import Path

from review_ticket.reports import ticket_disposition_return_draft
from review_ticket.storage import read_json, write_json
from review_ticket.ticket_disposition import evaluate_ticket_disposition
from review_ticket.workflow import _build_ticket_checklist, record_disposition
from tests.support import ISSUE, SHA1, SHA2, make_app
from tests.test_status_projection import REF_A, REF_B, REF_C, SHA3, _commit_dir, _seed_three_pr_session, _store


def _complete_pr(commit: Path, sha: str, *, event: str = "APPROVE") -> None:
    review = commit / "review"
    review.mkdir(parents=True, exist_ok=True)
    write_json(
        review / "findings.json",
        {"sha": sha, "summary": "ok", "findings": []},
    )
    write_json(
        review / "human-review.json",
        {"sha": sha, "rejected_review": False, "findings": {}, "recorded_at": "t"},
    )
    write_json(
        review / "manual-review.json",
        {
            "sha": sha,
            "completed": True,
            "notes": "",
            "findings": [],
            "disposition": "APPROVE",
            "recorded_at": "t",
        },
    )
    testing = commit / "testing"
    testing.mkdir(parents=True, exist_ok=True)
    digest = "sha256:" + "a" * 64
    write_json(testing / "environment.json", {"sha": sha, "digest": digest})
    write_json(
        testing / "test-results.json",
        {"sha": sha, "result": "pass", "digest": digest, "completed": True},
    )
    write_json(
        review / "publication.json",
        {
            "status": "success",
            "event": event,
            "sha": sha,
            "published_at": "2026-10-18T12:00:00Z",
        },
    )


def _seed_ticket_gates(tmp_path: Path) -> None:
    _seed_three_pr_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    session = read_json(root / "session.json")
    session["decisions"] = {
        "testing_notes": {"choice": "accept", "at": "t"},
        "readiness": {"choice": "approve", "at": "t"},
        "analyzers": {
            SHA1: {"choice": "accept_dispositions", "at": "t"},
            SHA2: {"choice": "accept_dispositions", "at": "t"},
            SHA3: {"choice": "accept_dispositions", "at": "t"},
        },
    }
    write_json(root / "session.json", session)
    for ref, sha in ((REF_A, SHA1), (REF_B, SHA2), (REF_C, SHA3)):
        _complete_pr(_commit_dir(tmp_path, ref, sha), sha)


def test_comment_receipt_does_not_enable_ticket_approve(tmp_path):
    _seed_ticket_gates(tmp_path)
    commit = _commit_dir(tmp_path, REF_B, SHA2)
    write_json(
        commit / "review" / "publication.json",
        {
            "status": "success",
            "event": "COMMENT",
            "sha": SHA2,
            "published_at": "2026-10-18T12:00:00Z",
        },
    )
    view = evaluate_ticket_disposition(_store(tmp_path), ISSUE)
    assert view.approve_enabled is False
    assert view.reject_enabled is True
    assert any("not an approval" in gap.detail.lower() for gap in view.gaps)


def test_all_prs_approve_enables_ticket_approve(tmp_path):
    _seed_ticket_gates(tmp_path)
    view = evaluate_ticket_disposition(_store(tmp_path), ISSUE)
    assert view.approve_enabled is True
    assert view.reject_enabled is False


def test_request_changes_receipt_blocks_approve_and_names_one_pr(tmp_path):
    _seed_ticket_gates(tmp_path)
    commit = _commit_dir(tmp_path, REF_B, SHA2)
    write_json(
        commit / "review" / "publication.json",
        {
            "status": "success",
            "event": "REQUEST_CHANGES",
            "sha": SHA2,
            "published_at": "2026-10-18T12:00:00Z",
        },
    )
    write_json(
        commit / "review" / "manual-review.json",
        {
            "sha": SHA2,
            "completed": True,
            "disposition": "REQUEST_CHANGES",
            "findings": [
                {"path": "src/Foo.cs", "line": 134, "blocking": True, "text": "null dereference"},
            ],
            "recorded_at": "t",
        },
    )
    view = evaluate_ticket_disposition(_store(tmp_path), ISSUE)
    assert view.approve_enabled is False
    assert len(view.return_attention) == 1
    assert view.return_attention[0].number == 12
    draft = ticket_disposition_return_draft(issue=ISSUE, attention=view.return_attention)
    assert "PR #12" in draft
    assert "Foo.cs" in draft
    assert "PR #87" not in draft


def test_build_ticket_checklist_requires_every_active_pr(tmp_path):
    _seed_ticket_gates(tmp_path)
    app, _runner, _world = make_app(tmp_path)
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    items = _build_ticket_checklist(app, session)
    assert any(item["id"] == "testing_notes" and item["ok"] for item in items)
    assert any(item["id"] == "readiness" and item["ok"] for item in items)
    pr_ids = [item["id"] for item in items if "github_approve" in item["id"]]
    assert len(pr_ids) == 3


def test_record_disposition_leave_and_override_unchanged(tmp_path):
    from review_ticket.util import sha256_text
    from tests.support import jira_document, passing_checks
    from tests.test_acceptance import _ready_issue

    _seed_ticket_gates(tmp_path)
    commit_b = _commit_dir(tmp_path, REF_B, SHA2)
    (commit_b / "review" / "publication.json").unlink()
    app, _runner, world = make_app(tmp_path)
    _ready_issue(world)
    world.required_checks = passing_checks()
    world.all_checks = passing_checks()
    notes = "Ran the cart tests and recorded the result."
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    session["active_pr"] = REF_A
    session["active_sha"] = SHA1
    session["decisions"]["testing_notes"] = {
        "choice": "accept",
        "notes_hash": sha256_text(notes),
        "at": "t",
    }
    write_json(tmp_path / "reviews" / ISSUE / "session.json", session)
    write_json(
        tmp_path / "reviews" / ISSUE / "issue.json",
        {
            "key": ISSUE,
            "summary": "Fix",
            "status": "Ready for Peer Review",
            "testing_notes": notes,
        },
    )
    result = record_disposition(app, ISSUE, choice="leave", notes="", override=False, revise=False)
    assert result.outcome.value == "COMPLETE"
    result = record_disposition(
        app,
        ISSUE,
        choice="approve",
        notes="Ship with one PR still open.",
        override=True,
        revise=True,
    )
    assert result.outcome.value == "READY"
    stored = read_json(tmp_path / "reviews" / ISSUE / "disposition.json")
    assert stored["override"] is True
