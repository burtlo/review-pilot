"""Headless testing-notes screen at the jira-issue gate (P2–P3)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from dataclasses import replace

from review_ticket.reports import return_comment
from review_ticket.storage import read_json, read_jsonl, write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.decision_panel import DecisionPanel, DecisionPanelState
from review_ticket.tui.readiness_screen import ReadinessScreen
from review_ticket.tui.status_screen import StatusScreen
from review_ticket.tui.testing_notes_screen import TestingNotesScreen
from review_ticket.util import sha256_text
from review_ticket.workflow import decide_notes
from textual.widgets import Button, Link, Markdown, Static, TextArea

from tests.support import ISSUE, jira_document, make_app, passing_checks
from tests.test_status_projection import _seed_three_pr_session, _store

# Tall enough for issue body (1fr) plus reject/post authorize controls.
_RUN_TEST_SIZE = (100, 52)


def _seed_jira_issue_session(tmp_path: Path) -> None:
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": None,
            "active_sha": None,
            "current_step": "jira-issue",
            "outcome": "ACTION_REQUIRED",
            "last_completed_step": None,
            "last_updated": "2026-10-17T00:00:00Z",
            "recommendation": "In Progress",
            "decisions": {},
            "pr_candidates": [],
            "next_command": f"review-ticket {ISSUE} notes --reject",
        },
    )


def test_jira_issue_without_notes_opens_testing_notes_screen(tmp_path):
    _seed_jira_issue_session(tmp_path)
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    world.issue["fields"]["description"] = (
        "## Acceptance Criteria\n\n- Ship safely\n\n## Overview\n\nFixture description body.\n"
    )
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            assert isinstance(tui.screen, TestingNotesScreen)
            link = tui.screen.query_one("#issue-link", Link)
            assert link.url == f"https://example.test/browse/{ISSUE}"
            desc = tui.screen.query_one("#description-md", Markdown).source
            assert "Fixture description body." in desc
            assert "## Ticket description" in desc
            assert "Testing notes assessment" in str(
                tui.screen.query_one("#assessment-heading", Static).render()
            )
            assessment = tui.screen.query_one("#assessment-md", Markdown).source
            assert "No testing notes were detected" in assessment
            assert "Testing notes assessment" not in assessment
            approve = tui.screen.query_one("#approve-btn", Button)
            assert approve.display is True
            assert approve.disabled is True
            assert tui.screen.query_one("#reject-btn", Button).display is True
            session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
            assert "testing_notes" not in (session.get("decisions") or {})
            acli_views = [call for call in runner.calls if call and call[0] == "acli" and "view" in call]
            assert len(acli_views) == 1

    asyncio.run(_run())


def test_ticket_panels_grow_when_terminal_grows_taller(tmp_path):
    """Spare rows go to the issue panes; the decision row stays one button tall."""
    _seed_jira_issue_session(tmp_path)
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            screen = tui.screen
            short_description = screen.query_one("#description-scroll").region.height
            short_assessment = screen.query_one("#assessment-scroll").region.height
            short_row = screen.query_one("#decision-row").region.height

            await pilot.resize_terminal(100, 70)
            await pilot.pause()

            tall_description = screen.query_one("#description-scroll").region.height
            tall_assessment = screen.query_one("#assessment-scroll").region.height
            panel = screen.query_one("#decision-panel")
            assert tall_description >= short_description + 10
            assert tall_assessment >= short_assessment + 10
            assert tall_assessment >= tall_description
            assert screen.query_one("#decision-row").region.height == short_row == 3
            assert panel.region.bottom == screen.size.height - 1

    asyncio.run(_run())


def test_human_review_session_stays_on_status_screen(tmp_path):
    _seed_three_pr_session(tmp_path)
    store = _store(tmp_path)
    app, runner, _world = make_app(tmp_path)
    tui = ReviewTicketApp(store=store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            assert isinstance(tui.screen, StatusScreen)
            assert not [call for call in runner.calls if call and call[0] == "acli"]

    asyncio.run(_run())


def test_reject_hides_description_keeps_notes_visible(tmp_path):
    _seed_jira_issue_session(tmp_path)
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await pilot.click("#reject-btn")
            await pilot.pause()
            assert tui.screen.query_one("#description-scroll").display is False
            assert tui.screen.query_one("#assessment-scroll").display is True

    asyncio.run(_run())


def test_reject_save_writes_draft_and_decision(tmp_path):
    _seed_jira_issue_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    step_jira_body = return_comment(
        issue=ISSUE,
        reason="No testing notes were found on the Jira issue.",
        notes="",
        links=[],
    )
    (root / "return-comment.md").write_text(step_jira_body, encoding="utf-8")
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await pilot.click("#reject-btn")
            await pilot.pause()
            draft = tui.screen.query_one("#return-draft", TextArea)
            assert draft.text == step_jira_body
            assert tui.focused is draft
            edited = "Edited return body for peer review.\n"
            draft.text = edited
            await pilot.click("#save-btn")
            await pilot.pause()
            session = read_json(root / "session.json")
            decision = session["decisions"]["testing_notes"]
            assert decision["choice"] == "reject"
            assert decision["notes_hash"] == sha256_text("")
            assert (root / "return-comment.md").read_text(encoding="utf-8") == edited
            assert session["return_draft"] == str(root / "return-comment.md")
            assert tui.screen.query_one("#approve-btn", Button).disabled is True
            assert tui.screen.query_one("#reject-btn", Button).disabled is True

    asyncio.run(_run())


def test_accept_advances_to_readiness_screen(tmp_path):
    _seed_jira_issue_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document("Ran the cart tests and recorded the result.")
    world.required_checks = passing_checks()
    world.all_checks = passing_checks()
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            assert isinstance(tui.screen, TestingNotesScreen)
            await pilot.click("#approve-btn")
            await pilot.pause()
            assert isinstance(tui.screen, ReadinessScreen)
            session = read_json(root / "session.json")
            assert session["decisions"]["testing_notes"]["choice"] == "accept"
            assert session.get("current_step") != "jira-issue"
            summary = tui.screen.query_one("#summary-md", Markdown).source
            assert "Overall" in summary
            assert not (root / "actions.jsonl").exists()

    asyncio.run(_run())


def test_reopen_after_saved_reject_restores_draft_preview(tmp_path):
    _seed_jira_issue_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)
    saved_body = "Draft kept after leaving the screen.\n"

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await pilot.click("#reject-btn")
            await pilot.pause()
            tui.screen.query_one("#return-draft", TextArea).text = saved_body
            await pilot.click("#save-btn")
            await pilot.pause()
            tui.pop_screen()
            tui.push_screen(TestingNotesScreen(tui.store, ISSUE, app))
            await pilot.pause()
            assert tui.screen.query_one("#description-scroll").display is False
            preview = tui.screen.query_one("#saved-preview-md", Markdown).source
            assert saved_body.rstrip() in preview
            panel = tui.screen.query_one("#decision-panel", DecisionPanel)
            assert panel._model.state == DecisionPanelState.SAVED

    asyncio.run(_run())


def _jira_comment_creates(runner) -> list[list[str]]:
    return [
        call
        for call in runner.calls
        if call and call[0] == "acli" and "comment" in call and "create" in call
    ]


def _jira_transitions(runner) -> list[list[str]]:
    return [call for call in runner.calls if call and call[0] == "acli" and "transition" in call]


async def _save_reject_draft(pilot, tui, body: str = "Edited return body for post.\n") -> None:
    await pilot.click("#reject-btn")
    await pilot.pause()
    tui.screen.query_one("#return-draft", TextArea).text = body
    await pilot.click("#save-btn")
    await pilot.pause()
    await pilot.click("#continue-btn")
    await pilot.pause()


def test_post_approve_posts_comment_and_shows_transition(tmp_path):
    _seed_jira_issue_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)
    body = "Edited return body for post.\n"

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await _save_reject_draft(pilot, tui, body)
            preview = tui.screen.query_one("#comment-preview-md", Markdown).source
            assert body.rstrip() in preview
            assert f"Comment on {ISSUE}" in preview
            await pilot.click("#comment-yes-btn")
            await pilot.pause()
            assert len(_jira_comment_creates(runner)) == 1
            actions = read_jsonl(root / "actions.jsonl")
            assert any(entry.get("status") == "success" and entry.get("kind") == "jira.comment" for entry in actions)
            transition_md = tui.screen.query_one("#transition-preview-md", Markdown).source
            assert "In Progress" in transition_md
            assert tui.screen.query_one("#transition-group").display is True

    asyncio.run(_run())


def test_post_deny_leaves_session_and_actions_unchanged(tmp_path):
    _seed_jira_issue_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await _save_reject_draft(pilot, tui)
            session_after_save = read_json(root / "session.json")
            await pilot.click("#comment-no-btn")
            await pilot.pause()
            assert read_json(root / "session.json") == session_after_save
            assert not (root / "actions.jsonl").exists()
            assert not _jira_comment_creates(runner)
            assert tui.screen.query_one("#transition-group").display is True

    asyncio.run(_run())


def test_second_post_approve_is_idempotent(tmp_path):
    _seed_jira_issue_session(tmp_path)
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)
    body = "Edited return body for post.\n"

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await _save_reject_draft(pilot, tui, body)
            await pilot.click("#comment-yes-btn")
            await pilot.pause()
            panel = tui.screen.query_one("#decision-panel", DecisionPanel)
            panel.restore_model(
                replace(
                    panel.model,
                    state=DecisionPanelState.COMMENT_CONFIRM,
                    comment_outcome=None,
                    comment_preview=f"Comment on {ISSUE}.\n\n{body.rstrip()}\n",
                )
            )
            await pilot.click("#comment-yes-btn")
            await pilot.pause()
            assert len(_jira_comment_creates(runner)) == 1

    asyncio.run(_run())


def test_transition_approve_returns_to_status_screen(tmp_path):
    _seed_jira_issue_session(tmp_path)
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await _save_reject_draft(pilot, tui)
            await pilot.click("#comment-yes-btn")
            await pilot.pause()
            await pilot.click("#transition-yes-btn")
            await pilot.pause()
            assert isinstance(tui.screen, StatusScreen)
            assert len(_jira_transitions(runner)) == 1

    asyncio.run(_run())


def test_transition_deny_does_not_transition(tmp_path):
    _seed_jira_issue_session(tmp_path)
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await _save_reject_draft(pilot, tui)
            await pilot.click("#comment-yes-btn")
            await pilot.pause()
            await pilot.click("#transition-no-btn")
            await pilot.pause()
            assert not _jira_transitions(runner)
            assert isinstance(tui.screen, StatusScreen)

    asyncio.run(_run())


def test_failed_post_shows_blocked_and_keeps_transition_hidden(tmp_path):
    _seed_jira_issue_session(tmp_path)
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    world.comment_code = 1
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await _save_reject_draft(pilot, tui)
            await pilot.click("#comment-yes-btn")
            await pilot.pause()
            preview = tui.screen.query_one("#comment-preview-md", Markdown).source
            assert "Failed" in preview
            assert tui.screen.query_one("#transition-group").display is False

    asyncio.run(_run())


def test_cli_decide_notes_reject_without_draft_body_uses_template(tmp_path):
    _seed_jira_issue_session(tmp_path)
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document("Some notes")
    decide_notes(app, ISSUE, "reject", "extra reviewer note", revise=False)
    body = (tmp_path / "reviews" / ISSUE / "return-comment.md").read_text(encoding="utf-8")
    assert "missing or not adequate" in body
    assert "extra reviewer note" in body
