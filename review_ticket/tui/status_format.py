"""Render P4 status projection as a status document."""

from __future__ import annotations

from review_ticket.reports import format_checks_table
from review_ticket.status_projection import PrStatusRow, StatusProjection
from review_ticket.util import short_sha


def format_status_document(projection: StatusProjection) -> str:
    """Build markdown for the read-only status screen body."""
    lines: list[str] = [f"# Review status — {projection.issue}", ""]
    if not projection.session_exists:
        lines.append(projection.missing_session_message or "No review session exists yet.")
        return "\n".join(lines)

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
    """One markdown line for the PR picker: linked ref, stored SHA, and progress."""
    short = short_sha(row.stored_sha) if row.stored_sha else "—"
    return f"{_pr_title(row)}  `{short}`  {row.progress.label}"


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
        f"**Stored SHA:** `{short}`",
        f"**Review progress:** {row.progress.label}",
        "",
    ]
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
