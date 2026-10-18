"""Reusable binary decision panel with Jira authorization states (spec §4)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Literal

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalGroup
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Markdown, Static, TextArea

ReceiptKind = Literal["saved", "posted", "moved", "failed", "declined"]


class DecisionPanelState(str, Enum):
    DECISION = "decision"
    EDITING = "editing"
    SAVED = "saved"
    COMMENT_CONFIRM = "comment_confirm"
    TRANSITION_CONFIRM = "transition_confirm"
    RECEIPT = "receipt"


class PanelRecommendation(str, Enum):
    """Which Approve/Reject button receives visual emphasis (order never changes)."""

    APPROVE = "approve"
    REJECT = "reject"
    NEUTRAL = "neutral"


class PanelEvent(str, Enum):
    CHOOSE_APPROVE = "choose_approve"
    CHOOSE_REJECT = "choose_reject"
    SAVE_DRAFT = "save_draft"
    CONTINUE_AFTER_SAVE = "continue_after_save"
    EDIT_AGAIN = "edit_again"
    COMMENT_YES = "comment_yes"
    COMMENT_NO = "comment_no"
    COMMENT_FAILED = "comment_failed"
    TRANSITION_YES = "transition_yes"
    TRANSITION_NO = "transition_no"
    TRANSITION_FAILED = "transition_failed"
    SHOW_RECEIPT = "show_receipt"


@dataclass(frozen=True, slots=True)
class ReceiptLine:
    label: str
    kind: ReceiptKind
    detail: str = ""


@dataclass(slots=True)
class DecisionPanelModel:
    """Pure state for the panel; screens drive external I/O from messages."""

    state: DecisionPanelState = DecisionPanelState.DECISION
    recommendation: PanelRecommendation = PanelRecommendation.NEUTRAL
    draft_text: str = ""
    saved: bool = False
    comment_preview: str = ""
    transition_preview: str = ""
    comment_outcome: ReceiptKind | None = None
    transition_outcome: ReceiptKind | None = None
    failure_detail: str = ""
    current_status: str = ""

    def receipt_lines(self) -> tuple[ReceiptLine, ...]:
        lines: list[ReceiptLine] = []
        if self.saved:
            lines.append(ReceiptLine("Draft saved", "saved"))
        if self.comment_outcome is not None:
            label = {
                "posted": "Comment posted",
                "declined": "Comment",
                "failed": "Comment posted",
            }[self.comment_outcome]
            lines.append(
                ReceiptLine(
                    label,
                    self.comment_outcome,
                    self.failure_detail if self.comment_outcome == "failed" else "",
                )
            )
        if self.transition_outcome is not None:
            label = {
                "moved": "Status moved",
                "declined": "Status move",
                "failed": "Status moved",
            }[self.transition_outcome]
            lines.append(
                ReceiptLine(
                    label,
                    self.transition_outcome,
                    self.failure_detail if self.transition_outcome == "failed" else "",
                )
            )
        if self.current_status:
            lines.append(ReceiptLine("Current status", "saved", self.current_status))
        return tuple(lines)


def transition_panel(model: DecisionPanelModel, event: PanelEvent, *, draft: str = "") -> DecisionPanelModel:
    """Advance the panel state machine without performing Jira/GitHub calls."""

    state = model.state
    if event == PanelEvent.CHOOSE_APPROVE and state == DecisionPanelState.DECISION:
        return model
    if event == PanelEvent.CHOOSE_REJECT and state == DecisionPanelState.DECISION:
        return replace(model, state=DecisionPanelState.EDITING, draft_text=draft)
    if event == PanelEvent.SAVE_DRAFT and state == DecisionPanelState.EDITING:
        body = draft if draft else model.draft_text
        return replace(
            model,
            state=DecisionPanelState.SAVED,
            draft_text=body,
            saved=True,
            failure_detail="",
        )
    if event == PanelEvent.EDIT_AGAIN and state == DecisionPanelState.SAVED:
        return replace(model, state=DecisionPanelState.EDITING, failure_detail="")
    if event == PanelEvent.CONTINUE_AFTER_SAVE and state == DecisionPanelState.SAVED:
        preview = model.comment_preview or model.draft_text
        return replace(
            model,
            state=DecisionPanelState.COMMENT_CONFIRM,
            comment_preview=preview,
            failure_detail="",
        )
    if event == PanelEvent.COMMENT_YES and state == DecisionPanelState.COMMENT_CONFIRM:
        return replace(
            model,
            state=DecisionPanelState.TRANSITION_CONFIRM,
            comment_outcome="posted",
            failure_detail="",
        )
    if event == PanelEvent.COMMENT_NO and state == DecisionPanelState.COMMENT_CONFIRM:
        return replace(
            model,
            state=DecisionPanelState.TRANSITION_CONFIRM,
            comment_outcome="declined",
            failure_detail="",
        )
    if event == PanelEvent.COMMENT_FAILED and state == DecisionPanelState.COMMENT_CONFIRM:
        return replace(
            model,
            state=DecisionPanelState.COMMENT_CONFIRM,
            comment_outcome="failed",
        )
    if event == PanelEvent.TRANSITION_YES and state == DecisionPanelState.TRANSITION_CONFIRM:
        return replace(
            model,
            state=DecisionPanelState.RECEIPT,
            transition_outcome="moved",
            failure_detail="",
        )
    if event == PanelEvent.TRANSITION_NO and state == DecisionPanelState.TRANSITION_CONFIRM:
        return replace(
            model,
            state=DecisionPanelState.RECEIPT,
            transition_outcome="declined",
            failure_detail="",
        )
    if event == PanelEvent.TRANSITION_FAILED and state == DecisionPanelState.TRANSITION_CONFIRM:
        return replace(
            model,
            state=DecisionPanelState.TRANSITION_CONFIRM,
            transition_outcome="failed",
        )
    if event == PanelEvent.SHOW_RECEIPT:
        return replace(model, state=DecisionPanelState.RECEIPT)
    return model


def format_receipt_markdown(lines: tuple[ReceiptLine, ...]) -> str:
    if not lines:
        return "_No operations recorded._"
    rows: list[str] = ["**Receipt**", ""]
    for line in lines:
        status = line.kind.upper()
        if line.kind == "saved" and line.label == "Current status":
            rows.append(f"- {line.label}: {line.detail}")
            continue
        suffix = f" — {line.detail}" if line.detail else ""
        rows.append(f"- {line.label}: {status}{suffix}")
    return "\n".join(rows)


class DecisionPanel(Widget):
    """Single dock that swaps controls per :class:`DecisionPanelState`."""

    DEFAULT_CSS = """
    DecisionPanel {
        width: 1fr;
        height: auto;
        padding: 0 1 1 1;
        background: $background;
        border-top: tall $primary-darken-2;
    }
    DecisionPanel VerticalGroup {
        width: 1fr;
        height: auto;
    }
    DecisionPanel HorizontalGroup {
        width: 1fr;
        height: auto;
    }
    DecisionPanel #decision-row > Button {
        width: 1fr;
    }
    DecisionPanel #yes-no-row > Button,
    DecisionPanel #transition-yes-no-row > Button {
        width: 1fr;
    }
    DecisionPanel #return-draft {
        height: auto;
        min-height: 6;
        max-height: 12;
    }
    DecisionPanel .panel-muted {
        color: $text-muted;
    }
    """

    class Approved(Message):
        """Reviewer chose Approve in the decision state."""

    class RejectChosen(Message):
        """Reviewer chose Reject; panel is entering edit mode."""

    class DraftSaved(Message):
        def __init__(self, body: str) -> None:
            super().__init__()
            self.body = body

    class CommentAuthorized(Message):
        def __init__(self, *, post: bool) -> None:
            super().__init__()
            self.post = post

    class TransitionAuthorized(Message):
        def __init__(self, *, move: bool) -> None:
            super().__init__()
            self.move = move

    def __init__(
        self,
        *,
        model: DecisionPanelModel | None = None,
        approve_label: str = "Approve",
        reject_label: str = "Reject",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._model = model or DecisionPanelModel()
        self._approve_label = approve_label
        self._reject_label = reject_label

    @property
    def model(self) -> DecisionPanelModel:
        return self._model

    def set_recommendation(self, recommendation: PanelRecommendation) -> None:
        self._model = replace(self._model, recommendation=recommendation)
        self._sync_decision_emphasis()

    def set_comment_preview(self, text: str) -> None:
        self._model = replace(self._model, comment_preview=text)

    def set_transition_preview(self, text: str) -> None:
        self._model = replace(self._model, transition_preview=text)

    def set_current_status(self, status: str) -> None:
        self._model = replace(self._model, current_status=status)

    def set_decision_enabled(self, enabled: bool) -> None:
        approve = self.query_one("#approve-btn", Button)
        reject = self.query_one("#reject-btn", Button)
        approve.disabled = not enabled
        reject.disabled = not enabled

    def set_approve_enabled(self, enabled: bool) -> None:
        self.query_one("#approve-btn", Button).disabled = not enabled

    def restore_model(self, model: DecisionPanelModel) -> None:
        self._model = model
        self._apply_model()

    def begin_reject_edit(self, prefill: str) -> None:
        self._model = transition_panel(self._model, PanelEvent.CHOOSE_REJECT, draft=prefill)
        self._apply_model()
        self.query_one("#return-draft", TextArea).focus()

    def record_comment_failure(self, detail: str) -> None:
        if self._model.state == DecisionPanelState.TRANSITION_CONFIRM:
            self._model = replace(
                self._model,
                state=DecisionPanelState.COMMENT_CONFIRM,
                comment_outcome="failed",
                failure_detail=detail,
            )
        else:
            self._model = transition_panel(
                replace(self._model, failure_detail=detail),
                PanelEvent.COMMENT_FAILED,
            )
        self._apply_model()

    def record_transition_failure(self, detail: str) -> None:
        self._model = transition_panel(
            replace(self._model, failure_detail=detail),
            PanelEvent.TRANSITION_FAILED,
        )
        preview = f"{self._model.transition_preview}\n\n**Failed:** {detail}"
        self.query_one("#transition-preview-md", Markdown).update(preview)
        self._apply_model()

    def show_receipt(self) -> None:
        """Move to the receipt dock; failed rows and draft_text are preserved."""
        self._model = transition_panel(self._model, PanelEvent.SHOW_RECEIPT)
        self._apply_model()

    def compose(self) -> ComposeResult:
        with VerticalGroup(id="panel-root"):
            with HorizontalGroup(id="decision-row"):
                yield Button(self._approve_label, id="approve-btn", variant="success")
                yield Button(self._reject_label, id="reject-btn", variant="error")
            with VerticalGroup(id="editing-group"):
                yield TextArea("", id="return-draft")
                with HorizontalGroup(id="editing-actions"):
                    yield Button("Save", id="save-btn", variant="primary")
            with VerticalGroup(id="saved-group"):
                yield Static("Locally saved feedback:", classes="panel-muted")
                yield Markdown("", id="saved-preview-md")
                yield Button("Continue", id="continue-btn", variant="primary")
                yield Button("Edit again", id="edit-again-btn")
            with VerticalGroup(id="comment-group"):
                yield Markdown("", id="comment-preview-md")
                with HorizontalGroup(id="yes-no-row"):
                    yield Button("Yes", id="comment-yes-btn", variant="success")
                    yield Button("No", id="comment-no-btn")
            with VerticalGroup(id="transition-group"):
                yield Markdown("", id="transition-preview-md")
                with HorizontalGroup(id="transition-yes-no-row"):
                    yield Button("Yes", id="transition-yes-btn", variant="success")
                    yield Button("No", id="transition-no-btn")
            with VerticalGroup(id="receipt-group"):
                yield Markdown("", id="receipt-md")

    def on_mount(self) -> None:
        self._apply_model()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "approve-btn":
            self.post_message(self.Approved())
            return
        if button_id == "reject-btn":
            self.post_message(self.RejectChosen())
            return
        if button_id == "save-btn":
            body = self.query_one("#return-draft", TextArea).text
            self._model = transition_panel(self._model, PanelEvent.SAVE_DRAFT, draft=body)
            self._apply_model()
            self.post_message(self.DraftSaved(body))
            return
        if button_id == "continue-btn":
            self._model = transition_panel(self._model, PanelEvent.CONTINUE_AFTER_SAVE)
            self._apply_model()
            return
        if button_id == "edit-again-btn":
            self._model = transition_panel(self._model, PanelEvent.EDIT_AGAIN)
            self._apply_model()
            return
        if button_id == "comment-yes-btn":
            self._model = transition_panel(self._model, PanelEvent.COMMENT_YES)
            self._apply_model()
            self.post_message(self.CommentAuthorized(post=True))
            return
        if button_id == "comment-no-btn":
            self._model = transition_panel(self._model, PanelEvent.COMMENT_NO)
            self._apply_model()
            self.post_message(self.CommentAuthorized(post=False))
            return
        if button_id == "transition-yes-btn":
            self._model = transition_panel(self._model, PanelEvent.TRANSITION_YES)
            self._apply_model()
            self.post_message(self.TransitionAuthorized(move=True))
            return
        if button_id == "transition-no-btn":
            self._model = transition_panel(self._model, PanelEvent.TRANSITION_NO)
            self._apply_model()
            self.post_message(self.TransitionAuthorized(move=False))
            return

    def _apply_model(self) -> None:
        state = self._model.state
        groups = {
            "decision-row": DecisionPanelState.DECISION,
            "editing-group": DecisionPanelState.EDITING,
            "saved-group": DecisionPanelState.SAVED,
            "comment-group": DecisionPanelState.COMMENT_CONFIRM,
            "transition-group": DecisionPanelState.TRANSITION_CONFIRM,
            "receipt-group": DecisionPanelState.RECEIPT,
        }
        for node_id, node_state in groups.items():
            if node_id == "decision-row":
                self.query_one(f"#{node_id}", HorizontalGroup).display = state == node_state
            else:
                self.query_one(f"#{node_id}", VerticalGroup).display = state == node_state

        if state == DecisionPanelState.EDITING:
            draft = self.query_one("#return-draft", TextArea)
            if draft.text != self._model.draft_text:
                draft.text = self._model.draft_text
        if state == DecisionPanelState.SAVED:
            self.query_one("#saved-preview-md", Markdown).update(self._model.draft_text)
        if state == DecisionPanelState.COMMENT_CONFIRM:
            preview = self._model.comment_preview
            if self._model.comment_outcome == "failed" and self._model.failure_detail:
                preview = f"{preview}\n\n**Failed:** {self._model.failure_detail}"
            self.query_one("#comment-preview-md", Markdown).update(preview)
        if state == DecisionPanelState.TRANSITION_CONFIRM:
            self.query_one("#transition-preview-md", Markdown).update(self._model.transition_preview)
        if state == DecisionPanelState.RECEIPT:
            self.query_one("#receipt-md", Markdown).update(format_receipt_markdown(self._model.receipt_lines()))
        self._sync_decision_emphasis()

    def _sync_decision_emphasis(self) -> None:
        if self._model.state != DecisionPanelState.DECISION:
            return
        approve = self.query_one("#approve-btn", Button)
        reject = self.query_one("#reject-btn", Button)
        rec = self._model.recommendation
        if rec == PanelRecommendation.APPROVE:
            approve.variant = "success"
            reject.variant = "default"
        elif rec == PanelRecommendation.REJECT:
            approve.variant = "default"
            reject.variant = "error"
        else:
            approve.variant = "success"
            reject.variant = "error"
