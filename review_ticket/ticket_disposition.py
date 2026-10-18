"""Ticket-level disposition gates across all included pull requests (spec §15)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from review_ticket.policy import (
    TRACK_BLOCKED,
    TRACK_COMPLETE_LOCALLY,
    TRACK_IN_PROGRESS,
    TRACK_NOT_STARTED,
    TRACK_PUBLICATION_PENDING,
    TRACK_PUBLISHED,
    TRACK_RETURNED,
    TRACK_STALE,
    _is_request_changes,
    functional_digest_matches,
    functional_testing_passed,
    manual_review_is_complete,
)
from review_ticket.reports import TicketReturnAttention
from review_ticket.storage import Store, read_json
from review_ticket.status_projection import PrStatusRow, PublicationReceipt, project_review_status


def _session_decision(session: dict[str, Any], name: str) -> dict[str, Any] | None:
    decisions = session.get("decisions") or {}
    value = decisions.get(name)
    return value if isinstance(value, dict) and "choice" in value else None


def _publication_event(receipt: PublicationReceipt | None) -> str:
    if not receipt or receipt.status not in {"success", "skipped"}:
        return ""
    return str(receipt.event or "").upper()


def github_receipt_is_approve(receipt: PublicationReceipt | None) -> bool:
    return _publication_event(receipt) == "APPROVE"


@dataclass(frozen=True)
class PrDispositionGap:
    ref: str
    number: int
    sha: str
    detail: str


@dataclass(frozen=True)
class TicketDispositionView:
    testing_notes_accepted: bool
    readiness_passed: bool
    approve_enabled: bool
    reject_enabled: bool
    disabled_reason: str
    gaps: tuple[PrDispositionGap, ...]
    return_attention: tuple[TicketReturnAttention, ...]


_TRACK_LABELS = {
    "automated": "Automated review",
    "manual": "Manual code review",
    "functional": "Functional testing",
    "publication": "GitHub publication",
}


def _gap_for_track(key: str, status: str, event: str) -> str | None:
    label = _TRACK_LABELS[key]
    if status == TRACK_STALE:
        return f"{label} is historical for the current HEAD."
    if key == "publication":
        if status == TRACK_PUBLISHED:
            if event != "APPROVE":
                return "Published GitHub review is not an approval."
            return None
        if status in {TRACK_PUBLICATION_PENDING, TRACK_IN_PROGRESS, TRACK_BLOCKED}:
            return "GitHub review is not published with Approve."
        return f"{label} is not complete ({status.replace('_', ' ')})."
    if key == "automated":
        if status in {TRACK_COMPLETE_LOCALLY, TRACK_PUBLICATION_PENDING, TRACK_PUBLISHED}:
            return None
        return f"{label} is not complete ({status.replace('_', ' ')})."
    if key == "manual":
        if status == TRACK_COMPLETE_LOCALLY:
            return None
        if status == TRACK_RETURNED:
            return "Manual code review requested changes."
        return f"{label} is not complete ({status.replace('_', ' ')})."
    if key == "functional":
        if status == TRACK_COMPLETE_LOCALLY:
            return None
        if status == TRACK_RETURNED:
            return "Functional testing found a defect."
        if status == TRACK_BLOCKED:
            return "Functional testing is blocked by the environment."
        return f"{label} is not complete ({status.replace('_', ' ')})."
    return f"{label} is not ready."


def pr_approve_gaps(row: PrStatusRow) -> tuple[str, ...]:
    if row.freshness.stale:
        return ("HEAD moved — refresh evidence before approving the ticket.",)
    tracks = dict(row.tracks)
    event = _publication_event(row.publication)
    gaps: list[str] = []
    for key in ("automated", "manual", "functional", "publication"):
        status = tracks.get(key, TRACK_NOT_STARTED)
        detail = _gap_for_track(key, status, event)
        if detail:
            gaps.append(detail)
    return tuple(gaps)


def _manual_blocking_lines(manual: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(manual, dict):
        return ()
    if not _is_request_changes(manual.get("disposition")):
        return ()
    lines: list[str] = []
    for finding in manual.get("findings") or []:
        if not isinstance(finding, dict):
            continue
        if not finding.get("blocking"):
            continue
        path = str(finding.get("path") or "unknown file")
        line_no = finding.get("line")
        if isinstance(line_no, int):
            path = f"{path}:{line_no}"
        text = " ".join(str(finding.get("text") or finding.get("body") or "").split())
        if text:
            lines.append(f"{path} — {text}")
        else:
            lines.append(path)
    if not lines:
        lines.append("Changes requested during manual code review.")
    return tuple(lines)


def _functional_blocking_lines(results: dict[str, Any] | None) -> tuple[str, ...]:
    if not isinstance(results, dict):
        return ()
    if results.get("result") != "fail" or results.get("failure_kind") == "environment":
        return ()
    lines: list[str] = []
    steps = str(results.get("steps") or "").strip()
    observed = str(results.get("observed") or results.get("notes") or "").strip()
    if steps:
        lines.append(steps)
    if observed and observed not in lines:
        lines.append(observed)
    if not lines:
        lines.append("Functional testing recorded a reproducible defect.")
    return tuple(lines)


def collect_return_attention(
    store: Store,
    issue: str,
    rows: tuple[PrStatusRow, ...],
) -> tuple[TicketReturnAttention, ...]:
    """Pull requests that belong in a ticket return draft — blockers only."""

    attention: list[TicketReturnAttention] = []
    for row in rows:
        if not row.stored_sha:
            continue
        commit = store.commit_dir(issue, row.owner, row.repo, row.number, row.stored_sha)
        review = commit / "review"
        manual = read_json(review / "manual-review.json")
        results = read_json(commit / "testing" / "test-results.json")
        publication = read_json(review / "publication.json")
        code_lines = list(_manual_blocking_lines(manual))
        func_lines = list(_functional_blocking_lines(results))
        github_line: str | None = None
        tracks = dict(row.tracks)
        if tracks.get("publication") == TRACK_RETURNED or (
            isinstance(publication, dict)
            and publication.get("status") in {"success", "skipped"}
            and _is_request_changes(publication.get("event"))
        ):
            github_line = "Changes requested on GitHub."
        if tracks.get("manual") == TRACK_RETURNED and not code_lines:
            code_lines.append("Changes requested during manual code review.")
        if tracks.get("functional") == TRACK_RETURNED and not func_lines:
            func_lines.append("Functional testing recorded a blocking defect.")
        if not code_lines and not func_lines and not github_line:
            continue
        attention.append(
            TicketReturnAttention(
                number=row.number,
                sha=row.stored_sha,
                code_lines=tuple(code_lines),
                functional_lines=tuple(func_lines),
                github_line=github_line,
            )
        )
    return tuple(attention)


def evaluate_ticket_disposition(store: Store, issue: str) -> TicketDispositionView:
    session_path = store.issue_dir(issue) / "session.json"
    session = read_json(session_path) or {}
    status = project_review_status(store, issue)
    rows = status.pr_rows
    testing_ok = (_session_decision(session, "testing_notes") or {}).get("choice") == "accept"
    readiness_ok = (_session_decision(session, "readiness") or {}).get("choice") == "approve"
    gaps: list[PrDispositionGap] = []
    if not testing_ok:
        gaps.append(
            PrDispositionGap(ref="", number=0, sha="", detail="Testing notes were not accepted.")
        )
    if not readiness_ok:
        gaps.append(
            PrDispositionGap(ref="", number=0, sha="", detail="PR readiness and analyzers gate is not recorded.")
        )
    for row in rows:
        for detail in pr_approve_gaps(row):
            gaps.append(
                PrDispositionGap(
                    ref=row.ref,
                    number=row.number,
                    sha=row.stored_sha,
                    detail=detail,
                )
            )
    return_attention = collect_return_attention(store, issue, rows)
    approve_enabled = testing_ok and readiness_ok and bool(rows) and not gaps
    reject_enabled = testing_ok and readiness_ok and bool(rows) and not approve_enabled
    if not rows:
        reject_enabled = False
    reason = "Ticket disposition is not available yet."
    if not testing_ok:
        reason = "Accept testing notes before deciding the ticket."
    elif not readiness_ok:
        reason = "Complete PR readiness before deciding the ticket."
    elif not rows:
        reason = "No pull requests are in scope for this ticket."
    elif approve_enabled:
        reason = "Every included pull request is ready for ticket approval."
    elif gaps:
        first = next((gap for gap in gaps if gap.ref), gaps[0])
        if first.ref:
            reason = (
                f"Blocking review work remains on {first.ref} ({first.sha[:12]}): {first.detail}"
            )
        else:
            reason = first.detail
    elif return_attention:
        first = return_attention[0]
        reason = f"Blocking review work remains on PR #{first.number} ({first.sha[:12]})."
    return TicketDispositionView(
        testing_notes_accepted=testing_ok,
        readiness_passed=readiness_ok,
        approve_enabled=approve_enabled,
        reject_enabled=reject_enabled,
        disabled_reason=reason,
        gaps=tuple(gaps),
        return_attention=return_attention,
    )


def build_checklist_facts(
    store: Store,
    issue: str,
    session: dict[str, Any],
    owner: str,
    repo: str,
    number: int,
    sha: str,
) -> dict[str, Any]:
    """Facts for :func:`review_ticket.policy.disposition_checklist` on one PR SHA."""

    from review_ticket.findings import apply_human_decisions
    from review_ticket.models import WorkflowError
    from review_ticket.workflow import get_decision

    commit_dir = store.commit_dir(issue, owner, repo, number, sha)
    checks = (read_json(commit_dir / "github-checks.json") or {}).get("outcome") == "READY"
    analyzers = get_decision(session, "analyzers", sha)
    findings = _load_analyzer_findings_from_store(store, issue, owner, repo, number, sha)
    unaddressed = any(item.get("attention") == "unaddressed" for item in findings)
    analyzers_clear = not unaddressed and (
        not any(item.get("attention") in {"dispositioned", "resolved"} for item in findings)
        or (analyzers or {}).get("choice") in {"accept_dispositions", "override"}
    )
    if (analyzers or {}).get("choice") == "override":
        analyzers_clear = True
    human = read_json(commit_dir / "review" / "human-review.json") or {}
    machine = (read_json(commit_dir / "review" / "findings.json") or {}).get("findings") or []
    open_must_fix = False
    if human and not human.get("rejected_review"):
        try:
            merged = apply_human_decisions(machine, human)
        except WorkflowError:
            merged = []
        open_must_fix = any(item.get("must_fix") and item.get("decision") != "reject" for item in merged)
    manual = read_json(commit_dir / "review" / "manual-review.json")
    results = read_json(commit_dir / "testing" / "test-results.json") or {}
    environment = read_json(commit_dir / "testing" / "environment.json") or {}
    testing_passed = functional_testing_passed(results, sha, environment)
    evidence = functional_digest_matches(results, environment, sha) and results.get("result") == "pass"
    publication = read_json(commit_dir / "review" / "publication.json") or {}
    receipt_ok = publication.get("status") in {"success", "skipped"} and str(
        publication.get("event") or ""
    ).upper() == "APPROVE"
    return {
        "sha_matches": True,
        "checks_passed": checks,
        "analyzers_clear": analyzers_clear,
        "open_must_fix": open_must_fix,
        "manual_review": manual_review_is_complete(manual, sha),
        "testing_passed": testing_passed,
        "evidence_matches": bool(evidence),
        "github_approve": receipt_ok,
    }


def _load_analyzer_findings_from_store(
    store: Store,
    issue: str,
    owner: str,
    repo: str,
    number: int,
    sha: str,
) -> list[dict[str, Any]]:
    commit = store.commit_dir(issue, owner, repo, number, sha)
    bugbot = (read_json(commit / "bugbot-findings.json") or {}).get("findings") or []
    codeql = (read_json(commit / "codeql-findings.json") or {}).get("findings") or []
    return list(bugbot) + list(codeql)
