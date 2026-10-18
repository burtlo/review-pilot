"""Jira testing-notes review screen with reject draft save and accept."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import HorizontalGroup, Vertical, VerticalGroup, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Link, Markdown, Static, TextArea

from review_ticket.models import Outcome
from review_ticket.reports import return_comment, testing_notes_assessment_markdown
from review_ticket.storage import read_json
from review_ticket.textutil import format_jira_body_markdown, issue_section_markdown
from review_ticket.util import fingerprint, sha256_text
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


class TestingNotesScreen(Screen[None]):
    """Refresh Jira issue fields; record testing-notes accept/reject decisions."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("shift+tab", "focus_issue_link", "Jira link"),
    ]

    CSS = """
    /* https://textual.textualize.io/how-to/design-a-layout/ — dock chrome, 1fr body */
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
        min-height: 8;
        margin: 0 1;
        border: tall $panel;
        background: $surface;
    }
    TestingNotesScreen #assessment-scroll {
        height: 1fr;
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
    TestingNotesScreen #workflow-dock {
        width: 1fr;
        height: auto;
        background: $background;
        border-top: tall $primary-darken-2;
        padding: 0 1 1 1;
    }
    /* Horizontal defaults to height: 1fr and would stretch this dock into the
       spare rows, leaving a blank band under the buttons. */
    TestingNotesScreen #workflow-dock HorizontalGroup {
        width: 1fr;
        height: auto;
    }
    TestingNotesScreen #return-draft {
        height: auto;
        min-height: 6;
        max-height: 12;
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
        self.query_one("#reject-panel", VerticalGroup).display = False
        self.query_one("#post-panel", VerticalGroup).display = False
        self.query_one("#transition-panel", VerticalGroup).display = False
        session = read_json(self._store.issue_dir(self._issue) / "session.json") or {}
        self._issue_data = refresh_issue(self._workflow_app, session)
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
        decision = get_decision(session, "testing_notes")
        revise = bool(getattr(self.app, "revise", False))
        if decision is not None and not revise:
            self._set_decision_buttons_enabled(False)
            if decision.get("choice") == "reject":
                self._show_reject_panel(prefill=self._read_return_draft(), focus=False)
                self._sync_authorize_panels()
        elif decision is not None and revise:
            self._set_decision_buttons_enabled(True)
        self.query_one("#description-scroll", VerticalScroll).focus()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        with Vertical(id="screen-fill"):
            yield Link(self._issue, id="issue-link")
            with Vertical(id="ticket-panels"):
                with VerticalScroll(id="description-scroll"):
                    yield Markdown("", id="description-md", classes="issue-body-md")
                yield Static("Testing notes assessment", id="assessment-heading")
                with VerticalScroll(id="assessment-scroll"):
                    yield Markdown("", id="assessment-md", classes="issue-body-md")
            with VerticalGroup(id="workflow-dock"):
                with HorizontalGroup(id="decision-row"):
                    yield Button("Accept", id="accept-btn", variant="success")
                    yield Button("Reject", id="reject-btn", variant="error")
                with VerticalGroup(id="reject-panel", classes="reject-panel"):
                    yield TextArea("", id="return-draft")
                    yield Button("Save", id="save-btn", variant="primary")
                with VerticalGroup(id="post-panel"):
                    yield Markdown("", id="post-preview-md")
                    with HorizontalGroup(id="post-actions"):
                        yield Button("Approve", id="post-approve-btn", variant="success")
                        yield Button("Deny", id="post-deny-btn")
                with VerticalGroup(id="transition-panel"):
                    yield Markdown("", id="transition-preview-md")
                    with HorizontalGroup(id="transition-actions"):
                        yield Button("Approve", id="transition-approve-btn", variant="success")
                        yield Button("Deny", id="transition-deny-btn")

    def action_focus_issue_link(self) -> None:
        self.query_one("#issue-link", Link).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "accept-btn":
            self._on_accept()
        elif event.button.id == "reject-btn":
            self._show_reject_panel(prefill=self._draft_prefill(), focus=True)
        elif event.button.id == "save-btn":
            self._on_save_reject()
        elif event.button.id == "post-approve-btn":
            self._on_post_approve()
        elif event.button.id == "post-deny-btn":
            self._on_post_deny()
        elif event.button.id == "transition-approve-btn":
            self._on_transition_approve()
        elif event.button.id == "transition-deny-btn":
            self._on_transition_deny()

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

    def _set_ticket_panels_visible(self, visible: bool) -> None:
        self.query_one("#ticket-panels", Vertical).display = visible

    def _show_reject_panel(self, *, prefill: str, focus: bool) -> None:
        self._set_ticket_panels_visible(not focus)
        panel = self.query_one("#reject-panel", VerticalGroup)
        panel.display = True
        draft = self.query_one("#return-draft", TextArea)
        draft.disabled = False
        draft.text = prefill
        if focus:
            draft.focus()

    def _set_decision_buttons_enabled(self, enabled: bool) -> None:
        self.query_one("#accept-btn", Button).disabled = not enabled
        self.query_one("#reject-btn", Button).disabled = not enabled

    def _on_save_reject(self) -> None:
        body = self.query_one("#return-draft", TextArea).text
        decide_notes(
            self._workflow_app,
            self._issue,
            "reject",
            "",
            revise=self._revise(),
            draft_body=body,
        )
        self._set_decision_buttons_enabled(False)
        self.query_one("#return-draft", TextArea).disabled = True
        self._show_post_panel()

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

    def _sync_authorize_panels(self) -> None:
        text = self._read_return_draft()
        status = self._in_progress_status()
        if self._transition_done(status):
            self.app.pop_screen()
            return
        if self._comment_posted(text):
            self._show_transition_panel()
        else:
            self._show_post_panel()

    def _show_post_panel(self) -> None:
        text = self._read_return_draft()
        self._set_ticket_panels_visible(False)
        self.query_one("#post-preview-md", Markdown).update(self._comment_preview(text))
        self.query_one("#post-panel", VerticalGroup).display = True
        self.query_one("#transition-panel", VerticalGroup).display = False

    def _show_transition_panel(self) -> None:
        status = self._in_progress_status()
        self._set_ticket_panels_visible(False)
        self.query_one("#transition-preview-md", Markdown).update(self._transition_preview(status))
        self.query_one("#post-panel", VerticalGroup).display = False
        self.query_one("#transition-panel", VerticalGroup).display = True

    def _on_post_approve(self) -> None:
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
            preview = self._comment_preview(body_file.read_text(encoding="utf-8"))
            self.query_one("#post-preview-md", Markdown).update(f"{preview}\n**Blocked:** {result.summary}")
            return
        self._show_transition_panel()

    def _on_post_deny(self) -> None:
        self.query_one("#post-panel", VerticalGroup).display = False
        draft = self.query_one("#return-draft", TextArea)
        draft.disabled = False

    def _on_transition_approve(self) -> None:
        status = self._in_progress_status()
        result = jira_transition(self._workflow_app, self._issue, status, yes=True)
        if result.outcome == Outcome.BLOCKED:
            preview = self._transition_preview(status)
            self.query_one("#transition-preview-md", Markdown).update(f"{preview}\n**Blocked:** {result.summary}")
            return
        self.app.pop_screen()

    def _on_transition_deny(self) -> None:
        return

    def _on_accept(self) -> None:
        decide_notes(self._workflow_app, self._issue, "accept", "", revise=self._revise())
        self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()
