"""P3: snapshot human-review save without resume or network I/O."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from review_ticket.models import WorkflowError
from review_ticket.storage import read_json, write_json
from review_ticket.workflow import apply_review, save_snapshot_review
from tests.support import ISSUE, SHA1, SHA2, make_app
from tests.test_acceptance import _commit, _seed_pr, _seed_publishable


def _seed_findings_only(tmp_path: Path, sha: str) -> Path:
    review = _commit(tmp_path, sha) / "review"
    review.mkdir(parents=True, exist_ok=True)
    write_json(
        review / "findings.json",
        {
            "summary": "Please validate quantity.",
            "approval_recommendation": "request_changes",
            "findings": [
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
                }
            ],
        },
    )
    write_json(review / "diff-lines.json", [["src/Example.cs", 142, "RIGHT"]])
    write_json(_commit(tmp_path, sha) / "snapshot.json", {"sha": sha})
    return review


def _accepted_human() -> dict:
    return {
        "rejected_review": False,
        "findings": {"F001": {"decision": "accept", "must_fix": True}},
        "added": [],
        "event": "REQUEST_CHANGES",
        "summary": "Please validate quantity.",
    }


def test_save_snapshot_writes_non_active_sha_without_runner_calls(tmp_path):
    app, runner, _ = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    _seed_findings_only(tmp_path, SHA2)
    session_before = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    human = _accepted_human()

    save_snapshot_review(app, ISSUE, human, sha=SHA2, revise=False)

    session_after = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    assert session_after["active_sha"] == SHA1
    assert session_after["active_pr"] == session_before["active_pr"]
    review = _commit(tmp_path, SHA2) / "review"
    stored = json.loads((review / "human-review.json").read_text(encoding="utf-8"))
    assert stored["findings"]["F001"]["decision"] == "accept"
    assert (review / "proposed-review.json").exists()
    assert (review / "review-preview.md").exists()
    assert runner.calls == []


def test_save_snapshot_refuses_existing_human_review(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    review = _seed_findings_only(tmp_path, SHA2)
    write_json(review / "human-review.json", _accepted_human())

    with pytest.raises(WorkflowError, match="already recorded"):
        save_snapshot_review(app, ISSUE, _accepted_human(), sha=SHA2, revise=False)


def test_save_snapshot_refuses_undecided_findings(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    _seed_findings_only(tmp_path, SHA2)
    human = {
        "rejected_review": False,
        "findings": {},
        "added": [],
        "summary": "Please validate quantity.",
    }

    with pytest.raises(WorkflowError, match="no accept/reject decision"):
        save_snapshot_review(app, ISSUE, human, sha=SHA2, revise=False)


def test_save_snapshot_allows_rejected_review_without_decisions(tmp_path):
    app, runner, _ = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    _seed_findings_only(tmp_path, SHA2)
    human = {
        "rejected_review": True,
        "findings": {},
        "added": [],
        "summary": "Reject automated output.",
    }

    save_snapshot_review(app, ISSUE, human, sha=SHA2, revise=False)

    review = _commit(tmp_path, SHA2) / "review"
    assert json.loads((review / "human-review.json").read_text(encoding="utf-8"))["rejected_review"] is True
    assert not (review / "proposed-review.json").exists()
    assert (review / "review-preview.md").exists()
    assert runner.calls == []


def test_apply_review_still_resumes_active_sha(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    review = _commit(tmp_path, SHA1) / "review"
    (review / "human-review.json").unlink()
    human = _accepted_human()

    with patch("review_ticket.workflow.resume") as resume_mock:
        resume_mock.return_value = None
        apply_review(app, ISSUE, human, revise=False)

    resume_mock.assert_called_once_with(app, ISSUE)
    assert json.loads((review / "human-review.json").read_text(encoding="utf-8"))["findings"]["F001"]["decision"] == "accept"
