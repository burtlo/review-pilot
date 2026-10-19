"""Unit tests for shared context header and decision panel (P1)."""

from __future__ import annotations

import asyncio

from textual.app import App, ComposeResult

from review_ticket.tui.context_header import ContextHeader, ContextHeaderView, format_context_header
from textual.widgets import Markdown

from review_ticket.tui.decision_panel import (
    DecisionPanel,
    DecisionPanelModel,
    DecisionPanelState,
    PanelEvent,
    PanelRecommendation,
    ReceiptLine,
    format_receipt_markdown,
    transition_panel,
)

_FULL_SHA = "abcdef0123456789abcdef0123456789abcdef01"


def test_format_context_header_includes_full_sha():
    text = format_context_header(
        ContextHeaderView(
            issue_key="DOTNETIOT-99",
            title="Add widgets",
            stage="jira-issue",
            active_pr="354",
            full_sha=_FULL_SHA,
            sha_stale=True,
            recommendation="Reject — missing notes",
        )
    )
    assert "DOTNETIOT-99 — Add widgets" in text
    assert _FULL_SHA in text
    assert "SHA stale" in text
    assert "PR 354" in text
    assert "Reject — missing notes" in text


def test_reject_path_state_machine_through_receipt():
    model = DecisionPanelModel()
    model = transition_panel(model, PanelEvent.CHOOSE_REJECT, draft="draft body")
    assert model.state == DecisionPanelState.EDITING
    model = transition_panel(model, PanelEvent.SAVE_DRAFT, draft="draft body")
    assert model.state == DecisionPanelState.SAVED
    assert model.saved is True
    model = transition_panel(model, PanelEvent.CONTINUE_AFTER_SAVE)
    assert model.state == DecisionPanelState.COMMENT_CONFIRM
    model = transition_panel(model, PanelEvent.COMMENT_NO)
    assert model.comment_outcome == "declined"
    assert model.state == DecisionPanelState.TRANSITION_CONFIRM
    model = transition_panel(model, PanelEvent.TRANSITION_YES)
    assert model.state == DecisionPanelState.RECEIPT
    kinds = {line.kind for line in model.receipt_lines()}
    assert kinds == {"saved", "declined", "moved"}


def test_comment_failure_stays_on_confirm_and_keeps_draft():
    model = DecisionPanelModel(
        state=DecisionPanelState.COMMENT_CONFIRM,
        draft_text="keep me",
        saved=True,
        comment_preview="preview",
    )
    model = transition_panel(
        replace_failure(model, "network"),
        PanelEvent.COMMENT_FAILED,
    )
    assert model.state == DecisionPanelState.COMMENT_CONFIRM
    assert model.draft_text == "keep me"
    assert model.comment_outcome == "failed"


def test_receipt_lines_include_failed_comment_with_detail():
    model = DecisionPanelModel(
        saved=True,
        draft_text="my draft",
        comment_outcome="failed",
        failure_detail="timeout",
    )
    lines = model.receipt_lines()
    failed = next(line for line in lines if line.kind == "failed")
    assert failed.detail == "timeout"
    assert model.draft_text == "my draft"


def test_format_receipt_markdown_shows_failed_row():
    lines = (
        ReceiptLine("Draft saved", "saved"),
        ReceiptLine("Comment posted", "failed", "network error"),
    )
    md = format_receipt_markdown(lines)
    assert "Comment posted: FAILED" in md
    assert "network error" in md


def test_show_receipt_after_comment_failure_preserves_draft():
    model = DecisionPanelModel(
        state=DecisionPanelState.COMMENT_CONFIRM,
        draft_text="keep me",
        saved=True,
        comment_preview="preview",
    )
    model = transition_panel(replace_failure(model, "network"), PanelEvent.COMMENT_FAILED)
    model = transition_panel(model, PanelEvent.SHOW_RECEIPT)
    assert model.state == DecisionPanelState.RECEIPT
    assert model.draft_text == "keep me"
    kinds = {line.kind for line in model.receipt_lines()}
    assert kinds == {"saved", "failed"}


def test_show_receipt_after_transition_failure_preserves_draft():
    model = DecisionPanelModel(
        state=DecisionPanelState.TRANSITION_CONFIRM,
        draft_text="keep me",
        saved=True,
        comment_outcome="posted",
        transition_preview="→ In Progress",
    )
    model = transition_panel(replace_failure(model, "forbidden"), PanelEvent.TRANSITION_FAILED)
    model = transition_panel(model, PanelEvent.SHOW_RECEIPT)
    assert model.state == DecisionPanelState.RECEIPT
    assert model.draft_text == "keep me"
    kinds = {line.kind for line in model.receipt_lines()}
    assert kinds == {"saved", "posted", "failed"}


def replace_failure(model: DecisionPanelModel, detail: str) -> DecisionPanelModel:
    from dataclasses import replace

    return replace(model, failure_detail=detail)


class _PanelHarness(App):
    def compose(self) -> ComposeResult:
        yield ContextHeader(
            ContextHeaderView(
                issue_key="DOTNETIOT-1",
                title="Harness",
                stage="status",
            ),
            id="header",
        )
        yield DecisionPanel(id="panel")


def test_decision_panel_mounts_single_visible_dock():
    async def _run() -> None:
        app = _PanelHarness()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            panel = app.query_one("#panel", DecisionPanel)
            assert panel.model.state == DecisionPanelState.DECISION
            assert app.query_one("#decision-row").display is True
            assert app.query_one("#editing-group").display is False
            assert app.query_one("#receipt-group").display is False

    asyncio.run(_run())


def test_recommendation_changes_emphasis_not_button_order():
    async def _run() -> None:
        app = _PanelHarness()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            panel = app.query_one("#panel", DecisionPanel)
            approve = app.query_one("#approve-btn")
            reject = app.query_one("#reject-btn")
            assert approve.region.x < reject.region.x
            approve_row = approve.region.x
            reject_row = reject.region.x

            panel.set_recommendation(PanelRecommendation.REJECT)
            await pilot.pause()
            assert approve.region.x == approve_row
            assert reject.region.x == reject_row
            assert str(reject.variant) == "error"
            assert str(approve.variant) == "default"

            panel.set_recommendation(PanelRecommendation.APPROVE)
            await pilot.pause()
            assert approve.region.x == approve_row
            assert reject.region.x == reject_row
            assert str(approve.variant) == "success"
            assert str(reject.variant) == "default"

    asyncio.run(_run())


def test_panel_swaps_dock_on_reject_save_continue():
    async def _run() -> None:
        app = _PanelHarness()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            panel = app.query_one("#panel", DecisionPanel)
            panel.begin_reject_edit("generated draft")
            await pilot.pause()
            assert panel.model.state == DecisionPanelState.EDITING
            assert app.query_one("#decision-row").display is False

            await pilot.click("#save-btn")
            await pilot.pause()
            assert panel.model.state == DecisionPanelState.SAVED
            assert app.query_one("#saved-group").display is True

            await pilot.click("#continue-btn")
            await pilot.pause()
            assert panel.model.state == DecisionPanelState.COMMENT_CONFIRM
            assert app.query_one("#comment-group").display is True

    asyncio.run(_run())


def test_receipt_md_shows_failed_row_and_keeps_draft_headless():
    async def _run() -> None:
        app = _PanelHarness()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            panel = app.query_one("#panel", DecisionPanel)
            panel.begin_reject_edit("generated draft")
            await pilot.pause()
            await pilot.click("#save-btn")
            await pilot.pause()
            await pilot.click("#continue-btn")
            await pilot.pause()
            panel.record_comment_failure("Jira unavailable")
            await pilot.pause()
            assert panel.model.draft_text == "generated draft"
            panel.show_receipt()
            await pilot.pause()
            assert panel.model.state == DecisionPanelState.RECEIPT
            assert app.query_one("#receipt-group").display is True
            receipt_md = app.query_one("#receipt-md", Markdown).source
            assert "FAILED" in receipt_md
            assert "Jira unavailable" in receipt_md
            assert panel.model.draft_text == "generated draft"

    asyncio.run(_run())


def test_equal_width_decision_buttons():
    async def _run() -> None:
        app = _PanelHarness()
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            approve = app.query_one("#approve-btn")
            reject = app.query_one("#reject-btn")
            assert approve.region.width == reject.region.width

    asyncio.run(_run())
