"""P12: ticket-level disposition predicate."""

from review_ticket.storage import write_json
from review_ticket.ticket_disposition import project_ticket_disposition
from tests.test_status_projection import REF_A, REF_B, REF_C, _commit_dir, _seed_three_pr_session, _store


def _seed_pr_ticket_ready(tmp_path, ref: str, sha: str) -> None:
    commit = _commit_dir(tmp_path, ref, sha)
    review = commit / "review"
    review.mkdir(parents=True, exist_ok=True)
    if not (review / "findings.json").exists():
        write_json(
            review / "findings.json",
            {
                "summary": "Review",
                "findings": [{"id": "F001", "title": "Issue", "explanation": "x", "must_fix": False}],
            },
        )
    write_json(
        review / "human-review.json",
        {
            "rejected_review": False,
            "findings": {"F001": {"decision": "accept", "must_fix": False}},
            "added": [],
        },
    )
    write_json(
        commit / "review" / "manual-review.json",
        {"completed": True, "notes": "ok", "findings": [], "disposition": "APPROVE"},
    )
    write_json(
        commit / "testing" / "test-results.json",
        {"sha": sha, "result": "pass", "digest": "sha256:abc"},
    )
    write_json(
        commit / "review" / "publication.json",
        {"status": "success", "event": "APPROVE", "sha": sha},
    )


def _seed_ticket_ready(tmp_path):
    _seed_three_pr_session(tmp_path)
    root = tmp_path / "reviews"
    from tests.test_status_projection import ISSUE

    issue_root = root / ISSUE
    session = __import__("review_ticket.storage", fromlist=["read_json"]).read_json(issue_root / "session.json")
    session["decisions"] = {
        "testing_notes": {"choice": "accept"},
        "pr_readiness": {"choice": "accept"},
    }
    write_json(issue_root / "session.json", session)
    sha = session["pr_shas"][REF_A]
    _seed_pr_ticket_ready(tmp_path, REF_A, sha)


def test_scenario_h_all_prs_ready_enables_ticket_approve(tmp_path):
    _seed_ticket_ready(tmp_path)
    from tests.test_status_projection import ISSUE

    root = tmp_path / "reviews" / ISSUE
    session = __import__("review_ticket.storage", fromlist=["read_json"]).read_json(root / "session.json")
    for ref in (REF_B, REF_C):
        _seed_pr_ticket_ready(tmp_path, ref, session["pr_shas"][ref])
    ticket = project_ticket_disposition(_store(tmp_path), ISSUE)
    assert ticket.dock_enabled is True
    assert ticket.approve_enabled is True


def test_request_changes_receipt_disables_ticket_approve(tmp_path):
    _seed_ticket_ready(tmp_path)
    from tests.test_status_projection import ISSUE

    root = tmp_path / "reviews" / ISSUE
    session = __import__("review_ticket.storage", fromlist=["read_json"]).read_json(root / "session.json")
    sha = session["pr_shas"][REF_A]
    write_json(
        _commit_dir(tmp_path, REF_A, sha) / "review" / "publication.json",
        {"status": "success", "event": "REQUEST_CHANGES", "sha": sha},
    )
    ticket = project_ticket_disposition(_store(tmp_path), ISSUE)
    assert ticket.approve_enabled is False
    assert any("REQUEST" in ticket.approve_reason.upper() or "Request" in ticket.approve_reason for _ in [0])


def test_comment_receipt_does_not_enable_ticket_approve(tmp_path):
    _seed_ticket_ready(tmp_path)
    from tests.test_status_projection import ISSUE

    root = tmp_path / "reviews" / ISSUE
    session = __import__("review_ticket.storage", fromlist=["read_json"]).read_json(root / "session.json")
    sha = session["pr_shas"][REF_A]
    write_json(
        _commit_dir(tmp_path, REF_A, sha) / "review" / "publication.json",
        {"status": "success", "event": "COMMENT", "sha": sha},
    )
    ticket = project_ticket_disposition(_store(tmp_path), ISSUE)
    assert ticket.dock_enabled is True
    assert ticket.approve_enabled is False
    assert "COMMENT" in ticket.approve_reason or "Comment" in ticket.approve_reason
