import json
from pathlib import Path

import pytest

from review_ticket.cli import main
from review_ticket.findings import apply_human_decisions, build_review_payload
from review_ticket.interactive_triage import (
    human_document_from_state,
    load_triage_state,
    process_triage_command,
    proposed_payload_from_human,
    publish_preview_counts,
    run_interactive_triage,
    TriageState,
    FindingState,
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


def test_process_triage_command_save_parity_with_apply_file(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    review = tmp_path / "reviews" / ISSUE / "prs" / "acme-widgets-pr-87" / "commits" / SHA1 / "review"
    (review / "human-review.json").unlink()
    state, document, sha, identity = load_triage_state(app, ISSUE)
    diff_index = {("src/Example.cs", 142, "RIGHT")}
    prompts = iter(["edited explanation"])
    human = None
    for cmd in ("t 1", "e 1", "w"):
        result = process_triage_command(
            state,
            cmd,
            document=document,
            diff_index=diff_index,
            prompt=lambda _: next(prompts),
            write=lambda _: None,
        )
        if isinstance(result, dict):
            human = result
    assert human is not None
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


def test_run_interactive_triage_requires_tty(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    app.interactive = False
    with pytest.raises(WorkflowError, match="interactive terminal"):
        run_interactive_triage(app, ISSUE, revise=False)


def test_cli_review_interactive_non_tty_errors(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    code = _run(app, [ISSUE, "review", "interactive"])
    assert code == 2
    assert "interactive terminal" in app.stderr.getvalue()


def test_run_interactive_triage_save_writes_review_files(tmp_path):
    app, _, _ = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    review = tmp_path / "reviews" / ISSUE / "prs" / "acme-widgets-pr-87" / "commits" / SHA1 / "review"
    (review / "human-review.json").unlink()
    app.interactive = True
    inputs = iter(["t 1", "w", ""])
    app.input_fn = lambda _: next(inputs)
    human = run_interactive_triage(app, ISSUE, revise=False)
    assert human["findings"]["F001"]["decision"] == "accept"
    from review_ticket.workflow import apply_review

    apply_review(app, ISSUE, human, revise=False)
    stored = json.loads((review / "human-review.json").read_text(encoding="utf-8"))
    assert stored["findings"]["F001"]["decision"] == "accept"
    assert (review / "proposed-review.json").exists()
