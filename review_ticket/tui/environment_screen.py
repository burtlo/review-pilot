"""Test environment / virtualization readiness for one PR SHA (spec §11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from review_ticket.environment_projection import (
    TestEnvironmentProjection,
    apply_read_only,
    format_environment_detail,
    project_test_environment,
    with_blocked_message,
)
from review_ticket.models import Outcome, WorkflowError
from review_ticket.tui.shared_chrome import ContextHeader, ReviewContext
from review_ticket.workflow import fetch_image, launch_environment, prepare_profile

if TYPE_CHECKING:
    from review_ticket.storage import Store
    from review_ticket.workflow import App as WorkflowApp


class EnvironmentScreen(Screen[None]):
    """Prepare, fetch, and launch via workflow — only on explicit button press."""

    BINDINGS = [("escape", "go_back", "Back")]

    CSS = """
    EnvironmentScreen {
        layout: vertical;
        overflow: hidden;
    }
    EnvironmentScreen Header {
        dock: top;
        height: auto;
    }
    EnvironmentScreen Footer {
        dock: bottom;
        height: auto;
    }
    EnvironmentScreen ContextHeader {
        dock: none;
        height: auto;
    }
    EnvironmentScreen #screen-fill {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        margin: 0 1;
    }
    EnvironmentScreen #detail {
        height: 1fr;
        min-height: 0;
        padding: 0 1;
    }
    EnvironmentScreen #busy {
        height: auto;
        color: $warning;
    }
    EnvironmentScreen #actions {
        height: auto;
        layout: horizontal;
        margin: 0 0 1 0;
    }
    EnvironmentScreen #actions Button {
        margin-right: 1;
    }
    """

    def __init__(
        self,
        store: Store,
        workflow_app: WorkflowApp | None,
        *,
        issue: str,
        ref: str,
        owner: str,
        repo: str,
        number: int,
        sha: str,
        stored_sha: str,
        stale: bool = False,
        historical: bool = False,
    ) -> None:
        super().__init__()
        self._store = store
        self._workflow_app = workflow_app
        self._issue = issue
        self._ref = ref
        self._owner = owner
        self._repo = repo
        self._number = number
        self._sha = sha
        self._stored_sha = stored_sha
        self._stale = stale
        self._historical = historical
        self._projection: TestEnvironmentProjection | None = None
        self._transient_blocked: str | None = None
        self._busy = False
        self._skip_resume_reload = True

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        with Vertical(id="screen-fill"):
            yield ContextHeader(
                ReviewContext(
                    issue_key=self._issue,
                    title="",
                    stage="Test environment",
                    outcome="ENV",
                    pr_number=self._number,
                    sha=self._sha,
                    head_sha=self._stored_sha,
                    stale=self._stale,
                    historical=self._historical,
                )
            )
            yield Static("", id="detail")
            yield Static("", id="busy")
            with Horizontal(id="actions"):
                yield Button("Prepare", id="btn-prepare", variant="primary")
                yield Button("Fetch image", id="btn-fetch")
                yield Button("Launch", id="btn-launch")

    def on_mount(self) -> None:
        self._reload()

    def on_screen_resume(self) -> None:
        if self._skip_resume_reload:
            self._skip_resume_reload = False
            return
        self._reload()

    def _reload(self) -> None:
        projection = project_test_environment(
            self._store,
            self._issue,
            owner=self._owner,
            repo=self._repo,
            number=self._number,
            sha=self._sha,
            ref=self._ref,
        )
        projection = apply_read_only(projection, historical=self._historical, head_stale=self._stale)
        if self._transient_blocked:
            projection = with_blocked_message(projection, self._transient_blocked)
        self._projection = projection
        self.query_one("#detail", Static).update(format_environment_detail(projection))
        self._sync_buttons()
        title = f"#{self._number} {self._repo}"
        self.query_one(ContextHeader).update_context(
            ReviewContext(
                issue_key=self._issue,
                title=title,
                stage="Test environment",
                outcome=projection.environment_outcome,
                pr_number=self._number,
                sha=self._sha,
                head_sha=self._stored_sha,
                stale=self._stale,
                historical=self._historical,
            )
        )

    def _sync_buttons(self) -> None:
        projection = self._projection
        busy = self._busy
        self.query_one("#busy", Static).update("Running…" if busy else "")
        prepare = self.query_one("#btn-prepare", Button)
        fetch = self.query_one("#btn-fetch", Button)
        launch = self.query_one("#btn-launch", Button)
        if projection is None:
            prepare.disabled = True
            fetch.disabled = True
            launch.disabled = True
            return
        prepare.disabled = busy or not projection.prepare_enabled
        fetch.disabled = busy or not projection.fetch_enabled
        launch.disabled = busy or not projection.launch_enabled

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._busy or self._projection is None:
            return
        if event.button.id == "btn-prepare":
            self._run_action("prepare")
        elif event.button.id == "btn-fetch":
            self._run_action("fetch")
        elif event.button.id == "btn-launch":
            self._run_action("launch")

    def _run_action(self, action: str) -> None:
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        if workflow_app is None:
            return
        self._busy = True
        self._transient_blocked = None
        self._sync_buttons()
        identity = (self._owner, self._repo, self._number)
        self._action_worker(action, workflow_app, identity)

    @work(thread=True, exclusive=True)
    def _action_worker(
        self,
        action: str,
        workflow_app: WorkflowApp,
        identity: tuple[str, str, int],
    ) -> None:
        blocked: str | None = None
        try:
            if action == "prepare":
                prepare_profile(workflow_app, self._issue, identity=identity, sha=self._sha)
            elif action == "fetch":
                result = fetch_image(workflow_app, self._issue, identity=identity, sha=self._sha)
                if result.outcome == Outcome.BLOCKED:
                    blocked = result.summary
            elif action == "launch":
                result = launch_environment(workflow_app, self._issue, identity=identity, sha=self._sha)
                if result.outcome == Outcome.BLOCKED:
                    blocked = result.summary
                elif result.outcome == Outcome.READY:
                    blocked = None
        except WorkflowError as exc:
            blocked = str(exc)
        except Exception as exc:  # noqa: BLE001 - show retryable error in the view
            blocked = str(exc)
        self.app.call_from_thread(self._finish_action, blocked)

    def _finish_action(self, blocked: str | None) -> None:
        self._busy = False
        self._transient_blocked = blocked
        self._reload()

    def action_go_back(self) -> None:
        if self.app.screen is self:
            self.app.pop_screen()
