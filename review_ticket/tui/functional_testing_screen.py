"""Functional testing capture screen (P11)."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static, TextArea

from review_ticket.config import Config
from review_ticket.models import WorkflowError
from review_ticket.runner import ScriptedRunner
from review_ticket.storage import read_json
from review_ticket.tui.context_header import ContextHeader, ContextHeaderView
from review_ticket.workflow import App as WorkflowApp
from review_ticket.workflow import record_tests

if TYPE_CHECKING:
    from review_ticket.storage import Store


class FunctionalTestingScreen(Screen[None]):
    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(
        self,
        store: Store,
        issue: str,
        workflow_app: WorkflowApp | None,
        *,
        ref: str,
        owner: str,
        repo: str,
        number: int,
        sha: str,
        revise: bool = False,
    ) -> None:
        super().__init__()
        self._store = store
        self._issue = issue
        self._workflow_app = workflow_app
        self.ref = ref
        self.owner = owner
        self.repo = repo
        self.number = number
        self.sha = sha
        self._revise = revise
        self._result = "pass"
        self._disposition: str | None = "COMMENT"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        yield ContextHeader(id="context-header")
        yield Static("Operational result", classes="section-label")
        with Horizontal(id="result-row"):
            yield Button("Pass", id="btn-pass", variant="success")
            yield Button("Fail", id="btn-fail", variant="error")
            yield Button("Blocked", id="btn-blocked")
        yield Static("Reviewer disposition (not the operational result)", classes="section-label")
        with Horizontal(id="disp-row"):
            yield Button("Approve", id="btn-disp-approve")
            yield Button("Comment", id="btn-disp-comment", variant="primary")
            yield Button("Request Changes", id="btn-disp-rc", variant="error")
        with VerticalScroll(id="form-scroll"):
            yield Static("Steps")
            yield TextArea("", id="steps")
            yield Static("Observed")
            yield TextArea("", id="observed")
            yield Static("Expected")
            yield TextArea("", id="expected")
            yield Static("Notes")
            yield TextArea("", id="notes")
            yield Static("Plan reference")
            yield TextArea("", id="plan-ref")
        yield Static("", id="message")
        with Horizontal(id="action-row"):
            yield Button("Save", id="btn-save", variant="primary")
            yield Button("Close", id="btn-close")

    def on_mount(self) -> None:
        issue_data = read_json(self._store.issue_dir(self._issue) / "issue.json") or {}
        title = str(issue_data.get("summary") or self._issue)
        self.query_one("#context-header", ContextHeader).set_view(
            ContextHeaderView(
                issue_key=self._issue,
                title=title,
                stage="functional-testing",
                active_pr=self.ref,
                full_sha=self.sha,
            )
        )
        existing = read_json(self._commit_dir() / "testing" / "test-results.json") or {}
        if existing:
            self._result = str(existing.get("result") or "pass")
            self._disposition = existing.get("disposition")
            self.query_one("#steps", TextArea).text = str(existing.get("steps") or "")
            self.query_one("#observed", TextArea).text = str(existing.get("observed") or "")
            self.query_one("#expected", TextArea).text = str(existing.get("expected") or "")
            self.query_one("#notes", TextArea).text = str(existing.get("notes") or "")
            self.query_one("#plan-ref", TextArea).text = str(existing.get("plan_reference") or "")
        self._sync_disposition_buttons()

    def _commit_dir(self):
        return self._store.commit_dir(self._issue, self.owner, self.repo, self.number, self.sha)

    def _workflow(self) -> WorkflowApp:
        if self._workflow_app is None:
            cache_dir = self._store.root.parent / ".review-ticket-cache"
            self._workflow_app = WorkflowApp(
                config=Config(reviews_dir=self._store.root, cache_dir=cache_dir),
                runner=ScriptedRunner(),
                interactive=False,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        return self._workflow_app

    def _sync_disposition_buttons(self) -> None:
        blocked = self._result == "blocked"
        self.query_one("#btn-disp-rc", Button).disabled = blocked

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "btn-pass":
            self._result = "pass"
        elif button_id == "btn-fail":
            self._result = "fail"
        elif button_id == "btn-blocked":
            self._result = "blocked"
            self._disposition = "COMMENT"
        elif button_id == "btn-disp-approve":
            self._disposition = "APPROVE"
        elif button_id == "btn-disp-comment":
            self._disposition = "COMMENT"
        elif button_id == "btn-disp-rc":
            self._disposition = "REQUEST_CHANGES"
        elif button_id == "btn-close":
            self.app.pop_screen()
            return
        elif button_id == "btn-save":
            self._save()
        self._sync_disposition_buttons()

    def _save(self) -> None:
        message = self.query_one("#message", Static)
        kind = "implementation" if self._result == "fail" else None
        try:
            record_tests(
                self._workflow(),
                self._issue,
                result=self._result,
                kind=kind,
                notes=self.query_one("#notes", TextArea).text,
                scenarios=[],
                evidence=[],
                revise=self._revise,
                pr_ref=self.ref,
                sha=self.sha,
                steps=self.query_one("#steps", TextArea).text,
                observed=self.query_one("#observed", TextArea).text,
                expected=self.query_one("#expected", TextArea).text,
                plan_reference=self.query_one("#plan-ref", TextArea).text,
                disposition=self._disposition,
            )
            message.update("Saved functional test results.")
        except WorkflowError as exc:
            message.update(str(exc))
