"""P5: headless PR review hub."""

from __future__ import annotations

import asyncio
from review_ticket.storage import read_json, write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.hub_screen import ReviewHubScreen, format_hub_document
from review_ticket.tui.shared_chrome import DecisionPanel
from review_ticket.hub_projection import project_review_hub
from textual.widgets import Button, Markdown
from review_ticket.ticket_disposition import evaluate_ticket_disposition
from tests.support import ISSUE, make_app
from tests.support import SHA1, SHA2
from tests.test_status_projection import REF_A, REF_B, _commit_dir, _seed_three_pr_session, _store
from tests.test_ticket_disposition import _seed_ticket_gates

PILOT_SIZE = (120, 48)


def test_hub_renders_three_pr_blocks_from_disk(tmp_path):
    _seed_three_pr_session(tmp_path)
    store = _store(tmp_path)
    projection = project_review_hub(store, ISSUE)
    assert len(projection.pr_blocks) == 3
    doc = format_hub_document(projection)
    assert "acme/widgets" in doc
    assert "acme/gadgets" in doc
    assert "acme/tools" in doc
    assert doc.count("### #") == 3
    assert "Automated review" in doc
    assert "Manual code review" in doc
    assert "Functional testing" in doc

    workflow, _runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=store, issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await pilot.click("#hub-btn")
            await pilot.pause()
            assert isinstance(app.screen, ReviewHubScreen)
            assert _runner.calls == []
            text = app.screen.query_one("#hub-doc", Markdown).source
            assert text.count("### #") == 3
            pr_list = app.screen.query_one("#pr-list")
            assert len(list(pr_list.children)) == 3

    asyncio.run(_run())


def test_local_curation_is_not_labeled_published(tmp_path):
    _seed_three_pr_session(tmp_path)
    store = _store(tmp_path)
    projection = project_review_hub(store, ISSUE)
    block_a = next(b for b in projection.pr_blocks if b.ref == REF_A)
    assert block_a.github_outcome == "Not published"
    doc = format_hub_document(projection)
    assert "GitHub review:** Not published" in doc
    assert "Published (Approve)" not in doc
    assert "Complete locally" in doc


def test_hub_publication_track_labels_differ_by_receipt_event(tmp_path):
    _seed_three_pr_session(tmp_path)
    write_json(
        _commit_dir(tmp_path, REF_A, SHA1) / "review" / "publication.json",
        {
            "status": "success",
            "event": "APPROVE",
            "sha": SHA1,
            "published_at": "2026-10-18T13:00:00Z",
        },
    )
    write_json(
        _commit_dir(tmp_path, REF_B, SHA2) / "review" / "publication.json",
        {
            "status": "success",
            "event": "COMMENT",
            "sha": SHA2,
            "published_at": "2026-10-18T14:00:00Z",
        },
    )
    store = _store(tmp_path)
    projection = project_review_hub(store, ISSUE)
    doc = format_hub_document(projection)
    assert "Published (Approve)" in doc
    assert "Published (Comment)" in doc
    block_a = next(b for b in projection.pr_blocks if b.ref == REF_A)
    block_b = next(b for b in projection.pr_blocks if b.ref == REF_B)
    pub_a = next(t for t in block_a.tracks if t.key == "publication")
    pub_b = next(t for t in block_b.tracks if t.key == "publication")
    assert pub_a.status_label == "Published (Approve)"
    assert pub_b.status_label == "Published (Comment)"


def test_hub_esc_does_not_write_session_active_pr(tmp_path):
    _seed_three_pr_session(tmp_path)
    session_path = tmp_path / "reviews" / ISSUE / "session.json"
    before = read_json(session_path)
    workflow, _runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await pilot.click("#hub-btn")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()

    asyncio.run(_run())
    after = read_json(session_path)
    assert after["active_pr"] == before["active_pr"]
    assert after["active_sha"] == before["active_sha"]


def test_ticket_approve_visible_and_disabled_with_blocker(tmp_path):
    _seed_three_pr_session(tmp_path)
    workflow, _runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await pilot.click("#hub-btn")
            await pilot.pause()
            panel = app.screen.query_one(DecisionPanel)
            approve = panel.query_one("#approve-btn", Button)
            reject = panel.query_one("#reject-btn", Button)
            assert approve.display is False
            assert reject.display is False

    asyncio.run(_run())


def test_ticket_approve_enabled_when_every_pr_ready(tmp_path):
    _seed_ticket_gates(tmp_path)
    assert evaluate_ticket_disposition(_store(tmp_path), ISSUE).approve_enabled
    workflow, _runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await pilot.click("#hub-btn")
            await pilot.pause()
            panel = app.screen.query_one(DecisionPanel)
            approve = panel.query_one("#approve-btn", Button)
            reject = panel.query_one("#reject-btn", Button)
            assert approve.disabled is False
            assert reject.disabled is True

    asyncio.run(_run())


def test_ticket_reject_enabled_for_request_changes_receipt(tmp_path):
    _seed_ticket_gates(tmp_path)
    write_json(
        _commit_dir(tmp_path, REF_B, SHA2) / "review" / "publication.json",
        {
            "status": "success",
            "event": "REQUEST_CHANGES",
            "sha": SHA2,
            "published_at": "2026-10-18T12:00:00Z",
        },
    )
    workflow, _runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await pilot.pause()
            await pilot.click("#hub-btn")
            await pilot.pause()
            panel = app.screen.query_one(DecisionPanel)
            assert panel.query_one("#approve-btn", Button).disabled is True
            assert panel.query_one("#reject-btn", Button).disabled is False
            assert "PR #12" in panel.state.default_prefill or "PR #12" in panel.state.draft

    asyncio.run(_run())
