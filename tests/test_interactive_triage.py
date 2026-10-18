import asyncio
import json
from pathlib import Path

import pytest

from review_ticket.cli import main, run_review_attach
from review_ticket.storage import write_json
from review_ticket.tui.status_screen import StatusScreen
from review_ticket.findings import apply_human_decisions, build_review_payload
from review_ticket.interactive_triage import (
    accept_finding,
    FindingState,
    human_document_from_state,
    load_triage_state,
    proposed_payload_from_human,
    publish_preview_counts,
    set_finding_explanation,
    triage_document_if_ready,
    TriageState,
)
from review_ticket.models import WorkflowError
from review_ticket.storage import write_json
from tests.support import make_app
from tests.test_acceptance import ISSUE, SHA1, _seed_publishable, _run


def test_publish_preview_counts_splits_inline_and_summary():
    diff_index = {("src/Example.cs", 142, "RIGHT")}
    machine = [
        {
            "id": "F001",
            "priority": "high",
            "must_fix": True,
            "path": "src/Example.cs",
            "line": 142,
            "side": "RIGHT",
            "title": "On diff",
            "explanation": "inline",
        },
        {
            "id": "F002",
            "priority": "low",
            "must_fix": False,
            "path": "src/Other.cs",
            "line": 9,
            "side": "RIGHT",
            "title": "Off diff",
            "explanation": "summary",
        },
    ]
    human = {
        "rejected_review": False,
        "findings": {
            "F001": {"decision": "accept", "must_fix": True},
            "F002": {"decision": "accept", "must_fix": False},
        },
        "added": [],
    }
    inline, summary = publish_preview_counts(machine, human, diff_index)
    assert inline == 1
    assert summary == 1


def test_human_document_matches_apply_file_shape():
    state = TriageState(
        findings=[
            FindingState(
                finding_id="F001",
                title="Title",
                automated_must_fix=True,
                path="a.cs",
                line=1,
                side="RIGHT",
                default_explanation="auto",
                decision="reject",
            ),
            FindingState(
                finding_id="F002",
                title="Two",
                automated_must_fix=False,
                path=None,
                line=None,
                side="RIGHT",
                default_explanation="keep",
                decision="accept",
                explanation="edited",
            ),
        ],
        summary="Summary text",
        event="REQUEST_CHANGES",
    )
    human = human_document_from_state(state)
    assert human == {
        "rejected_review": False,
        "findings": {
            "F001": {"decision": "reject", "must_fix": True},
            "F002": {"decision": "accept", "must_fix": False, "explanation": "edited"},
        },
        "added": [],
        "event": "REQUEST_CHANGES",
        "summary": "Summary text",
    }


def test_load_triage_state_by_identity_and_sha(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    identity = ("acme", "widgets", 87)
    state, document, sha, loaded_identity = load_triage_state(app, ISSUE, identity=identity, sha=SHA1)
    assert sha == SHA1
    assert loaded_identity == identity
    assert state.findings[0].finding_id == "F001"
    assert document["findings"][0]["id"] == "F001"


def test_named_transitions_save_parity_with_apply_file(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    review = tmp_path / "reviews" / ISSUE / "prs" / "acme-widgets-pr-87" / "commits" / SHA1 / "review"
    (review / "human-review.json").unlink()
    state, document, sha, identity = load_triage_state(app, ISSUE)
    diff_index = {("src/Example.cs", 142, "RIGHT")}
    accept_finding(state, "1")
    set_finding_explanation(state, "1", "edited explanation")
    human = triage_document_if_ready(state)
    file_human = {
        "rejected_review": False,
        "findings": {
            "F001": {"decision": "accept", "must_fix": True, "explanation": "edited explanation"}
        },
        "added": [],
        "summary": state.summary,
    }
    merged_file = apply_human_decisions(document["findings"], file_human)
    merged_tui = apply_human_decisions(document["findings"], human)
    assert merged_tui == merged_file
    payload_file = build_review_payload(
        sha=sha,
        event="REQUEST_CHANGES",
        summary=file_human["summary"],
        findings=merged_file,
        diff_index=diff_index,
    )
    payload_tui = proposed_payload_from_human(app, ISSUE, human, document, sha, identity)
    assert payload_tui == payload_file


def test_run_review_attach_requires_tty(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    app.interactive = False
    with pytest.raises(WorkflowError, match="interactive terminal"):
        run_review_attach(app, ISSUE, revise=False)


def test_run_review_attach_missing_session(tmp_path):
    app, _, _ = make_app(tmp_path)
    app.interactive = True
    with pytest.raises(WorkflowError, match=f"review-ticket {ISSUE}` first"):
        run_review_attach(app, ISSUE, revise=False)
    assert not (tmp_path / "reviews" / ISSUE / "session.json").exists()


def test_cli_review_attach_is_invalid(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    with pytest.raises(SystemExit) as exc:
        _run(app, [ISSUE, "review", "attach"])
    assert exc.value.code == 2


def test_cli_review_interactive_rejected(tmp_path):
    app, _, _ = make_app(tmp_path)
    with pytest.raises(SystemExit) as exc:
        _run(app, [ISSUE, "review", "interactive"])
    assert exc.value.code == 2


def test_cli_attach_non_tty_errors(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    code = _run(app, [ISSUE, "attach"])
    assert code == 2
    err = app.stderr.getvalue()
    assert "review apply --file" in err
    assert "jira comment" in err
    assert "notes" in err


def test_cli_attach_tty_starts_textual_app(tmp_path, monkeypatch):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    constructed: list[object] = []

    class _StubApp:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

        def run(self) -> None:
            return None

    monkeypatch.setattr("review_ticket.tui.ReviewTicketApp", _StubApp)
    app.stdout.seek(0)
    app.stdout.truncate()
    app.stderr.seek(0)
    app.stderr.truncate()
    code = main(
        [ISSUE, "attach"],
        runner=app.runner,
        config=app.config,
        interactive=True,
        stdout=app.stdout,
        stderr=app.stderr,
    )
    assert code == 0
    assert constructed
    assert constructed[0]["issue"] == ISSUE
    assert constructed[0]["workflow_app"].config.reviews_dir == app.config.reviews_dir
    assert constructed[0]["revise"] is False


def _seed_jira_issue_session(tmp_path: Path) -> None:
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": None,
            "active_sha": None,
            "current_step": "jira-issue",
            "outcome": "BLOCKED",
            "last_completed_step": None,
            "last_updated": "2026-10-17T00:00:00Z",
            "recommendation": "In Progress",
            "decisions": {},
            "pr_candidates": [],
            "next_command": f"review-ticket {ISSUE} notes --reject",
        },
    )


def test_attach_opens_status_without_pr_or_sha(tmp_path, monkeypatch):
    _seed_jira_issue_session(tmp_path)
    app, _, _ = make_app(tmp_path)
    constructed: list[object] = []

    class _StubApp:
        def __init__(self, **kwargs):
            constructed.append(kwargs)

        def run(self) -> None:
            return None

    monkeypatch.setattr("review_ticket.tui.ReviewTicketApp", _StubApp)
    code = main(
        [ISSUE, "attach"],
        runner=app.runner,
        config=app.config,
        interactive=True,
        stdout=app.stdout,
        stderr=app.stderr,
    )
    assert code == 0
    assert constructed


def test_attach_headless_status_without_pr_or_sha(tmp_path):
    from review_ticket.tui import ReviewTicketApp
    from review_ticket.tui.testing_notes_screen import TestingNotesScreen

    _seed_jira_issue_session(tmp_path)
    app, _, _ = make_app(tmp_path)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test() as pilot:
            await pilot.pause()
            assert isinstance(tui.screen, TestingNotesScreen)

    asyncio.run(_run())


def test_triage_save_writes_review_files(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    review = tmp_path / "reviews" / ISSUE / "prs" / "acme-widgets-pr-87" / "commits" / SHA1 / "review"
    (review / "human-review.json").unlink()
    state, document, _sha, _identity = load_triage_state(app, ISSUE)
    accept_finding(state, "1")
    human = triage_document_if_ready(state)
    assert human["findings"]["F001"]["decision"] == "accept"
    from review_ticket.workflow import apply_review

    apply_review(app, ISSUE, human, revise=False)
    stored = json.loads((review / "human-review.json").read_text(encoding="utf-8"))
    assert stored["findings"]["F001"]["decision"] == "accept"
    assert (review / "proposed-review.json").exists()
