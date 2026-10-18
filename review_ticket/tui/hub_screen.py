"""PR review hub — three tracks per PR after readiness (spec §7)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Markdown, Static

from review_ticket.hub_projection import HubProjection, HubPrBlock, HubTrackRow, flatten_track_rows, project_review_hub
from review_ticket.models import Outcome
from review_ticket.storage import read_json
from review_ticket.textutil import format_jira_body_markdown
from review_ticket.ticket_disposition import project_ticket_disposition, ticket_return_draft
from review_ticket.tui.context_header import ContextHeader, ContextHeaderView
from review_ticket.tui.decision_panel import DecisionPanel, DecisionPanelModel, DecisionPanelState
from review_ticket.tui.hub_format import format_hub_document, format_track_list_label
from review_ticket.tui.automated_prepare_screen import AutomatedPrepareScreen
from review_ticket.tui.manual_review_screen import ManualReviewScreen
from review_ticket.tui.publication_compose_screen import PublicationComposeScreen
from review_ticket.tui.test_environment_screen import TestEnvironmentScreen
from review_ticket.workflow import get_decision, jira_comment, jira_transition, record_ticket_disposition

if TYPE_CHECKING:
    from review_ticket.storage import Store
    from review_ticket.workflow import App as WorkflowApp


def should_auto_present_hub(session: dict[str, Any]) -> bool:
    notes = get_decision(session, "testing_notes")
    if notes is None or notes.get("choice") != "accept":
        return False
    gate = get_decision(session, "pr_readiness")
    return gate is not None and gate.get("choice") == "accept"


class ReviewHubScreen(Screen[None]):
    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("p", "open_publication", "Publish"),
    ]

    CSS = """
    ReviewHubScreen {
        layout: vertical;
        overflow: hidden;
    }
    ReviewHubScreen Header {
        dock: top;
        height: auto;
    }
    ReviewHubScreen Footer {
        dock: bottom;
        height: auto;
    }
    ReviewHubScreen #screen-fill {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        overflow: hidden;
        min-height: 0;
    }
    ReviewHubScreen #hub-scroll {
        height: 1fr;
        min-height: 0;
    }
    ReviewHubScreen #track-panel {
        height: auto;
        max-height: 35%;
        margin: 0 1;
        border: tall $panel;
        background: $surface;
    }
    ReviewHubScreen #track-list {
        height: auto;
        max-height: 10;
    }
    ReviewHubScreen #dock-note {
        height: auto;
        margin: 0 1;
        color: $text-muted;
    }
    ReviewHubScreen #decision-panel {
        height: auto;
        min-height: 0;
    }
    """

    def __init__(self, store: Store, issue: str, workflow_app: WorkflowApp | None = None) -> None:
        super().__init__()
        self._store = store
        self._issue = issue
        self._workflow_app = workflow_app
        self._projection: HubProjection | None = None
        self._track_rows: list[tuple[HubPrBlock, HubTrackRow]] = []
        self._skip_resume_reload = True

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        with Vertical(id="screen-fill"):
            yield ContextHeader(id="context-header")
            with VerticalScroll(id="hub-scroll"):
                yield Markdown("", id="hub-doc")
            with Vertical(id="track-panel"):
                yield ListView(id="track-list")
            yield Static("", id="dock-note")
            yield DecisionPanel(
                id="decision-panel",
                approve_label="Approve ticket",
                reject_label="Reject ticket",
            )

    def on_mount(self) -> None:
        self._reload_from_disk()
        if self._track_rows:
            self.query_one("#track-list", ListView).focus()

    def on_screen_resume(self) -> None:
        if self._skip_resume_reload:
            self._skip_resume_reload = False
            return
        self._reload_from_disk()

    def _reload_from_disk(self) -> None:
        self._projection = project_review_hub(self._store, self._issue)
        self._track_rows = flatten_track_rows(self._projection)
        session = self._session()
        self._render_context_header(session)
        self.query_one("#hub-doc", Markdown).update(format_hub_document(self._projection))
        self._render_track_list()
        self._sync_ticket_dock(self._projection)

    def _render_context_header(self, session: dict[str, Any]) -> None:
        projection = self._projection
        issue_data = read_json(self._store.issue_dir(self._issue) / "issue.json") or {}
        title = str(issue_data.get("summary") or projection.issue_title or self._issue)
        view = ContextHeaderView(
            issue_key=self._issue,
            title=title,
            stage="code-review-hub",
            outcome=str(session.get("outcome") or "") or None,
            active_pr=str(session.get("active_pr")) if session.get("active_pr") else None,
            full_sha=session.get("active_sha"),
            recommendation="Select a track to open it; press P to compose GitHub publication for the selected PR.",
        )
        self.query_one("#context-header", ContextHeader).set_view(view)

    def _render_track_list(self) -> None:
        list_view = self.query_one("#track-list", ListView)
        labels = [format_track_list_label(block, track) for block, track in self._track_rows]
        self.query_one("#track-panel").display = bool(labels)
        children = list(list_view.children)
        if len(children) != len(labels):
            list_view.clear()
            if labels:
                list_view.mount(*[ListItem(Markdown(text)) for text in labels])
                list_view.index = 0
        else:
            for child, text in zip(children, labels, strict=True):
                child.query_one(Markdown).update(text)

    def _sync_ticket_dock(self, projection: HubProjection) -> None:
        panel = self.query_one("#decision-panel", DecisionPanel)
        note = self.query_one("#dock-note", Static)
        ticket = project_ticket_disposition(self._store, self._issue)
        panel.display = True
        panel.set_decision_enabled(ticket.dock_enabled)
        if not ticket.dock_enabled:
            panel.set_approve_enabled(False)
            note.update(projection.ticket_dock_reason)
            return
        panel.query_one("#reject-btn", Button).disabled = not ticket.reject_enabled
        panel.set_approve_enabled(ticket.approve_enabled)
        note.update(ticket.approve_reason if not ticket.approve_enabled else "")

    def _selected_block(self) -> HubPrBlock | None:
        list_view = self.query_one("#track-list", ListView)
        index = list_view.index
        if index is None or index < 0 or index >= len(self._track_rows):
            return None
        return self._track_rows[index][0]

    def action_open_publication(self) -> None:
        block = self._selected_block()
        if block is None:
            return
        workflow_app = getattr(self.app, "workflow_app", None) or self._workflow_app
        self.app.push_screen(
            PublicationComposeScreen(
                self._store,
                self._issue,
                workflow_app,
                ref=block.ref,
                owner=block.owner,
                repo=block.repo,
                number=block.number,
                sha=block.stored_sha,
            )
        )

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def on_decision_panel_approved(self, _event: DecisionPanel.Approved) -> None:
        workflow_app = getattr(self.app, "workflow_app", None) or self._workflow_app
        if workflow_app is None:
            return
        record_ticket_disposition(workflow_app, self._issue, choice="approve", revise=self._revise())
        panel = self.query_one("#decision-panel", DecisionPanel)
        panel.set_decision_enabled(False)
        status = workflow_app.config.approved_status
        panel.restore_model(
            DecisionPanelModel(
                state=DecisionPanelState.TRANSITION_CONFIRM,
                saved=True,
                comment_outcome="declined",
                transition_preview=f"Transition {self._issue} to {status}.\n",
            )
        )

    def on_decision_panel_draft_saved(self, event: DecisionPanel.DraftSaved) -> None:
        workflow_app = getattr(self.app, "workflow_app", None) or self._workflow_app
        if workflow_app is None:
            return
        path = self._return_draft_path()
        path.write_text(event.body, encoding="utf-8")
        record_ticket_disposition(workflow_app, self._issue, choice="return", revise=self._revise())
        panel = self.query_one("#decision-panel", DecisionPanel)
        panel.set_decision_enabled(False)
        self._sync_ticket_transition_preview(panel, workflow_app.config.in_progress_status)

    def on_decision_panel_reject_chosen(self, _event: DecisionPanel.RejectChosen) -> None:
        panel = self.query_one("#decision-panel", DecisionPanel)
        workflow_app = getattr(self.app, "workflow_app", None) or self._workflow_app
        if workflow_app is None:
            return
        panel.begin_reject_edit(self._ticket_reject_prefill(workflow_app))

    def on_decision_panel_comment_authorized(self, event: DecisionPanel.CommentAuthorized) -> None:
        if not event.post:
            return
        workflow_app = getattr(self.app, "workflow_app", None) or self._workflow_app
        if workflow_app is None:
            return
        panel = self.query_one("#decision-panel", DecisionPanel)
        path = self._return_draft_path()
        if not path.exists():
            return
        result = jira_comment(workflow_app, self._issue, body_file=path, body=None, yes=True)
        if result.outcome == Outcome.BLOCKED:
            panel.record_comment_failure(result.summary)

    def on_decision_panel_transition_authorized(self, event: DecisionPanel.TransitionAuthorized) -> None:
        workflow_app = getattr(self.app, "workflow_app", None) or self._workflow_app
        if workflow_app is None:
            return
        panel = self.query_one("#decision-panel", DecisionPanel)
        if not event.move:
            return
        status = self._transition_status(workflow_app)
        result = jira_transition(workflow_app, self._issue, status, yes=True)
        if result.outcome == Outcome.BLOCKED:
            panel.record_transition_failure(result.summary)
            return
        self.app.pop_screen()

    def _ticket_reject_prefill(self, workflow_app: WorkflowApp) -> str:
        path = self._return_draft_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        ticket = project_ticket_disposition(self._store, self._issue)
        return ticket_return_draft(
            issue=self._issue,
            in_progress_status=workflow_app.config.in_progress_status,
            blockers=ticket.blockers,
        )

    def _return_draft_path(self) -> Path:
        return self._store.issue_dir(self._issue) / "return-comment.md"

    def _sync_ticket_transition_preview(self, panel: DecisionPanel, status: str) -> None:
        draft = self._return_draft_path()
        text = draft.read_text(encoding="utf-8") if draft.exists() else ""
        panel.set_comment_preview(self._comment_preview(text))
        panel.set_transition_preview(f"Transition {self._issue} to {status}.\n")
        issue_data = read_json(self._store.issue_dir(self._issue) / "issue.json") or {}
        panel.set_current_status(str(issue_data.get("status") or ""))

    def _comment_preview(self, text: str) -> str:
        body = format_jira_body_markdown(text).strip() or text.rstrip()
        return f"Comment on {self._issue}.\n\n{body}\n"

    def _transition_status(self, workflow_app: WorkflowApp) -> str:
        decision = get_decision(self._session(), "ticket_disposition") or {}
        if decision.get("choice") == "approve":
            return workflow_app.config.approved_status
        return workflow_app.config.in_progress_status

    def _revise(self) -> bool:
        return bool(getattr(self.app, "revise", False))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None or event.list_view.id != "track-list":
            return
        children = list(event.list_view.children)
        try:
            index = children.index(event.item)
        except ValueError:
            return
        if index < 0 or index >= len(self._track_rows):
            return
        block, track = self._track_rows[index]
        if not track.open_enabled:
            return
        workflow_app = getattr(self.app, "workflow_app", None) or self._workflow_app
        revise = bool(getattr(self.app, "revise", False))
        if track.kind == "automated":
            self.app.push_screen(
                AutomatedPrepareScreen(
                    self._store,
                    self._issue,
                    workflow_app,
                    focus_ref=block.ref,
                    revise=revise,
                )
            )
            return
        if track.kind == "manual":
            self.app.push_screen(
                ManualReviewScreen(
                    self._store,
                    self._issue,
                    workflow_app,
                    ref=block.ref,
                    owner=block.owner,
                    repo=block.repo,
                    number=block.number,
                    sha=block.stored_sha,
                    stale=block.navigation_stale,
                    revise=revise,
                )
            )
            return
        if track.kind == "functional":
            self.app.push_screen(
                TestEnvironmentScreen(
                    self._store,
                    self._issue,
                    workflow_app,
                    ref=block.ref,
                    owner=block.owner,
                    repo=block.repo,
                    number=block.number,
                    sha=block.stored_sha,
                    revise=revise,
                )
            )

    def _session(self) -> dict[str, Any]:
        return read_json(self._store.issue_dir(self._issue) / "session.json") or {}
