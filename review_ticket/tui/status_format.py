"""Render P4 status projection as a status document."""

from __future__ import annotations

from review_ticket.policy import (
    TRACK_BLOCKED,
    TRACK_COMPLETE_LOCALLY,
    TRACK_IN_PROGRESS,
    TRACK_NAMES,
    TRACK_NOT_STARTED,
    TRACK_PUBLICATION_PENDING,
    TRACK_PUBLISHED,
    TRACK_RETURNED,
    TRACK_STALE,
)
from review_ticket.reports import format_checks_table
from review_ticket.status_projection import (
    ArtifactTimestamps,
    PrStatusRow,
    PublicationReceipt,
    StatusProjection,
    format_pr_freshness,
)
from review_ticket.util import short_sha

TRACK_HEADINGS = {
    "automated": "Automated code review",
    "manual": "Manual code review",
    "functional": "Functional testing",
    "publication": "GitHub review",
}

_TRACK_STATUS_LABELS = {
    TRACK_NOT_STARTED: "Not started",
    TRACK_IN_PROGRESS: "In progress",
    TRACK_COMPLETE_LOCALLY: "Complete locally",
    TRACK_PUBLICATION_PENDING: "Publication pending",
    TRACK_PUBLISHED: "Published",
    TRACK_STALE: "Stale (historical SHA)",
    TRACK_BLOCKED: "Blocked",
    TRACK_RETURNED: "Changes requested",
}


def format_track_status_label(status: str) -> str:
    """Human-readable label for a track status token from classify_track_status."""
    return _TRACK_STATUS_LABELS.get(status, status.replace("_", " ").title())


def format_publication_track_label(track_status: str, receipt: PublicationReceipt | None) -> str:
    """Publication row uses receipt event when published; never local disposition."""
    if receipt and receipt.status in {"success", "skipped"} and receipt.event:
        event = str(receipt.event).replace("_", " ").title()
        return f"Published ({event})"
    if track_status == TRACK_PUBLICATION_PENDING:
        return format_track_status_label(track_status)
    return format_track_status_label(track_status)


def format_status_document(projection: StatusProjection) -> str:
    """Build markdown for the read-only status screen body."""
    title = projection.issue
    if projection.issue_title:
        title = f"{projection.issue} — {projection.issue_title}"
    lines: list[str] = [f"# Review status — {title}", ""]
    if not projection.session_exists:
        lines.append(projection.missing_session_message or "No review session exists yet.")
        return "\n".join(lines)

    if projection.session_last_updated:
        lines.append(f"**Session updated:** {projection.session_last_updated}")
        lines.append("")
    lines.extend(
        [
            f"**Current step:** {projection.current_step or '—'}",
            f"**Last completed step:** {projection.last_completed_step or '—'}",
            f"**Outcome:** {projection.outcome or '—'}",
            f"**Next action:** {projection.next_command or '—'}",
            "",
        ]
    )
    for row in projection.pr_rows:
        lines.extend(_format_pr_section(row))
    return "\n".join(lines)


def format_pr_list_label(row: PrStatusRow) -> str:
    """One markdown line for the PR picker: linked ref, stored SHA, and progress."""
    short = short_sha(row.stored_sha) if row.stored_sha else "—"
    return f"{_pr_title(row)}  `{short}`  {row.progress.label}"


def _pr_title(row: PrStatusRow) -> str:
    title = f"{row.owner}/{row.repo}#{row.number}"
    if row.url:
        return f"[{title}]({row.url})"
    return title


def _format_timestamp_lines(timestamps: ArtifactTimestamps) -> list[str]:
    pairs = [
        ("Snapshot captured", timestamps.captured_at),
        ("Checks captured", timestamps.checks_captured_at),
        ("Automated curation recorded", timestamps.curated_at),
        ("Manual review recorded", timestamps.manual_recorded_at),
        ("Functional testing recorded", timestamps.testing_recorded_at),
        ("GitHub review published", timestamps.published_at),
    ]
    lines = [f"- {label}: {value}" for label, value in pairs if value]
    if not lines:
        return []
    return ["**Artifact timestamps:**", *lines, ""]


def _format_track_lines(row: PrStatusRow) -> list[str]:
    by_name = dict(row.tracks)
    lines = ["**Review tracks:**"]
    for name in TRACK_NAMES:
        status = by_name.get(name, TRACK_NOT_STARTED)
        heading = TRACK_HEADINGS[name]
        if name == "publication":
            label = format_publication_track_label(status, row.publication)
        else:
            label = format_track_status_label(status)
        lines.append(f"- {heading}: {label}")
    lines.append("")
    return lines


def _format_pr_section(row: PrStatusRow) -> list[str]:
    short = short_sha(row.stored_sha) if row.stored_sha else "—"
    section = [
        f"## {_pr_title(row)}",
        "",
        f"**Stored SHA:** `{short}`",
        f"**Review progress:** {row.progress.label}",
        f"**Freshness:** {format_pr_freshness(row.freshness)}",
        "",
    ]
    section.extend(_format_track_lines(row))
    section.extend(_format_timestamp_lines(row.timestamps))
    if row.snapshot.stale and row.snapshot.open_sha:
        section.append(
            f"**Open snapshot:** `{short_sha(row.snapshot.open_sha)}` "
            "(not the stored commit — publish will refuse until run-review for the stored SHA)"
        )
        section.append("")
    check_dicts = [
        {
            "name": item.name,
            "required": item.required,
            "bucket": item.bucket,
            "state": item.state,
            "link": item.link,
        }
        for item in row.checks.rows
    ]
    if row.checks.summary:
        section.append(f"**Checks:** {row.checks.summary}")
        section.append("")
    section.append(format_checks_table(check_dicts))
    section.append("")
    return section
