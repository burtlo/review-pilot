"""Regression locks for multi-PR reviewer integration (P9)."""

from __future__ import annotations

from review_ticket.config import ReviewerProfile
from review_ticket.findings import apply_human_decisions, build_review_payload
from review_ticket.storage import read_json, write_json
from review_ticket.util import fingerprint
from tests.support import ISSUE, make_app
from tests.test_acceptance import SHA1, _commit, _ready_issue, _run, _seed_publishable, posts


def test_ready_handoff_shows_unset_reviewer_and_run_review_next(tmp_path):
    app, _runner, world = make_app(tmp_path, reviewer_command=None)
    _ready_issue(world)
    _run(app, [ISSUE, "notes", "--accept"])
    code = _run(app, [ISSUE, "analyzers", "--accept-dispositions"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "outcome: READY" in output
    assert "context:" in output and "prompt.md" in output
    assert "reviewer_command: unset" in output
    assert f"next: review-ticket {ISSUE} run-review" in output


def test_import_review_after_unset_reviewer_handoff(tmp_path):
    app, runner, world = make_app(tmp_path, reviewer_command=None)
    _ready_issue(world)
    _run(app, [ISSUE, "notes", "--accept"])
    code = _run(app, [ISSUE, "run-review"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "import-review" in output
    assert not any(call and call[0] == "reviewer" for call in runner.calls)
    review = _commit(tmp_path, SHA1) / "review"
    assert not (review / "findings.json").exists()

    imported = {
        "summary": "Imported peer review.",
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
                "explanation": "Quantity is not checked.",
            }
        ],
    }
    import_path = tmp_path / "imported-findings.json"
    write_json(import_path, imported)
    code = _run(app, [ISSUE, "import-review", "--file", str(import_path)])
    output = app.stdout.getvalue()
    assert code == 0
    assert (review / "findings.json").is_file()
    assert f"next: review-ticket {ISSUE} attach" in output
    stored = read_json(review / "findings.json")
    assert stored["findings"][0]["title"] == "Missing validation"


def test_run_review_uses_default_reviewer_for_unmapped_repository(tmp_path):
    app, runner, world = make_app(
        tmp_path,
        reviewer_command="reviewer {context} {output}",
        reviewer_by_repository={
            "kwik-trip-iot/KT.IoT.UI.Admin": ReviewerProfile(agent="ui-admin-reviewer"),
        },
    )
    _ready_issue(world)
    world.reviewer_output = {
        "summary": "Default route.",
        "approval_recommendation": "approve",
        "findings": [],
    }
    _run(app, [ISSUE, "notes", "--accept"])
    code = _run(app, [ISSUE, "run-review"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "reviewer: default" in output
    reviewer_calls = [call for call in runner.calls if call and call[0] == "reviewer"]
    assert len(reviewer_calls) == 1


def test_review_apply_file_matches_accept_all_proposed_payload(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    review = _commit(tmp_path, SHA1) / "review"
    (review / "human-review.json").unlink()
    (review / "proposed-review.json").unlink(missing_ok=True)

    human_path = tmp_path / "human-review.json"
    write_json(
        human_path,
        {
            "rejected_review": False,
            "findings": {"F001": {"decision": "accept", "must_fix": True}},
            "added": [],
            "event": "REQUEST_CHANGES",
            "summary": "Please validate quantity.",
        },
    )
    assert _run(app, [ISSUE, "review", "apply", "--file", str(human_path)]) == 0
    from_file = read_json(review / "proposed-review.json")

    (review / "human-review.json").unlink()
    (review / "proposed-review.json").unlink()
    assert _run(app, [ISSUE, "review", "apply", "--accept-all", "--event", "REQUEST_CHANGES"]) == 0
    from_flags = read_json(review / "proposed-review.json")
    assert from_file == from_flags


def test_publish_fingerprint_matches_payload_and_blocks_repeat_post(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    world.head_sha = SHA1
    review = _commit(tmp_path, SHA1) / "review"
    document = read_json(review / "findings.json")
    human = read_json(review / "human-review.json")
    diff_index = {tuple(row) for row in read_json(review / "diff-lines.json")}
    merged = apply_human_decisions(document["findings"], human)
    expected_digest = fingerprint(
        build_review_payload(
            sha=SHA1,
            event=human["event"],
            summary=human["summary"],
            findings=merged,
            diff_index=diff_index,
        )
    )

    assert _run(app, [ISSUE, "publish-review", "--yes"]) == 0
    assert len(posts(runner)) == 1
    payload = read_json(review / "publish-payload.json")
    receipt = read_json(review / "publication.json")
    assert receipt["fingerprint"] == fingerprint(payload)
    assert receipt["fingerprint"] == expected_digest

    assert _run(app, [ISSUE, "publish-review", "--yes"]) == 0
    assert len(posts(runner)) == 1
    assert "already published" in app.stdout.getvalue()
