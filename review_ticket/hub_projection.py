"""Read-only PR review hub model from on-disk artifacts."""

from __future__ import annotations

from dataclasses import dataclass

from review_ticket.policy import (
    TRACK_BLOCKED,
    TRACK_COMPLETE_LOCALLY,
    TRACK_IN_PROGRESS,
    TRACK_NOT_STARTED,
    TRACK_PUBLICATION_PENDING,
    TRACK_PUBLISHED,
    TRACK_RETURNED,
    TRACK_STALE,
)
from review_ticket.storage import Store, read_json
from review_ticket.status_projection import PrStatusRow, PublicationReceipt, project_review_status
from review_ticket.ticket_disposition import evaluate_ticket_disposition
from review_ticket.tui.status_format import format_publication_track_label, format_track_status_label
from review_ticket.util import parse_pr_ref, require_issue_key, short_sha

def _testing_environment_ready(store: Store, issue: str, row: PrStatusRow) -> bool:
    if not row.stored_sha:
        return False
    owner, repo, number = row.owner, row.repo, row.number
    commit = store.commit_dir(issue, owner, repo, number, row.stored_sha)
    testing = commit / "testing"
    profile = read_json(testing / "profile" / "profile.json")
    environment = read_json(testing / "environment.json") or {}
    if not profile:
        return False
    return environment.get("sha") == row.stored_sha and bool(environment.get("digest"))


TRACK_TITLES = {
    "automated": "Automated review",
    "manual": "Manual code review",
    "functional": "Functional testing",
    "publication": "GitHub publication",
}


@dataclass(frozen=True)
class HubTrackRow:
    key: str
    title: str
    status_label: str
    open_enabled: bool
    disabled_reason: str | None


@dataclass(frozen=True)
class HubPrBlock:
    ref: str
    owner: str
    repo: str
    number: int
    pr_title: str
    stored_sha: str
    head_stale: bool
    tracks: tuple[HubTrackRow, ...]
    github_outcome: str
    next_action: str
    next_action_enabled: bool
    next_action_reason: str | None
    snapshot_stale: bool
    open_sha: str
    publication: PublicationReceipt | None


@dataclass(frozen=True)
class HubTicketDock:
    approve_visible: bool
    approve_enabled: bool
    reject_visible: bool
    reject_enabled: bool
    disabled_reason: str


@dataclass(frozen=True)
class HubProjection:
    issue: str
    issue_title: str | None
    session_exists: bool
    missing_session_message: str | None
    pr_blocks: tuple[HubPrBlock, ...]
    ticket: HubTicketDock


def project_review_hub(store: Store, issue: str) -> HubProjection:
    """Build the hub screen model without network or session writes."""
    status = project_review_status(store, issue)
    if not status.session_exists:
        return HubProjection(
            issue=status.issue,
            issue_title=status.issue_title,
            session_exists=False,
            missing_session_message=status.missing_session_message,
            pr_blocks=(),
            ticket=_ticket_dock(store, status.issue, ()),
        )
    blocks = tuple(_pr_block(store, status.issue, row) for row in status.pr_rows)
    return HubProjection(
        issue=status.issue,
        issue_title=status.issue_title,
        session_exists=True,
        missing_session_message=None,
        pr_blocks=blocks,
        ticket=_ticket_dock(store, status.issue, blocks),
    )


def format_github_outcome(receipt: PublicationReceipt | None) -> str:
    """GitHub line uses publication receipt only — never local track disposition."""
    if not receipt or receipt.status not in {"success", "skipped"}:
        return "Not published"
    event = str(receipt.event or "").strip()
    if not event:
        return "Published"
    return event.replace("_", " ")


def _pr_block(store: Store, issue: str, row: PrStatusRow) -> HubPrBlock:
    by_name = dict(row.tracks)
    tracks = tuple(
        _track_row(key, by_name.get(key, TRACK_NOT_STARTED), row)
        for key in ("automated", "manual", "functional", "publication")
    )
    github = format_github_outcome(row.publication)
    next_action, next_enabled, next_reason = _next_action(store, issue, row, by_name)
    pr_title = _pr_title_from_disk(store, issue, row.ref)
    return HubPrBlock(
        ref=row.ref,
        owner=row.owner,
        repo=row.repo,
        number=row.number,
        pr_title=pr_title,
        stored_sha=row.stored_sha,
        head_stale=row.freshness.stale,
        tracks=tracks,
        github_outcome=github,
        next_action=next_action,
        next_action_enabled=next_enabled,
        next_action_reason=next_reason,
        snapshot_stale=row.snapshot.stale,
        open_sha=row.snapshot.open_sha or row.stored_sha,
        publication=row.publication,
    )


def _pr_title_from_disk(store: Store, issue: str, ref: str) -> str:
    try:
        owner, repo, number = parse_pr_ref(ref)
    except ValueError:
        return ""
    pr = read_json(store.pr_dir(issue, owner, repo, number) / "pr.json") or {}
    return str(pr.get("title") or "").strip()


def _track_row(key: str, status: str, row: PrStatusRow) -> HubTrackRow:
    if key == "publication":
        label = format_publication_track_label(status, row.publication)
    else:
        label = format_track_status_label(status)
    enabled, reason = _track_open_eligibility(key, status, row)
    return HubTrackRow(
        key=key,
        title=TRACK_TITLES[key],
        status_label=label,
        open_enabled=enabled,
        disabled_reason=reason,
    )


def _track_open_eligibility(key: str, status: str, row: PrStatusRow) -> tuple[bool, str | None]:
    if status == TRACK_STALE:
        return False, "Historical SHA — evidence is read-only until you refresh HEAD."
    if key == "automated":
        if not row.stored_sha:
            return False, "No HEAD SHA stored for this pull request."
        return True, None
    if key == "manual":
        if not row.stored_sha:
            return False, "No HEAD SHA stored for this pull request."
        auto = dict(row.tracks).get("automated", TRACK_NOT_STARTED)
        if auto not in {TRACK_COMPLETE_LOCALLY, TRACK_PUBLICATION_PENDING, TRACK_PUBLISHED, TRACK_RETURNED}:
            return False, "Complete automated review before manual code review."
        return True, None
    if key == "functional":
        if not row.stored_sha:
            return False, "No HEAD SHA stored for this pull request."
        manual = dict(row.tracks).get("manual", TRACK_NOT_STARTED)
        if manual not in {
            TRACK_COMPLETE_LOCALLY,
            TRACK_PUBLICATION_PENDING,
            TRACK_PUBLISHED,
            TRACK_RETURNED,
            TRACK_BLOCKED,
            TRACK_IN_PROGRESS,
        }:
            return False, "Complete manual code review before preparing the test environment."
        return True, None
    if key == "publication":
        if not row.stored_sha:
            return False, "No HEAD SHA stored for this pull request."
        pub = dict(row.tracks).get("publication", TRACK_NOT_STARTED)
        if pub == TRACK_STALE:
            return False, "Historical SHA — evidence is read-only until you refresh HEAD."
        if pub in {TRACK_PUBLISHED, TRACK_RETURNED}:
            return False, "A GitHub review receipt already exists for this SHA."
        if pub not in {TRACK_PUBLICATION_PENDING, TRACK_IN_PROGRESS, TRACK_BLOCKED}:
            return False, "Complete review tracks before publishing to GitHub."
        return True, None
    return False, "Track is not available."


def _next_action(
    store: Store, issue: str, row: PrStatusRow, tracks: dict[str, str]
) -> tuple[str, bool, str | None]:
    auto = tracks.get("automated", TRACK_NOT_STARTED)
    manual = tracks.get("manual", TRACK_NOT_STARTED)
    functional = tracks.get("functional", TRACK_NOT_STARTED)
    publication = tracks.get("publication", TRACK_NOT_STARTED)

    if row.freshness.stale:
        return "Refresh HEAD evidence", False, "HEAD moved — explicit refresh is required before new work."
    if auto == TRACK_NOT_STARTED:
        return "Generate automated review", True, None
    if auto == TRACK_IN_PROGRESS:
        return "Complete automated triage", True, None
    if auto == TRACK_COMPLETE_LOCALLY and manual == TRACK_NOT_STARTED:
        return "Start manual code review", True, None
    if manual == TRACK_IN_PROGRESS:
        return "Complete manual code review", True, None
    if manual in {TRACK_RETURNED, TRACK_BLOCKED}:
        return "Resolve manual review disposition", True, None
    if manual == TRACK_COMPLETE_LOCALLY and functional == TRACK_NOT_STARTED:
        if _testing_environment_ready(store, issue, row):
            return "Complete functional testing", True, None
        return "Prepare test environment", True, None
    if functional == TRACK_NOT_STARTED:
        return "Prepare test environment", False, "Complete manual code review first."
    if functional in {TRACK_IN_PROGRESS, TRACK_BLOCKED}:
        return "Complete functional testing", True, None
    if publication == TRACK_PUBLICATION_PENDING:
        return "Publish GitHub review", True, None
    if publication in {TRACK_IN_PROGRESS, TRACK_BLOCKED}:
        return "Publish GitHub review", True, None
    if publication == TRACK_NOT_STARTED:
        return "Publish GitHub review", False, "Finish automated triage before GitHub publication."
    if publication == TRACK_PUBLISHED:
        return "Review complete for this SHA", False, "No further action on this pull request."
    if publication == TRACK_RETURNED:
        return "Address requested changes", False, "Publication screen is not available yet."
    return "Continue review tracks", True, None


def _ticket_dock(store: Store, issue: str, blocks: tuple[HubPrBlock, ...]) -> HubTicketDock:
    view = evaluate_ticket_disposition(store, issue)
    visible = view.testing_notes_accepted and view.readiness_passed and bool(blocks)
    return HubTicketDock(
        approve_visible=visible,
        approve_enabled=view.approve_enabled,
        reject_visible=visible,
        reject_enabled=view.reject_enabled,
        disabled_reason=view.disabled_reason,
    )
