"""Ticket-level disposition predicates and reject drafts (P12)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from review_ticket.reports import return_comment
from review_ticket.status_projection import project_review_status
from review_ticket.storage import Store, read_json
from review_ticket.tracks import (
    TRACK_BLOCKED,
    TRACK_COMPLETE_LOCALLY,
    TRACK_IN_PROGRESS,
    TRACK_NOT_STARTED,
    TRACK_RETURNED,
    TRACK_STALE,
    functional_testing_passed,
    manual_review_complete,
)
from review_ticket.util import require_issue_key, short_sha
from review_ticket.workflow import get_decision


@dataclass(frozen=True)
class PrTicketBlocker:
    ref: str
    sha: str
    url: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class TicketDispositionProjection:
    dock_enabled: bool
    dock_reason: str
    approve_enabled: bool
    approve_reason: str
    reject_enabled: bool
    blockers: tuple[PrTicketBlocker, ...]


def _reject_blocker_lines(commit_dir, sha: str) -> list[str]:
    lines: list[str] = []
    human = read_json(commit_dir / "review" / "human-review.json") or {}
    if human.get("track_disposition") == "REQUEST_CHANGES" and human.get("track_disposition_confirmed"):
        lines.append("Automated review track confirmed Request Changes.")
    manual = read_json(commit_dir / "review" / "manual-review.json") or {}
    if manual.get("disposition") == "REQUEST_CHANGES":
        lines.append("Manual code review recorded Request Changes.")
    results = read_json(commit_dir / "testing" / "test-results.json") or {}
    if results.get("disposition") == "REQUEST_CHANGES":
        lines.append("Functional testing disposition is Request Changes.")
    if results.get("result") == "fail" and results.get("failure_kind") == "implementation":
        lines.append("Functional testing failed with an implementation defect.")
    publication = read_json(commit_dir / "review" / "publication.json") or {}
    if publication.get("status") in {"success", "skipped"} and publication.get("event") == "REQUEST_CHANGES":
        lines.append("GitHub review published Request Changes.")
    return lines


def _github_label(publication: dict[str, Any]) -> str:
    if publication.get("status") not in {"success", "skipped"}:
        return "Not published"
    event = (publication.get("event") or "").strip()
    return event.replace("_", " ") if event else "Not published"


def _pr_ready_for_ticket_approve(commit_dir, sha: str, tracks: dict[str, str]) -> list[str]:
    problems: list[str] = []
    if tracks.get("automated") in {TRACK_NOT_STARTED, TRACK_STALE, TRACK_IN_PROGRESS}:
        problems.append("Automated review track is not complete for the stored SHA.")
    if tracks.get("manual") != TRACK_COMPLETE_LOCALLY:
        problems.append("Manual review track is not complete.")
    if tracks.get("functional") != TRACK_COMPLETE_LOCALLY:
        if tracks.get("functional") in {TRACK_BLOCKED, TRACK_RETURNED, TRACK_STALE}:
            problems.append("Functional testing track is blocked or stale.")
        else:
            problems.append("Functional testing track is not complete.")
    if not manual_review_complete(commit_dir):
        problems.append("Manual code review is not complete for this SHA.")
    if not functional_testing_passed(commit_dir, expected_sha=sha):
        problems.append("Functional test pass is not recorded for this SHA.")
    publication = read_json(commit_dir / "review" / "publication.json") or {}
    label = _github_label(publication)
    if label == "Not published":
        problems.append("GitHub review is not published.")
    elif label != "APPROVE":
        problems.append(f"GitHub review is {label}, not Approve.")
    return problems


def project_ticket_disposition(store: Store, issue: str) -> TicketDispositionProjection:
    issue_key = require_issue_key(issue)
    session = read_json(store.issue_dir(issue_key) / "session.json") or {}
    notes = get_decision(session, "testing_notes")
    readiness = get_decision(session, "pr_readiness")
    if notes is None or notes.get("choice") != "accept":
        return TicketDispositionProjection(
            dock_enabled=False,
            dock_reason="Accept testing notes before ticket disposition.",
            approve_enabled=False,
            approve_reason="Testing notes were not accepted.",
            reject_enabled=False,
            blockers=(),
        )
    if readiness is None or readiness.get("choice") != "accept":
        return TicketDispositionProjection(
            dock_enabled=False,
            dock_reason="Pass the PR readiness gate before ticket disposition.",
            approve_enabled=False,
            approve_reason="PR readiness gate was not accepted.",
            reject_enabled=False,
            blockers=(),
        )

    status = project_review_status(store, issue_key)
    blockers: list[PrTicketBlocker] = []
    approve_problems: list[str] = []
    for row in status.pr_rows:
        ref = row.ref
        sha = row.stored_sha
        commit_dir = store.commit_dir(issue_key, row.owner, row.repo, row.number, sha)
        reject_lines = _reject_blocker_lines(commit_dir, sha)
        if reject_lines:
            blockers.append(
                PrTicketBlocker(
                    ref=ref,
                    sha=sha,
                    url=row.url,
                    lines=tuple(reject_lines),
                )
            )
        for problem in _pr_ready_for_ticket_approve(commit_dir, sha, row.tracks.current_tracks):
            approve_problems.append(f"{ref}: {problem}")

    approve_enabled = not approve_problems
    approve_reason = " ".join(approve_problems) if approve_problems else "All included pull requests are ready."

    return TicketDispositionProjection(
        dock_enabled=True,
        dock_reason="",
        approve_enabled=approve_enabled,
        approve_reason=approve_reason,
        reject_enabled=True,
        blockers=tuple(blockers),
    )


def ticket_return_draft(
    *,
    issue: str,
    in_progress_status: str,
    blockers: tuple[PrTicketBlocker, ...],
    notes: str = "",
) -> str:
    if not blockers:
        reason = "Peer review cannot approve the ticket yet; returning for additional work."
    else:
        sections: list[str] = []
        for blocker in blockers:
            header = f"{blocker.ref} — SHA `{short_sha(blocker.sha)}`"
            if blocker.url:
                header += f" ({blocker.url})"
            body = "\n".join(f"- {line}" for line in blocker.lines)
            sections.append(f"### {header}\n\n{body}")
        reason = (
            f"Requesting that {issue} return to **{in_progress_status}**.\n\n"
            + "\n\n".join(sections)
            + "\n\nThe ticket can be reviewed again after the blocking items are resolved."
        )
    links = [blocker.url for blocker in blockers if blocker.url]
    return return_comment(issue=issue, reason=reason, notes=notes, links=links)
