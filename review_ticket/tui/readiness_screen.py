"""PR readiness and analyzer disposition.

Paints stored reports only. Refresh is the action that calls ``resume``.
Approve records the gate locally and does not post a GitHub review.
Reject uses the shared decision panel.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Markdown, Static

from review_ticket.models import AuthorizationDenied, Outcome, WorkflowError
from review_ticket.policy import evaluate_analyzers, outcome_is_worse
from review_ticket.reports import ReadinessAttention, readiness_return_draft
from review_ticket.storage import read_json
from review_ticket.status_projection import format_pr_freshness, project_pr_freshness
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
from review_ticket.util import fingerprint, parse_pr_ref, sha256_text
from review_ticket.workflow import (
    _no_pr_summary,
    decide_analyzers,
    get_decision,
    jira_comment,
    jira_transition,
    record_readiness_gate,
    resume,
)

if TYPE_CHECKING:
    from review_ticket.storage import Store
    from review_ticket.workflow import App as WorkflowApp

COMMENT_DECLINED = "comment-declined"
TRANSITION_DECLINED = "transition-declined"

_CHECK_LABELS = {
    "READY": "Checks PASS",
    "WAITING": "Checks WAITING",
    "ACTION_REQUIRED": "Checks FAIL",
    "REVIEW_DECISION": "Checks MISSING",
    "BLOCKED": "Checks BLOCKED",
}


@dataclass(frozen=True)
class PrReadinessRow:
    ref: str
    owner: str
    repo: str
    number: int
    sha: str
    checks_outcome: str
    checks_label: str
    analyzer_outcome: str
    analyzer_label: str
    unaddressed: tuple[dict[str, Any], ...]
    check_problems: tuple[str, ...]
    satisfied: bool
    freshness: str


@dataclass(frozen=True)
class ReadinessView:
    overall: str
    overall_label: str
    rows: tuple[PrReadinessRow, ...]
    detail: str
    approve_enabled: bool
    decision_visible: bool
    refresh_visible: bool
    no_pull_request: bool


def _check_problems(checks: list[dict[str, Any]], outcome: str) -> tuple[str, ...]:
    """Blocking check lines. Successful checks are omitted."""

    problems: list[str] = []
    for check in checks:
        if not check.get("required"):
            continue
        bucket = str(check.get("bucket") or "")
        name = str(check.get("name") or "check")
        if bucket in {"fail", "cancel"}:
            problems.append(f"Required check failed: {name}")
        elif bucket == "missing":
            problems.append(f"Required check was not reported: {name}")
        elif bucket == "pending":
            problems.append(f"Required check is still running: {name}")
    if outcome == "ACTION_REQUIRED" and not problems:
        problems.append("Required checks failed.")
    if outcome == "BLOCKED":
        problems.append("Checks are blocked by the environment or tooling.")
    if outcome == "UNKNOWN":
        problems.append("Check evidence is not stored for this pull request.")
    return tuple(problems)


def _checks_label(outcome: str, *, acknowledged: bool) -> str:
    label = _CHECK_LABELS.get(outcome, "Checks UNKNOWN")
    if acknowledged and outcome == "REVIEW_DECISION":
        return f"{label} (acknowledged)"
    return label


def _analyzer_label(outcome: str, findings: list[dict[str, Any]], decision: str | None) -> str:
    unaddressed = [item for item in findings if item.get("attention") == "unaddressed"]
    bugbot = [item for item in unaddressed if item.get("source") == "bugbot"]
    codeql = [item for item in unaddressed if item.get("source") == "codeql"]
    if outcome != "READY" and bugbot:
        return f"Bugbot {len(bugbot)} OPEN"
    if outcome != "READY" and codeql:
        return f"CodeQL {len(codeql)} OPEN"
    if outcome == "READY" and decision == "override":
        return "Analyzers OVERRIDE"
    if outcome == "READY" and decision == "accept_dispositions":
        return "Analyzers ACCEPTED"
    if outcome == "READY":
        return "Analyzers PASS"
    if outcome == "REVIEW_DECISION":
        return "Analyzers REVIEW"
    if outcome == "ACTION_REQUIRED":
        return "Analyzers OPEN"
    if outcome == "BLOCKED":
        return "Analyzers BLOCKED"
    return "Analyzers UNKNOWN"


def _load_findings(commit: Path) -> tuple[list[dict[str, Any]], bool]:
    bugbot_path = commit / "bugbot-findings.json"
    codeql_path = commit / "codeql-findings.json"
    if not bugbot_path.exists() and not codeql_path.exists():
        return [], False
    bugbot = (read_json(bugbot_path) or {}).get("findings") or []
    codeql = (read_json(codeql_path) or {}).get("findings") or []
    return list(bugbot) + list(codeql), True


def _detail_markdown(store: Store, issue: str, rows: tuple[PrReadinessRow, ...]) -> str:
    issue_dir = store.issue_dir(issue)
    parts: list[str] = []
    readiness = issue_dir / "readiness.md"
    analyzers = issue_dir / "analyzers.md"
    if readiness.is_file() or analyzers.is_file():
        if readiness.is_file():
            parts.append(readiness.read_text(encoding="utf-8"))
        if analyzers.is_file():
            parts.append(analyzers.read_text(encoding="utf-8"))
    else:
        for row in rows:
            if not row.sha:
                continue
            commit = store.commit_dir(issue, row.owner, row.repo, row.number, row.sha)
            for name in ("readiness.md", "analyzers.md"):
                path = commit / name
                if path.is_file():
                    parts.append(path.read_text(encoding="utf-8"))
    cleaned = [part.strip() for part in parts if part.strip()]
    if not cleaned:
        return "_No readiness or analyzer report is stored yet._\n"
    return "\n\n".join(cleaned) + "\n"


def _rank_outcome(value: str) -> Outcome:
    if value in {"UNKNOWN", ""}:
        return Outcome.ACTION_REQUIRED
    try:
        return Outcome(value)
    except ValueError:
        return Outcome.ACTION_REQUIRED


def project_readiness(store: Store, issue: str, *, in_progress_status: str) -> ReadinessView:
    """Local projection over ``active_prs``. Does not call the runner."""

    session = read_json(store.issue_dir(issue) / "session.json") or {}
    refs = [str(item) for item in session.get("active_prs") or [] if item]
    if not refs and session.get("active_pr"):
        refs = [str(session["active_pr"])]
    pr_shas: dict[str, str] = session.get("pr_shas") or {}
    freshness_by_ref = {item.ref: item for item in project_pr_freshness(store, issue)}
    rows: list[PrReadinessRow] = []
    for ref in refs:
        owner, repo, number = parse_pr_ref(ref)
        sha = str(pr_shas.get(ref) or "")
        if not sha and ref == session.get("active_pr"):
            sha = str(session.get("active_sha") or "")
        checks: list[dict[str, Any]] = []
        findings: list[dict[str, Any]] = []
        findings_stored = False
        checks_outcome = "UNKNOWN"
        if sha:
            commit = store.commit_dir(issue, owner, repo, number, sha)
            payload = read_json(commit / "github-checks.json") or {}
            if payload:
                checks_outcome = str(payload.get("outcome") or "UNKNOWN")
                checks = list(payload.get("checks") or [])
            findings, findings_stored = _load_findings(commit)
        if any(check.get("required") and str(check.get("bucket") or "") == "pending" for check in checks):
            checks_outcome = "WAITING"
        decision = None
        if sha:
            decision = (get_decision(session, "analyzers", sha) or {}).get("choice")
        if findings_stored:
            analyzer_outcome, _, _ = evaluate_analyzers(
                findings,
                decision if isinstance(decision, str) else None,
                in_progress_status=in_progress_status,
            )
            analyzer_value = analyzer_outcome.value
        else:
            analyzer_value = "UNKNOWN"
        accepted_checks = bool(sha) and (get_decision(session, "missing_checks", sha) or {}).get("choice") == "accept"
        accepted_analyzers = (
            bool(sha) and (get_decision(session, "missing_analyzers", sha) or {}).get("choice") == "accept"
        )
        acknowledged = checks_outcome == "REVIEW_DECISION" and (accepted_checks or accepted_analyzers)
        checks_ok = checks_outcome == "READY" or acknowledged
        analyzer_ok = analyzer_value == "READY"
        problems = list(_check_problems(checks, checks_outcome))
        unaddressed = tuple(item for item in findings if item.get("attention") == "unaddressed")
        if analyzer_value == "UNKNOWN":
            problems.append("Analyzer evidence is not stored for this pull request.")
        elif not analyzer_ok and not unaddressed:
            if analyzer_value == "REVIEW_DECISION":
                problems.append("Analyzer findings still need acknowledgement.")
            elif analyzer_value == "ACTION_REQUIRED":
                problems.append("Analyzer findings still need a developer disposition.")
        rows.append(
            PrReadinessRow(
                ref=ref,
                owner=owner,
                repo=repo,
                number=number,
                sha=sha,
                checks_outcome=checks_outcome,
                checks_label=_checks_label(checks_outcome, acknowledged=acknowledged),
                analyzer_outcome=analyzer_value,
                analyzer_label=_analyzer_label(
                    analyzer_value,
                    findings,
                    decision if isinstance(decision, str) else None,
                ),
                unaddressed=unaddressed,
                check_problems=tuple(problems),
                satisfied=checks_ok and analyzer_ok,
                freshness=format_pr_freshness(freshness_by_ref[ref])
                if ref in freshness_by_ref
                else "current",
            )
        )
    detail = _detail_markdown(store, issue, tuple(rows))
    if not rows:
        return ReadinessView(
            overall="NO_PR",
            overall_label="NO PULL REQUEST",
            rows=(),
            detail=detail,
            approve_enabled=False,
            decision_visible=False,
            refresh_visible=True,
            no_pull_request=True,
        )
    if any(row.checks_outcome == "WAITING" for row in rows):
        overall = "WAITING"
        label = "WAITING"
    elif all(row.satisfied for row in rows):
        overall = "READY"
        label = "READY"
    else:
        worst = Outcome.COMPLETE
        for row in rows:
            if row.satisfied:
                continue
            for value in (row.checks_outcome, row.analyzer_outcome):
                candidate = _rank_outcome(value)
                if outcome_is_worse(candidate, worst):
                    worst = candidate
        if worst == Outcome.BLOCKED:
            overall, label = "BLOCKED", "BLOCKED"
        elif worst == Outcome.REVIEW_DECISION:
            overall, label = "REVIEW_DECISION", "REVIEW DECISION"
        else:
            overall, label = "ACTION_REQUIRED", "ACTION REQUIRED"
    return ReadinessView(
        overall=overall,
        overall_label=label,
        rows=tuple(rows),
        detail=detail,
        approve_enabled=overall == "READY",
        decision_visible=overall not in {"WAITING", "NO_PR"},
        refresh_visible=overall in {"WAITING", "NO_PR", "BLOCKED"},
        no_pull_request=False,
    )


def format_readiness_summary(view: ReadinessView, guidance: str = "") -> str:
    lines = [f"Overall: {view.overall_label}"]
    if guidance:
        lines.append(guidance)
    for row in view.rows:
        sha = row.sha or "SHA unknown"
        lines.append(f"PR #{row.number}  {sha}  {row.freshness}    {row.checks_label}    {row.analyzer_label}")
    return "\n".join(lines)


def pr_select_guidance(workflow_app: WorkflowApp, issue: str) -> str:
    """Same guidance ``step_pull_request`` shows when discovery finds nothing."""

    return (
        _no_pr_summary(workflow_app, issue)
        + "\n"
        + f"review-ticket {issue} pr select owner/repo#number"
    )


class ReadinessScreen(Screen[None]):
    """Ticket gate in front of code review. Paint reads disk. Refresh calls resume."""

    BINDINGS = [("escape", "go_back", "Back")]

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
    ReadinessScreen ContextHeader {
        dock: none;
        height: auto;
    }
    ReadinessScreen DecisionPanel {
        dock: none;
        height: auto;
    }
    ReadinessScreen #screen-fill {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        overflow: hidden;
        min-height: 0;
    }
    ReadinessScreen #summary-collapsed {
        height: auto;
        margin: 0 1;
        text-style: bold;
        display: none;
    }
    ReadinessScreen #readiness-summary {
        height: auto;
        margin: 0 1;
        text-wrap: wrap;
    }
    ReadinessScreen #refresh-btn {
        height: auto;
        margin: 0 1 1 1;
        width: 1fr;
    }
    ReadinessScreen #detail-scroll {
        height: 1fr;
        min-height: 4;
        margin: 0 1 1 1;
        border: tall $panel;
        background: $surface;
    }
    ReadinessScreen #detail-md {
        width: 1fr;
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, store: Store, issue: str, workflow_app: WorkflowApp) -> None:
        super().__init__()
        self._store = store
        self._issue = issue
        self._workflow_app = workflow_app
        self._view = ReadinessView(
            overall="NO_PR",
            overall_label="NO PULL REQUEST",
            rows=(),
            detail="",
            approve_enabled=False,
            decision_visible=False,
            refresh_visible=True,
            no_pull_request=True,
        )

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer(show_command_palette=False)
        with Vertical(id="screen-fill"):
            yield ContextHeader(ReviewContext(issue_key=self._issue, title="", stage="PR readiness"))
            yield Static("PR summary", id="summary-collapsed")
            yield Static("", id="readiness-summary", markup=False)
            yield Button("Refresh", id="refresh-btn", variant="primary")
            with VerticalScroll(id="detail-scroll"):
                yield Markdown("", id="detail-md")
            yield DecisionPanel(
                issue_key=self._issue,
                target_status=self._workflow_app.config.in_progress_status,
                current_status="",
                prefill="",
                prompt="Ticket readiness decision",
            )

    def on_mount(self) -> None:
        self._load()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id != "refresh-btn":
            return
        event.stop()
        self._refresh()

    def action_go_back(self) -> None:
        self._back_to_status()

    def on_approve_requested(self, message: ApproveRequested) -> None:
        message.stop()
        if not self._view.approve_enabled:
            return
        if self.query_one("#approve-btn", Button).disabled:
            return
        record_readiness_gate(self._workflow_app, self._issue, revise=self._revise())
        from review_ticket.tui.hub_screen import ReviewHubScreen

        self.app.switch_screen(ReviewHubScreen(self._store, self._issue, self._workflow_app))

    def on_reject_started(self, message: RejectStarted) -> None:
        message.stop()
        self._collapse_summary()

    def on_draft_saved(self, message: DraftSaved) -> None:
        message.stop()
        shas = tuple(row.sha for row in self._view.rows if row.sha and not row.satisfied)
        revise = self._revise()
        if not shas:
            shas = tuple(row.sha for row in self._view.rows if row.sha)
            revise = True
        decide_analyzers(
            self._workflow_app,
            self._issue,
            "return",
            "",
            revise=revise,
            draft_body=message.text,
            resume_after=False,
            only_shas=shas,
        )
        self._collapse_summary()

    def on_comment_authorized(self, message: CommentAuthorized) -> None:
        message.stop()
        panel = self.query_one(DecisionPanel)
        path = self._return_draft_path()
        if not path.exists():
            panel.record_comment_failure("The saved draft is missing.")
            return
        try:
            result = jira_comment(
                self._workflow_app,
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
        try:
            result = jira_transition(self._workflow_app, self._issue, message.status, yes=True)
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
        self._back_to_status()

    def _refresh(self) -> None:
        """Re-run resume only when the operator asks. Paint stays on disk."""

        resume(self._workflow_app, self._issue)
        self._load()

    def _load(self) -> None:
        status = self._workflow_app.config.in_progress_status
        self._view = project_readiness(self._store, self._issue, in_progress_status=status)
        session = self._session()
        guidance = pr_select_guidance(self._workflow_app, self._issue) if self._view.no_pull_request else ""
        self.query_one("#readiness-summary", Static).update(format_readiness_summary(self._view, guidance))
        self.query_one("#detail-md", Markdown).update(self._view.detail)
        title = str((read_json(self._store.issue_dir(self._issue) / "issue.json") or {}).get("summary") or "")
        pr_number = self._view.rows[0].number if len(self._view.rows) == 1 else None
        sha = self._view.rows[0].sha if len(self._view.rows) == 1 else ""
        recommendation = None
        if self._view.decision_visible:
            recommendation = "Approve" if self._view.approve_enabled else "Reject"
        self.query_one(ContextHeader).update_context(
            ReviewContext(
                issue_key=self._issue,
                title=title,
                stage="PR readiness",
                outcome=self._view.overall_label,
                pr_number=pr_number,
                sha=sha,
                recommendation=recommendation,
            )
        )
        panel = self.query_one(DecisionPanel)
        emphasis = Emphasis.APPROVE if self._view.approve_enabled else Emphasis.REJECT
        if panel.state.phase == PanelPhase.DECISION:
            panel.state.default_prefill = self._draft_text()
            panel.set_emphasis(emphasis)
            if self._view.overall == "WAITING":
                panel.set_prompt("Checks are still running.")
            elif self._view.no_pull_request:
                panel.set_prompt("Select a pull request before deciding.")
            else:
                panel.set_prompt("Ticket readiness decision")
            panel.set_decision_visible(self._view.decision_visible)
            self.query_one("#approve-btn", Button).disabled = not self._view.approve_enabled
            self._expand_summary()
        self.query_one("#refresh-btn", Button).display = self._view.refresh_visible
        self._focus_open()

    def _draft_text(self) -> str:
        if self._return_recorded():
            saved = self._read_return_draft()
            if saved.strip():
                return saved
        attention = [
            ReadinessAttention(
                number=row.number,
                sha=row.sha,
                findings=row.unaddressed,
                problems=row.check_problems if not row.satisfied else (),
            )
            for row in self._view.rows
            if not row.satisfied
        ]
        return readiness_return_draft(issue=self._issue, attention=attention)

    def _revise(self) -> bool:
        return bool(getattr(self.app, "revise", False))

    def _expand_summary(self) -> None:
        self.query_one("#readiness-summary").display = True
        self.query_one("#summary-collapsed").display = False

    def _collapse_summary(self) -> None:
        self.query_one("#readiness-summary").display = False
        self.query_one("#summary-collapsed").display = True
        self.query_one("#refresh-btn").display = False

    def _focus_open(self) -> None:
        panel = self.query_one(DecisionPanel)
        if panel.state.phase != PanelPhase.DECISION:
            return
        if not self._view.decision_visible:
            if self._view.refresh_visible:
                self.query_one("#refresh-btn", Button).focus()
            return
        approve = panel.query_one("#approve-btn", Button)
        reject = panel.query_one("#reject-btn", Button)
        if panel.state.emphasis == Emphasis.REJECT or approve.disabled:
            reject.focus()
        else:
            approve.focus()

    def _back_to_status(self) -> None:
        if self.app.screen is self:
            self.app.pop_screen()

    def _session(self) -> dict[str, Any]:
        return read_json(self._store.issue_dir(self._issue) / "session.json") or {}

    def _return_recorded(self) -> bool:
        session = self._session()
        for row in self._view.rows:
            if not row.sha:
                continue
            decision = get_decision(session, "analyzers", row.sha)
            if decision and decision.get("choice") == "return":
                return True
        return False

    def _return_draft_path(self) -> Path:
        return self._store.issue_dir(self._issue) / "return-comment.md"

    def _read_return_draft(self) -> str:
        path = self._return_draft_path()
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    def _analyzer_returns(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        bucket = (session.get("decisions") or {}).get("analyzers") or {}
        if not isinstance(bucket, dict) or "choice" in bucket:
            return []
        return [
            decision
            for decision in bucket.values()
            if isinstance(decision, dict) and decision.get("choice") == "return"
        ]

    def _set_flag(self, flag: str) -> None:
        session = self._session()
        decisions = self._analyzer_returns(session)
        if not decisions:
            return
        for decision in decisions:
            decision[flag] = True
        self._store.save_session(session)

    def _clear_flag(self, flag: str) -> None:
        session = self._session()
        decisions = self._analyzer_returns(session)
        if not decisions:
            return
        changed = False
        for decision in decisions:
            if flag in decision:
                decision.pop(flag, None)
                changed = True
        if changed:
            self._store.save_session(session)

    def _comment_action_key(self, text: str) -> str:
        session = self._session()
        sha = session.get("active_sha") or ""
        return fingerprint({"kind": "jira.comment", "issue": self._issue, "sha": sha, "body": sha256_text(text)})

    def _transition_action_key(self, status: str) -> str:
        session = self._session()
        sha = session.get("active_sha") or ""
        return fingerprint({"kind": "jira.transition", "issue": self._issue, "status": status, "sha": sha})

    def _comment_posted(self, text: str) -> bool:
        return self._store.successful_action(self._issue, self._comment_action_key(text)) is not None
