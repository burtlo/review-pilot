"""GitHub publication composition and authorize screen (P9)."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Markdown, Static, TextArea

from review_ticket.config import Config
from review_ticket.models import Outcome
from review_ticket.publication_compose import (
    build_compose_preview_markdown,
    project_publication_compose,
)
from review_ticket.runner import ScriptedRunner
from review_ticket.storage import read_json
from review_ticket.tui.context_header import ContextHeader, ContextHeaderView
from review_ticket.workflow import App as WorkflowApp
from review_ticket.workflow import publish_review

if TYPE_CHECKING:
    from review_ticket.storage import Store


class PublicationComposeScreen(Screen[None]):
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
        self._event = "COMMENT"
        self._authorized = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        yield ContextHeader(id="context-header")
        yield Static("Findings checklist is derived from saved automated and manual reviews.", id="hint")
        yield Static("General comment", classes="section-label")
        yield TextArea("", id="summary-edit")
        with Horizontal(id="event-row"):
            yield Button("Approve", id="btn-approve", variant="success")
            yield Button("Comment", id="btn-comment", variant="primary")
            yield Button("Request Changes", id="btn-rc", variant="error")
        with VerticalScroll(id="preview-scroll"):
            yield Markdown("", id="preview-md")
        yield Static("", id="message")
        with Horizontal(id="action-row"):
            yield Button("Refresh preview", id="btn-preview")
            yield Button("Authorize publish", id="btn-publish", variant="warning")

    def on_mount(self) -> None:
        self._render_header()
        projection = self._projection()
        summary = projection.summary_default
        if projection.functional_notes:
            summary = (summary + "\n\n## Functional testing\n\n" + projection.functional_notes).strip()
        self.query_one("#summary-edit", TextArea).text = summary
        self._sync_event_buttons(projection)
        self._refresh_preview()

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
        return project_publication_compose(
            self._commit_dir(),
            owner=self.owner,
            repo=self.repo,
            number=self.number,
            ref=self.ref,
            sha=self.sha,
        )

    def _render_header(self) -> None:
        issue_data = read_json(self._store.issue_dir(self._issue) / "issue.json") or {}
        title = str(issue_data.get("summary") or self._issue)
        projection = self._projection()
        receipt = projection.last_receipt_event or "not published"
        self.query_one("#context-header", ContextHeader).set_view(
            ContextHeaderView(
                issue_key=self._issue,
                title=title,
                stage="github-publication",
                active_pr=self.ref,
                full_sha=self.sha,
                recommendation=f"Latest receipt: {receipt.replace('_', ' ')}",
            )
        )

    def _diff_index(self) -> set[tuple[str, int, str]]:
        from review_ticket.textutil import parse_unified_diff

        stored = read_json(self._commit_dir() / "review" / "diff-lines.json")
        if isinstance(stored, list):
            return {(item[0], int(item[1]), item[2]) for item in stored}
        diff_path = self._commit_dir() / "diff.patch"
        if diff_path.exists():
            return parse_unified_diff(diff_path.read_text(encoding="utf-8"))
        return set()

    def _sync_event_buttons(self, projection) -> None:
        self.query_one("#btn-approve", Button).disabled = not projection.approve_allowed
        self.query_one("#btn-comment", Button).disabled = not projection.comment_allowed
        self.query_one("#btn-rc", Button).disabled = not projection.request_changes_allowed

    def _refresh_preview(self) -> None:
        projection = self._projection()
        self._sync_event_buttons(projection)
        summary = self.query_one("#summary-edit", TextArea).text
        preview = build_compose_preview_markdown(
            projection,
            summary=summary,
            event=self._event,
            diff_index=self._diff_index(),
            commit_dir=self._commit_dir(),
        )
        self.query_one("#preview-md", Markdown).update(preview)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "btn-approve":
            self._event = "APPROVE"
        elif button_id == "btn-comment":
            self._event = "COMMENT"
        elif button_id == "btn-rc":
            self._event = "REQUEST_CHANGES"
        elif button_id == "btn-preview":
            self._refresh_preview()
            return
        elif button_id == "btn-publish":
            self._authorize()
            return
        self._refresh_preview()

    def _authorize(self) -> None:
        message = self.query_one("#message", Static)
        summary = self.query_one("#summary-edit", TextArea).text
        result = publish_review(
            self._workflow(),
            self._issue,
            yes=True,
            event=self._event,
            skip=False,
            pr_ref=self.ref,
            sha=self.sha,
            summary=summary,
        )
        if result.outcome == Outcome.BLOCKED:
            message.update(result.summary)
            self._refresh_preview()
            return
        self._authorized = True
        message.update(result.summary)
        self._render_header()
        self._refresh_preview()
