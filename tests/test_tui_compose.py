"""P9: headless GitHub compose preview."""

from __future__ import annotations

import asyncio

from review_ticket.compose_projection import project_github_compose
from review_ticket.storage import write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.compose_screen import GitHubComposeScreen
from review_ticket.tui.hub_screen import ReviewHubScreen
from textual.widgets import Button, ListView
from tests.support import DIFF, ISSUE, make_app
from tests.test_status_projection import REF_B, _commit_dir, _seed_checks, _seed_findings, _seed_three_pr_session, _store

PILOT_SIZE = (120, 48)
SHA2 = "b" * 40


def _seed_compose_ready(tmp_path) -> None:
    _seed_three_pr_session(tmp_path)
    commit = _commit_dir(tmp_path, REF_B, SHA2)
    commit.mkdir(parents=True, exist_ok=True)
    _seed_checks(commit)
    _seed_findings(commit)
    review = commit / "review"
    write_json(
        review / "human-review.json",
        {
            "rejected_review": False,
            "findings": {"F001": {"decision": "accept", "must_fix": True}},
            "added": [],
            "disposition": "REQUEST_CHANGES",
            "blocker_confirmed": True,
            "event": "REQUEST_CHANGES",
            "summary": "Please fix the quantity check.",
        },
    )
    write_json(review / "diff-lines.json", [["src/Example.cs", 142, "RIGHT"]])
    (commit / "diff.patch").write_text(DIFF, encoding="utf-8")
    write_json(
        review / "manual-review.json",
        {
            "sha": SHA2,
            "completed": True,
            "notes": "Inspected manually.",
            "findings": [],
            "disposition": "COMMENT",
            "recorded_at": "2026-10-18T12:00:00Z",
        },
    )
    testing = commit / "testing"
    testing.mkdir(parents=True, exist_ok=True)
    functional_digest = "sha256:" + "c" * 64
    write_json(testing / "environment.json", {"sha": SHA2, "digest": functional_digest})
    write_json(
        testing / "test-results.json",
        {
            "sha": SHA2,
            "result": "pass",
            "digest": functional_digest,
            "recorded_at": "2026-10-18T12:00:00Z",
        },
    )


async def _open_compose_from_hub(pilot) -> None:
    await pilot.pause()
    await pilot.click("#hub-btn")
    await pilot.pause()
    pr_list = pilot.app.screen.query_one("#pr-list", ListView)
    pr_list.index = 1
    await pilot.pause()
    track_list = pilot.app.screen.query_one("#track-list", ListView)
    track_list.focus()
    track_list.index = 3
    await pilot.pause()
    children = list(track_list.children)
    if len(children) > 3:
        await pilot.click(children[3])
    await pilot.pause()


def test_compose_preview_lists_repo_pr_sha_and_omitted(tmp_path):
    _seed_compose_ready(tmp_path)
    store = _store(tmp_path)
    projection = project_github_compose(
        store,
        ISSUE,
        "acme",
        "gadgets",
        12,
        SHA2,
        diff_index={("src/Example.cs", 142, "RIGHT")},
    )
    assert "acme/gadgets" in projection.preview_text
    assert "#12" in projection.preview_text
    assert SHA2 in projection.preview_text
    assert "REQUEST_CHANGES" in projection.preview_text
    assert "Please fix the quantity check." in projection.preview_text


def test_headless_compose_preview_button(tmp_path):
    _seed_compose_ready(tmp_path)
    workflow, runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await _open_compose_from_hub(pilot)
            assert isinstance(app.screen, GitHubComposeScreen)
            await pilot.click("#btn-preview")
            await pilot.pause()
            panel = app.screen.query_one("#preview-panel")
            text = str(panel.render())
            assert "acme/gadgets" in text
            assert "REQUEST_CHANGES" in text
            assert runner.calls == []

    asyncio.run(_run())


def _seed_compose_without_manual(tmp_path) -> None:
    _seed_three_pr_session(tmp_path)
    commit = _commit_dir(tmp_path, REF_B, SHA2)
    commit.mkdir(parents=True, exist_ok=True)
    _seed_checks(commit)
    _seed_findings(commit)
    review = commit / "review"
    write_json(
        review / "human-review.json",
        {
            "rejected_review": False,
            "findings": {"F001": {"decision": "accept", "must_fix": True}},
            "added": [],
            "disposition": "COMMENT",
            "event": "COMMENT",
            "summary": "Please fix the quantity check.",
        },
    )
    write_json(review / "diff-lines.json", [["src/Example.cs", 142, "RIGHT"]])
    (commit / "diff.patch").write_text(DIFF, encoding="utf-8")
    testing = commit / "testing"
    testing.mkdir(parents=True, exist_ok=True)
    write_json(
        testing / "test-results.json",
        {"sha": SHA2, "result": "pass", "recorded_at": "2026-10-18T12:00:00Z"},
    )


def test_compose_disables_approve_and_comment_without_manual_review(tmp_path):
    _seed_compose_without_manual(tmp_path)
    workflow, _runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await _open_compose_from_hub(pilot)
            assert isinstance(app.screen, GitHubComposeScreen)
            approve = app.screen.query_one("#btn-outcome-approve", Button)
            comment = app.screen.query_one("#btn-outcome-comment", Button)
            assert approve.disabled is True
            assert comment.disabled is True

    asyncio.run(_run())


def test_hub_next_action_opens_compose(tmp_path):
    _seed_compose_ready(tmp_path)
    workflow, _runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await pilot.click("#hub-btn")
            await pilot.pause()
            assert isinstance(app.screen, ReviewHubScreen)
            pr_list = app.screen.query_one("#pr-list", ListView)
            pr_list.index = 1
            await pilot.pause()
            button = app.screen.query_one("#hub-next-btn", Button)
            assert "Publish" in str(button.label)
            await pilot.click("#hub-next-btn")
            await pilot.pause()
            assert isinstance(app.screen, GitHubComposeScreen)

    asyncio.run(_run())
