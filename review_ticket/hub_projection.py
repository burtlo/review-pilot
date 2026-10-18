"""Read-only PR review hub model (P5) built from on-disk tracks and receipts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from review_ticket.status_projection import PublicationReceipt, project_review_status
from review_ticket.storage import Store
from review_ticket.ticket_disposition import project_ticket_disposition
from review_ticket.tracks import (
    TRACK_BLOCKED,
    TRACK_COMPLETE_LOCALLY,
    TRACK_HISTORICAL,
    TRACK_IN_PROGRESS,
    TRACK_NOT_STARTED,
    TRACK_PUBLICATION_PENDING,
    TRACK_PUBLISHED,
    TRACK_RETURNED,
    TRACK_STALE,
)
from review_ticket.util import require_issue_key, short_sha

TrackKind = Literal["automated", "manual", "functional"]

_TRACK_TITLES: dict[TrackKind, str] = {
    "automated": "Automated review",
    "manual": "Manual code review",
    "functional": "Functional testing",
}


@dataclass(frozen=True)
class HubTrackRow:
    kind: TrackKind
    title: str
    status_label: str
    raw_status: str
    open_enabled: bool
    disabled_reason: str | None


@dataclass(frozen=True)
class HubPrBlock:
    ref: str
    owner: str
    repo: str
    number: int
    pr_title: str | None
    stored_sha: str
    url: str
    stale: bool
    stale_note: str | None
    tracks: tuple[HubTrackRow, HubTrackRow, HubTrackRow]
    github_publication: str
    next_action: str
    navigation_sha: str
    navigation_stale: bool


@dataclass(frozen=True)
class HubProjection:
    issue: str
    issue_title: str | None
    session_exists: bool
    pr_blocks: tuple[HubPrBlock, ...]
    ticket_dock_enabled: bool
    ticket_dock_reason: str


def project_review_hub(store: Store, issue: str) -> HubProjection:
    """Build the hub workspace model from session and per-commit artifacts."""
    issue_key = require_issue_key(issue)
    status = project_review_status(store, issue_key)
    blocks = tuple(_hub_block(row) for row in status.pr_rows)
    ticket = project_ticket_disposition(store, issue_key)
    return HubProjection(
        issue=status.issue,
        issue_title=status.issue_title,
        session_exists=status.session_exists,
        pr_blocks=blocks,
        ticket_dock_enabled=ticket.dock_enabled,
        ticket_dock_reason=ticket.dock_reason or ticket.approve_reason,
    )


def github_outcome_from_receipt(receipt: PublicationReceipt | None) -> str:
    """GitHub line uses publication receipts only, never local track completion."""
    if receipt is None:
        return "Not published"
    if receipt.status not in {"success", "skipped"}:
        return "Not published"
    event = (receipt.event or "").strip()
    if not event:
        return "Not published"
    return event.replace("_", " ")


def _hub_block(row) -> HubPrBlock:
    tracks = row.tracks.current_tracks
    stale = bool(row.snapshot.head_moved or row.snapshot.stale)
    stale_note = _stale_note(row)
    nav_sha = row.snapshot.open_sha or row.stored_sha
    nav_stale = row.snapshot.stale
    track_rows = (
        _track_row("automated", tracks.get("automated", TRACK_NOT_STARTED), row, stale),
        _track_row("manual", tracks.get("manual", TRACK_NOT_STARTED), row, stale),
        _track_row("functional", tracks.get("functional", TRACK_NOT_STARTED), row, stale),
    )
    return HubPrBlock(
        ref=row.ref,
        owner=row.owner,
        repo=row.repo,
        number=row.number,
        pr_title=row.pr_title,
        stored_sha=row.stored_sha,
        url=row.url,
        stale=stale,
        stale_note=stale_note,
        tracks=track_rows,
        github_publication=github_outcome_from_receipt(row.publication),
        next_action=_next_action(track_rows, row.publication, tracks),
        navigation_sha=nav_sha,
        navigation_stale=nav_stale,
    )


def _stale_note(row) -> str | None:
    if row.snapshot.head_moved and row.tracks.supersedes_sha:
        return (
            f"HEAD moved to `{short_sha(row.stored_sha)}`; "
            f"prior work at `{short_sha(row.tracks.supersedes_sha)}` is historical."
        )
    if row.snapshot.stale and row.snapshot.open_sha:
        return (
            f"Open snapshot `{short_sha(row.snapshot.open_sha)}` is not the stored SHA "
            f"`{short_sha(row.stored_sha)}`."
        )
    if row.tracks.current_tracks.get("functional") == TRACK_STALE:
        return "Functional test results do not match the stored SHA."
    return None


def _track_row(kind: TrackKind, raw: str, row, pr_stale: bool) -> HubTrackRow:
    title = _TRACK_TITLES[kind]
    status_label = _status_label(kind, raw)
    enabled, reason = _track_open_eligibility(kind, raw, row, pr_stale)
    return HubTrackRow(
        kind=kind,
        title=title,
        status_label=status_label,
        raw_status=raw,
        open_enabled=enabled,
        disabled_reason=reason,
    )


def _status_label(kind: TrackKind, raw: str) -> str:
    if raw == TRACK_NOT_STARTED:
        return "Not generated" if kind == "automated" else "Not started"
    mapping = {
        TRACK_IN_PROGRESS: "In progress",
        TRACK_COMPLETE_LOCALLY: "Complete",
        TRACK_PUBLICATION_PENDING: "Publication pending",
        TRACK_PUBLISHED: "Published on GitHub",
        TRACK_STALE: "Stale",
        TRACK_HISTORICAL: "Historical",
        TRACK_BLOCKED: "Blocked",
        TRACK_RETURNED: "Changes requested",
    }
    return mapping.get(raw, raw.replace("_", " ").title())


def _track_open_eligibility(
    kind: TrackKind,
    raw: str,
    row,
    pr_stale: bool,
) -> tuple[bool, str | None]:
    if kind == "automated":
        if raw == TRACK_HISTORICAL:
            return False, "Historical SHA — renew review on the current HEAD."
        if pr_stale and row.snapshot.head_moved:
            return True, None
        if not row.stored_sha:
            return False, "No stored SHA for this pull request."
        return True, None
    if kind == "manual":
        if raw == TRACK_HISTORICAL:
            return False, "Historical SHA — renew manual review on the current HEAD."
        if not row.stored_sha:
            return False, "No stored SHA for this pull request."
        return True, None
    if kind == "functional":
        if raw == TRACK_HISTORICAL:
            return False, "Historical SHA — renew functional testing on the current HEAD."
        if not row.stored_sha:
            return False, "No stored SHA for this pull request."
        return True, None
    return False, "Track is not available."


def _next_action(
    track_rows: tuple[HubTrackRow, HubTrackRow, HubTrackRow],
    receipt: PublicationReceipt | None,
    tracks: dict[str, str],
) -> str:
    automated, manual, functional = track_rows
    if automated.raw_status == TRACK_NOT_STARTED:
        return "Generate or import an automated review."
    if automated.raw_status == TRACK_IN_PROGRESS:
        return "Finish automated finding triage."
    if manual.raw_status in {TRACK_NOT_STARTED, TRACK_IN_PROGRESS}:
        return "Complete manual code review."
    if functional.raw_status in {TRACK_NOT_STARTED, TRACK_IN_PROGRESS, TRACK_STALE}:
        return "Record functional testing for this SHA."
    if github_outcome_from_receipt(receipt) == "Not published":
        if tracks.get("publication") == TRACK_PUBLICATION_PENDING:
            return "Compose and authorize GitHub publication."
        return "Publish GitHub review when tracks are ready."
    return "Review tracks or move to ticket disposition when all PRs are ready."


def flatten_track_rows(projection: HubProjection) -> list[tuple[HubPrBlock, HubTrackRow]]:
    """Stable list of (PR block, track row) pairs for list widgets."""
    rows: list[tuple[HubPrBlock, HubTrackRow]] = []
    for block in projection.pr_blocks:
        for track in block.tracks:
            rows.append((block, track))
    return rows
