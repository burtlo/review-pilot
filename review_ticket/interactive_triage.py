"""Interactive terminal triage for automated review findings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from review_ticket.findings import apply_human_decisions, build_review_payload
from review_ticket.models import WorkflowError
from review_ticket.policy import suggest_event as policy_suggest_event
from review_ticket.storage import read_json
from review_ticket.util import require_issue_key
from review_ticket.workflow import App, _diff_index, _require_identity, _require_review_session, _review_dir


@dataclass
class FindingState:
    finding_id: str
    title: str
    automated_must_fix: bool
    path: str | None
    line: int | None
    side: str
    default_explanation: str
    decision: str | None = None
    must_fix: bool | None = None
    explanation: str | None = None

    @property
    def effective_must_fix(self) -> bool:
        if self.must_fix is not None:
            return self.must_fix
        return self.automated_must_fix

    @property
    def effective_explanation(self) -> str:
        if self.explanation is not None:
            return self.explanation
        return self.default_explanation


TRACK_DISPOSITIONS = frozenset({"APPROVE", "COMMENT", "REQUEST_CHANGES"})


def decision_display_label(decision: str | None) -> str:
    if decision == "accept":
        return "include"
    if decision == "reject":
        return "exclude"
    return "undecided"


@dataclass
class TriageState:
    findings: list[FindingState] = field(default_factory=list)
    summary: str = ""
    event: str | None = None
    disposition: str | None = None
    blocker_confirmed: bool = False
    rejected_review: bool = False

    def all_decided(self) -> bool:
        if self.rejected_review:
            return True
        return all(item.decision in {"accept", "reject"} for item in self.findings)


def _triage_state_from_review_files(
    document: dict[str, Any],
    existing: dict[str, Any],
) -> TriageState:
    prior = (existing.get("findings") or {}) if isinstance(existing.get("findings"), dict) else {}
    rows: list[FindingState] = []
    for finding in document.get("findings") or []:
        fid = finding["id"]
        saved = prior.get(fid) if isinstance(prior.get(fid), dict) else {}
        decision = saved.get("decision")
        if decision not in {"accept", "reject"}:
            decision = None
        must_fix = saved.get("must_fix") if "must_fix" in saved else None
        explanation = saved.get("explanation")
        if explanation is not None:
            explanation = str(explanation)
        rows.append(
            FindingState(
                finding_id=fid,
                title=str(finding.get("title") or fid),
                automated_must_fix=bool(finding.get("must_fix")),
                path=finding.get("path"),
                line=finding.get("line") if isinstance(finding.get("line"), int) else None,
                side=str(finding.get("side") or "RIGHT"),
                default_explanation=str(finding.get("explanation") or ""),
                decision=decision,
                must_fix=bool(must_fix) if must_fix is not None else None,
                explanation=explanation,
            )
        )
    disposition = existing.get("disposition")
    if disposition not in TRACK_DISPOSITIONS:
        disposition = None
    blocker_confirmed = bool(existing.get("blocker_confirmed")) and disposition == "REQUEST_CHANGES"
    return TriageState(
        findings=rows,
        summary=str(existing.get("summary") or document.get("summary") or ""),
        event=existing.get("event"),
        disposition=disposition,
        blocker_confirmed=blocker_confirmed,
        rejected_review=bool(existing.get("rejected_review")),
    )


def load_triage_state(
    app: App,
    issue: str,
    *,
    identity: tuple[str, str, int] | None = None,
    sha: str | None = None,
) -> tuple[TriageState, dict[str, Any], str, tuple[str, str, int]]:
    issue = require_issue_key(issue)
    if identity is None or sha is None:
        session = _require_review_session(app, issue)
        resolved_identity = _require_identity(session)
        resolved_sha = session["active_sha"]
    else:
        resolved_identity = identity
        resolved_sha = sha
    review_dir = _review_dir(app, issue, resolved_identity, resolved_sha)
    document = read_json(review_dir / "findings.json")
    if not document:
        raise WorkflowError("No automated findings are stored. Run run-review or import-review first.")
    existing = read_json(review_dir / "human-review.json") or {}
    state = _triage_state_from_review_files(document, existing)
    return state, document, resolved_sha, resolved_identity


def publish_preview_counts(
    machine_findings: list[dict[str, Any]],
    human: dict[str, Any],
    diff_index: set[tuple[str, int, str]],
) -> tuple[int, int]:
    if human.get("rejected_review"):
        return 0, 0
    merged = apply_human_decisions(machine_findings, human)
    inline = 0
    summary_only = 0
    for finding in merged:
        if finding.get("decision") == "reject":
            continue
        path = finding.get("path")
        line = finding.get("line")
        side = finding.get("side") or "RIGHT"
        on_diff = bool(path) and isinstance(line, int) and (path, line, side) in diff_index
        if on_diff:
            inline += 1
        else:
            summary_only += 1
    return inline, summary_only


def human_document_from_state(state: TriageState) -> dict[str, Any]:
    if state.rejected_review:
        return {
            "rejected_review": True,
            "findings": {},
            "added": [],
            "event": state.event,
            "summary": state.summary,
        }
    decisions: dict[str, dict[str, Any]] = {}
    for item in state.findings:
        if item.decision not in {"accept", "reject"}:
            raise WorkflowError(
                f"Finding {item.finding_id} has no accept/reject decision. "
                "Decide each finding before saving."
            )
        entry: dict[str, Any] = {"decision": item.decision, "must_fix": item.effective_must_fix}
        if item.explanation is not None and item.explanation != item.default_explanation:
            entry["explanation"] = item.explanation
        decisions[item.finding_id] = entry
    document: dict[str, Any] = {
        "rejected_review": False,
        "findings": decisions,
        "added": [],
        "event": state.event,
        "summary": state.summary,
    }
    if state.disposition in TRACK_DISPOSITIONS:
        document["disposition"] = state.disposition
    if state.disposition == "REQUEST_CHANGES" and state.blocker_confirmed:
        document["blocker_confirmed"] = True
    return document


def _format_counts(inline: int, summary_only: int) -> str:
    return f"publish preview: {inline} inline comment(s), {summary_only} summary-only finding(s)"


def _render(
    state: TriageState,
    *,
    inline: int,
    summary_only: int,
    write: Callable[[str], None],
) -> None:
    write("\n")
    write("=== Review triage ===\n")
    write(_format_counts(inline, summary_only) + "\n")
    if state.rejected_review:
        write("automated review: REJECTED (nothing will publish)\n")
    write(f"summary: {state.summary or '(empty)'}\n")
    write(f"event: {state.event or '(auto)'}\n")
    write("\n")
    for index, item in enumerate(state.findings, start=1):
        if item.decision == "accept":
            mark = "accept"
        elif item.decision == "reject":
            mark = "reject"
        else:
            mark = "undecided"
        loc = ""
        if item.path:
            loc = f" @ {item.path}"
            if item.line is not None:
                loc += f":{item.line}"
        must = "must-fix" if item.effective_must_fix else "suggestion"
        write(f"  {index}. [{mark}] {item.finding_id} {item.title} ({must}){loc}\n")
    write("\n")
    write(
        "Commands: <n> select | t toggle | f must-fix | e explanation | "
        "s summary | v event | x reject-automated | w save | q quit\n"
    )


def _prompt(app: App, message: str) -> str:
    if app.input_fn is not None:
        return app.input_fn(message)
    app.write(message)
    return input()


def select_finding(state: TriageState, token: str) -> FindingState:
    if token.isdigit():
        index = int(token)
        if 1 <= index <= len(state.findings):
            return state.findings[index - 1]
    for item in state.findings:
        if item.finding_id == token:
            return item
    raise WorkflowError(f"Unknown finding {token!r}. Use a list number or finding id.")


def _require_open_review(state: TriageState) -> None:
    if state.rejected_review:
        raise WorkflowError("Automated review is rejected. Save with w or quit with q.")


def accept_finding(state: TriageState, token: str) -> None:
    _require_open_review(state)
    select_finding(state, token).decision = "accept"


def reject_finding(state: TriageState, token: str) -> None:
    _require_open_review(state)
    select_finding(state, token).decision = "reject"


def toggle_must_fix(state: TriageState, token: str) -> None:
    _require_open_review(state)
    target = select_finding(state, token)
    target.must_fix = not target.effective_must_fix


def set_finding_explanation(state: TriageState, token: str, explanation: str) -> None:
    _require_open_review(state)
    target = select_finding(state, token)
    if explanation.strip():
        target.explanation = explanation.rstrip("\n")


def set_summary(state: TriageState, summary: str) -> None:
    state.summary = summary.strip()


def set_event(state: TriageState, event: str | None) -> None:
    if event is None or not str(event).strip():
        state.event = None
        return
    text = str(event).strip().upper()
    if text in TRACK_DISPOSITIONS:
        state.event = text
        return
    raise WorkflowError("event must be COMMENT, APPROVE, or REQUEST_CHANGES.")


def set_track_disposition(state: TriageState, disposition: str | None) -> None:
    if disposition is None or not str(disposition).strip():
        state.disposition = None
        state.blocker_confirmed = False
        return
    text = str(disposition).strip().upper()
    if text not in TRACK_DISPOSITIONS:
        raise WorkflowError("disposition must be APPROVE, COMMENT, or REQUEST_CHANGES.")
    state.disposition = text
    if text != "REQUEST_CHANGES":
        state.blocker_confirmed = False


def confirm_blocker(state: TriageState) -> None:
    if state.disposition != "REQUEST_CHANGES":
        raise WorkflowError("Confirm a blocker only after choosing Request Changes disposition.")
    state.blocker_confirmed = True


def reject_automated_review(state: TriageState) -> None:
    state.rejected_review = True
    state.findings = []


def triage_document_if_ready(state: TriageState) -> dict[str, Any]:
    if not state.all_decided():
        raise WorkflowError(
            "Decide every finding (accept or reject) before saving, or reject the automated review."
        )
    return human_document_from_state(state)


def preview_counts_from_state(
    state: TriageState,
    document: dict[str, Any],
    diff_index: set[tuple[str, int, str]],
) -> tuple[int, int]:
    if state.rejected_review:
        return 0, 0
    machine_by_id = {str(item["id"]): item for item in document.get("findings") or []}
    inline = 0
    summary_only = 0
    for item in state.findings:
        if item.decision != "accept":
            continue
        finding = machine_by_id.get(item.finding_id, {})
        path = finding.get("path")
        line = finding.get("line")
        side = finding.get("side") or "RIGHT"
        on_diff = bool(path) and isinstance(line, int) and (path, line, side) in diff_index
        if on_diff:
            inline += 1
        else:
            summary_only += 1
    return inline, summary_only


def process_triage_command(
    state: TriageState,
    line: str,
    *,
    document: dict[str, Any],
    diff_index: set[tuple[str, int, str]],
    prompt: Callable[[str], str],
    write: Callable[[str], None],
) -> str | None:
    """Run one triage command. Returns human dict on save, None to continue or quit."""

    stripped = line.strip()
    if not stripped:
        return None
    parts = stripped.split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    if cmd == "q":
        return "quit"
    if cmd == "w":
        return triage_document_if_ready(state)
    if cmd == "x":
        reject_automated_review(state)
        return None
    if state.rejected_review and cmd not in {"w", "q", "s", "v"}:
        _require_open_review(state)

    if cmd == "s":
        set_summary(state, prompt("summary: "))
        return None
    if cmd == "v":
        text = prompt("event (COMMENT, APPROVE, REQUEST_CHANGES, or blank for auto): ")
        set_event(state, text if text.strip() else None)
        return None

    if cmd in {"t", "f", "e"}:
        if not arg:
            raise WorkflowError(f"Command {cmd} needs a finding number or id.")
        if cmd == "t":
            target = select_finding(state, arg)
            if target.decision == "accept":
                reject_finding(state, arg)
            elif target.decision == "reject":
                accept_finding(state, arg)
            else:
                accept_finding(state, arg)
            return None
        if cmd == "f":
            toggle_must_fix(state, arg)
            return None
        target = select_finding(state, arg)
        write(f"current explanation for {target.finding_id}:\n{target.effective_explanation}\n")
        set_finding_explanation(state, arg, prompt("new explanation (blank keeps current): "))
        return None

    if cmd.isdigit():
        item = select_finding(state, cmd)
        write(f"selected {item.finding_id}: {item.title}\n")
        write("  subcommands: t <n> toggle | f <n> must-fix | e <n> explanation\n")
        return None

    raise WorkflowError(f"Unknown command {cmd!r}.")


def proposed_payload_from_human(
    app: App,
    issue: str,
    human: dict[str, Any],
    document: dict[str, Any],
    sha: str,
    identity: tuple[str, str, int],
) -> dict[str, Any]:
    merged = apply_human_decisions(document.get("findings") or [], human)
    event = human.get("event") or policy_suggest_event(merged)
    summary = human.get("summary") or document.get("summary") or "Peer review."
    return build_review_payload(
        sha=sha,
        event=event,
        summary=summary,
        findings=merged,
        diff_index=_diff_index(app, issue, identity, sha),
    )
