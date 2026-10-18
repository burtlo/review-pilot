"""Render P5 hub projection as markdown."""

from __future__ import annotations

from review_ticket.hub_projection import HubPrBlock, HubProjection, HubTrackRow
from review_ticket.util import short_sha


def format_hub_document(projection: HubProjection) -> str:
    if not projection.session_exists:
        return "# Code review hub\n\nNo review session exists yet."
    title = projection.issue_title or projection.issue
    lines = [f"# Code review hub — {title}", ""]
    if not projection.pr_blocks:
        lines.append("No pull requests are included in this session.")
        return "\n".join(lines)
    for block in projection.pr_blocks:
        lines.extend(_format_pr_block(block))
    return "\n".join(lines)


def format_track_list_label(block: HubPrBlock, track: HubTrackRow) -> str:
    short = short_sha(block.stored_sha) if block.stored_sha else "—"
    pr = f"**{block.owner}/{block.repo}#{block.number}**"
    if block.pr_title:
        pr = f"{pr} — {block.pr_title}"
    state = track.status_label
    if not track.open_enabled and track.disabled_reason:
        state = f"{state} _(disabled: {track.disabled_reason})_"
    return f"{pr}  `{short}`  **{track.title}:** {state}"


def _format_pr_block(block: HubPrBlock) -> list[str]:
    short = short_sha(block.stored_sha) if block.stored_sha else "—"
    header = f"## {block.owner}/{block.repo}#{block.number}"
    if block.pr_title:
        header = f"{header} — {block.pr_title}"
    section = [
        header,
        "",
        f"**Repository:** `{block.owner}/{block.repo}`  **HEAD SHA:** `{short}`",
    ]
    if block.stale and block.stale_note:
        section.append(f"**Stale:** {block.stale_note}")
    section.append("")
    for index, track in enumerate(block.tracks, start=1):
        line = f"{index}. **{track.title}:** {track.status_label}"
        if not track.open_enabled and track.disabled_reason:
            line += f" — _{track.disabled_reason}_"
        section.append(line)
    section.append("")
    section.append(f"**GitHub review:** {block.github_publication}")
    section.append(f"**Next action:** {block.next_action}")
    section.append("")
    return section
