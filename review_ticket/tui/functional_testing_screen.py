"""Reviewer-administered functional testing for one PR SHA (spec §12)."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static, TextArea

from review_ticket.config import Config
from review_ticket.functional_testing_projection import (
    format_functional_environment_block,
    project_functional_testing,
)
from review_ticket.interactive_functional_testing import (
    confirm_functional_blocker,
    environment_blocks_request_changes,
    functional_document_from_state,
    load_functional_testing_state,
    set_functional_disposition,
    set_functional_result,
)
from review_ticket.models import WorkflowError
from review_ticket.runner import ScriptedRunner
from review_ticket.storage import read_json
from review_ticket.tui.compose_screen import GitHubComposeScreen
from review_ticket.tui.shared_chrome import ContextHeader, ReviewContext
from review_ticket.workflow import App as WorkflowApp, save_functional_testing

if TYPE_CHECKING:
    from review_ticket.storage import Store


class FunctionalTestingScreen(Screen[None]):
    """Capture functional testing notes and disposition; save does not publish."""

    BINDINGS = [("escape", "go_back", "Back")]

    CSS = """
    FunctionalTestingScreen {
        layout: vertical;
        overflow: hidden;
    }
    FunctionalTestingScreen Header {
        dock: top;
        height: auto;
    }
    FunctionalTestingScreen Footer {
        dock: bottom;
        height: auto;
    }
    FunctionalTestingScreen ContextHeader {
        dock: none;
        height: auto;
    }
    FunctionalTestingScreen #screen-fill {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        overflow: hidden;
        min-height: 0;
    }
    FunctionalTestingScreen #env-block {
        height: auto;
        margin: 0 1;
        padding: 0 1;
        border: tall $panel;
    }
    FunctionalTestingScreen #notes-scroll {
        height: 1fr;
        min-height: 0;
        margin: 0 1;
    }
    FunctionalTestingScreen .note-field {
        height: 5;
        margin: 0 0 1 0;
    }
    FunctionalTestingScreen #result-row,
    FunctionalTestingScreen #disposition-row,
    FunctionalTestingScreen #action-row {
        height: auto;
        margin: 0 1;
    }
    FunctionalTestingScreen #message {
        height: auto;
        margin: 0 1;
        color: $warning;
    }
    """

    def __init__(
        self,
        store: Store,
        workflow_app: WorkflowApp | None,
        issue: str,
        ref: str,
        owner: str,
        repo: str,
        number: int,
        sha: str,
        stored_sha: str,
        stale: bool,
        *,
        historical: bool = False,
        revise: bool = False,
    ) -> None:
        super().__init__()
        self._store = store
        self._workflow_app = workflow_app
        self.issue = issue
        self.ref = ref
        self.owner = owner
        self.repo = repo
        self.number = number
        self.sha = sha
        self.stored_sha = stored_sha
        self.stale = stale
        self.historical = historical
        self._revise = revise
        self._state = load_functional_testing_state(None)
        self._save_refused_after_save = False
        self._identity = (owner, repo, number)
        self._failure_kind: str | None = None

    @property
    def read_only(self) -> bool:
        return self.historical or self.stale

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        with Vertical(id="screen-fill"):
            yield ContextHeader(
                ReviewContext(
                    issue_key=self.issue,
                    title="",
                    stage="Functional testing",
                    outcome="TEST",
                    pr_number=self.number,
                    sha=self.sha,
                    head_sha=self.stored_sha,
                    stale=self.stale,
                    historical=self.historical,
                )
            )
            yield Static("", id="env-block")
            with VerticalScroll(id="notes-scroll"):
                yield Static("Steps taken")
                yield TextArea("", id="steps-edit", classes="note-field")
                yield Static("Observed results")
                yield TextArea("", id="observed-edit", classes="note-field")
                yield Static("Expected behavior")
                yield TextArea("", id="expected-edit", classes="note-field")
                yield Static("Plan reference / acceptance criteria")
                yield TextArea("", id="plan-edit", classes="note-field")
                yield Static("Notes")
                yield TextArea("", id="notes-edit", classes="note-field")
            yield Static("Operational result", id="result-label")
            with Horizontal(id="result-row"):
                yield Button("Pass", id="btn-result-pass")
                yield Button("Fail", id="btn-result-fail")
                yield Button("Blocked", id="btn-result-blocked")
            yield Static("Reviewer disposition")
            with Horizontal(id="disposition-row"):
                yield Button("Approve", id="btn-disposition-approve")
                yield Button("Comment", id="btn-disposition-comment")
                yield Button("Request Changes", id="btn-disposition-request-changes")
                yield Button("Confirm blocker", id="btn-confirm-blocker")
            yield Static("", id="message")
            with Horizontal(id="action-row"):
                yield Button("Save Testing Review", id="btn-save", variant="primary")
                yield Button("Publish Request Changes", id="btn-publish-rc", variant="warning")

    def on_mount(self) -> None:
        self._load_artifacts()
        self._reload_environment()
        self._refresh_chrome()

    def _testing_dir(self):
        return self._store.commit_dir(self.issue, self.owner, self.repo, self.number, self.sha) / "testing"

    def _load_artifacts(self) -> None:
        existing = read_json(self._testing_dir() / "test-results.json")
        self._state = load_functional_testing_state(existing)
        self._failure_kind = existing.get("failure_kind") if isinstance(existing, dict) else None
        self._save_refused_after_save = bool(existing and existing.get("completed")) and not self._revise
        self.query_one("#steps-edit", TextArea).text = self._state.steps
        self.query_one("#observed-edit", TextArea).text = self._state.observed
        self.query_one("#expected-edit", TextArea).text = self._state.expected
        self.query_one("#plan-edit", TextArea).text = self._state.plan_reference
        self.query_one("#notes-edit", TextArea).text = self._state.notes

    def _reload_environment(self) -> None:
        projection = project_functional_testing(
            self._store,
            self.issue,
            owner=self.owner,
            repo=self.repo,
            number=self.number,
            sha=self.sha,
            ref=self.ref,
            historical=self.historical,
            head_stale=self.stale,
        )
        self.query_one("#env-block", Static).update(format_functional_environment_block(projection))
        title = f"#{self.number} {self.repo}"
        self.query_one(ContextHeader).update_context(
            ReviewContext(
                issue_key=self.issue,
                title=title,
                stage="Functional testing",
                outcome="TEST",
                pr_number=self.number,
                sha=self.sha,
                head_sha=self.stored_sha,
                stale=self.stale,
                historical=self.historical,
            )
        )

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

    def _sync_state_from_inputs(self) -> None:
        self._state.steps = self.query_one("#steps-edit", TextArea).text
        self._state.observed = self.query_one("#observed-edit", TextArea).text
        self._state.expected = self.query_one("#expected-edit", TextArea).text
        self._state.plan_reference = self.query_one("#plan-edit", TextArea).text
        self._state.notes = self.query_one("#notes-edit", TextArea).text

    def _failure_kind_for_state(self) -> str | None:
        if self._state.result == "blocked":
            return "environment"
        if self._state.result == "fail":
            return self._failure_kind or "implementation"
        return None

    def _refresh_chrome(self) -> None:
        result = self._state.result
        for value, button_id in (
            ("pass", "btn-result-pass"),
            ("fail", "btn-result-fail"),
            ("blocked", "btn-result-blocked"),
        ):
            button = self.query_one(f"#{button_id}", Button)
            button.variant = "primary" if result == value else "default"
        disposition = self._state.disposition
        for event, button_id in (
            ("APPROVE", "btn-disposition-approve"),
            ("COMMENT", "btn-disposition-comment"),
            ("REQUEST_CHANGES", "btn-disposition-request-changes"),
        ):
            button = self.query_one(f"#{button_id}", Button)
            button.variant = "primary" if disposition == event else "default"
        blocks_rc = environment_blocks_request_changes(result, self._failure_kind_for_state())
        rc_button = self.query_one("#btn-disposition-request-changes", Button)
        rc_button.disabled = self.read_only or blocks_rc
        confirm = self.query_one("#btn-confirm-blocker", Button)
        confirm.disabled = self.read_only or disposition != "REQUEST_CHANGES" or blocks_rc
        confirm.label = "Blocker confirmed" if self._state.blocker_confirmed else "Confirm blocker"
        publish = self.query_one("#btn-publish-rc", Button)
        publish.disabled = self.read_only or not (
            self._state.blocker_confirmed and disposition == "REQUEST_CHANGES"
        )
        read_only = self.read_only
        for widget_id in (
            "#steps-edit",
            "#observed-edit",
            "#expected-edit",
            "#plan-edit",
            "#notes-edit",
            "#btn-result-pass",
            "#btn-result-fail",
            "#btn-result-blocked",
            "#btn-disposition-approve",
            "#btn-disposition-comment",
            "#btn-save",
        ):
            widget = self.query_one(widget_id)
            if hasattr(widget, "disabled"):
                widget.disabled = read_only or (widget_id == "#btn-save" and self._save_refused_after_save)

    def _show_message(self, text: str) -> None:
        self.query_one("#message", Static).update(text)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if self.read_only:
            return
        self._sync_state_from_inputs()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "btn-result-pass":
            if self.read_only:
                return
            set_functional_result(self._state, "pass")
            self._failure_kind = None
        elif button_id == "btn-result-fail":
            if self.read_only:
                return
            set_functional_result(self._state, "fail", failure_kind=self._failure_kind or "implementation")
            self._failure_kind = self._failure_kind or "implementation"
        elif button_id == "btn-result-blocked":
            if self.read_only:
                return
            set_functional_result(self._state, "blocked", failure_kind="environment")
            self._failure_kind = "environment"
        elif button_id == "btn-disposition-approve":
            if self.read_only:
                return
            set_functional_disposition(self._state, "APPROVE")
        elif button_id == "btn-disposition-comment":
            if self.read_only:
                return
            set_functional_disposition(self._state, "COMMENT")
        elif button_id == "btn-disposition-request-changes":
            if self.read_only or environment_blocks_request_changes(
                self._state.result, self._failure_kind_for_state()
            ):
                return
            set_functional_disposition(self._state, "REQUEST_CHANGES")
        elif button_id == "btn-confirm-blocker":
            if self.read_only:
                return
            try:
                confirm_functional_blocker(self._state)
            except WorkflowError as exc:
                self._show_message(str(exc))
                return
        elif button_id == "btn-save":
            self._persist()
            return
        elif button_id == "btn-publish-rc":
            self._open_compose()
            return
        else:
            return
        self._refresh_chrome()

    def _persist(self) -> None:
        if self._save_refused_after_save:
            self._show_message("Test results already exist for this SHA. Pass --revise to replace them.")
            return
        self._sync_state_from_inputs()
        try:
            document = functional_document_from_state(
                self._state,
                sha=self.sha,
                completed=True,
                failure_kind=self._failure_kind_for_state(),
            )
            save_functional_testing(
                self._workflow(),
                self.issue,
                document,
                sha=self.sha,
                identity=self._identity,
                revise=self._revise,
                completed=True,
            )
        except WorkflowError as exc:
            self._show_message(str(exc))
            return
        self._save_refused_after_save = True
        self._state.completed = True
        self._show_message("Functional testing review saved locally (not published).")

    def _open_compose(self) -> None:
        if not self._state.blocker_confirmed:
            return
        self.app.push_screen(
            GitHubComposeScreen(
                self._store,
                self._workflow_app,
                issue=self.issue,
                ref=self.ref,
                owner=self.owner,
                repo=self.repo,
                number=self.number,
                sha=self.sha,
                stored_sha=self.stored_sha,
                stale=self.stale,
                historical=self.historical,
            )
        )

    def action_go_back(self) -> None:
        self.app.pop_screen()
