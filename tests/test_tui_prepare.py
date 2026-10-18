"""P6: automated review preparation (Scenario D)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from review_ticket.prepare_projection import project_automated_review_prepare
from review_ticket.runner import CommandResult
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.hub_screen import ReviewHubScreen
from review_ticket.tui.prepare_screen import AutomatedReviewPrepareScreen
from review_ticket.tui.pr_screen import PrReviewScreen
from textual.widgets import Button, ListView, Static
from review_ticket.storage import read_json, write_json
from review_ticket.util import sha256_text
from tests.support import DIFF, ISSUE, SHA1, SHA2, jira_document, make_app
from tests.test_status_projection import (
    REF_A,
    REF_B,
    REF_C,
    SHA3,
    SHA_OLD,
    _commit_dir,
    _seed_checks,
    _seed_findings,
    _seed_three_pr_session,
    _store,
)

PILOT_SIZE = (120, 48)


def _seed_diff(commit_dir: Path) -> None:
    commit_dir.mkdir(parents=True, exist_ok=True)
    (commit_dir / "diff.patch").write_text(DIFF, encoding="utf-8")
    review = commit_dir / "review"
    review.mkdir(parents=True, exist_ok=True)
    write_json(review / "diff-lines.json", [["src/Example.cs", 142, "RIGHT"]])


def _seed_scenario_d(tmp_path: Path) -> None:
    _seed_three_pr_session(tmp_path)
    commit_b = _commit_dir(tmp_path, REF_B, SHA2)
    (commit_b / "review" / "findings.json").unlink(missing_ok=True)
    old = _commit_dir(tmp_path, REF_C, SHA_OLD)
    old.mkdir(parents=True, exist_ok=True)
    _seed_checks(old)
    _seed_findings(old)
    _seed_diff(_commit_dir(tmp_path, REF_B, SHA2))
    _seed_diff(_commit_dir(tmp_path, REF_C, SHA3))
    notes = "Ran the cart tests and recorded the result."
    root = tmp_path / "reviews" / ISSUE
    write_json(root / "issue.json", _jira_with_three_prs(notes))
    session = read_json(root / "session.json")
    session.setdefault("decisions", {})
    session["decisions"]["testing_notes"] = {
        "choice": "accept",
        "notes": notes,
        "notes_hash": sha256_text(notes),
        "at": "2026-10-18T12:00:00Z",
    }
    write_json(root / "session.json", session)


def _jira_with_three_prs(notes: str) -> dict:
    doc = jira_document(notes)
    doc["fields"]["description"] += (
        "\nhttps://github.com/acme/widgets/pull/87\n"
        "https://github.com/acme/gadgets/pull/12\n"
        "https://github.com/acme/tools/pull/3\n"
    )
    return doc


def _configure_world_for_run_review(world) -> None:
    world.issue = _jira_with_three_prs("Ran the cart tests and recorded the result.")


def _prime_session_for_run_review(app) -> None:
    from review_ticket.workflow import refresh_issue

    session = app.store.ensure_session(ISSUE)
    normalized = refresh_issue(app, session)
    notes = normalized.get("testing_notes") or ""
    session.setdefault("decisions", {})
    session["decisions"]["testing_notes"] = {
        "choice": "accept",
        "notes": notes,
        "notes_hash": sha256_text(notes),
        "at": "2026-10-18T12:00:00Z",
    }
    app.store.save_session(session)


def _reviewer_calls(runner) -> list[list[str]]:
    return [call for call in runner.calls if call and call[0] == "reviewer"]


def _select_ref(screen: AutomatedReviewPrepareScreen, ref: str) -> None:
    index = next(i for i, row in enumerate(screen._rows) if row.ref == ref)
    list_view = screen.query_one("#pr-list", ListView)
    list_view.index = index
    screen._select_row(index)


async def _open_prepare_screen(pilot, app) -> AutomatedReviewPrepareScreen:
    await pilot.click("#hub-btn")
    await pilot.pause()
    assert isinstance(app.screen, ReviewHubScreen)
    await pilot.press("enter")
    await pilot.pause()
    await pilot.press("enter")
    await pilot.pause()
    assert isinstance(app.screen, AutomatedReviewPrepareScreen)
    return app.screen


def test_scenario_d_labels_current_missing_stale(tmp_path):
    _seed_scenario_d(tmp_path)
    store = _store(tmp_path)
    projection = project_automated_review_prepare(store, ISSUE)
    by_ref = {row.ref: row for row in projection.rows}
    assert by_ref[REF_A].status == "current"
    assert by_ref[REF_A].status_label == "Current"
    assert by_ref[REF_B].status == "missing"
    assert by_ref[REF_B].status_label == "Missing"
    assert by_ref[REF_C].status == "stale"
    assert by_ref[REF_C].status_label == "Stale"


def test_mount_does_not_invoke_reviewer(tmp_path):
    _seed_scenario_d(tmp_path)
    workflow, runner, _world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await _open_prepare_screen(pilot, app)
            assert _reviewer_calls(runner) == []

    asyncio.run(_run())


def test_generate_selected_runs_one_identity(tmp_path):
    _seed_scenario_d(tmp_path)
    workflow, runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    _configure_world_for_run_review(world)
    _prime_session_for_run_review(workflow)
    world.head_by_repo["acme/tools"] = SHA3
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            screen = await _open_prepare_screen(pilot, app)
            _select_ref(screen, REF_C)
            await pilot.pause()
            await pilot.click("#generate-selected-btn")
            for _ in range(120):
                await pilot.pause(0.05)
                if not str(screen.query_one("#busy", Static).render()).strip():
                    break
            assert len(_reviewer_calls(runner)) == 1
            findings_c = _commit_dir(tmp_path, REF_C, SHA3) / "review" / "findings.json"
            assert findings_c.is_file()
            assert not (_commit_dir(tmp_path, REF_B, SHA2) / "review" / "findings.json").exists()

    asyncio.run(_run())


def test_missing_reviewer_command_shows_import_without_findings(tmp_path):
    _seed_scenario_d(tmp_path)
    workflow, runner, world = make_app(tmp_path, reviewer_command=None)
    _configure_world_for_run_review(world)
    _prime_session_for_run_review(workflow)
    world.head_by_repo["acme/gadgets"] = SHA2
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            screen = await _open_prepare_screen(pilot, app)
            _select_ref(screen, REF_B)
            await pilot.pause()
            assert "gadgets" in str(screen.query_one("#detail", Static).render())
            await pilot.click("#generate-selected-btn")
            for _ in range(120):
                await pilot.pause(0.05)
                if not str(screen.query_one("#busy", Static).render()).strip():
                    break
            _select_ref(screen, REF_B)
            assert _reviewer_calls(runner) == []
            detail = str(screen.query_one("#detail", Static).render())
            assert "import-review" in detail
            assert "prompt.md" in detail
            findings_b = _commit_dir(tmp_path, REF_B, SHA2) / "review" / "findings.json"
            assert not findings_b.exists()

    asyncio.run(_run())


def test_failed_runner_leaves_retryable_error(tmp_path):
    _seed_scenario_d(tmp_path)
    workflow, runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    _configure_world_for_run_review(world)
    _prime_session_for_run_review(workflow)
    world.head_by_repo["acme/gadgets"] = SHA2

    def fail_reviewer(argv, cwd, data, env):
        return CommandResult(list(argv), 1, "", "reviewer adapter failed")

    runner.routes.insert(0, (lambda argv: argv and argv[0] == "reviewer", fail_reviewer))
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            screen = await _open_prepare_screen(pilot, app)
            _select_ref(screen, REF_B)
            await pilot.pause()
            assert "gadgets" in str(screen.query_one("#detail", Static).render())
            await pilot.click("#generate-selected-btn")
            for _ in range(120):
                await pilot.pause(0.05)
                if not str(screen.query_one("#busy", Static).render()).strip():
                    break
            _select_ref(screen, REF_B)
            detail = str(screen.query_one("#detail", Static).render())
            assert "reviewer adapter failed" in detail
            assert "retry" in detail.lower()
            gen_btn = screen.query_one("#generate-selected-btn", Button)
            assert gen_btn.disabled is False

    asyncio.run(_run())


def test_view_opens_pr_screen_for_current_sha(tmp_path):
    _seed_scenario_d(tmp_path)
    workflow, _runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await _open_prepare_screen(pilot, app)
            await pilot.click("#row-action-btn")
            await pilot.pause()
            assert isinstance(app.screen, PrReviewScreen)
            assert app.screen.sha == SHA1

    asyncio.run(_run())


def test_prepare_esc_returns_to_hub(tmp_path):
    _seed_scenario_d(tmp_path)
    workflow, _runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await _open_prepare_screen(pilot, app)
            await pilot.press("escape")
            await pilot.pause()
            assert isinstance(app.screen, ReviewHubScreen)

    asyncio.run(_run())
