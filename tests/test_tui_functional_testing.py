"""P11: headless functional testing screen."""

from __future__ import annotations

import asyncio
from pathlib import Path

from review_ticket.storage import read_json, write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.functional_testing_screen import FunctionalTestingScreen
from textual.widgets import ListView, TextArea
from tests.support import ISSUE, SHA1, make_app
from tests.test_acceptance import _commit, _seed_pr
from tests.test_tui_environment import _seed_manual_complete

PILOT_SIZE = (120, 48)


def _seed_functional_fixture(tmp_path: Path) -> None:
    _seed_pr(tmp_path, SHA1)
    commit = _commit(tmp_path, SHA1)
    _seed_manual_complete(commit)
    testing = commit / "testing"
    testing.mkdir(parents=True, exist_ok=True)
    write_json(
        testing / "environment.json",
        {
            "sha": SHA1,
            "image": "acme/widgets:feature",
            "digest": "sha256:" + "a" * 64,
        },
    )
    (testing / "test-plan.md").write_text("# Plan\n", encoding="utf-8")


async def _open_functional_track(pilot) -> None:
    await pilot.pause()
    await pilot.click("#hub-btn")
    await pilot.pause()
    pr_list = pilot.app.screen.query_one("#pr-list", ListView)
    pr_list.index = 0
    await pilot.pause()
    track_list = pilot.app.screen.query_one("#track-list", ListView)
    track_list.focus()
    track_list.index = 2
    await pilot.pause()
    children = list(track_list.children)
    if len(children) > 2:
        await pilot.click(children[2])
    await pilot.pause()


def test_functional_screen_blocked_disables_request_changes(tmp_path):
    _seed_functional_fixture(tmp_path)
    workflow, runner, _world = make_app(tmp_path)
    from tests.test_status_projection import _store

    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            app.push_screen(
                FunctionalTestingScreen(
                    _store(tmp_path),
                    workflow,
                    issue=ISSUE,
                    ref="acme/widgets#87",
                    owner="acme",
                    repo="widgets",
                    number=87,
                    sha=SHA1,
                    stored_sha=SHA1,
                    stale=False,
                )
            )
            await pilot.pause()
            assert isinstance(app.screen, FunctionalTestingScreen)
            await pilot.click("#btn-result-blocked")
            rc = app.screen.query_one("#btn-disposition-request-changes")
            assert rc.disabled
            assert runner.calls == []

    asyncio.run(_run())


def test_functional_save_pass_comment_writes_json(tmp_path):
    _seed_functional_fixture(tmp_path)
    workflow, runner, _world = make_app(tmp_path)
    from tests.test_status_projection import _store

    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)
    testing = _commit(tmp_path, SHA1) / "testing"

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await _open_functional_track(pilot)
            assert isinstance(app.screen, FunctionalTestingScreen)
            app.screen.query_one("#steps-edit", TextArea).text = "Walk checkout"
            await pilot.click("#btn-result-pass")
            await pilot.click("#btn-disposition-comment")
            await pilot.click("#btn-save")
            await pilot.pause()

    asyncio.run(_run())
    assert runner.calls == []
    stored = read_json(testing / "test-results.json")
    assert stored["result"] == "pass"
    assert stored["disposition"] == "COMMENT"
    assert stored["steps"] == "Walk checkout"
    assert not (_commit(tmp_path, SHA1) / "review" / "publication.json").exists()
