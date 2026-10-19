"""P8: headless manual code review screen."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from review_ticket.storage import write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.manual_review_screen import ManualReviewScreen
from tests.support import DIFF, ISSUE, SHA2
from tests.test_status_projection import REF_B, _seed_three_pr_session, _store

PILOT_SIZE = (100, 48)


def _commit_dir(tmp_path: Path, ref: str, sha: str) -> Path:
    owner, rest = ref.split("/", 1)
    repo, number = rest.split("#", 1)
    slug = f"{owner}-{repo}-pr-{number}"
    return tmp_path / "reviews" / ISSUE / "prs" / slug / "commits" / sha


def test_complete_manual_review_writes_manual_json_not_publication(tmp_path):
    _seed_three_pr_session(tmp_path)
    commit = _commit_dir(tmp_path, REF_B, SHA2)
    commit.mkdir(parents=True, exist_ok=True)
    (commit / "diff.patch").write_text(DIFF, encoding="utf-8")
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            app.push_screen(
                ManualReviewScreen(
                    store,
                    ISSUE,
                    None,
                    ref=REF_B,
                    owner="acme",
                    repo="gadgets",
                    number=12,
                    sha=SHA2,
                    stale=False,
                )
            )
            await pilot.pause()
            await pilot.click("#btn-complete")
            await pilot.pause()

    asyncio.run(_run())
    manual_path = commit / "review" / "manual-review.json"
    assert manual_path.exists()
    payload = json.loads(manual_path.read_text(encoding="utf-8"))
    assert payload["completed"] is True
    assert not (commit / "review" / "publication.json").exists()
