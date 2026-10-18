"""Textual status screen bound to the P4 projection."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Label, ListItem, ListView, Markdown

from review_ticket.storage import Store
from review_ticket.status_projection import PrStatusRow, StatusProjection, project_review_status
from review_ticket.tui.pr_screen import PrReviewScreen
from review_ticket.tui.status_format import format_pr_list_label, format_status_document


class StatusScreen(Screen[None]):
    """Read-only session status; PR rows open the review screen without writing session."""

    BINDINGS = [("q", "quit_status", "Quit")]

    def __init__(self, store: Store, issue: str) -> None:
        super().__init__()
        self._store = store
        self._issue = issue
        self._projection: StatusProjection | None = None
        self._pr_rows: tuple[PrStatusRow, ...] = ()
        self._skip_resume_reload = True

    def on_mount(self) -> None:
        self._reload()
        if self._pr_rows:
            self.query_one("#pr-list", ListView).focus()

    def on_screen_resume(self) -> None:
        if self._skip_resume_reload:
            self._skip_resume_reload = False
            return
        self._reload()

    def _reload(self) -> None:
        self._projection = project_review_status(self._store, self._issue)
        self._pr_rows = self._projection.pr_rows
        self.query_one("#status-doc", Markdown).update(format_status_document(self._projection))
        list_view = self.query_one("#pr-list", ListView)
        labels = [format_pr_list_label(row) for row in self._pr_rows]
        children = list(list_view.children)
        if len(children) != len(labels):
            list_view.clear()
            if labels:
                list_view.mount(*[ListItem(Label(text)) for text in labels])
                list_view.index = 0
        else:
            for child, text in zip(children, labels, strict=True):
                child.query_one(Label).update(text)

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll(id="status-scroll"):
            yield Markdown("", id="status-doc")
        yield ListView(id="pr-list")
        yield Footer()

    def action_quit_status(self) -> None:
        self.app.exit()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None or event.list_view.id != "pr-list":
            return
        children = list(event.list_view.children)
        try:
            index = children.index(event.item)
        except ValueError:
            return
        if index < 0 or index >= len(self._pr_rows):
            return
        row = self._pr_rows[index]
        snapshot_sha = row.snapshot.open_sha or row.stored_sha
        workflow_app = getattr(self.app, "workflow_app", None)
        revise = bool(getattr(self.app, "revise", False))
        self.app.push_screen(
            PrReviewScreen(
                self._store,
                workflow_app,
                issue=self._issue,
                ref=row.ref,
                owner=row.owner,
                repo=row.repo,
                number=row.number,
                sha=snapshot_sha,
                stored_sha=row.stored_sha,
                stale=row.snapshot.stale,
                revise=revise,
            )
        )
