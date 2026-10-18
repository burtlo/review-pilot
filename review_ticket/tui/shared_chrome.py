"""Shared context header and decision panel.

Screens bind these widgets later. The panel is a local state machine: saving a
draft and answering No never call Jira or GitHub. Yes posts a message and waits
for the host to report success or failure through ``record_*``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, VerticalGroup
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static, TextArea

from review_ticket.util import short_sha

POST_QUESTION = "Post this comment to Jira?"
DECISION_BUTTONS = ("approve", "reject")

_RECEIPT_VALUE = {
    "not_attempted": "not attempted",
    "declined": "DECLINED",
    "failed": "FAILED",
    "posted": "YES",
    "moved": "YES",
}


class DecisionPanelError(ValueError):
    """The decision panel refused a transition."""


class Emphasis(str, Enum):
    """Which decision button is emphasized. Never a selection."""

    NONE = "none"
    APPROVE = "approve"
    REJECT = "reject"


class PanelPhase(str, Enum):
    DECISION = "decision"
    EDITING = "editing"
    SAVED = "saved"
    POST_CONFIRM = "post_confirm"
    TRANSITION_CONFIRM = "transition_confirm"
    RECEIPT = "receipt"


class OperationOutcome(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    POSTED = "posted"
    MOVED = "moved"
    DECLINED = "declined"
    FAILED = "failed"


class ApproveRequested(Message):
    """Local approve choice. Not a Jira or GitHub write."""

    def __init__(self, issue_key: str) -> None:
        super().__init__()
        self.issue_key = issue_key


class RejectStarted(Message):
    def __init__(self, issue_key: str, draft: str) -> None:
        super().__init__()
        self.issue_key = issue_key
        self.draft = draft


class DraftSaved(Message):
    """Local save finished. The body has not been posted."""

    def __init__(self, issue_key: str, text: str) -> None:
        super().__init__()
        self.issue_key = issue_key
        self.text = text


class CommentAuthorized(Message):
    """Reviewer answered Yes to posting. The panel does not perform the post."""

    def __init__(self, issue_key: str, text: str) -> None:
        super().__init__()
        self.issue_key = issue_key
        self.text = text


class CommentDeclined(Message):
    def __init__(self, issue_key: str, text: str) -> None:
        super().__init__()
        self.issue_key = issue_key
        self.text = text


class TransitionAuthorized(Message):
    """Reviewer answered Yes to the transition. The panel does not move the ticket."""

    def __init__(self, issue_key: str, status: str) -> None:
        super().__init__()
        self.issue_key = issue_key
        self.status = status


class TransitionDeclined(Message):
    def __init__(self, issue_key: str, status: str) -> None:
        super().__init__()
        self.issue_key = issue_key
        self.status = status


class PanelDismissed(Message):
    """Esc / back. A saved draft is left intact."""

    def __init__(self, issue_key: str, saved_draft: str | None) -> None:
        super().__init__()
        self.issue_key = issue_key
        self.saved_draft = saved_draft


def transition_question(status: str) -> str:
    if not status:
        raise DecisionPanelError("target status is required")
    return f"Move this ticket to {status}?"


def transition_preview(issue_key: str, target_status: str) -> str:
    return f"Ticket: {issue_key}\nTarget status: {target_status}"


@dataclass(frozen=True)
class ReviewContext:
    """Identity of the material under review."""

    issue_key: str
    title: str
    stage: str
    outcome: str | None = None
    pr_number: int | None = None
    sha: str = ""
    head_sha: str = ""
    stale: bool = False
    historical: bool = False
    recommendation: str | None = None


@dataclass(frozen=True)
class ContextHeaderText:
    issue: str
    stage: str
    pr: str
    freshness: str
    full_sha: str
    recommendation: str
    not_current: bool
    historical: bool
    stale: bool


def _sha_mismatch(ctx: ReviewContext) -> bool:
    return bool(ctx.sha and ctx.head_sha and ctx.sha != ctx.head_sha)


def render_context(ctx: ReviewContext) -> ContextHeaderText:
    """Compact header lines. The full SHA is never replaced by the short form."""

    mismatch = _sha_mismatch(ctx)
    not_current = bool(ctx.historical or ctx.stale or mismatch)
    title = ctx.title.strip()
    issue = f"{ctx.issue_key}  {title}" if title else ctx.issue_key
    stage = f"Stage: {ctx.stage}"
    if ctx.outcome:
        stage += f"   Outcome: {ctx.outcome}"
    pr_parts: list[str] = []
    if ctx.pr_number is not None:
        pr_parts.append(f"PR #{ctx.pr_number}")
    if ctx.sha:
        pr_parts.append(short_sha(ctx.sha))
    has_identity = bool(ctx.sha) or ctx.pr_number is not None
    if not has_identity and not not_current:
        freshness = ""
    elif not not_current:
        freshness = "current"
    else:
        short = short_sha(ctx.sha) if ctx.sha else ""
        reviewed = f"reviewed {short}" if short else "reviewed SHA"
        head = short_sha(ctx.head_sha) if ctx.head_sha and ctx.head_sha != ctx.sha else ""
        if head:
            relation = f"{reviewed} is not current HEAD {head}"
        else:
            relation = f"{reviewed} is not current HEAD"
        tags: list[str] = []
        if ctx.historical or mismatch:
            tags.append("HISTORICAL")
        if ctx.stale:
            tags.append("STALE")
        if not tags:
            tags.append("STALE")
        freshness = f"{' '.join(tags)} - {relation}"
    sha_lines: list[str] = []
    if ctx.sha:
        label = "Reviewed SHA" if not_current else "Full SHA"
        sha_lines.append(f"{label} {ctx.sha}")
    if ctx.head_sha and (not ctx.sha or ctx.head_sha != ctx.sha):
        sha_lines.append(f"Current HEAD {ctx.head_sha}")
    recommendation = f"Recommendation: {ctx.recommendation}" if ctx.recommendation else ""
    return ContextHeaderText(
        issue=issue,
        stage=stage,
        pr="  ".join(pr_parts),
        freshness=freshness,
        full_sha="\n".join(sha_lines),
        recommendation=recommendation,
        not_current=not_current,
        historical=bool(ctx.historical or mismatch),
        stale=bool(ctx.stale),
    )


class ContextHeader(Widget):
    """Persistent issue, stage, PR, and SHA header. Stacked, not two text columns."""

    DEFAULT_CSS = """
    ContextHeader {
        dock: top;
        layout: vertical;
        height: auto;
        width: 1fr;
        background: $surface;
        color: $text;
        padding: 0 1;
        border-bottom: tall $primary;
    }
    ContextHeader Static {
        width: 1fr;
        height: auto;
        text-wrap: wrap;
    }
    ContextHeader.historical #context-freshness {
        color: $error;
        text-style: bold;
    }
    ContextHeader.stale #context-freshness {
        color: $warning;
        text-style: bold;
    }
    """

    def __init__(
        self,
        context: ReviewContext,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self._review = context

    @property
    def context(self) -> ReviewContext:
        return self._review

    @property
    def full_sha(self) -> str:
        return self._review.sha

    def update_context(self, context: ReviewContext) -> None:
        self._review = context
        if self.is_mounted:
            self._show_lines()

    def on_mount(self) -> None:
        self._show_lines()

    def compose(self) -> ComposeResult:
        yield Static("", id="context-issue", markup=False)
        yield Static("", id="context-stage", markup=False)
        yield Static("", id="context-pr", markup=False)
        yield Static("", id="context-freshness", markup=False)
        yield Static("", id="context-sha", markup=False)
        yield Static("", id="context-recommendation", markup=False)

    def _show_lines(self) -> None:
        text = render_context(self._review)
        self.set_class(text.historical, "historical")
        self.set_class(text.stale, "stale")
        self._set_line("context-issue", text.issue)
        self._set_line("context-stage", text.stage)
        self._set_line("context-pr", text.pr)
        self._set_line("context-freshness", text.freshness)
        self._set_line("context-sha", text.full_sha)
        self._set_line("context-recommendation", text.recommendation)

    def _set_line(self, widget_id: str, text: str) -> None:
        widget = self.query_one(f"#{widget_id}", Static)
        widget.update(text)
        widget.display = bool(text)


@dataclass
class DecisionPanelState:
    """Local decision sequence. Methods mutate this object and do not perform I/O."""

    issue_key: str = ""
    target_status: str = "In Progress"
    current_status: str = ""
    default_prefill: str = ""
    phase: PanelPhase = PanelPhase.DECISION
    emphasis: Emphasis = Emphasis.NONE
    decision: str | None = None
    draft: str = ""
    saved_draft: str | None = None
    comment_authorized: bool | None = None
    transition_authorized: bool | None = None
    comment: OperationOutcome = OperationOutcome.NOT_ATTEMPTED
    transition: OperationOutcome = OperationOutcome.NOT_ATTEMPTED
    comment_error: str = ""
    transition_error: str = ""

    def decision_buttons(self) -> tuple[str, str]:
        """Approve then Reject. Emphasis does not change this order."""

        return DECISION_BUTTONS

    def set_emphasis(self, emphasis: Emphasis) -> None:
        self.emphasis = emphasis

    def choose_approve(self) -> None:
        self._require(PanelPhase.DECISION)
        self.decision = "approve"

    def choose_reject(self) -> None:
        self._require(PanelPhase.DECISION)
        self.decision = "reject"
        self.draft = self.saved_draft if self.saved_draft is not None else self.default_prefill
        self.phase = PanelPhase.EDITING

    def edit_draft(self, text: str) -> None:
        self._require(PanelPhase.EDITING)
        self.draft = text

    def save(self) -> None:
        """Store the draft locally. Does not post to Jira or GitHub."""

        self._require(PanelPhase.EDITING)
        self.saved_draft = self.draft
        self.phase = PanelPhase.SAVED

    def edit_again(self) -> None:
        if self.phase not in (PanelPhase.SAVED, PanelPhase.POST_CONFIRM):
            raise DecisionPanelError(f"phase is {self.phase.value}; expected saved or post_confirm")
        if self.saved_draft is None:
            raise DecisionPanelError("no saved draft")
        if self.phase == PanelPhase.POST_CONFIRM and self.comment_authorized is True:
            raise DecisionPanelError("waiting for the comment result")
        self.draft = self.saved_draft
        if self.comment == OperationOutcome.NOT_ATTEMPTED:
            self.comment_authorized = None
        self.phase = PanelPhase.EDITING

    def show_post_confirmation(self) -> None:
        self._require(PanelPhase.SAVED)
        if self.saved_draft is None:
            raise DecisionPanelError("save the draft before posting")
        self.phase = PanelPhase.POST_CONFIRM

    def answer_comment(self, yes: bool) -> None:
        """Record Yes or No for the Jira comment. No does not authorize a transition."""

        self._require(PanelPhase.POST_CONFIRM)
        if self.comment_authorized is not None or self.comment != OperationOutcome.NOT_ATTEMPTED:
            raise DecisionPanelError("comment authorization is already in progress")
        self.comment_authorized = yes
        if yes:
            return
        self.comment = OperationOutcome.DECLINED
        self.phase = PanelPhase.TRANSITION_CONFIRM

    def record_comment_success(self) -> None:
        self._require(PanelPhase.POST_CONFIRM)
        if self.comment_authorized is not True:
            raise DecisionPanelError("comment was not authorized")
        self.comment = OperationOutcome.POSTED
        self.comment_error = ""
        self.phase = PanelPhase.TRANSITION_CONFIRM

    def record_comment_failure(self, message: str) -> None:
        self._require(PanelPhase.POST_CONFIRM)
        if self.comment_authorized is not True:
            raise DecisionPanelError("comment was not authorized")
        self.comment = OperationOutcome.FAILED
        self.comment_error = message
        self.phase = PanelPhase.RECEIPT

    def answer_transition(self, yes: bool) -> None:
        self._require(PanelPhase.TRANSITION_CONFIRM)
        if self.transition_authorized is not None or self.transition != OperationOutcome.NOT_ATTEMPTED:
            raise DecisionPanelError("transition authorization is already in progress")
        self.transition_authorized = yes
        if yes:
            return
        self.transition = OperationOutcome.DECLINED
        self.phase = PanelPhase.RECEIPT

    def record_transition_success(self) -> None:
        self._require(PanelPhase.TRANSITION_CONFIRM)
        if self.transition_authorized is not True:
            raise DecisionPanelError("transition was not authorized")
        self.transition = OperationOutcome.MOVED
        self.transition_error = ""
        self.current_status = self.target_status
        self.phase = PanelPhase.RECEIPT

    def record_transition_failure(self, message: str) -> None:
        self._require(PanelPhase.TRANSITION_CONFIRM)
        if self.transition_authorized is not True:
            raise DecisionPanelError("transition was not authorized")
        self.transition = OperationOutcome.FAILED
        self.transition_error = message
        self.phase = PanelPhase.RECEIPT

    def retry(self) -> None:
        """Return to the failed step. Does not clear the saved draft."""

        self._require(PanelPhase.RECEIPT)
        if self.comment == OperationOutcome.FAILED:
            self.comment = OperationOutcome.NOT_ATTEMPTED
            self.comment_authorized = None
            self.comment_error = ""
            self.phase = PanelPhase.POST_CONFIRM
            return
        if self.transition == OperationOutcome.FAILED:
            self.transition = OperationOutcome.NOT_ATTEMPTED
            self.transition_authorized = None
            self.transition_error = ""
            self.phase = PanelPhase.TRANSITION_CONFIRM
            return
        raise DecisionPanelError("no failed operation to retry")

    @property
    def can_retry(self) -> bool:
        return self.comment == OperationOutcome.FAILED or self.transition == OperationOutcome.FAILED

    def _require(self, *phases: PanelPhase) -> None:
        if self.phase not in phases:
            allowed = ", ".join(phase.value for phase in phases)
            raise DecisionPanelError(f"phase is {self.phase.value}; expected {allowed}")


def receipt_rows(state: DecisionPanelState) -> tuple[tuple[str, str], ...]:
    current = state.target_status if state.transition == OperationOutcome.MOVED else state.current_status
    if not current:
        current = "unchanged"
    return (
        ("Draft saved", "YES" if state.saved_draft is not None else "NO"),
        ("Comment posted", _RECEIPT_VALUE[state.comment.value]),
        ("Status moved", _RECEIPT_VALUE[state.transition.value]),
        ("Current status", current),
    )


def format_receipt(state: DecisionPanelState) -> str:
    lines = ["Jira feedback"]
    for label, value in receipt_rows(state):
        lines.append(f"  {label:<18}{value}")
    if state.comment == OperationOutcome.FAILED and state.comment_error:
        lines.append(f"  Comment error: {state.comment_error}")
    if state.transition == OperationOutcome.FAILED and state.transition_error:
        lines.append(f"  Status error: {state.transition_error}")
    return "\n".join(lines)


def shortcut_hint(phase: PanelPhase) -> str:
    if phase == PanelPhase.EDITING:
        return "Tab: move   Arrows: scroll   Esc: back"
    return "Tab: move   Arrows: choice   Enter: activate   Esc: back"


class FocusLine(Static, can_focus=True):
    """Focus target that does not activate a decision or an external write."""


class DecisionPanel(Widget):
    """One bottom dock. Each phase replaces the controls in this dock.

    Approve stays on the left and Reject on the right. Recommendation changes
    emphasis only. Save, No, and Esc do not call Jira or GitHub.
    """

    BINDINGS = [("escape", "dismiss", "Back")]

    DEFAULT_CSS = """
    DecisionPanel {
        dock: bottom;
        layout: vertical;
        height: auto;
        width: 1fr;
        background: $background;
        border-top: tall $primary-darken-2;
        padding: 0 1 0 1;
    }
    DecisionPanel #decision-dock {
        height: auto;
        width: 1fr;
    }
    DecisionPanel #phase-decision,
    DecisionPanel #phase-editing,
    DecisionPanel #phase-saved,
    DecisionPanel #phase-post,
    DecisionPanel #phase-transition,
    DecisionPanel #phase-receipt {
        height: auto;
        width: 1fr;
    }
    DecisionPanel #draft-editor {
        height: auto;
        min-height: 6;
        max-height: 12;
    }
    DecisionPanel HorizontalGroup {
        height: auto;
        width: 1fr;
    }
    /* Both buttons share the row. Emphasis must not change this width. */
    DecisionPanel HorizontalGroup Button {
        width: 1fr;
        min-width: 0;
        margin: 0;
    }
    DecisionPanel Button.recommended {
        text-style: bold;
    }
    DecisionPanel #panel-prompt {
        text-style: bold;
        height: auto;
    }
    DecisionPanel #shortcut-footer {
        color: $text-muted;
        height: auto;
        margin-top: 1;
    }
    DecisionPanel FocusLine {
        height: auto;
        width: 1fr;
    }
    """

    def __init__(
        self,
        *,
        issue_key: str,
        target_status: str = "In Progress",
        current_status: str = "",
        prefill: str = "",
        emphasis: Emphasis = Emphasis.NONE,
        prompt: str = "Decision",
        editor_min_height: int = 6,
        editor_max_height: int = 12,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        if not target_status:
            raise DecisionPanelError("target status is required")
        self._prompt = prompt
        self._editor_min_height = editor_min_height
        self._editor_max_height = editor_max_height
        self.state = DecisionPanelState(
            issue_key=issue_key,
            target_status=target_status,
            current_status=current_status,
            default_prefill=prefill,
            emphasis=emphasis,
        )
        self._decision_visible = True

    def set_emphasis(self, emphasis: Emphasis) -> None:
        self.state.set_emphasis(emphasis)
        if self.is_mounted:
            self._apply_emphasis()

    def set_prompt(self, prompt: str) -> None:
        """Replace the decision-phase prompt. Other phases keep their own labels."""

        self._prompt = prompt
        if self.is_mounted and self.state.phase == PanelPhase.DECISION:
            self.query_one("#panel-prompt", Static).update(prompt)

    def set_decision_visible(self, visible: bool) -> None:
        """Hide Approve and Reject when the host gate is unfinished.

        The rest of the dock (edit, confirm, receipt) is unchanged.
        """

        self._decision_visible = visible
        if self.is_mounted:
            self._sync()

    def record_comment_success(self) -> None:
        self.state.record_comment_success()
        self._sync()
        self._focus_phase()

    def record_comment_failure(self, message: str) -> None:
        self.state.record_comment_failure(message)
        self._sync()
        self._focus_phase()

    def record_transition_success(self) -> None:
        self.state.record_transition_success()
        self._sync()
        self._focus_phase()

    def record_transition_failure(self, message: str) -> None:
        self.state.record_transition_failure(message)
        self._sync()
        self._focus_phase()

    def begin_approved_transition(self) -> None:
        """After a local ticket approval, ask Yes/No for the approved Jira status."""

        self.state.phase = PanelPhase.TRANSITION_CONFIRM
        self._sync()
        self._focus_phase()

    def restore_rejection(self, draft: str, *, comment_posted: bool) -> None:
        """Show a draft already saved on disk. Does not post or transition."""

        self.state.decision = "reject"
        self.state.draft = draft
        self.state.saved_draft = draft
        self.state.default_prefill = draft
        if comment_posted:
            self.state.comment = OperationOutcome.POSTED
            self.state.comment_authorized = True
            self.state.phase = PanelPhase.TRANSITION_CONFIRM
        else:
            self.state.phase = PanelPhase.SAVED
        if not self.is_mounted:
            return
        editor = self.query_one("#draft-editor", TextArea)
        if editor.text != draft:
            editor.text = draft
        self._sync()
        self._focus_phase()

    def compose(self) -> ComposeResult:
        approve_variant = "success" if self.state.emphasis == Emphasis.APPROVE else "default"
        reject_variant = "error" if self.state.emphasis == Emphasis.REJECT else "default"
        with VerticalGroup(id="decision-dock"):
            yield Static(self._prompt, id="panel-prompt", markup=False)
            with VerticalGroup(id="phase-decision"):
                with HorizontalGroup(id="decision-row"):
                    yield Button("Approve", id="approve-btn", variant=approve_variant)
                    yield Button("Reject", id="reject-btn", variant=reject_variant)
            with VerticalGroup(id="phase-editing"):
                yield TextArea("", id="draft-editor", soft_wrap=True, tab_behavior="focus")
                yield Button("Save", id="save-btn", variant="primary")
            with VerticalGroup(id="phase-saved"):
                yield FocusLine("", id="saved-preview", markup=False)
                with HorizontalGroup(id="saved-row"):
                    yield Button("Edit", id="edit-btn")
                    yield Button("Continue", id="continue-btn", variant="primary")
            with VerticalGroup(id="phase-post"):
                yield Static("", id="post-preview", markup=False)
                yield FocusLine(POST_QUESTION, id="post-question", markup=False)
                with HorizontalGroup(id="comment-row"):
                    yield Button("Yes", id="comment-yes-btn", variant="primary")
                    yield Button("No", id="comment-no-btn")
            with VerticalGroup(id="phase-transition"):
                yield Static("", id="transition-preview", markup=False)
                yield FocusLine("", id="transition-question", markup=False)
                with HorizontalGroup(id="transition-row"):
                    yield Button("Yes", id="transition-yes-btn", variant="primary")
                    yield Button("No", id="transition-no-btn")
            with VerticalGroup(id="phase-receipt"):
                yield FocusLine("", id="receipt-body", markup=False)
                yield Button("Retry", id="retry-btn", variant="warning")
            yield Static("", id="shortcut-footer", markup=False)

    def on_mount(self) -> None:
        editor = self.query_one("#draft-editor", TextArea)
        editor.styles.min_height = self._editor_min_height
        editor.styles.max_height = self._editor_max_height
        editor.styles.height = "auto"
        self._sync()
        self._focus_phase()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id not in _PANEL_BUTTONS:
            return
        event.stop()
        if button_id == "approve-btn":
            self._on_approve()
        elif button_id == "reject-btn":
            self._on_reject()
        elif button_id == "save-btn":
            self._on_save()
        elif button_id == "edit-btn":
            self._on_edit()
        elif button_id == "continue-btn":
            self._on_continue()
        elif button_id == "comment-yes-btn":
            self._on_comment_yes()
        elif button_id == "comment-no-btn":
            self._on_comment_no()
        elif button_id == "transition-yes-btn":
            self._on_transition_yes()
        elif button_id == "transition-no-btn":
            self._on_transition_no()
        elif button_id == "retry-btn":
            self._on_retry()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "draft-editor":
            return
        if self.state.phase != PanelPhase.EDITING:
            return
        self.state.edit_draft(event.text_area.text)

    def action_dismiss(self) -> None:
        """Leave the dock without dropping a locally saved draft."""

        self.post_message(PanelDismissed(self.state.issue_key, self.state.saved_draft))

    def _on_approve(self) -> None:
        self.state.choose_approve()
        self._sync()
        self.post_message(ApproveRequested(self.state.issue_key))

    def _on_reject(self) -> None:
        self.state.choose_reject()
        self._sync()
        self._focus_phase()
        self.post_message(RejectStarted(self.state.issue_key, self.state.draft))

    def _on_save(self) -> None:
        self.state.edit_draft(self.query_one("#draft-editor", TextArea).text)
        self.state.save()
        self._sync()
        self._focus_phase()
        self.post_message(DraftSaved(self.state.issue_key, self.state.saved_draft or ""))

    def _on_edit(self) -> None:
        self.state.edit_again()
        self._sync()
        self._focus_phase()

    def _on_continue(self) -> None:
        self.state.show_post_confirmation()
        self._sync()
        self._focus_phase()

    def _on_comment_yes(self) -> None:
        self.state.answer_comment(True)
        self._sync()
        self.post_message(CommentAuthorized(self.state.issue_key, self.state.saved_draft or ""))

    def _on_comment_no(self) -> None:
        self.state.answer_comment(False)
        self._sync()
        self._focus_phase()
        self.post_message(CommentDeclined(self.state.issue_key, self.state.saved_draft or ""))

    def _on_transition_yes(self) -> None:
        self.state.answer_transition(True)
        self._sync()
        self.post_message(
            TransitionAuthorized(self.state.issue_key, self.state.target_status)
        )

    def _on_transition_no(self) -> None:
        self.state.answer_transition(False)
        self._sync()
        self._focus_phase()
        self.post_message(TransitionDeclined(self.state.issue_key, self.state.target_status))

    def _on_retry(self) -> None:
        self.state.retry()
        self._sync()
        self._focus_phase()

    def _sync(self) -> None:
        phase = self.state.phase
        show_decision = phase == PanelPhase.DECISION and self._decision_visible
        for item, widget_id in _PHASE_IDS.items():
            shown = item == phase
            if item == PanelPhase.DECISION:
                shown = show_decision
            self.query_one(f"#{widget_id}").display = shown
        self.query_one("#approve-btn", Button).display = self._decision_visible
        self.query_one("#reject-btn", Button).display = self._decision_visible
        prompts = {
            PanelPhase.DECISION: self._prompt,
            PanelPhase.EDITING: "Return feedback",
            PanelPhase.SAVED: "Saved locally. This has not been posted.",
            PanelPhase.POST_CONFIRM: "Jira comment",
            PanelPhase.TRANSITION_CONFIRM: "Jira transition",
            PanelPhase.RECEIPT: "Jira feedback",
        }
        self.query_one("#panel-prompt", Static).update(prompts[phase])
        self.query_one("#shortcut-footer", Static).update(shortcut_hint(phase))
        saved = self.state.saved_draft or ""
        self.query_one("#saved-preview", Static).update(saved)
        self.query_one("#post-preview", Static).update(saved)
        self.query_one("#post-question", Static).update(POST_QUESTION)
        self.query_one("#transition-preview", Static).update(
            transition_preview(self.state.issue_key, self.state.target_status)
        )
        self.query_one("#transition-question", Static).update(
            transition_question(self.state.target_status)
        )
        self.query_one("#receipt-body", Static).update(format_receipt(self.state))
        self.query_one("#retry-btn", Button).display = phase == PanelPhase.RECEIPT and self.state.can_retry
        if phase == PanelPhase.EDITING:
            editor = self.query_one("#draft-editor", TextArea)
            if editor.text != self.state.draft:
                editor.text = self.state.draft
        self._apply_emphasis()
        comment_waiting = (
            phase == PanelPhase.POST_CONFIRM
            and self.state.comment_authorized is True
            and self.state.comment == OperationOutcome.NOT_ATTEMPTED
        )
        transition_waiting = (
            phase == PanelPhase.TRANSITION_CONFIRM
            and self.state.transition_authorized is True
            and self.state.transition == OperationOutcome.NOT_ATTEMPTED
        )
        self.query_one("#comment-yes-btn", Button).disabled = comment_waiting
        self.query_one("#comment-no-btn", Button).disabled = comment_waiting
        self.query_one("#transition-yes-btn", Button).disabled = transition_waiting
        self.query_one("#transition-no-btn", Button).disabled = transition_waiting

    def _apply_emphasis(self) -> None:
        approve = self.query_one("#approve-btn", Button)
        reject = self.query_one("#reject-btn", Button)
        approve.variant = "success" if self.state.emphasis == Emphasis.APPROVE else "default"
        reject.variant = "error" if self.state.emphasis == Emphasis.REJECT else "default"
        approve.set_class(self.state.emphasis == Emphasis.APPROVE, "recommended")
        reject.set_class(self.state.emphasis == Emphasis.REJECT, "recommended")

    def _focus_phase(self) -> None:
        phase = self.state.phase
        if phase == PanelPhase.DECISION:
            if not self._decision_visible:
                return
            target = "#reject-btn" if self.state.emphasis == Emphasis.REJECT else "#approve-btn"
        elif phase == PanelPhase.EDITING:
            target = "#draft-editor"
        elif phase == PanelPhase.SAVED:
            target = "#saved-preview"
        elif phase == PanelPhase.POST_CONFIRM:
            target = "#post-question"
        elif phase == PanelPhase.TRANSITION_CONFIRM:
            target = "#transition-question"
        else:
            target = "#receipt-body"
        self.query_one(target).focus()


_PHASE_IDS = {
    PanelPhase.DECISION: "phase-decision",
    PanelPhase.EDITING: "phase-editing",
    PanelPhase.SAVED: "phase-saved",
    PanelPhase.POST_CONFIRM: "phase-post",
    PanelPhase.TRANSITION_CONFIRM: "phase-transition",
    PanelPhase.RECEIPT: "phase-receipt",
}

_PANEL_BUTTONS = {
    "approve-btn",
    "reject-btn",
    "save-btn",
    "edit-btn",
    "continue-btn",
    "comment-yes-btn",
    "comment-no-btn",
    "transition-yes-btn",
    "transition-no-btn",
    "retry-btn",
}
