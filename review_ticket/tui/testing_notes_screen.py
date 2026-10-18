"""Jira testing-notes review screen with reject draft save and accept."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Link, Markdown, TextArea

from review_ticket.models import Outcome
from review_ticket.reports import return_comment
from review_ticket.storage import read_json
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

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, store: Store, issue: str, workflow_app: WorkflowApp) -> None:
        super().__init__()
        self._store = store
        self._issue = issue
        self._workflow_app = workflow_app
        self._issue_data: dict[str, Any] = {}

    def on_mount(self) -> None:
        self.query_one("#reject-panel", Vertical).display = False
        self.query_one("#post-panel", Vertical).display = False
        self.query_one("#transition-panel", Vertical).display = False
        session = read_json(self._store.issue_dir(self._issue) / "session.json") or {}
        self._issue_data = refresh_issue(self._workflow_app, session)
        url = str(self._issue_data.get("url") or "")
        summary = str(self._issue_data.get("summary") or self._issue)
        link = self.query_one("#issue-link", Link)
        if url:
            link.url = url
        link.update(summary)
        description = self._issue_data.get("description") or ""
        testing_notes = self._issue_data.get("testing_notes") or ""
        self.query_one("#description-md", Markdown).update(description or "_(No description.)_")
        self.query_one("#testing-notes-md", Markdown).update(
            testing_notes or "_(No testing notes on the issue.)_"
        )
        accept_btn = self.query_one("#accept-btn", Button)
        if not str(testing_notes).strip():
            accept_btn.display = False
        decision = get_decision(session, "testing_notes")
        revise = bool(getattr(self.app, "revise", False))
        if decision is not None and not revise:
            self._set_decision_buttons_enabled(False)
            if decision.get("choice") == "reject":
                self._show_reject_panel(prefill=self._read_return_draft(), focus=False)
                self._sync_authorize_panels()
        elif decision is not None and revise:
            self._set_decision_buttons_enabled(True)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Link(self._issue, id="issue-link")
        with VerticalScroll(id="description-scroll"):
            yield Markdown("", id="description-md")
        with VerticalScroll(id="testing-notes-scroll"):
            yield Markdown("", id="testing-notes-md")
        with Horizontal(id="decision-row"):
            yield Button("Accept", id="accept-btn", variant="success")
            yield Button("Reject", id="reject-btn", variant="error")
        with Vertical(id="reject-panel", classes="reject-panel"):
            yield TextArea("", id="return-draft")
            yield Button("Save", id="save-btn", variant="primary")
        with Vertical(id="post-panel"):
            yield Markdown("", id="post-preview-md")
            with Horizontal(id="post-actions"):
                yield Button("Approve", id="post-approve-btn", variant="success")
                yield Button("Deny", id="post-deny-btn")
        with Vertical(id="transition-panel"):
            yield Markdown("", id="transition-preview-md")
            with Horizontal(id="transition-actions"):
                yield Button("Approve", id="transition-approve-btn", variant="success")
                yield Button("Deny", id="transition-deny-btn")
        yield Footer()

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

    def _show_reject_panel(self, *, prefill: str, focus: bool) -> None:
        panel = self.query_one("#reject-panel", Vertical)
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
        return f"Comment on {self._issue}.\n\n{text.rstrip()}\n"

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
        self.query_one("#post-preview-md", Markdown).update(self._comment_preview(text))
        self.query_one("#post-panel", Vertical).display = True
        self.query_one("#transition-panel", Vertical).display = False

    def _show_transition_panel(self) -> None:
        status = self._in_progress_status()
        self.query_one("#transition-preview-md", Markdown).update(self._transition_preview(status))
        self.query_one("#post-panel", Vertical).display = False
        self.query_one("#transition-panel", Vertical).display = True

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
        self.query_one("#post-panel", Vertical).display = False
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
