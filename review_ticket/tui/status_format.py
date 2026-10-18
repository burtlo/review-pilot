"""Render P4/P13 status projection as a status document."""

from __future__ import annotations

from datetime import datetime, timezone

from review_ticket.reports import format_checks_table
from review_ticket.status_projection import (
    ArtifactTimestamps,
    PrStatusRow,
    PublicationReceipt,
    StatusProjection,
)
from review_ticket.tracks import (
    TRACK_HISTORICAL,
    TRACK_PUBLICATION_PENDING,
    TRACK_PUBLISHED,
)
from review_ticket.util import short_sha


def format_iso_local(value: str | None) -> str | None:
    """Format a stored ISO-8601 timestamp for display in local time only."""
    if not value:
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except ValueError:
        return value


def format_status_document(projection: StatusProjection) -> str:
    """Build markdown for the read-only status screen body."""
    title_suffix = f" — {projection.issue_title}" if projection.issue_title else ""
    lines: list[str] = [f"# Review status{title_suffix}", ""]
    if not projection.session_exists:
        lines.append(projection.missing_session_message or "No review session exists yet.")
        return "\n".join(lines)

    if projection.session_last_updated:
        local = format_iso_local(projection.session_last_updated)
        if local:
            lines.append(f"**Session last updated (local):** {local}")
            lines.append("")
    lines.extend(
        [
            f"**Current step:** {projection.current_step or '—'}",
            f"**Last completed step:** {projection.last_completed_step or '—'}",
            f"**Outcome:** {projection.outcome or '—'}",
            f"**Next command:** {projection.next_command or '—'}",
            "",
        ]
    )
    for row in projection.pr_rows:
        lines.extend(_format_pr_section(row))
    return "\n".join(lines)


def format_pr_list_label(row: PrStatusRow) -> str:
    """One markdown line for the PR picker: linked ref, stored SHA, tracks, and progress."""
    short = short_sha(row.stored_sha) if row.stored_sha else "—"
    head_note = " HEAD moved" if row.snapshot.head_moved else ""
    tracks = row.tracks.current_tracks
    track_bits = "/".join(
        tracks.get(key, "—") for key in ("automated", "manual", "functional", "publication")
    )
    title = _pr_title(row)
    if row.pr_title:
        title = f"{title} — {row.pr_title}"
    return f"{title}  `{short}`{head_note}  `{track_bits}`  {row.progress.label}"


def _pr_title(row: PrStatusRow) -> str:
    title = f"{row.owner}/{row.repo}#{row.number}"
    if row.url:
        return f"[{title}]({row.url})"
    return title


def _format_pr_section(row: PrStatusRow) -> list[str]:
    short = short_sha(row.stored_sha) if row.stored_sha else "—"
    section = [
        f"## {_pr_title(row)}",
        "",
    ]
    if row.pr_title:
        section.append(f"**PR title:** {row.pr_title}")
        section.append("")
    section.extend(
        [
            f"**Stored SHA:** `{short}`",
            f"**Review progress:** {row.progress.label}",
            "",
        ]
    )
    if row.snapshot.head_moved and row.tracks.supersedes_sha:
        section.append(
            f"**HEAD moved:** current `{short}` supersedes `{short_sha(row.tracks.supersedes_sha)}`. "
            "Prior tracks and receipts are historical; renew review on the current SHA."
        )
        section.append(
            _format_track_lines(
                row.tracks.current_tracks,
                label="Current tracks",
                publication_receipt=row.publication,
            )
        )
        for historical in row.tracks.historical:
            section.append(
                _format_track_lines(
                    historical.tracks,
                    label=f"Historical `{short_sha(historical.sha)}`",
                    publication_event=historical.publication_event,
                )
            )
        section.append("")
    else:
        section.append(
            _format_track_lines(
                row.tracks.current_tracks,
                label="Tracks",
                publication_receipt=row.publication,
            )
        )
        section.append(_format_publication_receipt(row.publication, row.tracks.current_tracks))
        section.append("")
        if row.snapshot.stale and row.snapshot.open_sha:
            section.append(
                f"**Open snapshot:** `{short_sha(row.snapshot.open_sha)}` "
                "(not the stored commit — publish will refuse until run-review for the stored SHA)"
            )
            section.append("")
    timestamp_lines = _format_artifact_timestamps(row.timestamps)
    if timestamp_lines:
        section.extend(timestamp_lines)
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


def _format_track_lines(
    tracks: dict[str, str],
    *,
    label: str,
    publication_event: str | None = None,
    publication_receipt: PublicationReceipt | None = None,
) -> str:
    automated = tracks.get("automated", "—")
    manual = tracks.get("manual", "—")
    functional = tracks.get("functional", "—")
    publication = tracks.get("publication", "—")
    if publication_event and publication == TRACK_HISTORICAL:
        publication = f"{publication} ({publication_event})"
    elif publication_receipt and publication in {
        TRACK_PUBLICATION_PENDING,
        TRACK_PUBLISHED,
        TRACK_HISTORICAL,
    }:
        receipt_event = publication_receipt.event or "—"
        if publication_receipt.status in {"success", "skipped"}:
            publication = f"{publication} (receipt: {publication_receipt.status} · {receipt_event})"
    return (
        f"**{label}:** automated {automated}; manual {manual}; "
        f"functional {functional}; publication {publication}"
    )


def _format_publication_receipt(
    receipt: PublicationReceipt | None,
    tracks: dict[str, str],
) -> str:
    if receipt and (receipt.status or receipt.event):
        when = format_iso_local(receipt.published_at or receipt.recorded_at)
        parts = [part for part in (receipt.status, receipt.event) if part]
        summary = " · ".join(parts) if parts else "recorded"
        if when:
            return f"**GitHub publication (receipt):** {summary} at {when} (local)"
        return f"**GitHub publication (receipt):** {summary}"
    if tracks.get("publication") == TRACK_PUBLICATION_PENDING:
        return "**GitHub publication (receipt):** none (publication pending locally)"
    return "**GitHub publication (receipt):** none"


def _format_artifact_timestamps(timestamps: ArtifactTimestamps) -> list[str]:
    rows: list[str] = []
    mapping = (
        ("Snapshot captured (local)", timestamps.snapshot_captured_at),
        ("Functional tests recorded (local)", timestamps.tests_recorded_at),
        ("Publication published (local)", timestamps.publication_published_at),
        ("Publication recorded (local)", timestamps.publication_recorded_at),
    )
    for label, raw in mapping:
        local = format_iso_local(raw)
        if local:
            rows.append(f"- **{label}:** {local}")
    if not rows:
        return []
    return ["**Artifact timestamps:**", *rows]
