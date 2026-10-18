"""P3: headless PR readiness gate (scenario C)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from review_ticket.storage import write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.readiness_screen import ReadinessScreen
from review_ticket.tui.testing_notes_screen import TestingNotesScreen
from textual.widgets import Button, Markdown

from tests.support import ISSUE, SHA1, SHA2, jira_document, make_app, passing_checks
from tests.test_status_projection import REF_A, REF_B, REF_C, _commit_dir, _pr_slug, _seed_checks, _store

_RUN_TEST_SIZE = (100, 52)
SHA_C = "c" * 40


def _seed_readiness_session(tmp_path: Path, *, waiting: bool = False) -> None:
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": REF_A,
            "active_sha": SHA1,
            "active_prs": [REF_A, REF_B, REF_C],
            "pr_shas": {REF_A: SHA1, REF_B: SHA2, REF_C: SHA_C},
            "current_step": "analyzer-findings",
            "last_completed_step": "github-readiness",
            "outcome": "ACTION_REQUIRED",
            "decisions": {"testing_notes": {"choice": "accept", "at": "2026-10-17T00:00:00Z"}},
        },
    )
    for ref, sha, url in (
        (REF_A, SHA1, "https://github.com/acme/widgets/pull/87"),
        (REF_B, SHA2, "https://github.com/acme/gadgets/pull/12"),
        (REF_C, SHA_C, "https://github.com/acme/tools/pull/3"),
    ):
        write_json(
            root / "prs" / _pr_slug(ref) / "pr.json",
            {"url": url, "number": int(ref.split("#")[-1])},
        )
        commit = _commit_dir(tmp_path, ref, sha)
        commit.mkdir(parents=True, exist_ok=True)
        if waiting and ref == REF_A:
            write_json(
                commit / "github-checks.json",
                {
                    "sha": sha,
                    "required_raw": [{"name": "build"}],
                    "all_raw": [],
                    "checks": [
                        {
                            "name": "build",
                            "required": True,
                            "bucket": "pending",
                            "state": "IN_PROGRESS",
                            "link": "https://example.test/build",
                        }
                    ],
                    "outcome": "WAITING",
                    "summary": "Required checks are still running: build.",
                },
            )
        else:
            _seed_checks(commit)
        write_json(
            commit / "bugbot-findings.json",
            {
                "sha": sha,
                "findings": (
                    [
                        {
                            "source": "bugbot",
                            "id": "bugbot:PRRT_9",
                            "path": "src/Foo.cs",
                            "line": 134,
                            "url": "https://github.com/acme/tools/pull/3#discussion_r9",
                            "body": "Bugbot: potential null reference",
                            "attention": "unaddressed",
                        }
                    ]
                    if ref == REF_C
                    else []
                ),
            },
        )
        write_json(commit / "codeql-findings.json", {"sha": sha, "findings": []})
        (commit / "readiness.md").write_text(f"# Readiness {ref}\n\nChecks ok.\n", encoding="utf-8")
        (commit / "analyzers.md").write_text(f"# Analyzers {ref}\n\nDetail.\n", encoding="utf-8")


def test_readiness_screen_mount_does_not_call_runner(tmp_path):
    _seed_readiness_session(tmp_path)
    app, runner, _world = make_app(tmp_path)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            tui.pop_screen()
            tui.push_screen(ReadinessScreen(app.store, ISSUE, app))
            await pilot.pause()
            assert isinstance(tui.screen, ReadinessScreen)
            assert not [c for c in runner.calls if c]

    asyncio.run(_run())


def test_scenario_c_blocks_approve_and_filters_reject_draft(tmp_path):
    _seed_readiness_session(tmp_path)
    app, _runner, _world = make_app(tmp_path)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            tui.pop_screen()
            tui.push_screen(ReadinessScreen(app.store, ISSUE, app))
            await pilot.pause()
            approve = tui.screen.query_one("#approve-btn", Button)
            assert approve.display is True
            assert approve.disabled is True
            detail = tui.screen.query_one("#detail-md", Markdown).source
            assert "Readiness" in detail
            await pilot.click("#reject-btn")
            await pilot.pause()
            draft = tui.screen.query_one("#return-draft").text
            assert REF_C in draft
            assert REF_A not in draft
            assert REF_B not in draft
            assert "null reference" in draft.lower() or "Bugbot" in draft

    asyncio.run(_run())


def test_waiting_hides_approve_reject_shows_refresh(tmp_path):
    _seed_readiness_session(tmp_path, waiting=True)
    app, _runner, _world = make_app(tmp_path)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            tui.pop_screen()
            tui.push_screen(ReadinessScreen(app.store, ISSUE, app))
            await pilot.pause()
            panel = tui.screen.query_one("#decision-panel")
            assert panel.display is False
            assert tui.screen.query_one("#refresh-row").display is True

    asyncio.run(_run())


def test_accept_testing_notes_opens_readiness_screen(tmp_path):
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "current_step": "jira-issue",
            "outcome": "REVIEW_DECISION",
            "decisions": {},
        },
    )
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document("Ran the cart tests and recorded the result.")
    world.required_checks = passing_checks()
    world.all_checks = passing_checks()
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            assert isinstance(tui.screen, TestingNotesScreen)
            await pilot.click("#approve-btn")
            await pilot.pause()
            assert isinstance(tui.screen, ReadinessScreen)

    asyncio.run(_run())
