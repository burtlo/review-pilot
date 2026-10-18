"""P5: headless status screen bound to P4 projection."""

from __future__ import annotations

import asyncio
from pathlib import Path

from review_ticket.storage import Store, write_json
from textual.widgets import Markdown

from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.pr_screen import PrReviewScreen
from review_ticket.tui.status_screen import StatusScreen
from tests.support import ISSUE, SHA1, SHA2
from tests.test_status_projection import REF_A, _seed_three_pr_session, _store

SHA_OLD = "d" * 40


def _pr_slug(ref: str) -> str:
    owner, rest = ref.split("/", 1)
    repo, number = rest.split("#", 1)
    return f"{owner}-{repo}-pr-{number}"


def _commit_dir(tmp_path: Path, ref: str, sha: str) -> Path:
    return tmp_path / "reviews" / ISSUE / "prs" / _pr_slug(ref) / "commits" / sha


def _seed_findings(commit_dir: Path) -> None:
    review = commit_dir / "review"
    review.mkdir(parents=True, exist_ok=True)
    write_json(
        review / "findings.json",
        {
            "summary": "Review",
            "findings": [{"id": "F001", "title": "Issue", "explanation": "x"}],
        },
    )


def test_status_screen_renders_three_pr_fixture(tmp_path):
    _seed_three_pr_session(tmp_path)
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, StatusScreen)
            text = app.screen.query_one("#status-doc", Markdown).source
            assert ISSUE in text
            assert "human-review" in text
            assert "analyzer-findings" in text
            assert "REVIEW_DECISION" in text
            assert f"review-ticket {ISSUE} attach" in text
            assert "acme/widgets#87" in text
            assert "acme/gadgets#12" in text
            assert "acme/tools#3" in text
            assert "build" in text
            assert "Human review recorded" in text
            assert "Undecided" in text
            assert "No snapshot" in text
            pr_list = app.screen.query_one("#pr-list")
            assert len(list(pr_list.children)) == 3

    asyncio.run(_run())


def test_status_quit_does_not_touch_session_json(tmp_path):
    _seed_three_pr_session(tmp_path)
    session_path = tmp_path / "reviews" / ISSUE / "session.json"
    before = session_path.read_bytes()
    mtime_before = session_path.stat().st_mtime
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("q")
            await pilot.pause()

    asyncio.run(_run())
    assert session_path.read_bytes() == before
    assert session_path.stat().st_mtime == mtime_before


def test_pr_row_opens_stub_with_snapshot_sha_not_session_write(tmp_path):
    _seed_three_pr_session(tmp_path)
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, PrReviewScreen)
            assert app.screen.ref == REF_A
            assert app.screen.sha == SHA1
            assert app.screen.stored_sha == SHA1
            assert app.screen.stale is False

    asyncio.run(_run())


def test_pr_row_uses_stale_open_sha_from_projection(tmp_path):
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": REF_A,
            "active_sha": SHA1,
            "active_prs": [REF_A],
            "pr_shas": {REF_A: SHA2},
            "current_step": "human-review",
            "outcome": "READY",
        },
    )
    write_json(root / "prs" / _pr_slug(REF_A) / "pr.json", {"url": "https://github.com/acme/widgets/pull/87"})
    _commit_dir(tmp_path, REF_A, SHA2).mkdir(parents=True, exist_ok=True)
    _seed_findings(_commit_dir(tmp_path, REF_A, SHA_OLD))
    session_path = root / "session.json"
    before = session_path.read_bytes()
    mtime_before = session_path.stat().st_mtime
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, PrReviewScreen)
            assert app.screen.sha == SHA_OLD
            assert app.screen.stored_sha == SHA2
            assert app.screen.stale is True

    asyncio.run(_run())
    assert session_path.read_bytes() == before
    assert session_path.stat().st_mtime == mtime_before
