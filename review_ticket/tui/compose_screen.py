"""GitHub review composition and publication (spec §13)."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Label, ListItem, ListView, Static, TextArea

from review_ticket.compose_projection import ComposeProjection, project_github_compose
from review_ticket.config import Config
from review_ticket.models import Outcome, WorkflowError
from review_ticket.runner import ScriptedRunner
from review_ticket.storage import read_json
from review_ticket.textutil import parse_unified_diff
from review_ticket.tui.shared_chrome import ContextHeader, ReviewContext
from review_ticket.workflow import App as WorkflowApp, publish_review, save_publication_draft

if TYPE_CHECKING:
    from review_ticket.storage import Store


class GitHubComposeScreen(Screen[None]):
    """Compose selected findings and authorize GitHub publication."""

    BINDINGS = [("escape", "go_back", "Back")]

    CSS = """
    GitHubComposeScreen {
        layout: vertical;
        overflow: hidden;
    }
    GitHubComposeScreen Header {
        dock: top;
        height: auto;
    }
    GitHubComposeScreen Footer {
        dock: bottom;
        height: auto;
    }
    GitHubComposeScreen ContextHeader {
        dock: none;
        height: auto;
    }
    GitHubComposeScreen #screen-fill {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        overflow: hidden;
        min-height: 0;
    }
    GitHubComposeScreen #finding-scroll {
        height: 1fr;
        min-height: 0;
        margin: 0 1;
        border: tall $panel;
    }
    GitHubComposeScreen #summary-edit {
        height: 6;
        margin: 0 1;
    }
    GitHubComposeScreen #outcome-row {
        height: auto;
        margin: 0 1;
    }
    GitHubComposeScreen #outcome-row Button {
        width: 1fr;
    }
    GitHubComposeScreen #preview-panel {
        height: auto;
        max-height: 12;
        margin: 0 1;
        padding: 0 1;
        border: tall $panel;
    }
    GitHubComposeScreen #message {
        height: auto;
        margin: 0 1;
    }
    GitHubComposeScreen #actions {
        height: auto;
        margin: 0 1 1 1;
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
        self._projection: ComposeProjection | None = None
        self._selection: dict[str, bool] = {}
        self._event = "COMMENT"
        self._preview_visible = False
        self._identity = (owner, repo, number)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        with Vertical(id="screen-fill"):
            yield ContextHeader(
                ReviewContext(
                    issue_key=self.issue,
                    title="",
                    stage="GitHub review",
                    outcome="PUBLISH",
                    pr_number=self.number,
                    sha=self.sha,
                    head_sha=self.stored_sha,
                    stale=self.stale,
                    historical=self.historical,
                )
            )
            yield Static("", id="checklist-heading")
            with VerticalScroll(id="finding-scroll"):
                yield ListView(id="finding-list")
            yield Label("General review comment")
            yield TextArea("", id="summary-edit")
            with Horizontal(id="outcome-row"):
                yield Button("Approve", id="btn-outcome-approve")
                yield Button("Comment", id="btn-outcome-comment")
                yield Button("Request Changes", id="btn-outcome-request-changes")
            yield Static("", id="preview-panel")
            yield Static("", id="message")
            with Horizontal(id="actions"):
                yield Button("Save draft", id="btn-save-draft")
                yield Button("Preview GitHub review", id="btn-preview", variant="primary")
                yield Button("Authorize publish", id="btn-publish", variant="success")
                yield Button("No", id="btn-cancel-preview")

    def on_mount(self) -> None:
        self.query_one("#btn-cancel-preview", Button).display = False
        self.query_one("#btn-publish", Button).display = False
        self._reload()

    def _workflow(self) -> WorkflowApp:
        if self._workflow_app is None:
            cache_dir = self._store.root.parent / ".review-ticket-cache"
            self._workflow_app = WorkflowApp(
                config=Config(reviews_dir=self._store.root),
                runner=ScriptedRunner(),
                interactive=False,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )
        return self._workflow_app

    def _diff_index(self) -> set[tuple[str, int, str]]:
        review_dir = self._review_dir()
        stored = read_json(review_dir / "diff-lines.json")
        if isinstance(stored, list):
            return {(str(item[0]), int(item[1]), str(item[2])) for item in stored}
        commit_dir = self._store.commit_dir(self.issue, self.owner, self.repo, self.number, self.sha)
        diff_path = commit_dir / "diff.patch"
        if diff_path.exists():
            return parse_unified_diff(diff_path.read_text(encoding="utf-8"))
        return set()

    def _review_dir(self):
        return self._store.commit_dir(self.issue, self.owner, self.repo, self.number, self.sha) / "review"

    def _reload(self) -> None:
        self._projection = project_github_compose(
            self._store,
            self.issue,
            self.owner,
            self.repo,
            self.number,
            self.sha,
            diff_index=self._diff_index(),
            stale=self.stale,
            historical=self.historical,
        )
        self._event = self._projection.event
        self._selection = {
            row.finding_id: row.selected for row in self._projection.rows if not row.omitted
        }
        for row in self._projection.rows:
            if row.omitted:
                self._selection.setdefault(row.finding_id, False)
        self.query_one("#summary-edit", TextArea).text = self._projection.summary
        self.query_one("#checklist-heading", Static).update(
            f"Selected for publication: {self._projection.selected_count} "
            f"(omitted: {self._projection.omitted_count})"
        )
        self._mount_findings()
        self._refresh_chrome()

    def _mount_findings(self) -> None:
        list_view = self.query_one("#finding-list", ListView)
        list_view.clear()
        if not self._projection:
            return
        for row in self._projection.rows:
            if row.omitted:
                label = f"[omitted] {row.kind}: {row.title} — {row.omit_reason}"
                list_view.mount(ListItem(Static(label)))
                continue
            checked = self._selection.get(row.finding_id, True)
            box = Checkbox(f"{row.kind}: {row.title}", value=checked, id=f"chk-{row.finding_id}")
            list_view.mount(ListItem(box))

    def _refresh_chrome(self) -> None:
        if not self._projection:
            return
        buttons = self._projection.buttons
        approve = self.query_one("#btn-outcome-approve", Button)
        comment = self.query_one("#btn-outcome-comment", Button)
        request = self.query_one("#btn-outcome-request-changes", Button)
        approve.variant = "primary" if self._event == "APPROVE" else "default"
        comment.variant = "primary" if self._event == "COMMENT" else "default"
        request.variant = "primary" if self._event == "REQUEST_CHANGES" else "default"
        approve.disabled = self._projection.read_only or not buttons.approve_enabled
        comment.disabled = self._projection.read_only or not buttons.comment_enabled
        request.disabled = self._projection.read_only or not buttons.request_changes_enabled
        read_only = self._projection.read_only
        for widget_id in ("#summary-edit", "#btn-save-draft", "#btn-preview"):
            self.query_one(widget_id).disabled = read_only
        message = self.query_one("#message", Static)
        if self._projection.read_only_reason:
            message.update(self._projection.read_only_reason)
        elif self._event == "APPROVE" and not buttons.approve_enabled:
            message.update(buttons.approve_reason or "")
        elif self._event == "COMMENT" and not buttons.comment_enabled:
            message.update(buttons.comment_reason or "")
        elif self._event == "REQUEST_CHANGES" and not buttons.request_changes_enabled:
            message.update(buttons.request_changes_reason or "")
        else:
            message.update("")

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if not event.checkbox.id or not event.checkbox.id.startswith("chk-"):
            return
        finding_id = event.checkbox.id.removeprefix("chk-")
        self._selection[finding_id] = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "btn-outcome-approve":
            self._event = "APPROVE"
        elif button_id == "btn-outcome-comment":
            self._event = "COMMENT"
        elif button_id == "btn-outcome-request-changes":
            self._event = "REQUEST_CHANGES"
        elif button_id == "btn-save-draft":
            self._save_draft()
            return
        elif button_id == "btn-preview":
            self._show_preview()
            return
        elif button_id == "btn-publish":
            self._authorize_publish()
            return
        elif button_id == "btn-cancel-preview":
            self._hide_preview()
            return
        else:
            return
        self._refresh_chrome()

    def _current_draft(self) -> dict[str, Any]:
        return {
            "sha": self.sha,
            "event": self._event,
            "summary": self.query_one("#summary-edit", TextArea).text,
            "selection": dict(self._selection),
        }

    def _save_draft(self) -> None:
        try:
            save_publication_draft(
                self._workflow(),
                self.issue,
                self._current_draft(),
                sha=self.sha,
                identity=self._identity,
            )
        except WorkflowError as exc:
            self.query_one("#message", Static).update(str(exc))
            return
        self.query_one("#message", Static).update("Draft saved locally. Nothing was posted to GitHub.")
        self._reload()

    def _show_preview(self) -> None:
        self._save_draft_silent()
        projection = project_github_compose(
            self._store,
            self.issue,
            self.owner,
            self.repo,
            self.number,
            self.sha,
            diff_index=self._diff_index(),
            stale=self.stale,
            historical=self.historical,
        )
        self.query_one("#preview-panel", Static).update(projection.preview_text)
        self.query_one("#btn-cancel-preview", Button).display = True
        self.query_one("#btn-publish", Button).display = True
        publish = self.query_one("#btn-publish", Button)
        publish.disabled = projection.read_only or not self._outcome_allowed(projection)
        self._preview_visible = True

    def _hide_preview(self) -> None:
        self.query_one("#preview-panel", Static).update("")
        self.query_one("#btn-cancel-preview", Button).display = False
        self.query_one("#btn-publish", Button).display = False
        self._preview_visible = False

    def _outcome_allowed(self, projection: ComposeProjection) -> bool:
        if self._event == "APPROVE":
            return projection.buttons.approve_enabled
        if self._event == "COMMENT":
            return projection.buttons.comment_enabled
        if self._event == "REQUEST_CHANGES":
            return projection.buttons.request_changes_enabled
        return False

    def _save_draft_silent(self) -> None:
        try:
            save_publication_draft(
                self._workflow(),
                self.issue,
                self._current_draft(),
                sha=self.sha,
                identity=self._identity,
            )
        except WorkflowError:
            pass

    def _authorize_publish(self) -> None:
        projection = project_github_compose(
            self._store,
            self.issue,
            self.owner,
            self.repo,
            self.number,
            self.sha,
            diff_index=self._diff_index(),
            stale=self.stale,
            historical=self.historical,
        )
        if not self._outcome_allowed(projection):
            self.query_one("#message", Static).update("Selected outcome is not allowed yet.")
            return
        try:
            result = publish_review(
                self._workflow(),
                self.issue,
                yes=True,
                event=self._event,
                skip=False,
                identity=self._identity,
                sha=self.sha,
            )
        except WorkflowError as exc:
            self.query_one("#message", Static).update(str(exc))
            return
        if result.outcome == Outcome.BLOCKED:
            self.query_one("#message", Static).update(result.summary)
            return
        receipt = read_json(self._review_dir() / "publication.json")
        event = str((receipt or {}).get("event") or self._event)
        self.query_one("#message", Static).update(f"Published to GitHub: {event.replace('_', ' ')}.")
        self.app.pop_screen()

    def action_go_back(self) -> None:
        if self._preview_visible:
            self._hide_preview()
            return
        self.app.pop_screen()
