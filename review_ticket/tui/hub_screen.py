"""PR review hub — workspace after readiness (§7)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Markdown, Static

from review_ticket.hub_projection import HubPrBlock, HubProjection, HubTrackRow, project_review_hub
from review_ticket.tui.compose_screen import GitHubComposeScreen
from review_ticket.tui.environment_screen import EnvironmentScreen
from review_ticket.tui.functional_testing_screen import FunctionalTestingScreen
from review_ticket.tui.manual_review_screen import ManualCodeReviewScreen
from review_ticket.tui.prepare_screen import AutomatedReviewPrepareScreen
from review_ticket.status_projection import project_review_status, snapshot_is_historical
from review_ticket.models import AuthorizationDenied, Outcome, WorkflowError
from review_ticket.reports import ticket_disposition_return_draft
from review_ticket.storage import read_json
from review_ticket.ticket_disposition import evaluate_ticket_disposition
from review_ticket.tui.shared_chrome import (
    ApproveRequested,
    CommentAuthorized,
    CommentDeclined,
    ContextHeader,
    DecisionPanel,
    DraftSaved,
    Emphasis,
    PanelDismissed,
    PanelPhase,
    RejectStarted,
    ReviewContext,
    TransitionAuthorized,
    TransitionDeclined,
)
from review_ticket.util import short_sha
from review_ticket.workflow import get_decision, jira_comment, jira_transition, record_disposition

COMMENT_DECLINED = "comment-declined"
TRANSITION_DECLINED = "transition-declined"

if TYPE_CHECKING:
    from review_ticket.storage import Store
    from review_ticket.workflow import App as WorkflowApp


class TrackPlaceholderScreen(Screen[None]):
    """Temporary host until P8/P10/P11 track screens land."""

    BINDINGS = [("escape", "go_back", "Back")]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        yield Static(self._message, id="placeholder-msg")

    def action_go_back(self) -> None:
        self.app.pop_screen()


def format_hub_pr_markdown(block: HubPrBlock) -> str:
    head = short_sha(block.stored_sha) if block.stored_sha else "—"
    title = block.pr_title or f"PR #{block.number}"
    stale_note = ""
    if block.head_stale:
        stale_note = "\n**HEAD:** stale — refresh required before new work."
    lines = [
        f"### #{block.number} {title}",
        f"**Repo:** `{block.owner}/{block.repo}`  **HEAD:** `{head}`{stale_note}",
        "",
    ]
    for index, track in enumerate(block.tracks, start=1):
        gate = ""
        if not track.open_enabled and track.disabled_reason:
            gate = f" — _{track.disabled_reason}_"
        lines.append(f"{index}. **{track.title}:** {track.status_label}{gate}")
    lines.extend(
        [
            "",
            f"**GitHub review:** {block.github_outcome}",
            f"**Next action:** {block.next_action}",
        ]
    )
    if not block.next_action_enabled and block.next_action_reason:
        lines.append(f"_{block.next_action_reason}_")
    return "\n".join(lines)


def format_hub_document(projection: HubProjection) -> str:
    title = projection.issue
    if projection.issue_title:
        title = f"{projection.issue} — {projection.issue_title}"
    if not projection.session_exists:
        return projection.missing_session_message or "No review session exists yet."
    parts = [f"# Code review hub — {title}", ""]
    for block in projection.pr_blocks:
        parts.append(format_hub_pr_markdown(block))
        parts.append("")
    return "\n".join(parts).rstrip()


def _track_list_label(track: HubTrackRow) -> str:
    suffix = ""
    if not track.open_enabled and track.disabled_reason:
        suffix = f" — {track.disabled_reason}"
    return f"{track.title}: {track.status_label}{suffix}"


class ReviewHubScreen(Screen[None]):
    """Per-PR track summary. Does not write session or generate on mount."""

    BINDINGS = [("escape", "go_back", "Back")]

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
    ReviewHubScreen ContextHeader {
        dock: none;
        height: auto;
    }
    ReviewHubScreen DecisionPanel {
        dock: none;
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
        margin: 0 1;
    }
    ReviewHubScreen #hub-doc {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    ReviewHubScreen #lists {
        height: auto;
        max-height: 35%;
        margin: 0 1 1 1;
        layout: horizontal;
    }
    ReviewHubScreen #pr-list {
        width: 1fr;
        height: auto;
        max-height: 10;
        border: tall $panel;
    }
    ReviewHubScreen #track-list {
        width: 1fr;
        height: auto;
        max-height: 10;
        border: tall $panel;
        margin-left: 1;
    }
    ReviewHubScreen #ticket-prompt {
        height: auto;
        margin: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, store: Store, issue: str, workflow_app: WorkflowApp | None = None) -> None:
        super().__init__()
        self._store = store
        self._issue = issue
        self._workflow_app = workflow_app
        self._projection: HubProjection | None = None
        self._blocks: tuple[HubPrBlock, ...] = ()
        self._track_rows: tuple[HubTrackRow, ...] = ()
        self._skip_resume_reload = True

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        with Vertical(id="screen-fill"):
            yield ContextHeader(
                ReviewContext(issue_key=self._issue, title="", stage="Code review hub", outcome="HUB")
            )
            with VerticalScroll(id="hub-scroll"):
                yield Markdown("", id="hub-doc")
            with Horizontal(id="lists"):
                yield ListView(id="pr-list")
                yield ListView(id="track-list")
            yield Static("", id="ticket-prompt")
            yield Button("Next action", id="hub-next-btn", variant="primary")
            yield DecisionPanel(
                issue_key=self._issue,
                target_status="In Progress",
                prompt="Ticket disposition",
            )

    def on_mount(self) -> None:
        self._reload()
        if self._blocks:
            self.query_one("#pr-list", ListView).focus()

    def on_screen_resume(self) -> None:
        if self._skip_resume_reload:
            self._skip_resume_reload = False
            return
        self._reload()

    def _reload(self) -> None:
        self._projection = project_review_hub(self._store, self._issue)
        self._blocks = self._projection.pr_blocks
        self.query_one("#hub-doc", Markdown).update(format_hub_document(self._projection))
        self._sync_pr_list()
        pr_index = self.query_one("#pr-list", ListView).index
        if pr_index is None or pr_index < 0:
            pr_index = 0
        self._select_pr(pr_index)
        title = self._projection.issue_title or ""
        self.query_one(ContextHeader).update_context(
            ReviewContext(
                issue_key=self._issue,
                title=title,
                stage="Code review hub",
                outcome="HUB",
            )
        )
        ticket = self._projection.ticket
        disposition = evaluate_ticket_disposition(self._store, self._issue)
        self.query_one("#ticket-prompt", Static).update(ticket.disabled_reason)
        self._sync_next_action_button(pr_index)
        panel = self.query_one(DecisionPanel)
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        if workflow_app is not None:
            panel.state.target_status = workflow_app.config.in_progress_status
        panel.set_prompt("Ticket disposition")
        emphasis = Emphasis.APPROVE if ticket.approve_enabled else Emphasis.REJECT
        if panel.state.phase == PanelPhase.DECISION:
            panel.state.default_prefill = self._reject_draft_text(disposition)
            panel.set_emphasis(emphasis if ticket.approve_visible else Emphasis.NONE)
            panel.set_decision_visible(ticket.approve_visible or ticket.reject_visible)
            approve = panel.query_one("#approve-btn", Button)
            reject = panel.query_one("#reject-btn", Button)
            approve.disabled = not ticket.approve_enabled
            reject.disabled = not ticket.reject_enabled

    def _sync_pr_list(self) -> None:
        list_view = self.query_one("#pr-list", ListView)
        labels = [f"#{block.number} {block.repo} `{short_sha(block.stored_sha)}`" for block in self._blocks]
        children = list(list_view.children)
        if len(children) != len(labels):
            list_view.clear()
            if labels:
                list_view.mount(*[ListItem(Static(text)) for text in labels])
                list_view.index = 0
        else:
            for child, text in zip(children, labels, strict=True):
                child.query_one(Static).update(text)

    def _sync_next_action_button(self, pr_index: int) -> None:
        button = self.query_one("#hub-next-btn", Button)
        if pr_index < 0 or pr_index >= len(self._blocks):
            button.display = False
            return
        block = self._blocks[pr_index]
        button.label = block.next_action
        button.disabled = not block.next_action_enabled
        button.display = True

    def _select_pr(self, index: int) -> None:
        if not self._blocks:
            self._track_rows = ()
            self.query_one("#track-list", ListView).clear()
            return
        index = max(0, min(index, len(self._blocks) - 1))
        block = self._blocks[index]
        self._track_rows = block.tracks
        list_view = self.query_one("#track-list", ListView)
        labels = [_track_list_label(track) for track in self._track_rows]
        children = list(list_view.children)
        if len(children) != len(labels):
            list_view.clear()
            if labels:
                list_view.mount(*[ListItem(Static(text)) for text in labels])
                list_view.index = 0
        else:
            for child, text in zip(children, labels, strict=True):
                child.query_one(Static).update(text)
        self._sync_next_action_button(index)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "hub-next-btn":
            return
        pr_index = self.query_one("#pr-list", ListView).index or 0
        if pr_index < 0 or pr_index >= len(self._blocks):
            return
        block = self._blocks[pr_index]
        if not block.next_action_enabled:
            return
        if block.next_action == "Publish GitHub review":
            self._open_publication(block)
            return
        if block.next_action == "Prepare test environment":
            self._open_test_environment(block)
            return
        if block.next_action == "Complete functional testing":
            self._open_functional_testing(block)

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view.id != "pr-list" or event.list_view.index is None:
            return
        self._select_pr(event.list_view.index)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item is None:
            return
        if event.list_view.id == "pr-list":
            children = list(event.list_view.children)
            try:
                index = children.index(event.item)
            except ValueError:
                return
            self._select_pr(index)
            self.query_one("#track-list", ListView).focus()
            return
        if event.list_view.id != "track-list":
            return
        children = list(event.list_view.children)
        try:
            track_index = children.index(event.item)
        except ValueError:
            return
        if track_index < 0 or track_index >= len(self._track_rows):
            return
        pr_index = self.query_one("#pr-list", ListView).index or 0
        if pr_index < 0 or pr_index >= len(self._blocks):
            return
        self._open_track(self._blocks[pr_index], self._track_rows[track_index])

    def _open_track(self, block: HubPrBlock, track: HubTrackRow) -> None:
        if not track.open_enabled:
            return
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        revise = bool(getattr(self.app, "revise", False))
        if track.key == "automated":
            self.app.push_screen(AutomatedReviewPrepareScreen(self._store, self._issue, workflow_app))
            return
        if track.key == "manual":
            status_row = next(
                (item for item in project_review_status(self._store, self._issue).pr_rows if item.ref == block.ref),
                None,
            )
            stale = block.head_stale
            historical = False
            stored_sha = block.stored_sha
            if status_row is not None:
                stored_sha = status_row.stored_sha
                stale = status_row.freshness.stale
                historical = snapshot_is_historical(status_row.freshness, block.stored_sha)
            self.app.push_screen(
                ManualCodeReviewScreen(
                    self._store,
                    workflow_app,
                    issue=self._issue,
                    ref=block.ref,
                    owner=block.owner,
                    repo=block.repo,
                    number=block.number,
                    sha=block.stored_sha,
                    stored_sha=stored_sha,
                    stale=stale,
                    historical=historical,
                    revise=revise,
                )
            )
            return
        if track.key == "publication":
            self._open_publication(block)
            return
        if track.key == "functional":
            self._open_functional_testing(block)
            return
        self.app.push_screen(TrackPlaceholderScreen(track.disabled_reason or "Track is not available yet."))

    def _open_functional_testing(self, block: HubPrBlock) -> None:
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        status_row = next(
            (item for item in project_review_status(self._store, self._issue).pr_rows if item.ref == block.ref),
            None,
        )
        stored_sha = block.stored_sha
        stale = block.head_stale
        historical = False
        if status_row is not None:
            stored_sha = status_row.stored_sha
            stale = status_row.freshness.stale
            historical = snapshot_is_historical(status_row.freshness, block.stored_sha)
        revise = bool(getattr(self.app, "revise", False))
        self.app.push_screen(
            FunctionalTestingScreen(
                self._store,
                workflow_app,
                issue=self._issue,
                ref=block.ref,
                owner=block.owner,
                repo=block.repo,
                number=block.number,
                sha=block.stored_sha,
                stored_sha=stored_sha,
                stale=stale,
                historical=historical,
                revise=revise,
            )
        )

    def _open_test_environment(self, block: HubPrBlock) -> None:
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        status_row = next(
            (item for item in project_review_status(self._store, self._issue).pr_rows if item.ref == block.ref),
            None,
        )
        stored_sha = block.stored_sha
        stale = block.head_stale
        historical = False
        if status_row is not None:
            stored_sha = status_row.stored_sha
            stale = status_row.freshness.stale
            historical = snapshot_is_historical(status_row.freshness, block.stored_sha)
        self.app.push_screen(
            EnvironmentScreen(
                self._store,
                workflow_app,
                issue=self._issue,
                ref=block.ref,
                owner=block.owner,
                repo=block.repo,
                number=block.number,
                sha=block.stored_sha,
                stored_sha=stored_sha,
                stale=stale,
                historical=historical,
            )
        )

    def _open_publication(self, block: HubPrBlock) -> None:
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        status_row = next(
            (item for item in project_review_status(self._store, self._issue).pr_rows if item.ref == block.ref),
            None,
        )
        stored_sha = block.stored_sha
        stale = block.head_stale
        historical = False
        if status_row is not None:
            stored_sha = status_row.freshness.current_sha or status_row.stored_sha
            stale = status_row.freshness.stale
            historical = snapshot_is_historical(status_row.freshness, block.stored_sha)
        self.app.push_screen(
            GitHubComposeScreen(
                self._store,
                workflow_app,
                issue=self._issue,
                ref=block.ref,
                owner=block.owner,
                repo=block.repo,
                number=block.number,
                sha=block.stored_sha,
                stored_sha=stored_sha,
                stale=stale,
                historical=historical,
            )
        )

    def action_go_back(self) -> None:
        if self.app.screen is self:
            self.app.pop_screen()

    def on_approve_requested(self, message: ApproveRequested) -> None:
        message.stop()
        panel = self.query_one(DecisionPanel)
        if panel.query_one("#approve-btn", Button).disabled:
            return
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        if workflow_app is None:
            return
        try:
            record_disposition(
                workflow_app,
                self._issue,
                choice="approve",
                notes="",
                override=False,
                revise=self._revise(),
            )
        except WorkflowError as exc:
            panel.set_prompt(str(exc))
            return
        panel.state.target_status = workflow_app.config.approved_status
        panel.begin_approved_transition()

    def on_reject_started(self, message: RejectStarted) -> None:
        message.stop()

    def on_draft_saved(self, message: DraftSaved) -> None:
        message.stop()
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        if workflow_app is None:
            return
        try:
            record_disposition(
                workflow_app,
                self._issue,
                choice="return",
                notes="",
                override=False,
                revise=self._revise(),
                draft_body=message.text,
            )
        except WorkflowError as exc:
            panel = self.query_one(DecisionPanel)
            panel.record_comment_failure(str(exc))
            return

    def on_comment_authorized(self, message: CommentAuthorized) -> None:
        message.stop()
        panel = self.query_one(DecisionPanel)
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        if workflow_app is None:
            return
        path = self._return_draft_path()
        if not path.exists():
            panel.record_comment_failure("The saved draft is missing.")
            return
        try:
            result = jira_comment(
                workflow_app,
                self._issue,
                body_file=path,
                body=None,
                yes=True,
            )
        except (WorkflowError, AuthorizationDenied) as exc:
            panel.record_comment_failure(str(exc))
            return
        if result.outcome == Outcome.BLOCKED:
            panel.record_comment_failure(result.summary)
            return
        self._clear_flag(COMMENT_DECLINED)
        panel.record_comment_success()

    def on_comment_declined(self, message: CommentDeclined) -> None:
        message.stop()
        self._set_flag(COMMENT_DECLINED)

    def on_transition_authorized(self, message: TransitionAuthorized) -> None:
        message.stop()
        panel = self.query_one(DecisionPanel)
        workflow_app = self._workflow_app or getattr(self.app, "workflow_app", None)
        if workflow_app is None:
            return
        try:
            result = jira_transition(workflow_app, self._issue, message.status, yes=True)
        except (WorkflowError, AuthorizationDenied) as exc:
            panel.record_transition_failure(str(exc))
            return
        if result.outcome == Outcome.BLOCKED:
            panel.record_transition_failure(result.summary)
            return
        self._clear_flag(TRANSITION_DECLINED)
        panel.record_transition_success()

    def on_transition_declined(self, message: TransitionDeclined) -> None:
        message.stop()
        self._set_flag(TRANSITION_DECLINED)

    def on_panel_dismissed(self, message: PanelDismissed) -> None:
        message.stop()
        self.action_go_back()

    def _revise(self) -> bool:
        return bool(getattr(self.app, "revise", False))

    def _reject_draft_text(self, disposition: Any) -> str:
        path = self._return_draft_path()
        if path.exists():
            saved = path.read_text(encoding="utf-8")
            if saved.strip():
                return saved
        if disposition.return_attention:
            return ticket_disposition_return_draft(
                issue=self._issue,
                attention=disposition.return_attention,
            )
        return ticket_disposition_return_draft(issue=self._issue, attention=())

    def _return_draft_path(self) -> Path:
        return self._store.issue_dir(self._issue) / "return-comment.md"

    def _session(self) -> dict[str, Any]:
        return read_json(self._store.issue_dir(self._issue) / "session.json") or {}

    def _disposition_decision(self) -> dict[str, Any] | None:
        return get_decision(self._session(), "disposition")

    def _set_flag(self, flag: str) -> None:
        session = self._session()
        decision = self._disposition_decision()
        if decision is None:
            return
        decision[flag] = True
        self._store.save_session(session)

    def _clear_flag(self, flag: str) -> None:
        session = self._session()
        decision = self._disposition_decision()
        if decision is None or flag not in decision:
            return
        decision.pop(flag, None)
        self._store.save_session(session)
