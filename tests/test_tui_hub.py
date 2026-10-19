"""P5: headless PR review hub."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from review_ticket.storage import read_json, write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.hub_screen import ReviewHubScreen
from textual.widgets import Button, Markdown

from tests.support import ISSUE
from tests.test_status_projection import REF_A, REF_B, _seed_three_pr_session, _store

_RUN_TEST_SIZE = (110, 56)


def _seed_hub_session(tmp_path: Path) -> None:
    _seed_three_pr_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    session = read_json(root / "session.json") or {}
    session["decisions"] = {
        "testing_notes": {"choice": "accept", "at": "2026-10-17T00:00:00Z"},
        "pr_readiness": {"choice": "accept", "at": "2026-10-17T01:00:00Z"},
    }
    write_json(root / "session.json", session)


def test_hub_renders_three_prs_with_three_track_rows_each(tmp_path):
    _seed_hub_session(tmp_path)
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            app.pop_screen()
            app.push_screen(ReviewHubScreen(store, ISSUE))
            await pilot.pause()
            assert isinstance(app.screen, ReviewHubScreen)
            doc = app.screen.query_one("#hub-doc", Markdown).source
            assert REF_A.split("#")[0] in doc
            assert REF_B.split("#")[0] in doc
            assert "Automated review" in doc
            assert "Manual code review" in doc
            assert "Functional testing" in doc
            track_list = app.screen.query_one("#track-list")
            assert len(list(track_list.children)) == 9

    asyncio.run(_run())


def test_local_completion_is_not_labeled_published_on_github_line(tmp_path):
    _seed_hub_session(tmp_path)
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            app.pop_screen()
            app.push_screen(ReviewHubScreen(store, ISSUE))
            await pilot.pause()
            doc = app.screen.query_one("#hub-doc", Markdown).source
            assert "**GitHub review:** COMMENT" in doc
            gadgets_block = doc.split("acme/gadgets#12")[1].split("## ")[0]
            assert "**GitHub review:** Not published" in gadgets_block
            assert "Published on GitHub" not in gadgets_block

    asyncio.run(_run())


def test_hub_request_changes_receipt_keeps_ticket_approve_disabled(tmp_path):
    _seed_hub_session(tmp_path)
    from tests.test_status_projection import ISSUE, _commit_dir

    root = tmp_path / "reviews" / ISSUE
    session = read_json(root / "session.json")
    sha = session["pr_shas"][REF_A]
    write_json(
        _commit_dir(tmp_path, REF_A, sha) / "review" / "publication.json",
        {"status": "success", "event": "REQUEST_CHANGES", "sha": sha},
    )
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            app.pop_screen()
            app.push_screen(ReviewHubScreen(store, ISSUE))
            await pilot.pause()
            approve = app.screen.query_one("#approve-btn", Button)
            assert approve.disabled is True

    asyncio.run(_run())


def test_ticket_dock_enabled_with_approve_disabled_until_ready(tmp_path):
    _seed_hub_session(tmp_path)
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            app.pop_screen()
            app.push_screen(ReviewHubScreen(store, ISSUE))
            await pilot.pause()
            approve = app.screen.query_one("#approve-btn", Button)
            reject = app.screen.query_one("#reject-btn", Button)
            assert approve.display is True
            assert reject.display is True
            assert reject.disabled is False
            assert approve.disabled is True

    asyncio.run(_run())


def test_hub_escape_does_not_write_session(tmp_path):
    _seed_hub_session(tmp_path)
    session_path = tmp_path / "reviews" / ISSUE / "session.json"
    before = session_path.read_bytes()
    mtime_before = session_path.stat().st_mtime
    active_before = json.loads(before.decode())["active_pr"]
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            app.pop_screen()
            app.push_screen(ReviewHubScreen(store, ISSUE))
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(_run())
    after = json.loads(session_path.read_text(encoding="utf-8"))
    assert session_path.read_bytes() == before
    assert session_path.stat().st_mtime == mtime_before
    assert after["active_pr"] == active_before


def test_status_hotkey_opens_hub_when_readiness_accepted(tmp_path):
    _seed_hub_session(tmp_path)
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            await pilot.press("h")
            await pilot.pause()
            assert isinstance(app.screen, ReviewHubScreen)

    asyncio.run(_run())
