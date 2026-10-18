"""Automated review preparation — explicit generate only (Scenario D)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Static

from review_ticket.models import Outcome, WorkflowError
from review_ticket.prepare_projection import (
    PreparePrRow,
    PrepareProjection,
    format_prepare_detail,
    format_prepare_row_label,
    import_handoff_hint,
    project_automated_review_prepare,
)
from review_ticket.status_projection import project_review_status, snapshot_is_historical
from review_ticket.tui.pr_screen import PrReviewScreen
from review_ticket.tui.shared_chrome import ContextHeader, ReviewContext
from review_ticket.util import short_sha
from review_ticket.workflow import run_review

if TYPE_CHECKING:
    from review_ticket.storage import Store
    from review_ticket.workflow import App as WorkflowApp


class GenerationFinished(Message):
    def __init__(
        self,
        results: list[tuple[PreparePrRow, object | None, str | None]],
    ) -> None:
        super().__init__()
        self.results = results


class AutomatedReviewPrepareScreen(Screen[None]):
    """Per-PR current / missing / stale table. Generation runs only on button press."""

    BINDINGS = [("escape", "go_back", "Back")]

    CSS = """
    AutomatedReviewPrepareScreen {
        layout: vertical;
        overflow: hidden;
    }
    AutomatedReviewPrepareScreen Header {
        dock: top;
        height: auto;
    }
    AutomatedReviewPrepareScreen Footer {
        dock: bottom;
        height: auto;
    }
    AutomatedReviewPrepareScreen ContextHeader {
        dock: none;
        height: auto;
    }
    AutomatedReviewPrepareScreen #screen-fill {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        overflow: hidden;
        min-height: 0;
    }
    AutomatedReviewPrepareScreen #prepare-scroll {
        height: 1fr;
        min-height: 0;
        margin: 0 1;
    }
    AutomatedReviewPrepareScreen #pr-list {
        height: auto;
        max-height: 12;
        border: tall $panel;
    }
    AutomatedReviewPrepareScreen #detail {
        height: auto;
        margin: 1 0;
        padding: 0 1;
    }
    AutomatedReviewPrepareScreen #busy {
        height: auto;
        margin: 0 1;
        color: $warning;
    }
    AutomatedReviewPrepareScreen #actions {
        height: auto;
        margin: 0 1 1 1;
        layout: horizontal;
    }
    AutomatedReviewPrepareScreen #actions Button {
        margin-right: 1;
    }
    """

    def __init__(self, store: Store, issue: str, workflow_app: WorkflowApp | None = None) -> None:
        super().__init__()
        self._store = store
        self._issue = issue
        self._workflow_app = workflow_app
        self._projection: PrepareProjection | None = None
        self._rows: tuple[PreparePrRow, ...] = ()
        self._row_errors: dict[str, str] = {}
        self._import_hints: dict[str, str] = {}
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
                    stage="Automated code reviews",
                    outcome="PREPARE",
                )
            )
            with VerticalScroll(id="prepare-scroll"):
                yield ListView(id="pr-list")
                yield Static("", id="detail")
            yield Static("", id="busy")
            with Horizontal(id="actions"):
                yield Button("Row action", id="row-action-btn", variant="primary")
                yield Button("Generate Selected", id="generate-selected-btn")
                yield Button("Generate All Missing", id="generate-all-btn")

    def on_mount(self) -> None:
        self._reload()
        if self._rows:
            self.query_one("#pr-list", ListView).focus()

    def on_screen_resume(self) -> None:
        if self._skip_resume_reload:
            self._skip_resume_reload = False
            return
        self._reload()

    def action_go_back(self) -> None:
        if self.app.screen is self:
            self.app.pop_screen()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "pr-list" or event.list_view.index is None:
            return
        self._select_row(event.list_view.index)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None or event.list_view.id != "pr-list":
            return
        children = list(event.list_view.children)
        try:
            index = children.index(event.item)
        except ValueError:
            return
        self._select_row(index)
        self._row_action()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        event.stop()
        if self._busy:
            return
        if button_id == "row-action-btn":
            self._row_action()
        elif button_id == "generate-selected-btn":
            index = self.query_one("#pr-list", ListView).index or 0
            if 0 <= index < len(self._rows):
                row = self._rows[index]
                if row.generate_enabled:
                    self._start_generation((row,))
        elif button_id == "generate-all-btn":
            targets = tuple(row for row in self._rows if row.generate_enabled)
            if targets:
                self._start_generation(targets)

    def on_generation_finished(self, message: GenerationFinished) -> None:
        message.stop()
        self._busy = False
        for row, result, error in message.results:
            ref = row.ref
            if error:
                self._row_errors[ref] = error
                self._import_hints.pop(ref, None)
                continue
            if result is None:
                continue
            step_result = result
            if step_result.outcome == Outcome.BLOCKED:
                self._row_errors[ref] = step_result.summary
                self._import_hints.pop(ref, None)
                continue
            self._row_errors.pop(ref, None)
            review_dir = self._store.commit_dir(self._issue, row.owner, row.repo, row.number, row.head_sha) / "review"
            if not (review_dir / "findings.json").is_file():
                context_path = step_result.report_path
                if not context_path or not str(context_path).endswith("prompt.md"):
                    from review_ticket.prepare_projection import context_bundle_path

                    context_path = context_bundle_path(
                        self._store,
                        self._issue,
                        (row.owner, row.repo, row.number),
                        row.head_sha,
                    )
                if context_path:
                    self._import_hints[ref] = import_handoff_hint(self._issue, context_path)
            else:
                self._import_hints.pop(ref, None)
        self._set_busy(False)
        self._reload()

    def _reload(self) -> None:
        self._projection = project_automated_review_prepare(self._store, self._issue)
        self._rows = self._projection.rows
        title = self._projection.issue_title or ""
        self.query_one(ContextHeader).update_context(
            ReviewContext(
                issue_key=self._issue,
                title=title,
                stage="Automated code reviews",
                outcome="PREPARE",
            )
        )
        list_view = self.query_one("#pr-list", ListView)
        labels = [format_prepare_row_label(row) for row in self._rows]
        children = list(list_view.children)
        if len(children) != len(labels):
            list_view.clear()
            if labels:
                list_view.mount(*[ListItem(Static(text)) for text in labels])
                list_view.index = 0
        else:
            for child, text in zip(children, labels, strict=True):
                child.query_one(Static).update(text)
        index = list_view.index
        if index is None or index < 0:
            index = 0
        self._select_row(index)

    def _select_row(self, index: int) -> None:
        if not self._rows:
            self.query_one("#detail", Static).update("No pull requests in this session.")
            self._sync_action_buttons(None)
            return
        index = max(0, min(index, len(self._rows) - 1))
        row = self._rows[index]
        error = self._row_errors.get(row.ref)
        import_hint = self._import_hints.get(row.ref)
        self.query_one("#detail", Static).update(
            format_prepare_detail(row, error=error, import_hint=import_hint)
        )
        self._sync_action_buttons(row)

    def _sync_action_buttons(self, row: PreparePrRow | None) -> None:
        row_btn = self.query_one("#row-action-btn", Button)
        gen_sel = self.query_one("#generate-selected-btn", Button)
        gen_all = self.query_one("#generate-all-btn", Button)
        busy = self._busy
        if row is None:
            row_btn.disabled = True
            gen_sel.disabled = True
            gen_all.disabled = True
            return
        row_btn.label = row.row_action
        row_btn.disabled = busy or not (row.view_enabled or row.generate_enabled)
        gen_sel.disabled = busy or not row.generate_enabled
        any_missing = any(item.generate_enabled for item in self._rows)
        gen_all.disabled = busy or not any_missing

    def _row_action(self) -> None:
        index = self.query_one("#pr-list", ListView).index or 0
        if index < 0 or index >= len(self._rows):
            return
        row = self._rows[index]
        if row.view_enabled:
            self._open_pr_review(row)
        elif row.generate_enabled:
            self._start_generation((row,))

    def _open_pr_review(self, row: PreparePrRow) -> None:
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        revise = bool(getattr(self.app, "revise", False))
        status_row = next(
            (item for item in project_review_status(self._store, self._issue).pr_rows if item.ref == row.ref),
            None,
        )
        stale = False
        historical = False
        stored_sha = row.head_sha
        if status_row is not None:
            stored_sha = status_row.stored_sha
            stale = status_row.snapshot.stale
            historical = snapshot_is_historical(status_row.freshness, row.view_sha)
        self.app.push_screen(
            PrReviewScreen(
                self._store,
                workflow_app,
                issue=self._issue,
                ref=row.ref,
                owner=row.owner,
                repo=row.repo,
                number=row.number,
                sha=row.view_sha,
                stored_sha=stored_sha,
                stale=stale,
                historical=historical,
                revise=revise,
            )
        )

    def _start_generation(self, targets: tuple[PreparePrRow, ...]) -> None:
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        if workflow_app is None:
            return
        self._busy = True
        self._set_busy(True)
        self._generate_worker(targets, workflow_app)

    def _set_busy(self, busy: bool) -> None:
        label = "Running automated review…" if busy else ""
        self.query_one("#busy", Static).update(label)
        index = self.query_one("#pr-list", ListView).index or 0
        if self._rows and 0 <= index < len(self._rows):
            self._sync_action_buttons(self._rows[index])

    @work(thread=True, exclusive=True)
    def _generate_worker(self, targets: tuple[PreparePrRow, ...], workflow_app: WorkflowApp) -> None:
        revise = bool(getattr(self.app, "revise", False))
        results: list[tuple[PreparePrRow, object | None, str | None]] = []
        for row in targets:
            identity = (row.owner, row.repo, row.number)
            try:
                result = run_review(
                    workflow_app,
                    self._issue,
                    revise=revise,
                    identity=identity,
                    sha=row.head_sha,
                )
                results.append((row, result, None))
            except WorkflowError as exc:
                results.append((row, None, str(exc)))
            except Exception as exc:  # noqa: BLE001 - surface in the row for retry
                results.append((row, None, str(exc)))
        self.app.call_from_thread(self._apply_generation_results, results)

    def _apply_generation_results(
        self,
        results: list[tuple[PreparePrRow, object | None, str | None]],
    ) -> None:
        self.post_message(GenerationFinished(results))
