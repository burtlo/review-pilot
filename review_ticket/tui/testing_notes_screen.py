"""Jira testing-notes review screen with shared context header and decision panel."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Link, Markdown, Static

from review_ticket.models import Outcome
from review_ticket.reports import return_comment, testing_notes_assessment_markdown
from review_ticket.storage import read_json
from review_ticket.textutil import format_jira_body_markdown, issue_section_markdown
from review_ticket.tui.context_header import ContextHeader, ContextHeaderView
from review_ticket.tui.decision_panel import (
    DecisionPanel,
    DecisionPanelModel,
    DecisionPanelState,
    PanelRecommendation,
)
from review_ticket.util import fingerprint, sha256_text
from review_ticket.tui.readiness_screen import ReadinessScreen
from review_ticket.tui.status_screen import StatusScreen
from review_ticket.workflow import decide_notes, get_decision, jira_comment, jira_transition, refresh_issue

if TYPE_CHECKING:
    from review_ticket.storage import Store
    from review_ticket.workflow import App as WorkflowApp


def should_auto_present_testing_notes(session: dict[str, Any]) -> bool:
    if session.get("current_step") != "jira-issue":
        return False
    decision = get_decision(session, "testing_notes")
    if decision is None:
        return True
    return decision.get("choice") == "reject"


def _panel_recommendation(issue_data: dict[str, Any]) -> PanelRecommendation:
    if (issue_data.get("testing_notes") or "").strip():
        return PanelRecommendation.APPROVE
    return PanelRecommendation.REJECT


def _header_recommendation(issue_data: dict[str, Any]) -> str:
    if (issue_data.get("testing_notes") or "").strip():
        return "Approve — notes present"
    return "Reject — missing notes"


class TestingNotesScreen(Screen[None]):
    """Refresh Jira issue fields; record testing-notes accept/reject decisions."""

    __test__ = False  # pytest: name starts with "Test"; not a test case

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
        min-height: 18;
        layout: vertical;
        overflow: hidden;
    }
    TestingNotesScreen #description-scroll {
        height: 1fr;
        min-height: 6;
        margin: 0 1;
        border: tall $panel;
        background: $surface;
    }
    TestingNotesScreen #assessment-scroll {
        height: 2fr;
        min-height: 8;
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
    TestingNotesScreen #decision-panel {
        height: auto;
        min-height: 0;
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

    def on_mount(self) -> None:
        session = read_json(self._store.issue_dir(self._issue) / "session.json") or {}
        self._issue_data = refresh_issue(self._workflow_app, session)
        self._render_context_header(session)
        url = str(self._issue_data.get("url") or "")
        summary = str(self._issue_data.get("summary") or self._issue)
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
        panel = self.query_one("#decision-panel", DecisionPanel)
        panel.set_recommendation(_panel_recommendation(self._issue_data))
        self._sync_authorization_previews(panel)
        self._sync_approve_enabled(panel)

        decision = get_decision(session, "testing_notes")
        revise = bool(getattr(self.app, "revise", False))
        if decision is not None and not revise:
            panel.set_decision_enabled(False)
            if decision.get("choice") == "reject":
                self._restore_reject_flow(panel)
        elif decision is not None and revise:
            panel.set_decision_enabled(True)

        self.query_one("#description-scroll", VerticalScroll).focus()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        with Vertical(id="screen-fill"):
            yield ContextHeader(id="context-header")
            yield Link(self._issue, id="issue-link")
            with Vertical(id="ticket-panels"):
                with VerticalScroll(id="description-scroll"):
                    yield Markdown("", id="description-md", classes="issue-body-md")
                yield Static("Testing notes assessment", id="assessment-heading")
                with VerticalScroll(id="assessment-scroll"):
                    yield Markdown("", id="assessment-md", classes="issue-body-md")
            yield DecisionPanel(id="decision-panel")

    def action_focus_issue_link(self) -> None:
        self.query_one("#issue-link", Link).focus()

    def on_decision_panel_reject_chosen(self, _event: DecisionPanel.RejectChosen) -> None:
        self.query_one("#description-scroll", VerticalScroll).display = False
        panel = self.query_one("#decision-panel", DecisionPanel)
        panel.begin_reject_edit(self._draft_prefill())

    def on_decision_panel_draft_saved(self, event: DecisionPanel.DraftSaved) -> None:
        decide_notes(
            self._workflow_app,
            self._issue,
            "reject",
            "",
            revise=self._revise(),
            draft_body=event.body,
        )
        panel = self.query_one("#decision-panel", DecisionPanel)
        panel.set_decision_enabled(False)
        self._sync_authorization_previews(panel)

    def on_decision_panel_approved(self, _event: DecisionPanel.Approved) -> None:
        decide_notes(self._workflow_app, self._issue, "accept", "", revise=self._revise())
        self._pop_after_decision()

    def on_decision_panel_comment_authorized(self, event: DecisionPanel.CommentAuthorized) -> None:
        panel = self.query_one("#decision-panel", DecisionPanel)
        if not event.post:
            return
        body_file = self._return_draft_path()
        if not body_file.exists():
            return
        result = jira_comment(
            self._workflow_app,
            self._issue,
            body_file=body_file,
            body=None,
            yes=True,
        )
        if result.outcome == Outcome.BLOCKED:
            panel.record_comment_failure(result.summary)

    def on_decision_panel_transition_authorized(self, event: DecisionPanel.TransitionAuthorized) -> None:
        panel = self.query_one("#decision-panel", DecisionPanel)
        if event.move:
            status = self._in_progress_status()
            result = jira_transition(self._workflow_app, self._issue, status, yes=True)
            if result.outcome == Outcome.BLOCKED:
                panel.record_transition_failure(result.summary)
                return
        self._return_to_status()

    def _return_to_status(self) -> None:
        while not isinstance(self.app.screen, StatusScreen):
            self.app.pop_screen()

    def _pop_after_decision(self) -> None:
        self.app.pop_screen()
        self.app.push_screen(ReadinessScreen(self._store, self._issue, self._workflow_app))

    def _revise(self) -> bool:
        return bool(getattr(self.app, "revise", False))

    def _draft_prefill(self) -> str:
        path = self._return_draft_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        return return_comment(
            issue=self._issue,
            reason="No testing notes were found on the Jira issue.",
            notes="",
            links=[],
        )

    def _return_draft_path(self) -> Path:
        return self._store.issue_dir(self._issue) / "return-comment.md"

    def _read_return_draft(self) -> str:
        path = self._return_draft_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        return self._draft_prefill()

    def _render_context_header(self, session: dict[str, Any]) -> None:
        view = ContextHeaderView(
            issue_key=self._issue,
            title=str(self._issue_data.get("summary") or self._issue),
            stage=str(session.get("current_step") or "jira-issue"),
            outcome=session.get("outcome"),
            active_pr=str(session.get("active_pr")) if session.get("active_pr") else None,
            full_sha=session.get("active_sha"),
            recommendation=_header_recommendation(self._issue_data),
        )
        self.query_one("#context-header", ContextHeader).set_view(view)

    def _sync_approve_enabled(self, panel: DecisionPanel) -> None:
        notes_present = bool((self._issue_data.get("testing_notes") or "").strip())
        panel.set_approve_enabled(notes_present)

    def _sync_authorization_previews(self, panel: DecisionPanel) -> None:
        text = self._read_return_draft()
        panel.set_comment_preview(self._comment_preview(text))
        panel.set_transition_preview(self._transition_preview(self._in_progress_status()))
        session = self._session()
        status_name = str(self._issue_data.get("status") or session.get("recommendation") or "")
        if status_name:
            panel.set_current_status(status_name)

    def _session(self) -> dict[str, Any]:
        return read_json(self._store.issue_dir(self._issue) / "session.json") or {}

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

    def _comment_preview(self, text: str) -> str:
        body = format_jira_body_markdown(text).strip() or text.rstrip()
        return f"Comment on {self._issue}.\n\n{body}\n"

    def _transition_preview(self, status: str) -> str:
        session = self._session()
        sha = session.get("active_sha") or ""
        preview = f"Transition {self._issue} to {status}."
        if sha:
            preview += f"\nReview SHA: {sha}"
        return preview + "\n"

    def _in_progress_status(self) -> str:
        return self._workflow_app.config.in_progress_status

    def _restore_reject_flow(self, panel: DecisionPanel) -> None:
        status = self._in_progress_status()
        if self._transition_done(status):
            self._return_to_status()
            return
        draft = self._read_return_draft()
        self.query_one("#description-scroll", VerticalScroll).display = False
        if self._comment_posted(draft):
            model = DecisionPanelModel(
                state=DecisionPanelState.TRANSITION_CONFIRM,
                draft_text=draft,
                saved=True,
                comment_preview=self._comment_preview(draft),
                transition_preview=self._transition_preview(status),
                comment_outcome="posted",
            )
            panel.restore_model(model)
            return
        model = DecisionPanelModel(
            state=DecisionPanelState.SAVED,
            draft_text=draft,
            saved=True,
            comment_preview=self._comment_preview(draft),
            transition_preview=self._transition_preview(status),
        )
        panel.restore_model(model)

    def action_go_back(self) -> None:
        self.app.pop_screen()
