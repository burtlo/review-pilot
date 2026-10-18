"""P6: headless PR review screen triage."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from review_ticket.storage import Store, read_json, write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.pr_screen import PrReviewScreen
from review_ticket.tui.status_screen import StatusScreen
from textual.widgets import Button, Markdown, Static, TextArea

PILOT_SIZE = (120, 48)
from tests.support import ISSUE, SHA1, SHA2, make_app
from tests.test_status_projection import REF_A, REF_B, REF_C, _seed_three_pr_session, _store

SHA_OLD = "d" * 40
NARRATIVE_MARKER = "AUTOMATED REVIEW NARRATIVE FOR PILOT"


def _pr_slug(ref: str) -> str:
    owner, rest = ref.split("/", 1)
    repo, number = rest.split("#", 1)
    return f"{owner}-{repo}-pr-{number}"


def _commit_dir(tmp_path: Path, ref: str, sha: str) -> Path:
    return tmp_path / "reviews" / ISSUE / "prs" / _pr_slug(ref) / "commits" / sha


def _seed_rich_findings(commit_dir: Path) -> None:
    review = commit_dir / "review"
    review.mkdir(parents=True, exist_ok=True)
    write_json(
        review / "findings.json",
        {
            "summary": "Please validate quantity.",
            "findings": [
                {
                    "id": "F001",
                    "title": "Missing validation",
                    "must_fix": True,
                    "path": "src/Example.cs",
                    "line": 142,
                    "side": "RIGHT",
                    "explanation": "Original automated explanation.",
                    "suggested_change": "if (qty < 0) throw;",
                }
            ],
        },
    )
    write_json(review / "diff-lines.json", [["src/Example.cs", 142, "RIGHT"]])
    (review / "reviewer-report.md").write_text(f"# Report\n\n{NARRATIVE_MARKER}\n", encoding="utf-8")


def _make_review_app(tmp_path: Path, *, revise: bool = False) -> ReviewTicketApp:
    workflow_app, _, _ = make_app(tmp_path)
    store = _store(tmp_path)
    return ReviewTicketApp(
        store=store,
        issue=ISSUE,
        workflow_app=workflow_app,
        revise=revise,
    )


async def _open_pr_row(pilot, row_index: int) -> None:
    for _ in range(row_index):
        await pilot.press("down")
    await pilot.press("enter")
    await pilot.pause()


def test_open_pr_leaves_active_pr_and_sha_unchanged(tmp_path):
    _seed_three_pr_session(tmp_path)
    session_path = tmp_path / "reviews" / ISSUE / "session.json"
    before = read_json(session_path)
    app = _make_review_app(tmp_path)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await _open_pr_row(pilot, 1)
            await pilot.pause()
            assert isinstance(app.screen, PrReviewScreen)

    asyncio.run(_run())
    after = read_json(session_path)
    assert after["active_pr"] == before["active_pr"]
    assert after["active_sha"] == before["active_sha"]


def test_empty_state_hides_triage_buttons(tmp_path):
    _seed_three_pr_session(tmp_path)
    app = _make_review_app(tmp_path)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await _open_pr_row(pilot, 2)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PrReviewScreen)
            assert screen.query_one("#empty-state", Static).display is True
            assert screen.query_one("#review-body").display is False
            assert screen.query_one("#action-buttons").display is False

    asyncio.run(_run())


def test_stale_banner_lists_stored_sha_and_publish_refusal(tmp_path):
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
    _seed_rich_findings(_commit_dir(tmp_path, REF_A, SHA_OLD))
    app = _make_review_app(tmp_path)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            text = str(app.screen.query_one("#stale-banner", Static).render())
            assert SHA2[:12] in text or "Stored SHA" in text
            assert "not the stored commit" in text
            assert "run-review" in text

    asyncio.run(_run())


def test_detail_pane_shows_narrative_and_explanation(tmp_path):
    _seed_three_pr_session(tmp_path)
    _seed_rich_findings(_commit_dir(tmp_path, REF_B, SHA2))
    app = _make_review_app(tmp_path)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await _open_pr_row(pilot, 1)
            await pilot.pause()
            narrative = app.screen.query_one("#narrative", Markdown).source
            assert NARRATIVE_MARKER in narrative
            explanation = app.screen.query_one("#explanation-edit", TextArea).text
            assert "Original automated explanation." in explanation
            suggested = str(app.screen.query_one("#suggested-change", Static).render())
            assert "if (qty < 0)" in suggested

    asyncio.run(_run())


def test_save_writes_human_review_for_snapshot_sha(tmp_path):
    _seed_three_pr_session(tmp_path)
    _seed_rich_findings(_commit_dir(tmp_path, REF_B, SHA2))
    app = _make_review_app(tmp_path)
    review_dir = _commit_dir(tmp_path, REF_B, SHA2) / "review"

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await _open_pr_row(pilot, 1)
            await pilot.pause()
            await pilot.click("#btn-accept")
            await pilot.pause()
            await pilot.click("#btn-save")
            await pilot.pause()

    asyncio.run(_run())
    stored = json.loads((review_dir / "human-review.json").read_text(encoding="utf-8"))
    assert stored["findings"]["F001"]["decision"] == "accept"


def test_close_does_not_write_human_review(tmp_path):
    _seed_three_pr_session(tmp_path)
    _seed_rich_findings(_commit_dir(tmp_path, REF_B, SHA2))
    app = _make_review_app(tmp_path)
    review_dir = _commit_dir(tmp_path, REF_B, SHA2) / "review"

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await _open_pr_row(pilot, 1)
            await pilot.pause()
            await pilot.click("#btn-accept")
            await pilot.pause()
            await pilot.click("#btn-close")
            await pilot.pause()
            assert isinstance(app.screen, StatusScreen)

    asyncio.run(_run())
    assert not (review_dir / "human-review.json").exists()


def test_second_save_without_revise_is_refused(tmp_path):
    _seed_three_pr_session(tmp_path)
    _seed_rich_findings(_commit_dir(tmp_path, REF_B, SHA2))
    app = _make_review_app(tmp_path)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await _open_pr_row(pilot, 1)
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PrReviewScreen)
            await pilot.click("#btn-accept")
            await pilot.pause()
            screen._save_review()
            await pilot.pause()
            screen._save_review()
            await pilot.pause()
            message = str(screen.query_one("#message", Static).render())
            assert "already recorded" in message

    asyncio.run(_run())


def test_return_to_status_shows_recorded_progress_after_save(tmp_path):
    _seed_three_pr_session(tmp_path)
    _seed_rich_findings(_commit_dir(tmp_path, REF_B, SHA2))
    app = _make_review_app(tmp_path)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await _open_pr_row(pilot, 1)
            await pilot.pause()
            await pilot.click("#btn-accept")
            await pilot.click("#btn-save")
            await pilot.pause()
            await pilot.click("#btn-close")
            await pilot.pause()
            assert isinstance(app.screen, StatusScreen)
            doc = app.screen.query_one("#status-doc", Markdown).source
            assert "Human review recorded" in doc
            assert SHA2[:12] in doc

    asyncio.run(_run())
