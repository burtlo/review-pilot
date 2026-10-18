"""PR readiness and analyzer disposition gate (spec §6, scenario C)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, ListItem, ListView, Markdown, Static

from review_ticket.models import Outcome
from review_ticket.readiness_projection import ReadinessGateProjection, project_readiness_gate
from review_ticket.reports import readiness_return_draft
from review_ticket.storage import read_json
from review_ticket.textutil import format_jira_body_markdown
from review_ticket.tui.context_header import ContextHeader, ContextHeaderView
from review_ticket.tui.hub_screen import ReviewHubScreen
from review_ticket.tui.decision_panel import (
    DecisionPanel,
    DecisionPanelModel,
    DecisionPanelState,
    PanelRecommendation,
)
from review_ticket.util import fingerprint, sha256_text, short_sha
from review_ticket.workflow import assess, decide_readiness, get_decision, jira_comment, jira_transition, resume

if TYPE_CHECKING:
    from review_ticket.storage import Store
    from review_ticket.workflow import App as WorkflowApp


def should_auto_present_readiness(session: dict[str, Any]) -> bool:
    notes = get_decision(session, "testing_notes")
    if notes is None or notes.get("choice") != "accept":
        return False
    gate = get_decision(session, "pr_readiness")
    if gate is None:
        return True
    return gate.get("choice") == "reject"


def _panel_recommendation(projection: ReadinessGateProjection) -> PanelRecommendation:
    if projection.gate_approvable:
        return PanelRecommendation.APPROVE
    if projection.waiting:
        return PanelRecommendation.NEUTRAL
    return PanelRecommendation.REJECT


def _header_recommendation(projection: ReadinessGateProjection) -> str:
    if projection.waiting:
        return "Refresh — checks still running"
    if projection.gate_approvable:
        return "Approve — readiness gate satisfied"
    return "Reject — findings need attention"


def _row_label(row) -> str:
    return (
        f"**{row.ref}** `{short_sha(row.sha)}`  "
        f"Checks **{row.checks_outcome.value}**  "
        f"Analyzers **{row.analyzer_outcome.value}**"
    )


class ReadinessScreen(Screen[None]):
    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("r", "refresh_gate", "Refresh"),
    ]

    CSS = """
    ReadinessScreen {
        layout: vertical;
        overflow: hidden;
    }
    ReadinessScreen Header {
        dock: top;
        height: auto;
    }
    ReadinessScreen Footer {
        dock: bottom;
        height: auto;
    }
    ReadinessScreen #screen-fill {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        overflow: hidden;
        min-height: 0;
    }
    ReadinessScreen #summary-md {
        height: auto;
        margin: 0 1;
    }
    ReadinessScreen #pr-panel {
        height: auto;
        max-height: 30%;
        margin: 0 1;
        border: tall $panel;
        background: $surface;
    }
    ReadinessScreen #pr-list {
        height: auto;
        max-height: 8;
    }
    ReadinessScreen #detail-scroll {
        height: 1fr;
        min-height: 8;
        margin: 0 1;
        border: tall $panel;
        background: $surface;
    }
    ReadinessScreen #refresh-row {
        height: auto;
        margin: 0 1 0 1;
    }
    ReadinessScreen #refresh-row Button {
        width: 1fr;
    }
    ReadinessScreen #decision-panel {
        height: auto;
        min-height: 0;
    }
    ReadinessScreen #no-pr-md {
        height: 1fr;
        margin: 0 1;
    }
    """

    def __init__(self, store: Store, issue: str, workflow_app: WorkflowApp) -> None:
        super().__init__()
        self._store = store
        self._issue = issue
        self._workflow_app = workflow_app
        self._projection: ReadinessGateProjection | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        with Vertical(id="screen-fill"):
            yield ContextHeader(id="context-header")
            yield Markdown("", id="summary-md")
            with Vertical(id="pr-panel"):
                yield ListView(id="pr-list")
            with VerticalScroll(id="detail-scroll"):
                yield Markdown("", id="detail-md")
            yield Markdown("", id="no-pr-md")
            with Horizontal(id="refresh-row"):
                yield Button("Refresh", id="refresh-btn", variant="primary")
            yield DecisionPanel(id="decision-panel")

    def on_mount(self) -> None:
        self._reload_from_disk()
        self.query_one("#detail-scroll", VerticalScroll).focus()

    def _reload_from_disk(self) -> None:
        self._projection = project_readiness_gate(self._store, self._issue, self._workflow_app.config)
        projection = self._projection
        session = self._session()
        self._render_context_header(session, projection)
        overall = f"**Overall:** {projection.ticket_outcome.value} — {projection.ticket_summary}"
        self.query_one("#summary-md", Markdown).update(overall)
        no_pr = self.query_one("#no-pr-md", Markdown)
        pr_panel = self.query_one("#pr-panel")
        detail_scroll = self.query_one("#detail-scroll")
        if not projection.has_prs:
            pr_panel.display = False
            detail_scroll.display = False
            no_pr.display = True
            no_pr.update(projection.detail_markdown)
        else:
            no_pr.display = False
            pr_panel.display = True
            detail_scroll.display = True
            self._render_pr_list(projection)
            self.query_one("#detail-md", Markdown).update(projection.detail_markdown)
        self._sync_decision_area(projection, session)

    def _render_pr_list(self, projection: ReadinessGateProjection) -> None:
        list_view = self.query_one("#pr-list", ListView)
        labels = [_row_label(row) for row in projection.pr_rows]
        list_view.clear()
        if labels:
            list_view.mount(*[ListItem(Markdown(text)) for text in labels])
            list_view.index = 0

    def _sync_decision_area(self, projection: ReadinessGateProjection, session: dict[str, Any]) -> None:
        refresh_row = self.query_one("#refresh-row", Horizontal)
        panel = self.query_one("#decision-panel", DecisionPanel)
        waiting = projection.waiting
        refresh_row.display = waiting or not projection.has_prs
        panel.display = projection.has_prs and not waiting
        if not panel.display:
            return
        panel.set_recommendation(_panel_recommendation(projection))
        panel.set_approve_enabled(projection.gate_approvable)
        self._sync_authorization_previews(panel)
        decision = get_decision(session, "pr_readiness")
        revise = bool(getattr(self.app, "revise", False))
        if decision is not None and not revise:
            panel.set_decision_enabled(False)
            if decision.get("choice") == "reject":
                self._restore_reject_flow(panel)
        elif decision is not None and revise:
            panel.set_decision_enabled(True)

    def _render_context_header(self, session: dict[str, Any], projection: ReadinessGateProjection) -> None:
        issue_data = read_json(self._store.issue_dir(self._issue) / "issue.json") or {}
        view = ContextHeaderView(
            issue_key=self._issue,
            title=str(issue_data.get("summary") or self._issue),
            stage="pr-readiness",
            outcome=projection.ticket_outcome.value,
            active_pr=str(session.get("active_pr")) if session.get("active_pr") else None,
            full_sha=session.get("active_sha"),
            recommendation=_header_recommendation(projection),
        )
        self.query_one("#context-header", ContextHeader).set_view(view)

    def action_refresh_gate(self) -> None:
        self._run_refresh()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "refresh-btn":
            self._run_refresh()

    def _run_refresh(self) -> None:
        session = self._session()
        step = str(session.get("current_step") or "")
        if step in {"github-readiness", "jira-issue"} or not session.get("last_completed_step"):
            resume(self._workflow_app, self._issue)
        else:
            assess(self._workflow_app, self._issue)
        self._reload_from_disk()

    def on_decision_panel_reject_chosen(self, _event: DecisionPanel.RejectChosen) -> None:
        self.query_one("#pr-panel").display = False
        self.query_one("#detail-scroll").display = True
        panel = self.query_one("#decision-panel", DecisionPanel)
        panel.begin_reject_edit(self._draft_prefill())

    def on_decision_panel_draft_saved(self, event: DecisionPanel.DraftSaved) -> None:
        decide_readiness(
            self._workflow_app,
            self._issue,
            "reject",
            "",
            revise=self._revise(),
            draft_body=event.body,
        )
        panel = self.query_one("#decision-panel", DecisionPanel)
        panel.set_decision_enabled(False)
        self._sync_authorization_previews(panel)

    def on_decision_panel_approved(self, _event: DecisionPanel.Approved) -> None:
        decide_readiness(self._workflow_app, self._issue, "accept", "", revise=self._revise())
        self.app.pop_screen()
        self.app.push_screen(ReviewHubScreen(self._store, self._issue, self._workflow_app))

    def on_decision_panel_comment_authorized(self, event: DecisionPanel.CommentAuthorized) -> None:
        panel = self.query_one("#decision-panel", DecisionPanel)
        if not event.post:
            return
        body_file = self._return_draft_path()
        if not body_file.exists():
            return
        result = jira_comment(
            self._workflow_app,
            self._issue,
            body_file=body_file,
            body=None,
            yes=True,
        )
        if result.outcome == Outcome.BLOCKED:
            panel.record_comment_failure(result.summary)

    def on_decision_panel_transition_authorized(self, event: DecisionPanel.TransitionAuthorized) -> None:
        panel = self.query_one("#decision-panel", DecisionPanel)
        if event.move:
            status = self._in_progress_status()
            result = jira_transition(self._workflow_app, self._issue, status, yes=True)
            if result.outcome == Outcome.BLOCKED:
                panel.record_transition_failure(result.summary)
                return
        self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def _revise(self) -> bool:
        return bool(getattr(self.app, "revise", False))

    def _draft_prefill(self) -> str:
        path = self._return_draft_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        projection = self._projection or project_readiness_gate(
            self._store, self._issue, self._workflow_app.config
        )
        blocks = [
            {
                "ref": item.ref,
                "sha": item.sha,
                "url": item.url,
                "lines": list(item.lines),
                "links": list(item.links),
            }
            for item in projection.attention
        ]
        return readiness_return_draft(
            issue=self._issue,
            in_progress_status=self._workflow_app.config.in_progress_status,
            blocks=blocks,
            notes="",
        )

    def _return_draft_path(self) -> Path:
        return self._store.issue_dir(self._issue) / "return-comment.md"

    def _read_return_draft(self) -> str:
        path = self._return_draft_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        return self._draft_prefill()

    def _sync_authorization_previews(self, panel: DecisionPanel) -> None:
        text = self._read_return_draft()
        panel.set_comment_preview(self._comment_preview(text))
        panel.set_transition_preview(self._transition_preview(self._in_progress_status()))
        issue_data = read_json(self._store.issue_dir(self._issue) / "issue.json") or {}
        session = self._session()
        status_name = str(issue_data.get("status") or session.get("recommendation") or "")
        if status_name:
            panel.set_current_status(status_name)

    def _session(self) -> dict[str, Any]:
        return read_json(self._store.issue_dir(self._issue) / "session.json") or {}

    def _comment_preview(self, text: str) -> str:
        body = format_jira_body_markdown(text).strip() or text.rstrip()
        return f"Comment on {self._issue}.\n\n{body}\n"

    def _transition_preview(self, status: str) -> str:
        session = self._session()
        sha = session.get("active_sha") or ""
        preview = f"Transition {self._issue} to {status}."
        if sha:
            preview += f"\nReview SHA: {sha}"
        return preview + "\n"

    def _in_progress_status(self) -> str:
        return self._workflow_app.config.in_progress_status

    def _comment_action_key(self, text: str) -> str:
        session = self._session()
        sha = session.get("active_sha") or ""
        return fingerprint(
            {"kind": "jira.comment", "issue": self._issue, "sha": sha, "body": sha256_text(text)}
        )

    def _transition_action_key(self, status: str) -> str:
        session = self._session()
        sha = session.get("active_sha") or ""
        return fingerprint({"kind": "jira.transition", "issue": self._issue, "status": status, "sha": sha})

    def _comment_posted(self, text: str) -> bool:
        return self._store.successful_action(self._issue, self._comment_action_key(text)) is not None

    def _transition_done(self, status: str) -> bool:
        return self._store.successful_action(self._issue, self._transition_action_key(status)) is not None

    def _restore_reject_flow(self, panel: DecisionPanel) -> None:
        status = self._in_progress_status()
        if self._transition_done(status):
            self.app.pop_screen()
            return
        draft = self._read_return_draft()
        self.query_one("#pr-panel").display = False
        if self._comment_posted(draft):
            model = DecisionPanelModel(
                state=DecisionPanelState.TRANSITION_CONFIRM,
                draft_text=draft,
                saved=True,
                comment_preview=self._comment_preview(draft),
                transition_preview=self._transition_preview(status),
                comment_outcome="posted",
            )
            panel.restore_model(model)
            return
        model = DecisionPanelModel(
            state=DecisionPanelState.SAVED,
            draft_text=draft,
            saved=True,
            comment_preview=self._comment_preview(draft),
            transition_preview=self._transition_preview(status),
        )
        panel.restore_model(model)
