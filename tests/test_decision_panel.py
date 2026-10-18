"""State machine and headless mount tests for the shared decision panel."""

from __future__ import annotations

import asyncio

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button, Static, TextArea

import review_ticket.workflow as workflow
from review_ticket.tui.shared_chrome import (
    POST_QUESTION,
    ApproveRequested,
    CommentAuthorized,
    CommentDeclined,
    ContextHeader,
    DecisionPanel,
    DecisionPanelError,
    DecisionPanelState,
    DraftSaved,
    Emphasis,
    OperationOutcome,
    PanelDismissed,
    PanelPhase,
    ReviewContext,
    TransitionAuthorized,
    TransitionDeclined,
    format_receipt,
    receipt_rows,
    render_context,
    transition_question,
)
from review_ticket.util import short_sha

_SHA = "6bbbf1214e22f6c5bb9e4ae2db75719cd1094fec"
_HEAD = "abcdef1234567890abcdef1234567890abcdef12"
_PHASE_IDS = (
    "phase-decision",
    "phase-editing",
    "phase-saved",
    "phase-post",
    "phase-transition",
    "phase-receipt",
)


def _saved(text: str = "draft") -> DecisionPanelState:
    state = DecisionPanelState(issue_key="DOTNETIOT-2550", default_prefill="generated")
    state.choose_reject()
    state.edit_draft(text)
    state.save()
    return state


def _shown_phases(panel: DecisionPanel) -> list[str]:
    return [phase_id for phase_id in _PHASE_IDS if panel.query_one(f"#{phase_id}").display]


def _plain(widget: Static) -> str:
    content = widget.content
    return content if isinstance(content, str) else str(content)


def _watch_external(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def _fail(name: str):
        def inner(*_args, **_kwargs):
            calls.append(name)
            raise AssertionError(name)

        return inner

    monkeypatch.setattr(workflow, "jira_comment", _fail("jira_comment"))
    monkeypatch.setattr(workflow, "jira_transition", _fail("jira_transition"))
    monkeypatch.setattr(workflow, "publish_review", _fail("publish_review"))
    return calls


def test_emphasis_does_not_change_button_order_or_phase():
    state = DecisionPanelState()
    assert state.decision_buttons() == ("approve", "reject")
    assert state.phase == PanelPhase.DECISION
    for emphasis in (Emphasis.REJECT, Emphasis.APPROVE, Emphasis.NONE):
        state.set_emphasis(emphasis)
        assert state.decision_buttons() == ("approve", "reject")
        assert state.phase == PanelPhase.DECISION
        assert state.saved_draft is None


def test_save_is_local_and_refuses_to_run_before_reject():
    state = DecisionPanelState(default_prefill="generated")
    with pytest.raises(DecisionPanelError):
        state.save()
    state.choose_approve()
    assert state.decision == "approve"
    assert state.phase == PanelPhase.DECISION
    assert state.comment == OperationOutcome.NOT_ATTEMPTED
    state.choose_reject()
    state.edit_draft("Please add steps.\n")
    state.save()
    assert state.phase == PanelPhase.SAVED
    assert state.saved_draft == "Please add steps.\n"
    assert state.comment_authorized is None
    assert state.transition_authorized is None


def test_edit_again_keeps_the_previous_save_until_the_next_save():
    state = _saved("saved body")
    state.edit_again()
    assert state.phase == PanelPhase.EDITING
    assert state.draft == "saved body"
    assert state.saved_draft == "saved body"
    state.edit_draft("changed")
    assert state.saved_draft == "saved body"
    state.save()
    assert state.saved_draft == "changed"


def test_comment_no_does_not_authorize_or_skip_the_transition():
    state = _saved("body")
    state.show_post_confirmation()
    state.answer_comment(False)
    assert state.comment == OperationOutcome.DECLINED
    assert state.comment_authorized is False
    assert state.transition_authorized is None
    assert state.transition == OperationOutcome.NOT_ATTEMPTED
    assert state.phase == PanelPhase.TRANSITION_CONFIRM
    assert state.saved_draft == "body"


def test_yes_and_no_are_independent():
    declined_comment = _saved("body")
    declined_comment.show_post_confirmation()
    declined_comment.answer_comment(False)
    declined_comment.answer_transition(True)
    assert declined_comment.comment == OperationOutcome.DECLINED
    assert declined_comment.transition_authorized is True
    assert declined_comment.transition == OperationOutcome.NOT_ATTEMPTED
    declined_comment.record_transition_success()
    assert dict(receipt_rows(declined_comment)) == {
        "Draft saved": "YES",
        "Comment posted": "DECLINED",
        "Status moved": "YES",
        "Current status": "In Progress",
    }

    declined_move = _saved("body")
    declined_move.show_post_confirmation()
    declined_move.answer_comment(True)
    assert declined_move.phase == PanelPhase.POST_CONFIRM
    assert declined_move.transition_authorized is None
    declined_move.record_comment_success()
    declined_move.answer_transition(False)
    assert declined_move.comment == OperationOutcome.POSTED
    assert declined_move.transition == OperationOutcome.DECLINED
    assert declined_move.saved_draft == "body"
    assert dict(receipt_rows(declined_move))["Comment posted"] == "YES"
    assert dict(receipt_rows(declined_move))["Status moved"] == "DECLINED"


def test_receipt_lists_saved_posted_moved_and_status():
    state = _saved("hello")
    state.show_post_confirmation()
    state.answer_comment(True)
    state.record_comment_success()
    state.answer_transition(True)
    state.record_transition_success()
    assert dict(receipt_rows(state)) == {
        "Draft saved": "YES",
        "Comment posted": "YES",
        "Status moved": "YES",
        "Current status": "In Progress",
    }
    text = format_receipt(state)
    assert text.startswith("Jira feedback")
    assert "Draft saved" in text
    assert "Comment posted" in text
    assert "Status moved" in text
    assert "Current status" in text
    assert transition_question("In Progress") == "Move this ticket to In Progress?"


def test_failed_comment_receipt_keeps_the_draft_and_can_retry():
    state = _saved("keep me")
    state.show_post_confirmation()
    state.answer_comment(True)
    state.record_comment_failure("acli unavailable")
    assert state.phase == PanelPhase.RECEIPT
    assert state.saved_draft == "keep me"
    assert state.draft == "keep me"
    assert state.can_retry is True
    rows = dict(receipt_rows(state))
    assert rows["Draft saved"] == "YES"
    assert rows["Comment posted"] == "FAILED"
    assert rows["Status moved"] == "not attempted"
    assert "acli unavailable" in format_receipt(state)
    state.retry()
    assert state.phase == PanelPhase.POST_CONFIRM
    assert state.saved_draft == "keep me"
    assert state.comment == OperationOutcome.NOT_ATTEMPTED
    assert state.comment_authorized is None


def test_failed_transition_retries_without_clearing_the_posted_comment():
    state = _saved("keep me")
    state.current_status = "Peer Review"
    state.show_post_confirmation()
    state.answer_comment(True)
    state.record_comment_success()
    state.answer_transition(True)
    state.record_transition_failure("transition failed")
    assert state.saved_draft == "keep me"
    rows = dict(receipt_rows(state))
    assert rows["Comment posted"] == "YES"
    assert rows["Status moved"] == "FAILED"
    assert rows["Current status"] == "Peer Review"
    state.retry()
    assert state.phase == PanelPhase.TRANSITION_CONFIRM
    assert state.comment == OperationOutcome.POSTED
    assert state.saved_draft == "keep me"


def test_historical_sha_is_not_labeled_current():
    text = render_context(
        ReviewContext(
            issue_key="DOTNETIOT-2550",
            title="Fix timezone",
            stage="Code review",
            outcome="REVIEW_DECISION",
            pr_number=144,
            sha=_SHA,
            head_sha=_HEAD,
            historical=True,
            recommendation="Reject",
        )
    )
    assert text.issue == "DOTNETIOT-2550  Fix timezone"
    assert text.stage == "Stage: Code review   Outcome: REVIEW_DECISION"
    assert "PR #144" in text.pr
    assert short_sha(_SHA) in text.pr
    assert _SHA not in text.pr
    assert "HISTORICAL" in text.freshness
    assert "not current HEAD" in text.freshness
    assert short_sha(_HEAD) in text.freshness
    assert not text.freshness.startswith("current")
    assert text.full_sha == f"Reviewed SHA {_SHA}\nCurrent HEAD {_HEAD}"
    assert text.recommendation == "Recommendation: Reject"
    assert text.not_current is True


def test_current_sha_shows_short_form_and_full_sha():
    text = render_context(
        ReviewContext(
            issue_key="DOTNETIOT-2550",
            title="Fix timezone",
            stage="PR readiness",
            pr_number=144,
            sha=_SHA,
            head_sha=_SHA,
            recommendation="Approve",
        )
    )
    assert text.freshness == "current"
    assert text.full_sha == f"Full SHA {_SHA}"
    assert short_sha(_SHA) in text.pr
    assert _SHA not in text.pr
    assert text.not_current is False


def test_stale_sha_warns_instead_of_saying_current():
    text = render_context(
        ReviewContext(
            issue_key="DOTNETIOT-2550",
            title="Fix timezone",
            stage="PR readiness",
            pr_number=144,
            sha=_SHA,
            stale=True,
        )
    )
    assert text.freshness.startswith("STALE")
    assert "not current HEAD" in text.freshness
    assert text.freshness != "current"
    assert text.full_sha == f"Reviewed SHA {_SHA}"


def test_ticket_context_omits_an_absent_sha():
    text = render_context(
        ReviewContext(
            issue_key="DOTNETIOT-2550",
            title="Fix [timezone]",
            stage="Testing notes",
            outcome="ACTION_REQUIRED",
            recommendation="Reject",
        )
    )
    assert text.pr == ""
    assert text.full_sha == ""
    assert text.freshness == ""
    assert "[timezone]" in text.issue
    assert "Outcome: ACTION_REQUIRED" in text.stage


class _PanelOnlyApp(App[None]):
    """Mounts the decision panel and nothing else."""

    ENABLE_COMMAND_PALETTE = False

    def __init__(self, emphasis: Emphasis = Emphasis.NONE) -> None:
        super().__init__()
        self.emphasis = emphasis
        self.events: list[str] = []

    def compose(self) -> ComposeResult:
        yield DecisionPanel(
            issue_key="DOTNETIOT-2550",
            prefill="Generated draft.\n",
            emphasis=self.emphasis,
            prompt="Are the testing notes adequate?",
        )

    def on_approve_requested(self, _message: ApproveRequested) -> None:
        self.events.append("approve")

    def on_draft_saved(self, message: DraftSaved) -> None:
        self.events.append(f"saved:{message.text}")

    def on_comment_authorized(self, _message: CommentAuthorized) -> None:
        self.events.append("comment-yes")

    def on_comment_declined(self, _message: CommentDeclined) -> None:
        self.events.append("comment-no")

    def on_transition_authorized(self, message: TransitionAuthorized) -> None:
        self.events.append(f"transition-yes:{message.status}")

    def on_transition_declined(self, _message: TransitionDeclined) -> None:
        self.events.append("transition-no")

    def on_panel_dismissed(self, message: PanelDismissed) -> None:
        self.events.append(f"dismiss:{message.saved_draft}")


def test_headless_app_mounts_the_panel_only_and_keeps_button_positions():
    app = _PanelOnlyApp(emphasis=Emphasis.APPROVE)

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert isinstance(pilot.app.screen, type(app.screen))
            assert len(list(app.query(DecisionPanel))) == 1
            assert not list(app.query("TestingNotesScreen"))
            panel = app.query_one(DecisionPanel)
            assert panel.region.bottom == app.screen.size.height
            assert _shown_phases(panel) == ["phase-decision"]
            approve = panel.query_one("#approve-btn", Button)
            reject = panel.query_one("#reject-btn", Button)
            row = [child.id for child in panel.query_one("#decision-row").children]
            assert row == ["approve-btn", "reject-btn"]
            assert approve.region.width == reject.region.width
            assert approve.region.width > 0
            assert approve.region.x < reject.region.x
            origin = (approve.region.x, reject.region.x, approve.region.width, reject.region.width)
            assert approve.variant == "success"
            assert approve.has_class("recommended")
            assert reject.variant == "default"
            assert not reject.has_class("recommended")

            panel.set_emphasis(Emphasis.REJECT)
            await pilot.pause()
            approve = panel.query_one("#approve-btn", Button)
            reject = panel.query_one("#reject-btn", Button)
            assert (approve.region.x, reject.region.x, approve.region.width, reject.region.width) == origin
            assert [child.id for child in panel.query_one("#decision-row").children] == row
            assert reject.variant == "error"
            assert reject.has_class("recommended")
            assert approve.variant == "default"
            assert not approve.has_class("recommended")
            assert _shown_phases(panel) == ["phase-decision"]

            panel.set_emphasis(Emphasis.NONE)
            await pilot.pause()
            approve = panel.query_one("#approve-btn", Button)
            reject = panel.query_one("#reject-btn", Button)
            assert (approve.region.x, reject.region.x, approve.region.width, reject.region.width) == origin
            assert approve.variant == "default"
            assert reject.variant == "default"
            assert not approve.has_class("recommended")
            assert not reject.has_class("recommended")

    asyncio.run(_run())


def test_headless_save_and_independent_yes_no_do_not_call_jira(monkeypatch):
    calls = _watch_external(monkeypatch)
    app = _PanelOnlyApp()

    async def _run() -> None:
        async with app.run_test(size=(80, 36)) as pilot:
            await pilot.pause()
            panel = app.query_one(DecisionPanel)
            await pilot.click("#approve-btn")
            await pilot.pause()
            assert panel.state.decision == "approve"
            assert panel.state.phase == PanelPhase.DECISION
            assert _shown_phases(panel) == ["phase-decision"]
            assert calls == []

            await pilot.click("#reject-btn")
            await pilot.pause()
            assert _shown_phases(panel) == ["phase-editing"]
            assert panel.query_one("#phase-decision").region.height == 0
            editor = panel.query_one("#draft-editor", TextArea)
            assert editor.text == "Generated draft.\n"
            assert panel.region.height > 0
            edited = "Please add [steps].\n"
            editor.text = edited
            await pilot.click("#save-btn")
            await pilot.pause()
            assert panel.state.phase == PanelPhase.SAVED
            assert panel.state.saved_draft == edited
            assert _plain(panel.query_one("#saved-preview", Static)) == edited
            assert "not been posted" in _plain(panel.query_one("#panel-prompt", Static))
            assert _shown_phases(panel) == ["phase-saved"]
            assert calls == []
            assert app.events == ["approve", f"saved:{edited}"]

            await pilot.click("#continue-btn")
            await pilot.pause()
            assert _shown_phases(panel) == ["phase-post"]
            assert _plain(panel.query_one("#post-preview", Static)) == edited
            assert _plain(panel.query_one("#post-question", Static)) == POST_QUESTION
            assert calls == []
            yes = panel.query_one("#comment-yes-btn", Button)
            no = panel.query_one("#comment-no-btn", Button)
            assert yes.region.width == no.region.width
            assert yes.region.x < no.region.x
            labels = {yes.label.plain, no.label.plain}
            assert labels == {"Yes", "No"}

            await pilot.click("#comment-no-btn")
            await pilot.pause()
            assert panel.state.comment == OperationOutcome.DECLINED
            assert panel.state.transition_authorized is None
            assert panel.state.phase == PanelPhase.TRANSITION_CONFIRM
            assert _shown_phases(panel) == ["phase-transition"]
            assert "DOTNETIOT-2550" in _plain(panel.query_one("#transition-preview", Static))
            assert "In Progress" in _plain(panel.query_one("#transition-preview", Static))
            question = _plain(panel.query_one("#transition-question", Static))
            assert question == "Move this ticket to In Progress?"
            assert calls == []
            assert "comment-yes" not in app.events

            await pilot.click("#transition-yes-btn")
            await pilot.pause()
            assert panel.state.comment == OperationOutcome.DECLINED
            assert panel.state.transition_authorized is True
            assert panel.state.transition == OperationOutcome.NOT_ATTEMPTED
            assert panel.state.saved_draft == edited
            assert calls == []
            panel.record_transition_success()
            await pilot.pause()
            assert _shown_phases(panel) == ["phase-receipt"]
            receipt = _plain(panel.query_one("#receipt-body", Static))
            assert "Comment posted" in receipt
            assert "DECLINED" in receipt
            assert "Status moved" in receipt
            assert "YES" in receipt
            assert panel.state.saved_draft == edited
            assert panel.query_one("#draft-editor", TextArea).text == edited
            assert panel.query_one("#retry-btn", Button).display is False

            await pilot.press("escape")
            await pilot.pause()
            assert panel.state.saved_draft == edited
            assert app.events[-1] == f"dismiss:{edited}"
            assert calls == []

    asyncio.run(_run())


def test_headless_failed_receipt_keeps_the_draft(monkeypatch):
    calls = _watch_external(monkeypatch)
    app = _PanelOnlyApp()

    async def _run() -> None:
        async with app.run_test(size=(80, 36)) as pilot:
            await pilot.pause()
            panel = app.query_one(DecisionPanel)
            await pilot.click("#reject-btn")
            await pilot.pause()
            editor = panel.query_one("#draft-editor", TextArea)
            edited = "Keep this draft.\n"
            editor.text = edited
            await pilot.click("#save-btn")
            await pilot.pause()
            await pilot.click("#continue-btn")
            await pilot.pause()
            await pilot.click("#comment-yes-btn")
            await pilot.pause()
            assert panel.state.comment_authorized is True
            assert panel.state.comment == OperationOutcome.NOT_ATTEMPTED
            assert panel.state.phase == PanelPhase.POST_CONFIRM
            assert panel.state.transition_authorized is None
            assert calls == []
            assert "comment-yes" in app.events

            panel.record_comment_failure("acli unavailable")
            await pilot.pause()
            assert _shown_phases(panel) == ["phase-receipt"]
            receipt = _plain(panel.query_one("#receipt-body", Static))
            assert "FAILED" in receipt
            assert "acli unavailable" in receipt
            assert "Draft saved" in receipt
            assert panel.state.saved_draft == edited
            assert panel.query_one("#draft-editor", TextArea).text == edited
            assert panel.query_one("#retry-btn", Button).display is True

            await pilot.click("#retry-btn")
            await pilot.pause()
            assert panel.state.phase == PanelPhase.POST_CONFIRM
            assert _shown_phases(panel) == ["phase-post"]
            assert _plain(panel.query_one("#post-preview", Static)) == edited
            assert panel.state.saved_draft == edited
            assert calls == []

    asyncio.run(_run())


class _HeaderOnlyApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield ContextHeader(
            ReviewContext(
                issue_key="DOTNETIOT-2550",
                title="Fix [timezone] handling",
                stage="Code review",
                outcome="REVIEW_DECISION",
                pr_number=144,
                sha=_SHA,
                head_sha=_HEAD,
                historical=True,
                recommendation="Reject",
            )
        )


def test_headless_context_header_shows_full_sha_and_historical_marker():
    app = _HeaderOnlyApp()

    async def _run() -> None:
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            header = app.query_one(ContextHeader)
            assert header.region.y == 0
            assert header.full_sha == _SHA
            assert "[timezone]" in _plain(header.query_one("#context-issue", Static))
            pr = _plain(header.query_one("#context-pr", Static))
            assert "PR #144" in pr
            assert short_sha(_SHA) in pr
            assert _SHA not in pr
            freshness = _plain(header.query_one("#context-freshness", Static))
            assert "HISTORICAL" in freshness
            assert "not current HEAD" in freshness
            assert not freshness.startswith("current")
            sha_line = _plain(header.query_one("#context-sha", Static))
            assert f"Reviewed SHA {_SHA}" in sha_line
            assert f"Current HEAD {_HEAD}" in sha_line
            assert header.has_class("historical")

    asyncio.run(_run())


class _StackedChromeApp(App[None]):
    ENABLE_COMMAND_PALETTE = False
    CSS = """
    #evidence {
        height: 1fr;
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        yield ContextHeader(
            ReviewContext(
                issue_key="DOTNETIOT-2550",
                title="Fix timezone handling",
                stage="Testing notes",
                recommendation="Reject",
            )
        )
        yield Static("Evidence stays reachable while the dock changes.", id="evidence", markup=False)
        yield DecisionPanel(issue_key="DOTNETIOT-2550", prefill="Need steps.\n", emphasis=Emphasis.REJECT)


def test_header_and_panel_leave_evidence_reachable_while_editing():
    app = _StackedChromeApp()

    async def _run() -> None:
        async with app.run_test(size=(80, 36)) as pilot:
            await pilot.pause()
            header = app.query_one(ContextHeader)
            panel = app.query_one(DecisionPanel)
            evidence = app.query_one("#evidence", Static)
            assert header.region.y == 0
            assert evidence.region.y > header.region.y
            assert panel.region.y > evidence.region.y
            assert evidence.region.height > 0
            before_evidence = evidence.region.height
            before_panel = panel.region.height
            await pilot.click("#reject-btn")
            await pilot.pause()
            assert _shown_phases(panel) == ["phase-editing"]
            assert evidence.display is True
            assert evidence.region.height > 0
            assert evidence.region.height < before_evidence
            assert panel.region.height > before_panel
            assert "Evidence stays reachable" in _plain(evidence)

    asyncio.run(_run())
