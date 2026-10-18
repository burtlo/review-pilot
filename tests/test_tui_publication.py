"""P9: publication compose screen."""

from __future__ import annotations

import asyncio
from pathlib import Path

from review_ticket.findings import build_review_payload
from review_ticket.publication_compose import build_compose_preview_markdown, merged_publication_findings, project_publication_compose
from review_ticket.storage import read_json, write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.publication_compose_screen import PublicationComposeScreen
from textual.widgets import Button, Markdown

from tests.support import ISSUE, SHA1
from tests.test_acceptance import _commit, _seed_publishable
from tests.test_status_projection import REF_A, _seed_three_pr_session, _store

_RUN_TEST_SIZE = (110, 56)


def _seed_compose_ready(tmp_path: Path) -> None:
    _seed_publishable(tmp_path, SHA1)
    commit = _commit(tmp_path, SHA1)
    write_json(
        commit / "review" / "manual-review.json",
        {"completed": True, "notes": "Reviewed diff", "findings": [], "disposition": "APPROVE"},
    )
    write_json(
        commit / "testing" / "test-results.json",
        {"sha": SHA1, "result": "pass", "notes": "Cart flow ok"},
    )


def test_compose_preview_payload_matches_publish_review(tmp_path):
    _seed_compose_ready(tmp_path)
    commit = _commit(tmp_path, SHA1)
    write_json(
        commit / "review" / "manual-review.json",
        {
            "completed": True,
            "notes": "Reviewed diff",
            "findings": [
                {
                    "path": "src/Other.cs",
                    "line": 9,
                    "blocking": True,
                    "text": "Manual-only concern on another file.",
                }
            ],
            "disposition": "APPROVE",
        },
    )
    projection = project_publication_compose(
        commit,
        owner="acme",
        repo="widgets",
        number=87,
        ref=REF_A,
        sha=SHA1,
    )
    summary = projection.summary_default
    diff_index = {tuple(item) for item in read_json(commit / "review" / "diff-lines.json")}
    event = "COMMENT"
    payload = build_review_payload(
        sha=SHA1,
        event=event,
        summary=summary,
        findings=merged_publication_findings(commit),
        diff_index=diff_index,
    )
    preview = build_compose_preview_markdown(
        projection,
        summary=summary,
        event=event,
        diff_index=diff_index,
        commit_dir=commit,
    )
    assert payload["event"] == event
    assert "Manual-only concern" in preview
    assert "src/Other.cs" in preview
    assert len(payload.get("comments") or []) + len(
        [line for line in preview.splitlines() if "src/Example.cs" in line]
    ) >= 1


def test_compose_comment_disabled_without_manual_review(tmp_path):
    _seed_three_pr_session(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            app.pop_screen()
            app.push_screen(
                PublicationComposeScreen(
                    store,
                    ISSUE,
                    None,
                    ref=REF_A,
                    owner="acme",
                    repo="widgets",
                    number=87,
                    sha=SHA1,
                )
            )
            await pilot.pause()
            comment = app.screen.query_one("#btn-comment", Button)
            assert comment.disabled is True

    asyncio.run(_run())


def test_compose_preview_and_approve_disabled_without_tests(tmp_path):
    _seed_three_pr_session(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    commit = _commit(tmp_path, SHA1)
    write_json(
        commit / "review" / "manual-review.json",
        {"completed": True, "notes": "ok", "findings": [], "disposition": "APPROVE"},
    )
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            app.pop_screen()
            app.push_screen(
                PublicationComposeScreen(
                    store,
                    ISSUE,
                    None,
                    ref=REF_A,
                    owner="acme",
                    repo="widgets",
                    number=87,
                    sha=SHA1,
                )
            )
            await pilot.pause()
            approve = app.screen.query_one("#btn-approve", Button)
            assert approve.disabled is True
            await pilot.click("#btn-preview")
            await pilot.pause()
            preview = app.screen.query_one("#preview-md", Markdown).source
            assert "GitHub publication" in preview
            assert SHA1[:12] in preview or SHA1 in preview

    asyncio.run(_run())


def test_compose_approve_enabled_with_manual_and_pass(tmp_path):
    _seed_compose_ready(tmp_path)
    store = _store(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE)

    async def _run() -> None:
        async with app.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            app.pop_screen()
            app.push_screen(
                PublicationComposeScreen(
                    store,
                    ISSUE,
                    None,
                    ref=REF_A,
                    owner="acme",
                    repo="widgets",
                    number=87,
                    sha=SHA1,
                )
            )
            await pilot.pause()
            approve = app.screen.query_one("#btn-approve", Button)
            assert approve.disabled is False
            summary = app.screen.query_one("#summary-edit")
            assert "Cart flow ok" in summary.text or "Peer review" in summary.text

    asyncio.run(_run())
