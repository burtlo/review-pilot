"""Headless testing-notes screen at the jira-issue gate (P2)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from review_ticket.reports import return_comment
from review_ticket.storage import read_json, read_jsonl, write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.shared_chrome import DecisionPanel
from review_ticket.tui.readiness_screen import ReadinessScreen
from review_ticket.tui.status_screen import StatusScreen
from review_ticket.tui.testing_notes_screen import COMMENT_DECLINED, TRANSITION_DECLINED, TestingNotesScreen
from review_ticket.util import sha256_text
from review_ticket.workflow import decide_notes
from textual.containers import VerticalScroll
from textual.widgets import Button, Link, Markdown, Static, TextArea

from tests.support import ISSUE, jira_document, make_app, passing_checks
from tests.test_status_projection import _seed_three_pr_session, _store

# Tall enough for stacked evidence plus the shared decision panel.
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


def _plain(widget: Static) -> str:
    content = widget.content
    return content if isinstance(content, str) else str(content)


def _actions(root: Path) -> list[dict]:
    path = root / "actions.jsonl"
    if not path.exists():
        return []
    return list(read_jsonl(path))


def _successes(root: Path, kind: str | None = None) -> list[dict]:
    return [
        entry
        for entry in _actions(root)
        if entry.get("status") == "success" and (kind is None or entry.get("kind") == kind)
    ]


def _receipt_values(text: str) -> dict[str, str]:
    labels = ("Draft saved", "Comment posted", "Status moved", "Current status")
    found: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        for label in labels:
            if stripped.startswith(label):
                found[label] = stripped[len(label) :].strip()
    return found


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
            assert "Acceptance criteria" in assessment or "Acceptance Criteria" in assessment
            approve = tui.screen.query_one("#approve-btn", Button)
            reject = tui.screen.query_one("#reject-btn", Button)
            assert approve.display is True
            assert reject.display is True
            # step_jira never offers accept for an empty notes body.
            assert approve.disabled is True
            assert reject.disabled is False
            assert reject.has_class("recommended")
            assert reject.variant == "error"
            assert not approve.has_class("recommended")
            assert approve.region.width == reject.region.width
            assert approve.region.x < reject.region.x
            description = tui.screen.query_one("#description-scroll")
            notes = tui.screen.query_one("#assessment-scroll")
            assert description.display is True
            assert notes.display is True
            assert notes.region.height > description.region.height
            share = notes.region.height / (notes.region.height + description.region.height)
            assert share >= 0.55
            session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
            assert "testing_notes" not in (session.get("decisions") or {})
            acli_views = [call for call in runner.calls if call and call[0] == "acli" and "view" in call]
            assert len(acli_views) == 1

    asyncio.run(_run())


def test_description_and_notes_scroll_independently(tmp_path):
    _seed_jira_issue_session(tmp_path)
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=(100, 36)) as pilot:
            await pilot.pause()
            screen = tui.screen
            screen.query_one("#description-md", Markdown).update("\n".join(f"desc line {i}" for i in range(80)))
            screen.query_one("#assessment-md", Markdown).update("\n".join(f"note line {i}" for i in range(80)))
            await pilot.pause()
            description = screen.query_one("#description-scroll", VerticalScroll)
            notes = screen.query_one("#assessment-scroll", VerticalScroll)
            notes.scroll_to(y=4, animate=False)
            await pilot.pause()
            assert notes.scroll_y > 0
            assert description.scroll_y == 0
            held = notes.scroll_y
            description.scroll_to(y=3, animate=False)
            await pilot.pause()
            assert description.scroll_y > 0
            assert notes.scroll_y == held

    asyncio.run(_run())


def test_ticket_panels_grow_when_terminal_grows_taller(tmp_path):
    """Spare rows go to the stacked panes; the approve/reject row stays one button tall."""
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
            panel = screen.query_one(DecisionPanel)

            await pilot.resize_terminal(100, 70)
            await pilot.pause()

            tall_description = screen.query_one("#description-scroll").region.height
            tall_assessment = screen.query_one("#assessment-scroll").region.height
            assert tall_description >= short_description + 10
            assert tall_assessment >= short_assessment + 10
            assert tall_assessment > tall_description
            assert screen.query_one("#decision-row").region.height == short_row
            footer = screen.query_one("Footer")
            assert panel.region.bottom <= footer.region.y
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


def test_reject_edit_hides_description_and_shows_notes(tmp_path):
    _seed_jira_issue_session(tmp_path)
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await pilot.click("#reject-btn")
            await pilot.pause()
            screen = tui.screen
            description = screen.query_one("#description-scroll")
            notes = screen.query_one("#assessment-scroll", VerticalScroll)
            assert description.display is False
            assert screen.query_one("#description-collapsed").display is True
            assert notes.display is True
            assert notes.region.height > 0
            assert "No testing notes were detected" in screen.query_one("#assessment-md", Markdown).source
            editor = screen.query_one("#draft-editor", TextArea)
            assert editor.display is True
            assert "No testing notes were found" in editor.text
            assert tui.focused is editor
            assert screen.query_one("#phase-decision").display is False
            assert screen.query_one("#phase-editing").display is True

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
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await pilot.click("#reject-btn")
            await pilot.pause()
            draft = tui.screen.query_one("#draft-editor", TextArea)
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
            assert tui.screen.query_one("#phase-saved").display is True
            assert tui.screen.query_one("#phase-post").display is False
            assert edited in _plain(tui.screen.query_one("#saved-preview", Static))
            assert not _jira_comment_creates(runner)
            assert _successes(root) == []
            assert tui.screen.query_one("#description-scroll").display is False
            assert tui.screen.query_one("#assessment-scroll").display is True

    asyncio.run(_run())


def test_scenario_a_approve_stores_acceptance_without_jira_write(tmp_path):
    _seed_jira_issue_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document("Ran the cart tests and recorded the result.")
    world.required_checks = passing_checks()
    world.all_checks = passing_checks()
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            assert isinstance(tui.screen, TestingNotesScreen)
            approve = tui.screen.query_one("#approve-btn", Button)
            reject = tui.screen.query_one("#reject-btn", Button)
            assert approve.disabled is False
            assert reject.disabled is False
            assert approve.has_class("recommended")
            assert approve.variant == "success"
            assert not reject.has_class("recommended")
            await pilot.click("#approve-btn")
            await pilot.pause()
            assert isinstance(tui.screen, ReadinessScreen)
            session = read_json(root / "session.json")
            assert session["decisions"]["testing_notes"]["choice"] == "accept"
            assert session.get("current_step") != "jira-issue"
            summary = _plain(tui.screen.query_one("#readiness-summary", Static))
            assert "87" in summary
            assert "PR #" in summary
            assert _successes(root) == []
            assert not _jira_comment_creates(runner)
            assert not _jira_transitions(runner)
            assert not [call for call in runner.calls if call and call[0] == "reviewer"]

    asyncio.run(_run())


def test_reopen_shows_saved_draft(tmp_path):
    _seed_jira_issue_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)
    edited = "Edited return body for peer review.\n"

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await _save_reject_draft(pilot, tui, edited)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(tui.screen, StatusScreen)
            tui.push_screen(TestingNotesScreen(app.store, ISSUE, app))
            await pilot.pause()
            screen = tui.screen
            assert isinstance(screen, TestingNotesScreen)
            assert screen.query_one("#phase-saved").display is True
            assert edited in _plain(screen.query_one("#saved-preview", Static))
            assert (root / "return-comment.md").read_text(encoding="utf-8") == edited
            assert screen.query_one("#description-scroll").display is False
            assert screen.query_one("#assessment-scroll").display is True

    asyncio.run(_run())


def test_revise_reenables_saved_decision(tmp_path):
    _seed_jira_issue_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    notes = "Ran the cart tests and recorded the result."
    saved = "Saved rejection draft.\n"
    (root / "return-comment.md").write_text(saved, encoding="utf-8")
    session = read_json(root / "session.json")
    session["decisions"] = {
        "testing_notes": {
            "choice": "reject",
            "notes": "",
            "notes_hash": sha256_text(notes),
            "at": "2026-10-17T00:00:00Z",
        }
    }
    write_json(root / "session.json", session)
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document(notes)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=True)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            approve = tui.screen.query_one("#approve-btn", Button)
            reject = tui.screen.query_one("#reject-btn", Button)
            assert approve.disabled is False
            assert reject.disabled is False
            assert tui.screen.query_one("#phase-decision").display is True
            await pilot.click("#reject-btn")
            await pilot.pause()
            assert tui.screen.query_one("#draft-editor", TextArea).text == saved

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
    tui.screen.query_one("#draft-editor", TextArea).text = body
    await pilot.click("#save-btn")
    await pilot.pause()


async def _continue_to_post(pilot) -> None:
    await pilot.click("#continue-btn")
    await pilot.pause()


def test_scenario_b_posts_and_transitions_only_after_each_yes(tmp_path):
    _seed_jira_issue_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)
    body = "Edited return body for post.\n"

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            reject = tui.screen.query_one("#reject-btn", Button)
            assert reject.has_class("recommended")
            await _save_reject_draft(pilot, tui, body)
            assert tui.screen.query_one("#description-scroll").display is False
            assert tui.screen.query_one("#assessment-scroll").display is True
            assert not _jira_comment_creates(runner)
            await _continue_to_post(pilot)
            assert body.rstrip() in _plain(tui.screen.query_one("#post-preview", Static))
            assert "Post this comment to Jira?" in _plain(tui.screen.query_one("#post-question", Static))
            assert not _jira_comment_creates(runner)
            assert tui.screen.query_one("#phase-transition").display is False
            await pilot.click("#comment-yes-btn")
            await pilot.pause()
            assert len(_jira_comment_creates(runner)) == 1
            assert len(_successes(root, "jira.comment")) == 1
            assert not _jira_transitions(runner)
            assert tui.screen.query_one("#phase-transition").display is True
            assert "In Progress" in _plain(tui.screen.query_one("#transition-preview", Static))
            assert tui.screen.query_one("#description-scroll").display is False
            assert tui.screen.query_one("#assessment-scroll").display is True
            await pilot.click("#transition-yes-btn")
            await pilot.pause()
            assert len(_jira_transitions(runner)) == 1
            assert len(_successes(root, "jira.transition")) == 1
            receipt = _receipt_values(_plain(tui.screen.query_one("#receipt-body", Static)))
            assert receipt["Draft saved"] == "YES"
            assert receipt["Comment posted"] == "YES"
            assert receipt["Status moved"] == "YES"
            assert receipt["Current status"] == "In Progress"
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(tui.screen, StatusScreen)

    asyncio.run(_run())


def test_post_deny_records_decline_and_leaves_the_draft(tmp_path):
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
            await _continue_to_post(pilot)
            await pilot.click("#comment-no-btn")
            await pilot.pause()
            session = read_json(root / "session.json")
            decision = session["decisions"]["testing_notes"]
            assert decision["choice"] == "reject"
            assert decision[COMMENT_DECLINED] is True
            assert TRANSITION_DECLINED not in decision
            assert (root / "return-comment.md").read_text(encoding="utf-8") == body
            assert _successes(root) == []
            assert not _jira_comment_creates(runner)
            assert not _jira_transitions(runner)
            assert tui.screen.query_one("#phase-transition").display is True
            assert tui.screen.query_one("#phase-post").display is False

    asyncio.run(_run())


def test_reopen_after_post_does_not_comment_again(tmp_path):
    _seed_jira_issue_session(tmp_path)
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await _save_reject_draft(pilot, tui)
            await _continue_to_post(pilot)
            await pilot.click("#comment-yes-btn")
            await pilot.pause()
            assert len(_jira_comment_creates(runner)) == 1
            await pilot.press("escape")
            await pilot.pause()
            tui.push_screen(TestingNotesScreen(app.store, ISSUE, app))
            await pilot.pause()
            assert tui.screen.query_one("#phase-transition").display is True
            assert len(_jira_comment_creates(runner)) == 1

    asyncio.run(_run())


def test_transition_deny_records_decline_without_moving_status(tmp_path):
    _seed_jira_issue_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await _save_reject_draft(pilot, tui)
            await _continue_to_post(pilot)
            await pilot.click("#comment-yes-btn")
            await pilot.pause()
            await pilot.click("#transition-no-btn")
            await pilot.pause()
            assert not _jira_transitions(runner)
            assert _successes(root, "jira.transition") == []
            assert len(_successes(root, "jira.comment")) == 1
            decision = read_json(root / "session.json")["decisions"]["testing_notes"]
            assert decision[TRANSITION_DECLINED] is True
            receipt = _receipt_values(_plain(tui.screen.query_one("#receipt-body", Static)))
            assert receipt["Comment posted"] == "YES"
            assert receipt["Status moved"] == "DECLINED"
            assert tui.screen.query_one("#phase-transition").display is False
            assert tui.screen.query_one("#phase-receipt").display is True

    asyncio.run(_run())


def test_failed_post_shows_failure_and_keeps_transition_hidden(tmp_path):
    _seed_jira_issue_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    world.comment_code = 1
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await _save_reject_draft(pilot, tui)
            await _continue_to_post(pilot)
            await pilot.click("#comment-yes-btn")
            await pilot.pause()
            assert tui.screen.query_one("#phase-transition").display is False
            assert tui.screen.query_one("#phase-receipt").display is True
            receipt = _plain(tui.screen.query_one("#receipt-body", Static))
            values = _receipt_values(receipt)
            assert values["Draft saved"] == "YES"
            assert values["Comment posted"] == "FAILED"
            assert values["Status moved"] == "not attempted"
            assert "comment failed" in receipt
            assert not _jira_transitions(runner)
            assert _successes(root) == []
            assert (root / "return-comment.md").exists()

    asyncio.run(_run())


def test_cli_decide_notes_reject_without_draft_body_uses_template(tmp_path):
    _seed_jira_issue_session(tmp_path)
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document("Some notes")
    decide_notes(app, ISSUE, "reject", "extra reviewer note", revise=False)
    body = (tmp_path / "reviews" / ISSUE / "return-comment.md").read_text(encoding="utf-8")
    assert "missing or not adequate" in body
    assert "extra reviewer note" in body
