"""Jira testing-notes review on the shared decision panel.

Approve stores acceptance and opens the PR readiness screen. Reject keeps
the notes visible, saves a local draft, then asks separately before posting
a comment or moving the ticket.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Link, Markdown, Static

from review_ticket.models import AuthorizationDenied, Outcome, WorkflowError
from review_ticket.reports import return_comment, testing_notes_assessment_markdown
from review_ticket.storage import read_json
from review_ticket.textutil import issue_section_markdown
from review_ticket.tui.readiness_screen import ReadinessScreen
from review_ticket.tui.shared_chrome import (
    ApproveRequested,
    CommentAuthorized,
    CommentDeclined,
    ContextHeader,
    DecisionPanel,
    DraftSaved,
    Emphasis,
    PanelDismissed,
    PanelPhase,
    RejectStarted,
    ReviewContext,
    TransitionAuthorized,
    TransitionDeclined,
)
from review_ticket.util import fingerprint, sha256_text
from review_ticket.workflow import decide_notes, get_decision, jira_comment, jira_transition, refresh_issue

if TYPE_CHECKING:
    from review_ticket.storage import Store
    from review_ticket.workflow import App as WorkflowApp

COMMENT_DECLINED = "comment-declined"
TRANSITION_DECLINED = "transition-declined"


def should_auto_present_testing_notes(session: dict[str, Any]) -> bool:
    if session.get("current_step") != "jira-issue":
        return False
    decision = get_decision(session, "testing_notes")
    if decision is None:
        return True
    return decision.get("choice") == "reject"


class TestingNotesScreen(Screen[None]):
    """Refresh Jira issue fields and record the testing-notes decision."""

    __test__ = False

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("shift+tab", "focus_issue_link", "Jira link"),
    ]

    CSS = """
    TestingNotesScreen {
        layout: vertical;
        overflow: hidden;
    }
    TestingNotesScreen Header {
        dock: top;
        height: auto;
    }
    TestingNotesScreen Footer {
        dock: bottom;
        height: auto;
    }
    /* Header and Footer already occupy the edges. Undock the shared chrome
       so it stacks in the body instead of painting on top of them. */
    TestingNotesScreen ContextHeader {
        dock: none;
        height: auto;
    }
    TestingNotesScreen DecisionPanel {
        dock: none;
        height: auto;
    }
    TestingNotesScreen #screen-fill {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        overflow: hidden;
        min-height: 0;
    }
    TestingNotesScreen #issue-link {
        height: auto;
        margin: 0 1;
    }
    TestingNotesScreen #ticket-panels {
        height: 1fr;
        min-height: 0;
        layout: vertical;
        overflow: hidden;
    }
    TestingNotesScreen #description-collapsed {
        height: auto;
        margin: 0 1;
        text-style: bold;
        display: none;
    }
    /* 2fr + 3fr gives the notes about 60% of the evidence height. */
    TestingNotesScreen #description-scroll {
        height: 2fr;
        min-height: 4;
        margin: 0 1;
        border: tall $panel;
        background: $surface;
    }
    TestingNotesScreen #assessment-scroll {
        height: 3fr;
        min-height: 6;
        margin: 0 1 1 1;
        border: tall $panel;
        background: $surface;
    }
    TestingNotesScreen #assessment-heading {
        height: auto;
        margin: 0 1 0 1;
        text-style: bold;
        color: $text;
    }
    TestingNotesScreen .issue-body-md {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    TestingNotesScreen .issue-body-md MarkdownBlock {
        text-wrap: wrap;
    }
    """

    def __init__(self, store: Store, issue: str, workflow_app: WorkflowApp) -> None:
        super().__init__()
        self._store = store
        self._issue = issue
        self._workflow_app = workflow_app
        self._issue_data: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        with Vertical(id="screen-fill"):
            yield ContextHeader(
                ReviewContext(issue_key=self._issue, title="", stage="Testing notes")
            )
            yield Link(self._issue, id="issue-link")
            with Vertical(id="ticket-panels"):
                yield Static("Issue description", id="description-collapsed")
                with VerticalScroll(id="description-scroll"):
                    yield Markdown("", id="description-md", classes="issue-body-md")
                yield Static("Testing notes assessment", id="assessment-heading")
                with VerticalScroll(id="assessment-scroll"):
                    yield Markdown("", id="assessment-md", classes="issue-body-md")
            yield DecisionPanel(
                issue_key=self._issue,
                target_status=self._workflow_app.config.in_progress_status,
                current_status="",
                prefill="",
                prompt="Are the testing notes adequate?",
            )

    def on_mount(self) -> None:
        session = read_json(self._store.issue_dir(self._issue) / "session.json") or {}
        self._issue_data = refresh_issue(self._workflow_app, session)
        summary = str(self._issue_data.get("summary") or self._issue)
        url = str(self._issue_data.get("url") or "")
        link = self.query_one("#issue-link", Link)
        if url:
            link.url = url
        link.update(summary)
        description = self._issue_data.get("description") or ""
        self.query_one("#description-md", Markdown).update(
            issue_section_markdown("Ticket description", description, empty_placeholder="_(No description.)_")
        )
        self.query_one("#assessment-md", Markdown).update(
            testing_notes_assessment_markdown(self._issue_data)
        )
        emphasis = self._emphasis()
        recommendation = "Approve" if emphasis == Emphasis.APPROVE else "Reject"
        outcome = session.get("outcome")
        self.query_one(ContextHeader).update_context(
            ReviewContext(
                issue_key=self._issue,
                title=summary,
                stage="Testing notes",
                outcome=str(outcome) if outcome else None,
                recommendation=recommendation,
            )
        )
        panel = self.query_one(DecisionPanel)
        panel.state.current_status = str(self._issue_data.get("status") or "")
        panel.state.default_prefill = self._draft_prefill()
        panel.set_emphasis(emphasis)

        decision = get_decision(session, "testing_notes")
        revise = self._revise()
        if decision is not None and decision.get("choice") == "reject" and not revise:
            status = self._in_progress_status()
            if self._transition_done(status):
                self._back_to_status()
                return
            draft = self._read_return_draft()
            self._collapse_description()
            panel.restore_rejection(draft, comment_posted=self._comment_posted(draft))
        else:
            self._expand_description()
        self._apply_gate()
        self._focus_open_decision()

    def action_focus_issue_link(self) -> None:
        self.query_one("#issue-link", Link).focus()

    def action_go_back(self) -> None:
        self._back_to_status()

    def on_approve_requested(self, message: ApproveRequested) -> None:
        message.stop()
        if self.query_one("#approve-btn", Button).disabled:
            return
        decide_notes(self._workflow_app, self._issue, "accept", "", revise=self._revise())
        self.app.switch_screen(ReadinessScreen(self._store, self._issue, self._workflow_app))

    def on_reject_started(self, message: RejectStarted) -> None:
        message.stop()
        self._collapse_description()

    def on_draft_saved(self, message: DraftSaved) -> None:
        message.stop()
        decide_notes(
            self._workflow_app,
            self._issue,
            "reject",
            "",
            revise=self._revise(),
            draft_body=message.text,
        )
        self._collapse_description()
        self._apply_gate(lock_decision=True)

    def on_comment_authorized(self, message: CommentAuthorized) -> None:
        message.stop()
        panel = self.query_one(DecisionPanel)
        path = self._return_draft_path()
        if not path.exists():
            panel.record_comment_failure("The saved draft is missing.")
            return
        try:
            result = jira_comment(
                self._workflow_app,
                self._issue,
                body_file=path,
                body=None,
                yes=True,
            )
        except (WorkflowError, AuthorizationDenied) as exc:
            panel.record_comment_failure(str(exc))
            return
        if result.outcome == Outcome.BLOCKED:
            panel.record_comment_failure(result.summary)
            return
        self._clear_flag(COMMENT_DECLINED)
        panel.record_comment_success()

    def on_comment_declined(self, message: CommentDeclined) -> None:
        message.stop()
        self._set_flag(COMMENT_DECLINED)

    def on_transition_authorized(self, message: TransitionAuthorized) -> None:
        message.stop()
        panel = self.query_one(DecisionPanel)
        try:
            result = jira_transition(self._workflow_app, self._issue, message.status, yes=True)
        except (WorkflowError, AuthorizationDenied) as exc:
            panel.record_transition_failure(str(exc))
            return
        if result.outcome == Outcome.BLOCKED:
            panel.record_transition_failure(result.summary)
            return
        self._clear_flag(TRANSITION_DECLINED)
        panel.record_transition_success()

    def on_transition_declined(self, message: TransitionDeclined) -> None:
        message.stop()
        self._set_flag(TRANSITION_DECLINED)

    def on_panel_dismissed(self, message: PanelDismissed) -> None:
        message.stop()
        self._back_to_status()

    def _revise(self) -> bool:
        return bool(getattr(self.app, "revise", False))

    def _notes_text(self) -> str:
        return (self._issue_data.get("testing_notes") or "").strip()

    def _emphasis(self) -> Emphasis:
        return Emphasis.APPROVE if self._notes_text() else Emphasis.REJECT

    def _draft_prefill(self) -> str:
        path = self._return_draft_path()
        if path.exists():
            saved = path.read_text(encoding="utf-8")
            if saved.strip():
                return saved
        if self._notes_text():
            reason = "The testing notes are missing or not adequate for peer review."
        else:
            reason = "No testing notes were found on the Jira issue."
        return return_comment(issue=self._issue, reason=reason, notes="", links=[])

    def _return_draft_path(self) -> Path:
        return self._store.issue_dir(self._issue) / "return-comment.md"

    def _read_return_draft(self) -> str:
        path = self._return_draft_path()
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if text.strip():
                return text
        return self._draft_prefill()

    def _expand_description(self) -> None:
        self.query_one("#description-scroll").display = True
        self.query_one("#description-collapsed").display = False

    def _collapse_description(self) -> None:
        self.query_one("#description-scroll").display = False
        self.query_one("#description-collapsed").display = True

    def _apply_gate(self, *, lock_decision: bool | None = None) -> None:
        """Disable Approve when testing notes are empty.

        ``step_jira`` never offers accept for an empty notes body. A saved
        decision stays locked until ``--revise``.
        """

        decision = get_decision(self._session(), "testing_notes")
        if lock_decision is None:
            lock_decision = decision is not None and not self._revise()
        notes_present = bool(self._notes_text())
        self.query_one("#reject-btn", Button).disabled = lock_decision
        self.query_one("#approve-btn", Button).disabled = lock_decision or not notes_present

    def _focus_open_decision(self) -> None:
        panel = self.query_one(DecisionPanel)
        if panel.state.phase != PanelPhase.DECISION:
            return
        approve = panel.query_one("#approve-btn", Button)
        reject = panel.query_one("#reject-btn", Button)
        if panel.state.emphasis == Emphasis.REJECT or approve.disabled:
            reject.focus()
        else:
            approve.focus()

    def _back_to_status(self) -> None:
        if self.app.screen is self:
            self.app.pop_screen()

    def _session(self) -> dict[str, Any]:
        return read_json(self._store.issue_dir(self._issue) / "session.json") or {}

    def _set_flag(self, flag: str) -> None:
        session = self._session()
        decision = get_decision(session, "testing_notes")
        if decision is None:
            return
        decision[flag] = True
        self._store.save_session(session)

    def _clear_flag(self, flag: str) -> None:
        session = self._session()
        decision = get_decision(session, "testing_notes")
        if decision is None or flag not in decision:
            return
        decision.pop(flag, None)
        self._store.save_session(session)

    def _comment_action_key(self, text: str) -> str:
        session = self._session()
        sha = session.get("active_sha") or ""
        return fingerprint(
            {"kind": "jira.comment", "issue": self._issue, "sha": sha, "body": sha256_text(text)}
        )

    def _transition_action_key(self, status: str) -> str:
        session = self._session()
        sha = session.get("active_sha") or ""
        return fingerprint({"kind": "jira.transition", "issue": self._issue, "status": status, "sha": sha})

    def _comment_posted(self, text: str) -> bool:
        return self._store.successful_action(self._issue, self._comment_action_key(text)) is not None

    def _transition_done(self, status: str) -> bool:
        return self._store.successful_action(self._issue, self._transition_action_key(status)) is not None

    def _in_progress_status(self) -> str:
        return self._workflow_app.config.in_progress_status
