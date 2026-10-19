"""Test environment status and lifecycle actions (P10)."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Markdown, Static

from review_ticket.config import Config
from review_ticket.models import Outcome
from review_ticket.runner import ScriptedRunner
from review_ticket.storage import read_json
from review_ticket.test_env_projection import format_test_environment_markdown, project_test_environment
from review_ticket.tui.context_header import ContextHeader, ContextHeaderView
from review_ticket.workflow import App as WorkflowApp
from review_ticket.workflow import fetch_image, launch_environment, prepare_profile

if TYPE_CHECKING:
    from review_ticket.storage import Store


class TestEnvironmentScreen(Screen[None]):
    BINDINGS = [("escape", "go_back", "Back")]

    CSS = """
    TestEnvironmentScreen {
        layout: vertical;
    }
    TestEnvironmentScreen #env-scroll {
        height: 1fr;
        min-height: 0;
    }
    TestEnvironmentScreen #action-row {
        height: auto;
        margin: 0 1;
    }
    """

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
        self._busy = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        yield ContextHeader(id="context-header")
        with VerticalScroll(id="env-scroll"):
            yield Markdown("", id="env-doc")
        with Vertical(id="action-row"):
            yield Button("Prepare", id="btn-prepare")
            yield Button("Fetch", id="btn-fetch")
            yield Button("Launch", id="btn-launch")
            yield Button("Functional tests", id="btn-functional")
        yield Static("", id="status-line")

    def on_mount(self) -> None:
        self._render()

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

    def _commit_dir(self):
        return self._store.commit_dir(self._issue, self.owner, self.repo, self.number, self.sha)

    def _projection(self):
        return project_test_environment(
            self._commit_dir(),
            sha=self.sha,
            issue=self._issue,
            pr_ref=self.ref,
        )

    def _render(self) -> None:
        projection = self._projection()
        issue_data = read_json(self._store.issue_dir(self._issue) / "issue.json") or {}
        title = str(issue_data.get("summary") or self._issue)
        self.query_one("#context-header", ContextHeader).set_view(
            ContextHeaderView(
                issue_key=self._issue,
                title=title,
                stage="test-environment",
                active_pr=self.ref,
                full_sha=self.sha,
                recommendation="Prepare, fetch, and launch only when you press a button.",
            )
        )
        self.query_one("#env-doc", Markdown).update(format_test_environment_markdown(projection))
        status = self.query_one("#status-line", Static)
        if projection.digest_uncertain:
            status.update("BLOCKED — digest does not match this SHA.")
        elif projection.blocked_reason:
            status.update(f"BLOCKED — {projection.blocked_reason}")
        else:
            status.update("")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button_id in ("btn-prepare", "btn-fetch", "btn-launch", "btn-functional"):
            self.query_one(f"#{button_id}", Button).disabled = busy

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._busy:
            return
        button_id = event.button.id or ""
        if button_id == "btn-functional":
            from review_ticket.tui.functional_testing_screen import FunctionalTestingScreen

            self.app.push_screen(
                FunctionalTestingScreen(
                    self._store,
                    self._issue,
                    self._workflow_app,
                    ref=self.ref,
                    owner=self.owner,
                    repo=self.repo,
                    number=self.number,
                    sha=self.sha,
                    revise=self._revise,
                )
            )
            return
        workflow = self._workflow()
        target = {"pr_ref": self.ref, "sha": self.sha}
        self._set_busy(True)
        if button_id == "btn-prepare":
            prepare_profile(workflow, self._issue, **target)
        elif button_id == "btn-fetch":
            result = fetch_image(workflow, self._issue, **target)
            if result.outcome == Outcome.BLOCKED:
                self.query_one("#status-line", Static).update(f"BLOCKED — {result.summary}")
        elif button_id == "btn-launch":
            result = launch_environment(workflow, self._issue, **target)
            if result.outcome == Outcome.BLOCKED:
                self.query_one("#status-line", Static).update(f"BLOCKED — {result.summary}")
        self._set_busy(False)
        self._render()
