"""Per-PR review triage screen for a single commit snapshot."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Markdown, Static, TextArea

from review_ticket.interactive_triage import (
    FindingState,
    TriageState,
    accept_finding,
    load_triage_state,
    preview_counts_from_state,
    reject_automated_review,
    reject_finding,
    set_event,
    set_finding_explanation,
    set_summary,
    toggle_must_fix,
    triage_document_if_ready,
)
from review_ticket.config import Config
from review_ticket.textutil import parse_unified_diff
from review_ticket.models import WorkflowError
from review_ticket.runner import ScriptedRunner
from review_ticket.storage import read_json
from review_ticket.util import short_sha
from review_ticket.workflow import App as WorkflowApp
from review_ticket.workflow import save_snapshot_review

if TYPE_CHECKING:
    from review_ticket.storage import Store


class PrReviewScreen(Screen[None]):
    """Triage one snapshot; does not change session active PR or SHA."""

    BINDINGS = [("escape", "close_review", "Close")]

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
        self._revise = revise
        self._identity = (owner, repo, number)
        self._document: dict[str, Any] | None = None
        self._state: TriageState | None = None
        self._diff_index: set[tuple[str, int, str]] = set()
        self._selected_index = 0
        self._has_findings = False
        self._human_on_disk = False
        self._save_refused_after_save = False
        self._narrative = ""

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("", id="pr-header")
        yield Static("", id="stale-banner", classes="stale-banner")
        yield Static("", id="empty-state")
        with Vertical(id="review-body"):
            yield ListView(id="finding-list")
            with VerticalScroll(id="detail-scroll"):
                yield Markdown("", id="narrative")
                yield Static("Selected finding", classes="section-label")
                yield Static("", id="finding-meta")
                yield Static("Explanation", classes="section-label")
                yield TextArea("", id="explanation-edit")
                yield Static("Suggested change", classes="section-label")
                yield Static("", id="suggested-change")
            with Horizontal(id="prompt-row"):
                yield Input(placeholder="Review summary", id="summary-input")
                yield Input(placeholder="Event (COMMENT, APPROVE, REQUEST_CHANGES)", id="event-input")
            yield Static("", id="message")
            with Horizontal(id="action-buttons"):
                yield Button("accept", id="btn-accept", variant="success")
                yield Button("reject", id="btn-reject", variant="error")
                yield Button("must-fix", id="btn-must-fix")
                yield Button("edit summary", id="btn-edit-summary")
                yield Button("edit event", id="btn-edit-event")
                yield Button("reject automated", id="btn-reject-automated", variant="warning")
                yield Button("save", id="btn-save", variant="primary")
                yield Button("close", id="btn-close")
        yield Footer()

    def on_mount(self) -> None:
        self._load_snapshot()
        self._apply_layout_mode()
        if self._has_findings:
            self._refresh_chrome()
            self._mount_findings()
            self._select_index(0)
            if self._state and self._state.findings:
                self.query_one("#finding-list", ListView).focus()

    def _review_dir(self):
        return self._store.commit_dir(self.issue, self.owner, self.repo, self.number, self.sha) / "review"

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

    def _load_snapshot(self) -> None:
        review_dir = self._review_dir()
        findings_path = review_dir / "findings.json"
        self._has_findings = findings_path.exists()
        if not self._has_findings:
            self._narrative = ""
            return
        workflow = self._workflow()
        self._state, self._document, _, _ = load_triage_state(
            workflow,
            self.issue,
            identity=self._identity,
            sha=self.sha,
        )
        self._diff_index = self._load_diff_index()
        report_path = review_dir / "reviewer-report.md"
        if report_path.exists():
            self._narrative = report_path.read_text(encoding="utf-8")
        else:
            self._narrative = ""
        existing = read_json(review_dir / "human-review.json")
        self._human_on_disk = bool(existing)
        self._save_refused_after_save = bool(existing) and not self._revise

    def _apply_layout_mode(self) -> None:
        empty = self.query_one("#empty-state", Static)
        body = self.query_one("#review-body", Vertical)
        banner = self.query_one("#stale-banner", Static)
        header = self.query_one("#pr-header", Static)
        reviewed = short_sha(self.sha) if self.sha else "—"
        stored = short_sha(self.stored_sha) if self.stored_sha else "—"
        inline = summary_only = 0
        if self._has_findings and self._state and self._document:
            inline, summary_only = preview_counts_from_state(self._state, self._document, self._diff_index)
        header.update(
            f"Issue: {self.issue}\n"
            f"PR: {self.owner}/{self.repo}#{self.number}\n"
            f"Reviewed SHA: {reviewed}\n"
            f"publish preview: {inline} inline comment(s), {summary_only} summary-only finding(s)"
        )
        if self.stale:
            banner.update(
                f"Stored SHA: {stored} — this open review is not the stored commit. "
                f"Publish will refuse until run-review is run for the stored SHA."
            )
            banner.display = True
        else:
            banner.update("")
            banner.display = False
        action_bar = self.query_one("#action-buttons", Horizontal)
        if self._has_findings:
            empty.display = False
            body.display = True
            action_bar.display = True
        else:
            ref = f"{self.owner}/{self.repo}#{self.number}"
            empty.update(
                "There is no automated review for this pull request at the stored commit.\n\n"
                "`run-review` runs once per PR (readiness already ran for all tracked PRs). "
                "From a terminal:\n\n"
                f"  review-ticket {self.issue} pr select {ref}\n"
                f"  review-ticket {self.issue} run-review\n\n"
                "Re-open attach and select this PR to triage findings. "
                "Repeat for each PR before `publish-review` (switch with `pr select` each time)."
            )
            empty.display = True
            body.display = False
            action_bar.display = False

    def _finding_label(self, index: int, item: FindingState) -> str:
        if item.decision == "accept":
            mark = "accept"
        elif item.decision == "reject":
            mark = "reject"
        else:
            mark = "undecided"
        must = "must-fix" if item.effective_must_fix else "suggestion"
        return f"{index + 1}. [{mark}] {item.finding_id} {item.title} ({must})"

    def _refresh_finding_list(self) -> None:
        list_view = self.query_one("#finding-list", ListView)
        if not self._state:
            list_view.remove_children()
            return
        if self._state.rejected_review:
            list_view.remove_children()
            return
        children = list(list_view.children)
        if len(children) != len(self._state.findings):
            list_view.remove_children()
            for index, item in enumerate(self._state.findings):
                list_view.mount(
                    ListItem(Label(self._finding_label(index, item)), id=f"finding-{index}")
                )
            return
        for index, (child, item) in enumerate(zip(children, self._state.findings, strict=True)):
            child.query_one(Label).update(self._finding_label(index, item))

    def _mount_findings(self) -> None:
        self._refresh_finding_list()
        if not self._state:
            return
        summary_input = self.query_one("#summary-input", Input)
        event_input = self.query_one("#event-input", Input)
        summary_input.value = self._state.summary or ""
        event_input.value = self._state.event or ""
        self.query_one("#narrative", Markdown).update(self._narrative or "_(No reviewer narrative on disk.)_")
        prompt_row = self.query_one("#prompt-row", Horizontal)
        prompt_row.display = False

    def _machine_finding(self, finding_id: str) -> dict[str, Any]:
        if not self._document:
            return {}
        for row in self._document.get("findings") or []:
            if str(row.get("id")) == finding_id:
                return row
        return {}

    def _select_index(self, index: int) -> None:
        if not self._state or not self._state.findings:
            return
        index = max(0, min(index, len(self._state.findings) - 1))
        self._selected_index = index
        list_view = self.query_one("#finding-list", ListView)
        list_view.index = index
        item = self._state.findings[index]
        machine = self._machine_finding(item.finding_id)
        meta = self.query_one("#finding-meta", Static)
        loc = ""
        if item.path:
            loc = f" @ {item.path}"
            if item.line is not None:
                loc += f":{item.line}"
        meta.update(f"**{item.finding_id}** — {item.title}{loc}")
        explanation = self.query_one("#explanation-edit", TextArea)
        explanation.text = item.effective_explanation
        suggested = str(machine.get("suggested_change") or "").strip()
        self.query_one("#suggested-change", Static).update(suggested or "_(none)_")

    def _refresh_chrome(self) -> None:
        self._apply_layout_mode()
        if self._state and self._state.rejected_review:
            self.query_one("#finding-list", ListView).display = False
            self.query_one("#explanation-edit", TextArea).disabled = True
            self.query_one("#btn-accept", Button).disabled = True
            self.query_one("#btn-reject", Button).disabled = True
            self.query_one("#btn-must-fix", Button).disabled = True
        else:
            self.query_one("#finding-list", ListView).display = True
            self.query_one("#explanation-edit", TextArea).disabled = False
            self.query_one("#btn-accept", Button).disabled = False
            self.query_one("#btn-reject", Button).disabled = False
            self.query_one("#btn-must-fix", Button).disabled = False

    def _selected_finding_id(self) -> str:
        if not self._state or not self._state.findings:
            raise WorkflowError("No finding is selected.")
        return self._state.findings[self._selected_index].finding_id

    def _show_message(self, text: str) -> None:
        self.query_one("#message", Static).update(text)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id != "finding-list" or event.item is None:
            return
        children = list(event.list_view.children)
        try:
            index = children.index(event.item)
        except ValueError:
            return
        self._select_index(index)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != "explanation-edit" or not self._state:
            return
        if self._state.rejected_review:
            return
        token = self._selected_finding_id()
        set_finding_explanation(self._state, token, event.text_area.text)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if button_id == "btn-close":
            self.action_close_review()
            return
        if not self._has_findings or not self._state:
            return
        if button_id == "btn-accept":
            accept_finding(self._state, self._selected_finding_id())
        elif button_id == "btn-reject":
            reject_finding(self._state, self._selected_finding_id())
        elif button_id == "btn-must-fix":
            toggle_must_fix(self._state, self._selected_finding_id())
        elif button_id == "btn-edit-summary":
            row = self.query_one("#prompt-row", Horizontal)
            row.display = True
            self.query_one("#summary-input", Input).focus()
            return
        elif button_id == "btn-edit-event":
            row = self.query_one("#prompt-row", Horizontal)
            row.display = True
            self.query_one("#event-input", Input).focus()
            return
        elif button_id == "btn-reject-automated":
            reject_automated_review(self._state)
        elif button_id == "btn-save":
            self._save_review()
            return
        else:
            return
        self._mount_findings()
        self._select_index(self._selected_index)
        self._refresh_chrome()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self._state:
            return
        try:
            if event.input.id == "summary-input":
                set_summary(self._state, event.value)
                self.query_one("#summary-input", Input).value = self._state.summary
            elif event.input.id == "event-input":
                set_event(self._state, event.value if event.value.strip() else None)
                self.query_one("#event-input", Input).value = self._state.event or ""
        except WorkflowError as exc:
            self._show_message(str(exc))
            return
        self._show_message("")

    def _save_review(self) -> None:
        if self._save_refused_after_save:
            self._show_message("A human review is already recorded. Pass --revise to replace it.")
            return
        if not self._state:
            return
        try:
            human = triage_document_if_ready(self._state)
            save_snapshot_review(
                self._workflow(),
                self.issue,
                human,
                sha=self.sha,
                identity=self._identity,
                revise=self._revise,
            )
        except WorkflowError as exc:
            self._show_message(str(exc))
            return
        self._save_refused_after_save = True
        self._human_on_disk = True
        self._show_message("Human review saved.")

    def action_close_review(self) -> None:
        self.app.pop_screen()
