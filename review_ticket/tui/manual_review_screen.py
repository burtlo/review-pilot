"""Human code review screen (P8)."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, ListItem, ListView, Static, TextArea

from review_ticket.config import Config
from review_ticket.manual_review import suppress_duplicate_manual_findings
from review_ticket.models import WorkflowError
from review_ticket.runner import ScriptedRunner
from review_ticket.storage import read_json
from review_ticket.textutil import diff_excerpt
from review_ticket.util import short_sha
from review_ticket.workflow import App as WorkflowApp
from review_ticket.workflow import save_manual_review

if TYPE_CHECKING:
    from review_ticket.storage import Store


class ManualReviewScreen(Screen[None]):
    BINDINGS = [("escape", "close_review", "Close")]

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
        stale: bool,
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
        self.stale = stale
        self._revise = revise
        self._identity = (owner, repo, number)
        self._files: list[str] = []
        self._selected_file = 0
        self._findings: list[dict[str, Any]] = []
        self._notes = ""
        self._disposition: str | None = None
        self._saved = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="manual-header")
        with Vertical(id="manual-body"):
            yield ListView(id="file-list")
            with VerticalScroll(id="diff-scroll"):
                yield Static("", id="diff-excerpt")
            yield Static("Reviewer notes", classes="section-label")
            yield TextArea("", id="notes-edit")
            yield Static("Manual findings preview (duplicates against included automated findings omitted)", id="preview-label")
            yield Static("", id="finding-preview")
            with Horizontal(id="disposition-row"):
                yield Button("Approve", id="btn-disp-approve", variant="success")
                yield Button("Comment", id="btn-disp-comment")
                yield Button("Request Changes", id="btn-disp-rc", variant="error")
            yield Static("", id="message")
            with Horizontal(id="action-row"):
                yield Button("Save", id="btn-save", variant="primary")
                yield Button("Complete review", id="btn-complete")
                yield Button("Close", id="btn-close")

    def on_mount(self) -> None:
        self._load()
        self._render_header()
        self._mount_files()
        self._select_file(0)

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

    def _load(self) -> None:
        commit_dir = self._commit_dir()
        diff_path = commit_dir / "diff.patch"
        diff_text = diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""
        self._files = _paths_from_diff(diff_text)
        existing = read_json(commit_dir / "review" / "manual-review.json") or {}
        self._notes = str(existing.get("notes") or "")
        self._findings = list(existing.get("findings") or [])
        self._disposition = existing.get("disposition")
        self._saved = bool(existing)
        self.query_one("#notes-edit", TextArea).text = self._notes

    def _render_header(self) -> None:
        reviewed = short_sha(self.sha)
        self.query_one("#manual-header", Static).update(
            f"Issue: {self._issue}\nPR: {self.ref}\nSHA: {reviewed}\nHuman code review"
        )

    def _mount_files(self) -> None:
        list_view = self.query_one("#file-list", ListView)
        list_view.clear()
        if not self._files:
            list_view.mount(ListItem(Static("(no diff on disk)")))
            return
        for index, path in enumerate(self._files):
            list_view.mount(ListItem(Static(path), id=f"file-{index}"))

    def _select_file(self, index: int) -> None:
        if not self._files:
            self.query_one("#diff-excerpt", Static).update("_(No diff.patch for this SHA.)_")
            self._refresh_preview()
            return
        index = max(0, min(index, len(self._files) - 1))
        self._selected_file = index
        list_view = self.query_one("#file-list", ListView)
        list_view.index = index
        path = self._files[index]
        diff_path = self._commit_dir() / "diff.patch"
        diff_text = diff_path.read_text(encoding="utf-8") if diff_path.exists() else ""
        excerpt = diff_excerpt(diff_text, path, None)
        self.query_one("#diff-excerpt", Static).update(excerpt or f"_(No excerpt for {path})_")
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        review_dir = self._commit_dir() / "review"
        human = read_json(review_dir / "human-review.json") or {}
        machine = (read_json(review_dir / "findings.json") or {}).get("findings") or []
        kept = suppress_duplicate_manual_findings(self._findings, human, machine)
        lines = [f"- {row.get('path') or 'general'}:{row.get('line') or '—'} {row.get('text') or ''}" for row in kept]
        self.query_one("#finding-preview", Static).update("\n".join(lines) if lines else "_(no manual findings)_")

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "file-list" or event.item is None:
            return
        children = list(event.list_view.children)
        try:
            index = children.index(event.item)
        except ValueError:
            return
        self._select_file(index)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id == "notes-edit":
            self._notes = event.text_area.text

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "btn-close":
            self.action_close_review()
            return
        if self.stale:
            self._show_message("Historical snapshots are read-only.")
            return
        if button_id == "btn-disp-approve":
            self._disposition = "APPROVE"
        elif button_id == "btn-disp-comment":
            self._disposition = "COMMENT"
        elif button_id == "btn-disp-rc":
            self._disposition = "REQUEST_CHANGES"
        elif button_id == "btn-save":
            self._persist(completed=False)
            return
        elif button_id == "btn-complete":
            self._persist(completed=True)
            return
        else:
            return
        self._show_message(f"Local disposition: {self._disposition} (not published).")

    def _persist(self, *, completed: bool) -> None:
        if self._saved and not self._revise:
            self._show_message("A manual review is already recorded. Pass --revise to replace it.")
            return
        document = {
            "notes": self._notes,
            "findings": self._findings,
            "disposition": self._disposition,
            "completed": completed,
        }
        try:
            save_manual_review(
                self._workflow(),
                self._issue,
                document,
                sha=self.sha,
                identity=self._identity,
                revise=self._revise,
                completed=completed,
            )
        except WorkflowError as exc:
            self._show_message(str(exc))
            return
        self._saved = True
        self._show_message("Manual review saved." if not completed else "Manual review completed.")

    def _show_message(self, text: str) -> None:
        self.query_one("#message", Static).update(text)

    def action_close_review(self) -> None:
        self.app.pop_screen()


def _paths_from_diff(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ "):
            name = line[4:].strip()
            if name == "/dev/null":
                continue
            path = name[2:] if name.startswith("b/") else name
            if path not in paths:
                paths.append(path)
    return paths
