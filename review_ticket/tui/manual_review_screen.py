"""Manual code review track for one PR SHA (spec §10)."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static, TextArea

from review_ticket.config import Config
from review_ticket.interactive_manual_review import (
    ManualReviewState,
    confirm_manual_blocker,
    load_manual_review_state,
    manual_document_from_state,
    publication_preview_manual_findings,
    set_manual_disposition,
)
from review_ticket.models import WorkflowError
from review_ticket.runner import ScriptedRunner
from review_ticket.storage import read_json
from review_ticket.textutil import parse_unified_diff, unified_diff_excerpt
from review_ticket.tui.shared_chrome import ContextHeader, ReviewContext
from review_ticket.workflow import App as WorkflowApp, save_manual_review

if TYPE_CHECKING:
    from review_ticket.storage import Store


class ManualCodeReviewScreen(Screen[None]):
    """Record manual inspection and findings; save does not publish."""

    BINDINGS = [("escape", "go_back", "Back")]

    CSS = """
    ManualCodeReviewScreen {
        layout: vertical;
        overflow: hidden;
    }
    ManualCodeReviewScreen Header {
        dock: top;
        height: auto;
    }
    ManualCodeReviewScreen Footer {
        dock: bottom;
        height: auto;
    }
    ManualCodeReviewScreen ContextHeader {
        dock: none;
        height: auto;
    }
    ManualCodeReviewScreen #screen-fill {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        overflow: hidden;
        min-height: 0;
    }
    ManualCodeReviewScreen #review-body {
        layout: horizontal;
        height: 1fr;
        min-height: 0;
    }
    ManualCodeReviewScreen #review-body.stacked {
        layout: vertical;
    }
    ManualCodeReviewScreen #finding-list {
        width: 2fr;
        height: 1fr;
        min-height: 0;
    }
    ManualCodeReviewScreen #review-body.stacked #finding-list {
        width: 1fr;
        height: auto;
        max-height: 10;
    }
    ManualCodeReviewScreen #detail-scroll {
        width: 3fr;
        height: 1fr;
        min-height: 0;
    }
    ManualCodeReviewScreen #diff-excerpt {
        height: auto;
        margin: 0 0 1 0;
        padding: 0 1;
        background: $surface;
        border: tall $panel;
    }
    ManualCodeReviewScreen #notes-edit {
        height: 6;
        margin: 0 1 1 1;
    }
    ManualCodeReviewScreen #preview-panel {
        height: auto;
        margin: 0 1;
        padding: 0 1;
        border: tall $panel;
    }
    ManualCodeReviewScreen #disposition-row {
        height: auto;
        margin: 0 1;
    }
    ManualCodeReviewScreen #message {
        height: auto;
        margin: 0 1;
    }
    ManualCodeReviewScreen #action-buttons {
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
        self._state: ManualReviewState | None = None
        self._document: dict[str, Any] = {}
        self._human: dict[str, Any] | None = None
        self._diff_index: set[tuple[str, int, str]] = set()
        self._diff_text: str = ""
        self._selected_index = 0
        self._save_refused_after_save = False
        self._identity = (owner, repo, number)

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
                    stage="Manual code review",
                    outcome="MANUAL",
                    pr_number=self.number,
                    sha=self.sha,
                    head_sha=self.stored_sha,
                    stale=self.stale,
                    historical=self.historical,
                )
            )
            with Horizontal(id="review-body"):
                yield ListView(id="finding-list")
                with VerticalScroll(id="detail-scroll"):
                    yield Static("", id="finding-meta")
                    yield Static("", id="diff-excerpt")
                    with Horizontal():
                        yield Label("Path")
                        yield Input(placeholder="src/File.cs", id="path-input")
                    with Horizontal():
                        yield Label("Line")
                        yield Input(placeholder="142", id="line-input")
                    yield TextArea("", id="finding-text")
                    yield Button("Blocking", id="btn-blocking", variant="default")
            yield TextArea("", id="notes-edit")
            yield Static("", id="preview-panel")
            with Horizontal(id="disposition-row"):
                yield Button("Approve", id="btn-disposition-approve")
                yield Button("Comment", id="btn-disposition-comment")
                yield Button("Request Changes", id="btn-disposition-request-changes")
                yield Button("Confirm blocker", id="btn-confirm-blocker")
            yield Static("", id="message")
            with Horizontal(id="action-buttons"):
                yield Button("Add finding", id="btn-add-finding")
                yield Button("Remove finding", id="btn-remove-finding")
                yield Button("Save", id="btn-save", variant="primary")
                yield Button("Complete review", id="btn-complete", variant="success")

    def on_mount(self) -> None:
        self._load_artifacts()
        self._mount_findings()
        self._select_index(0)
        self._refresh_chrome()

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

    def _load_diff_index(self) -> set[tuple[str, int, str]]:
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

    def _load_artifacts(self) -> None:
        review_dir = self._review_dir()
        self._document = read_json(review_dir / "findings.json") or {}
        self._human = read_json(review_dir / "human-review.json")
        existing = read_json(review_dir / "manual-review.json")
        self._state = load_manual_review_state(existing)
        self._save_refused_after_save = bool(existing and existing.get("completed")) and not self._revise
        commit_dir = self._store.commit_dir(self.issue, self.owner, self.repo, self.number, self.sha)
        diff_path = commit_dir / "diff.patch"
        self._diff_text = diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""
        self._diff_index = self._load_diff_index()
        notes = self.query_one("#notes-edit", TextArea)
        notes.text = self._state.notes if self._state else ""

    def _mount_findings(self) -> None:
        list_view = self.query_one("#finding-list", ListView)
        list_view.clear()
        if not self._state or not self._state.findings:
            list_view.mount(ListItem(Static("_(no manual findings yet)_")))
            return
        for item in self._state.findings:
            loc = item.path or "general"
            if item.line is not None:
                loc = f"{loc}:{item.line}"
            label = f"{item.finding_id} {'[blocking]' if item.blocking else ''} {loc}"
            list_view.mount(ListItem(Static(label.strip())))

    def _select_index(self, index: int) -> None:
        if not self._state or not self._state.findings:
            self.query_one("#finding-meta", Static).update("Add a manual finding to begin.")
            self.query_one("#diff-excerpt", Static).update("")
            return
        index = max(0, min(index, len(self._state.findings) - 1))
        self._selected_index = index
        item = self._state.findings[index]
        list_view = self.query_one("#finding-list", ListView)
        list_view.index = index
        self.query_one("#finding-meta", Static).update(f"**{item.finding_id}**")
        self.query_one("#path-input", Input).value = item.path or ""
        line_input = self.query_one("#line-input", Input)
        line_input.value = str(item.line) if item.line is not None else ""
        self.query_one("#finding-text", TextArea).text = item.text
        blocking = self.query_one("#btn-blocking", Button)
        blocking.variant = "error" if item.blocking else "default"
        blocking.label = "Blocking (on)" if item.blocking else "Blocking (off)"
        excerpt = self.query_one("#diff-excerpt", Static)
        if item.path and isinstance(item.line, int) and (item.path, item.line, "RIGHT") in self._diff_index:
            text = unified_diff_excerpt(self._diff_text, item.path, item.line, side="RIGHT")
            excerpt.update(text or f"{item.path}:{item.line} (on diff)")
        elif item.path and item.line is not None:
            excerpt.update(f"{item.path}:{item.line}")
        else:
            excerpt.update("_(No diff context for this location.)_")
        self._update_preview()

    def _update_preview(self) -> None:
        if not self._state:
            return
        preview_rows = publication_preview_manual_findings(
            self._state,
            document=self._document,
            human=self._human,
        )
        lines = ["**Publication preview (manual inline, duplicates omitted)**"]
        if not preview_rows:
            lines.append("_(none)_")
        else:
            for row in preview_rows:
                loc = row.get("path") or "general"
                if row.get("line") is not None:
                    loc = f"{loc}:{row['line']}"
                lines.append(f"- `{loc}` — {str(row.get('text') or '').strip()}")
        self.query_one("#preview-panel", Static).update("\n".join(lines))

    def _apply_layout_mode(self) -> None:
        body = self.query_one("#review-body")
        stacked = self.app.size.width < 100
        body.set_class(stacked, "stacked")

    def _refresh_chrome(self) -> None:
        self._apply_layout_mode()
        disposition = self._state.disposition if self._state else None
        for event, button_id in (
            ("APPROVE", "btn-disposition-approve"),
            ("COMMENT", "btn-disposition-comment"),
            ("REQUEST_CHANGES", "btn-disposition-request-changes"),
        ):
            button = self.query_one(f"#{button_id}", Button)
            button.variant = "primary" if disposition == event else "default"
        confirm = self.query_one("#btn-confirm-blocker", Button)
        confirm.disabled = disposition != "REQUEST_CHANGES" or self.read_only
        if self._state and self._state.blocker_confirmed:
            confirm.label = "Blocker confirmed"
        else:
            confirm.label = "Confirm blocker"
        read_only = self.read_only
        for widget_id in (
            "#notes-edit",
            "#finding-text",
            "#path-input",
            "#line-input",
            "#btn-add-finding",
            "#btn-remove-finding",
            "#btn-save",
            "#btn-complete",
            "#btn-disposition-approve",
            "#btn-disposition-comment",
            "#btn-disposition-request-changes",
        ):
            widget = self.query_one(widget_id)
            if hasattr(widget, "disabled"):
                widget.disabled = read_only or (
                    widget_id == "#btn-save" and self._save_refused_after_save
                )
        self._update_preview()

    def _show_message(self, text: str) -> None:
        self.query_one("#message", Static).update(text)

    def _parse_line(self, value: str) -> int | None:
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            raise WorkflowError("Line must be an integer.") from None

    def _sync_selected_finding_from_inputs(self) -> None:
        if not self._state or not self._state.findings:
            return
        item = self._state.findings[self._selected_index]
        item.path = self.query_one("#path-input", Input).value.strip() or None
        item.line = self._parse_line(self.query_one("#line-input", Input).value)
        item.text = self.query_one("#finding-text", TextArea).text.strip()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "finding-list" or event.item is None:
            return
        children = list(event.list_view.children)
        try:
            index = children.index(event.item)
        except ValueError:
            return
        if index < len(self._state.findings if self._state else []):
            self._select_index(index)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if self.read_only or not self._state:
            return
        if event.text_area.id == "notes-edit":
            self._state.notes = event.text_area.text
            return
        if event.text_area.id == "finding-text":
            self._sync_selected_finding_from_inputs()
            self._update_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        if self.read_only or not self._state:
            return
        if event.input.id in {"path-input", "line-input"}:
            try:
                self._sync_selected_finding_from_inputs()
            except WorkflowError as exc:
                self._show_message(str(exc))
                return
            self._update_preview()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "btn-blocking":
            if self.read_only or not self._state or not self._state.findings:
                return
            item = self._state.findings[self._selected_index]
            item.blocking = not item.blocking
            self._select_index(self._selected_index)
            return
        if self.read_only:
            return
        if not self._state:
            return
        if button_id == "btn-add-finding":
            try:
                self._state.add_finding(path=None, line=None, text="New manual finding", blocking=False)
            except WorkflowError as exc:
                self._show_message(str(exc))
                return
            self._mount_findings()
            self._select_index(len(self._state.findings) - 1)
            self._refresh_chrome()
            return
        if button_id == "btn-remove-finding":
            if not self._state.findings:
                return
            token = self._state.findings[self._selected_index].finding_id
            self._state.remove_finding(token)
            self._mount_findings()
            self._select_index(max(0, self._selected_index - 1))
            self._refresh_chrome()
            return
        if button_id == "btn-disposition-approve":
            set_manual_disposition(self._state, "APPROVE")
        elif button_id == "btn-disposition-comment":
            set_manual_disposition(self._state, "COMMENT")
        elif button_id == "btn-disposition-request-changes":
            set_manual_disposition(self._state, "REQUEST_CHANGES")
        elif button_id == "btn-confirm-blocker":
            try:
                confirm_manual_blocker(self._state)
            except WorkflowError as exc:
                self._show_message(str(exc))
                return
        elif button_id == "btn-save":
            self._persist(completed=False)
            return
        elif button_id == "btn-complete":
            self._persist(completed=True)
            return
        else:
            return
        self._refresh_chrome()

    def _persist(self, *, completed: bool) -> None:
        if self._save_refused_after_save:
            self._show_message("Manual review is already recorded. Pass --revise to replace it.")
            return
        if not self._state:
            return
        try:
            self._sync_selected_finding_from_inputs()
            document = manual_document_from_state(self._state, sha=self.sha, completed=completed)
            save_manual_review(
                self._workflow(),
                self.issue,
                document,
                sha=self.sha,
                identity=self._identity,
                revise=self._revise,
                completed=completed,
            )
        except WorkflowError as exc:
            self._show_message(str(exc))
            return
        if completed:
            self._save_refused_after_save = True
        self._state.completed = completed
        label = "completed" if completed else "saved"
        self._show_message(f"Manual review {label} locally (not published).")

    def action_go_back(self) -> None:
        self.app.pop_screen()
