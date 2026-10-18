"""Automated review preparation table (P6, scenario D)."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Markdown, Static

from review_ticket.config import Config
from review_ticket.prepare_projection import PreparePrRow, PrepareProjection, project_automated_prepare
from review_ticket.runner import ScriptedRunner
from review_ticket.storage import read_json
from review_ticket.tui.context_header import ContextHeader, ContextHeaderView
from review_ticket.tui.pr_screen import PrReviewScreen
from review_ticket.workflow import App as WorkflowApp
from review_ticket.workflow import generate_automated_review

if TYPE_CHECKING:
    from review_ticket.storage import Store


class AutomatedPrepareScreen(Screen[None]):
    BINDINGS = [("escape", "go_back", "Back")]

    CSS = """
    AutomatedPrepareScreen {
        layout: vertical;
    }
    AutomatedPrepareScreen #prepare-scroll {
        height: 1fr;
        min-height: 0;
    }
    AutomatedPrepareScreen #detail-panel {
        height: auto;
        max-height: 40%;
        margin: 0 1;
        border: tall $panel;
    }
    AutomatedPrepareScreen #action-row {
        height: auto;
        margin: 0 1;
    }
    """

    def __init__(
        self,
        store: Store,
        issue: str,
        workflow_app: WorkflowApp | None = None,
        *,
        focus_ref: str | None = None,
        revise: bool = False,
    ) -> None:
        super().__init__()
        self._store = store
        self._issue = issue
        self._workflow_app = workflow_app
        self._focus_ref = focus_ref
        self._revise = revise
        self._projection: PrepareProjection | None = None
        self._rows: list[PreparePrRow] = []
        self._selected = 0
        self._busy = False
        self._generation_ran = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        yield ContextHeader(id="context-header")
        with VerticalScroll(id="prepare-scroll"):
            yield Markdown("", id="prepare-table")
        with Vertical(id="detail-panel"):
            yield Static("", id="detail-text")
            yield Static("", id="import-hint")
        with Vertical(id="action-row"):
            yield Button("View selected", id="btn-view", variant="primary")
            yield Button("Generate selected", id="btn-generate-one")
            yield Button("Generate all missing", id="btn-generate-all")

    def on_mount(self) -> None:
        self._reload()
        if self._focus_ref:
            for index, row in enumerate(self._rows):
                if row.ref == self._focus_ref:
                    self._selected = index
                    break
        self._render_detail()

    @property
    def generation_ran_on_mount(self) -> bool:
        return self._generation_ran

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

    def _reload(self) -> None:
        self._projection = project_automated_prepare(self._store, self._issue)
        self._rows = list(self._projection.rows)
        self._render_table()
        self._render_header()

    def _render_header(self) -> None:
        issue_data = read_json(self._store.issue_dir(self._issue) / "issue.json") or {}
        title = str(issue_data.get("summary") or self._issue)
        view = ContextHeaderView(
            issue_key=self._issue,
            title=title,
            stage="automated-preparation",
            recommendation="Generate reviews explicitly; nothing runs on entry.",
        )
        self.query_one("#context-header", ContextHeader).set_view(view)

    def _render_table(self) -> None:
        lines = [
            "# Automated code reviews",
            "",
            "| PR | HEAD | Status | Action |",
            "| --- | --- | --- | --- |",
        ]
        for index, row in enumerate(self._rows):
            mark = "**" if index == self._selected else ""
            end = "**" if index == self._selected else ""
            short = row.head_sha[:12] if row.head_sha else "—"
            lines.append(
                f"| {mark}{row.owner}/{row.repo}#{row.number}{end} | `{short}` | "
                f"{row.status_label} | {row.action_label} |"
            )
        self.query_one("#prepare-table", Markdown).update("\n".join(lines))

    def _selected_row(self) -> PreparePrRow | None:
        if not self._rows:
            return None
        return self._rows[max(0, min(self._selected, len(self._rows) - 1))]

    def _render_detail(self) -> None:
        row = self._selected_row()
        detail = self.query_one("#detail-text", Static)
        hint = self.query_one("#import-hint", Static)
        if row is None:
            detail.update("No pull requests in scope.")
            hint.update("")
            return
        detail.update(f"Selected: {row.ref}\n\n{row.detail}")
        if row.import_context_path and row.status in {"missing", "failed"}:
            hint.update(
                "No reviewer_command is configured. Context is at:\n"
                f"  {row.import_context_path}\n"
                "Run import-review after the external reviewer finishes. findings.json is not written automatically."
            )
        elif row.generation_error:
            hint.update(f"Last error: {row.generation_error}")
        else:
            hint.update("")

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for button_id in ("btn-view", "btn-generate-one", "btn-generate-all"):
            self.query_one(f"#{button_id}", Button).disabled = busy

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self._busy:
            return
        button_id = event.button.id or ""
        if button_id == "btn-view":
            self._open_view()
        elif button_id == "btn-generate-one":
            self._generate_selected()
        elif button_id == "btn-generate-all":
            self._generate_all_missing()

    def _open_view(self) -> None:
        row = self._selected_row()
        if row is None or row.status not in {"current", "stale"}:
            return
        owner, repo, number = row.owner, row.repo, row.number
        stored_sha = row.head_sha
        nav_sha = stored_sha
        stale = row.status == "stale"
        self.app.push_screen(
            PrReviewScreen(
                self._store,
                self._workflow(),
                issue=self._issue,
                ref=row.ref,
                owner=owner,
                repo=repo,
                number=number,
                sha=nav_sha,
                stored_sha=stored_sha,
                stale=stale,
                revise=self._revise,
            )
        )

    def _generate_selected(self) -> None:
        row = self._selected_row()
        if row is None or not row.head_sha:
            return
        if row.status == "current" and not self._revise:
            return
        self._run_generation([(row.owner, row.repo, row.number), row.head_sha])

    def _generate_all_missing(self) -> None:
        targets: list[tuple[tuple[str, str, int], str]] = []
        for row in self._rows:
            if row.status in {"missing", "stale", "failed"} and row.head_sha:
                targets.append(((row.owner, row.repo, row.number), row.head_sha))
        if not targets:
            return
        self._set_busy(True)
        workflow = self._workflow()
        for identity, sha in targets:
            row = row_from_identity(self._rows, identity)
            generate_automated_review(
                workflow,
                self._issue,
                identity=identity,
                sha=sha,
                revise=self._revise or row_status_needs_revise(row),
            )
        self._generation_ran = True
        self._set_busy(False)
        self._reload()
        self._render_detail()

    def _run_generation(self, target: tuple[tuple[str, str, int], str]) -> None:
        identity, sha = target
        self._set_busy(True)
        generate_automated_review(
            self._workflow(),
            self._issue,
            identity=identity,
            sha=sha,
            revise=self._revise,
        )
        self._generation_ran = True
        self._set_busy(False)
        self._reload()
        self._render_detail()


def row_from_identity(rows: list[PreparePrRow], identity: tuple[str, str, int]) -> PreparePrRow | None:
    owner, repo, number = identity
    for row in rows:
        if row.owner == owner and row.repo == repo and row.number == number:
            return row
    return None


def row_status_needs_revise(row: PreparePrRow | None) -> bool:
    return row is not None and row.status == "failed"
