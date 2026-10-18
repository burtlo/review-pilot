"""Minimal Textual application shell for review-ticket."""

from __future__ import annotations

from textual.app import App

from review_ticket.storage import Store, read_json
from review_ticket.tui.status_screen import StatusScreen
from review_ticket.tui.testing_notes_screen import TestingNotesScreen, should_auto_present_testing_notes
from review_ticket.workflow import App as WorkflowApp


class ReviewTicketApp(App[None]):
    """Root Textual app for review-ticket attach."""

    TITLE = "review-ticket"
    ENABLE_COMMAND_PALETTE = False

    def __init__(
        self,
        store: Store | None = None,
        issue: str | None = None,
        workflow_app: WorkflowApp | None = None,
        *,
        revise: bool = False,
    ) -> None:
        super().__init__()
        self.store = store
        self.issue = issue
        self.workflow_app = workflow_app
        self.revise = revise

    def on_mount(self) -> None:
        if self.store is None or self.issue is None:
            return
        session = read_json(self.store.issue_dir(self.issue) / "session.json") or {}
        self.push_screen(StatusScreen(self.store, self.issue))
        if self.workflow_app is not None and should_auto_present_testing_notes(session):
            self.push_screen(TestingNotesScreen(self.store, self.issue, self.workflow_app))
