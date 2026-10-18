"""P8: headless manual code review screen."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from review_ticket.storage import read_json, write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.manual_review_screen import ManualCodeReviewScreen
from textual.widgets import ListView
from tests.support import DIFF, ISSUE, SHA2, make_app
from tests.test_status_projection import REF_B, _commit_dir, _seed_checks, _seed_findings, _seed_three_pr_session, _store

PILOT_SIZE = (120, 48)


def _pr_slug(ref: str) -> str:
    owner, rest = ref.split("/", 1)
    repo, number = rest.split("#", 1)
    return f"{owner}-{repo}-pr-{number}"


def _seed_automated_complete(commit_dir: Path) -> None:
    commit_dir.mkdir(parents=True, exist_ok=True)
    _seed_findings(commit_dir)
    review = commit_dir / "review"
    write_json(
        review / "human-review.json",
        {
            "rejected_review": False,
            "findings": {"F001": {"decision": "accept", "must_fix": False}},
            "added": [],
            "recorded_at": "2026-10-18T11:00:00Z",
        },
    )
    (commit_dir / "diff.patch").write_text(DIFF, encoding="utf-8")
    write_json(review / "diff-lines.json", [["src/Example.cs", 142, "RIGHT"]])


def _seed_manual_review_fixture(tmp_path: Path) -> None:
    _seed_three_pr_session(tmp_path)
    commit = _commit_dir(tmp_path, REF_B, SHA2)
    commit.mkdir(parents=True, exist_ok=True)
    _seed_checks(commit)
    _seed_automated_complete(commit)


async def _open_manual_track(pilot) -> None:
    await pilot.pause()
    await pilot.click("#hub-btn")
    await pilot.pause()
    pr_list = pilot.app.screen.query_one("#pr-list", ListView)
    pr_list.index = 1
    await pilot.pause()
    track_list = pilot.app.screen.query_one("#track-list", ListView)
    track_list.focus()
    track_list.index = 1
    await pilot.pause()
    children = list(track_list.children)
    if len(children) > 1:
        await pilot.click(children[1])
    await pilot.pause()


def test_manual_review_complete_writes_json_without_publication(tmp_path):
    _seed_manual_review_fixture(tmp_path)
    workflow, runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)
    review_dir = _commit_dir(tmp_path, REF_B, SHA2) / "review"

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await _open_manual_track(pilot)
            assert isinstance(app.screen, ManualCodeReviewScreen)
            await pilot.click("#btn-disposition-approve")
            await pilot.click("#btn-complete")
            await pilot.pause()

    asyncio.run(_run())
    assert runner.calls == []
    manual = read_json(review_dir / "manual-review.json")
    assert manual["completed"] is True
    assert manual["disposition"] == "APPROVE"
    assert manual["sha"] == SHA2
    assert manual.get("recorded_at")
    assert not (review_dir / "publication.json").exists()


def test_request_changes_sets_p9_handoff_flag_only(tmp_path):
    _seed_manual_review_fixture(tmp_path)
    workflow, _runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)
    review_dir = _commit_dir(tmp_path, REF_B, SHA2) / "review"

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await _open_manual_track(pilot)
            await pilot.click("#btn-disposition-request-changes")
            await pilot.click("#btn-confirm-blocker")
            await pilot.click("#btn-complete")
            await pilot.pause()

    asyncio.run(_run())
    manual = json.loads((review_dir / "manual-review.json").read_text(encoding="utf-8"))
    assert manual["disposition"] == "REQUEST_CHANGES"
    assert manual.get("p9_handoff") is True
    assert not (review_dir / "publication.json").exists()


def test_hub_opens_manual_track_screen(tmp_path):
    _seed_manual_review_fixture(tmp_path)
    workflow, _runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await _open_manual_track(pilot)
            assert isinstance(app.screen, ManualCodeReviewScreen)

    asyncio.run(_run())
