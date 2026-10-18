"""P6: automated review preparation screen (scenario D)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from review_ticket.storage import read_json, write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.automated_prepare_screen import AutomatedPrepareScreen
from textual.widgets import Button, Markdown

from tests.support import DIFF, ISSUE, SHA1, SHA2, make_app
from tests.test_status_projection import REF_A, REF_B, REF_C, SHA3, _seed_three_pr_session, _store

PILOT_SIZE = (110, 56)
SHA_OLD = "d" * 40


def _pr_slug(ref: str) -> str:
    owner, rest = ref.split("/", 1)
    repo, number = rest.split("#", 1)
    return f"{owner}-{repo}-pr-{number}"


def _commit_dir(tmp_path: Path, ref: str, sha: str) -> Path:
    return tmp_path / "reviews" / ISSUE / "prs" / _pr_slug(ref) / "commits" / sha


def _seed_hub_ready(tmp_path: Path) -> None:
    _seed_three_pr_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    session = read_json(root / "session.json") or {}
    session["decisions"] = {
        "testing_notes": {"choice": "accept"},
        "pr_readiness": {"choice": "accept"},
    }
    write_json(root / "session.json", session)
    # Current findings for REF_A
    review_a = _commit_dir(tmp_path, REF_A, SHA1) / "review"
    review_a.mkdir(parents=True, exist_ok=True)
    write_json(review_a / "findings.json", {"summary": "ok", "findings": []})
    # Stale findings for REF_B at old sha only
    review_b_old = _commit_dir(tmp_path, REF_B, SHA_OLD) / "review"
    review_b_old.mkdir(parents=True, exist_ok=True)
    write_json(review_b_old / "findings.json", {"summary": "old", "findings": []})
    commit_b = _commit_dir(tmp_path, REF_B, SHA2)
    commit_b.mkdir(parents=True, exist_ok=True)
    findings_b = commit_b / "review" / "findings.json"
    if findings_b.exists():
        findings_b.unlink()


def test_prepare_mount_does_not_invoke_reviewer(tmp_path):
    _seed_hub_ready(tmp_path)
    workflow_app, runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    world.reviewer_output = {
        "summary": "Generated",
        "approval_recommendation": "comment",
        "findings": [{"id": "F001", "title": "T", "explanation": "E"}],
    }
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE, workflow_app=workflow_app)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            app.push_screen(AutomatedPrepareScreen(store, ISSUE, workflow_app))
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, AutomatedPrepareScreen)
            assert screen.generation_ran_on_mount is False
            assert not any(call[0] == "reviewer" for call in runner.calls)

    asyncio.run(_run())


def test_prepare_table_labels_view_generate_stale(tmp_path):
    _seed_hub_ready(tmp_path)
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            app.push_screen(AutomatedPrepareScreen(store, ISSUE))
            await pilot.pause()
            doc = app.screen.query_one("#prepare-table", Markdown).source
            assert "| Current | View |" in doc
            assert "| Stale | Generate |" in doc
            assert "| Missing | Generate |" in doc

    asyncio.run(_run())


def test_generate_selected_writes_findings_for_one_pr(tmp_path):
    _seed_hub_ready(tmp_path)
    workflow_app, runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    world.reviewer_output = {
        "summary": "Generated",
        "approval_recommendation": "comment",
        "findings": [{"id": "F001", "title": "T", "explanation": "E"}],
    }
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE, workflow_app=workflow_app)
    target_dir = _commit_dir(tmp_path, REF_C, SHA3) / "review"
    commit_c = _commit_dir(tmp_path, REF_C, SHA3)
    (commit_c / "diff.patch").write_text(DIFF, encoding="utf-8")
    review_c = commit_c / "review"
    review_c.mkdir(parents=True, exist_ok=True)
    write_json(review_c / "diff-lines.json", [])

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            app.push_screen(AutomatedPrepareScreen(store, ISSUE, workflow_app, focus_ref=REF_C))
            await pilot.pause()
            await pilot.click("#btn-generate-one")
            await pilot.pause()

    asyncio.run(_run())
    assert (target_dir / "findings.json").exists()
    reviewer_calls = [call for call in runner.calls if call and call[0] == "reviewer"]
    assert len(reviewer_calls) == 1


def test_missing_reviewer_command_shows_import_without_findings(tmp_path):
    _seed_hub_ready(tmp_path)
    workflow_app, _, _ = make_app(tmp_path, reviewer_command=None)
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE, workflow_app=workflow_app)
    target = _commit_dir(tmp_path, REF_C, SHA3) / "review"
    commit_c = _commit_dir(tmp_path, REF_C, SHA3)
    (commit_c / "diff.patch").write_text(DIFF, encoding="utf-8")
    review_c = commit_c / "review"
    review_c.mkdir(parents=True, exist_ok=True)
    write_json(review_c / "diff-lines.json", [])

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            app.push_screen(AutomatedPrepareScreen(store, ISSUE, workflow_app, focus_ref=REF_C))
            await pilot.pause()
            await pilot.click("#btn-generate-one")
            await pilot.pause()
            hint = str(app.screen.query_one("#import-hint").render())
            assert "import-review" in hint or "import" in hint.casefold()

    asyncio.run(_run())
    assert not (target / "findings.json").exists()
    assert (target / "context" / "prompt.md").exists()


def test_failed_generation_is_retryable(tmp_path):
    _seed_hub_ready(tmp_path)
    workflow_app, runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    world.reviewer_output = {"summary": "bad", "findings": [{"id": "F1", "title": "Incomplete"}]}
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE, workflow_app=workflow_app)
    commit_c = _commit_dir(tmp_path, REF_C, SHA3)
    (commit_c / "diff.patch").write_text(DIFF, encoding="utf-8")
    review_c = commit_c / "review"
    review_c.mkdir(parents=True, exist_ok=True)
    write_json(review_c / "diff-lines.json", [])

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            app.push_screen(AutomatedPrepareScreen(store, ISSUE, workflow_app, focus_ref=REF_C))
            await pilot.pause()
            await pilot.click("#btn-generate-one")
            await pilot.pause()
            doc = app.screen.query_one("#prepare-table", Markdown).source
            assert "| Failed | Retry |" in doc
            assert app.screen.query_one("#btn-generate-one", Button).disabled is False

    asyncio.run(_run())
