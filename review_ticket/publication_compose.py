"""GitHub publication composition helpers (P9)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from review_ticket.findings import apply_human_decisions, build_review_payload
from review_ticket.manual_review import suppress_duplicate_manual_findings
from review_ticket.models import WorkflowError
from review_ticket.reports import review_preview
from review_ticket.storage import read_json
from review_ticket.tracks import publication_eligibility
from review_ticket.util import short_sha


@dataclass(frozen=True)
class ComposeFindingRow:
    source: str
    finding_id: str
    title: str
    included: bool
    path: str | None
    line: int | None


@dataclass(frozen=True)
class PublicationComposeProjection:
    owner: str
    repo: str
    number: int
    ref: str
    sha: str
    summary_default: str
    functional_notes: str
    finding_rows: tuple[ComposeFindingRow, ...]
    omitted_count: int
    approve_allowed: bool
    approve_reason: str
    comment_allowed: bool
    comment_reason: str
    request_changes_allowed: bool
    request_changes_reason: str
    last_receipt_event: str | None


def _manual_as_findings(manual_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for index, row in enumerate(manual_rows):
        merged.append(
            {
                "id": f"manual-{index + 1}",
                "title": "Manual finding",
                "explanation": str(row.get("text") or row.get("body") or ""),
                "path": row.get("path"),
                "line": row.get("line"),
                "side": "RIGHT",
                "must_fix": bool(row.get("blocking")),
                "decision": "accept",
            }
        )
    return merged


def merged_publication_findings(commit_dir: Path) -> list[dict[str, Any]]:
    review = commit_dir / "review"
    document = read_json(review / "findings.json") or {}
    human = read_json(review / "human-review.json") or {}
    machine = list(document.get("findings") or [])
    if human.get("rejected_review"):
        automated: list[dict[str, Any]] = []
    else:
        automated = apply_human_decisions(machine, human)
    manual_doc = read_json(review / "manual-review.json") or {}
    manual_rows = suppress_duplicate_manual_findings(
        list(manual_doc.get("findings") or []),
        human,
        machine,
    )
    return automated + _manual_as_findings(manual_rows)


def compose_finding_rows(commit_dir: Path) -> tuple[tuple[ComposeFindingRow, ...], int]:
    review = commit_dir / "review"
    document = read_json(review / "findings.json") or {}
    human = read_json(review / "human-review.json") or {}
    machine = list(document.get("findings") or [])
    decisions = human.get("findings") or {}
    rows: list[ComposeFindingRow] = []
    omitted = 0
    for finding in machine:
        fid = str(finding.get("id") or "")
        entry = decisions.get(fid) or {}
        included = entry.get("decision") == "accept" and not human.get("rejected_review")
        if not included:
            omitted += 1
        rows.append(
            ComposeFindingRow(
                source="automated",
                finding_id=fid,
                title=str(finding.get("title") or "Finding"),
                included=included,
                path=finding.get("path"),
                line=finding.get("line") if isinstance(finding.get("line"), int) else None,
            )
        )
    manual_doc = read_json(review / "manual-review.json") or {}
    manual_rows = suppress_duplicate_manual_findings(
        list(manual_doc.get("findings") or []),
        human,
        machine,
    )
    for index, row in enumerate(manual_rows):
        rows.append(
            ComposeFindingRow(
                source="manual",
                finding_id=f"manual-{index + 1}",
                title="Manual finding",
                included=True,
                path=row.get("path"),
                line=row.get("line") if isinstance(row.get("line"), int) else None,
            )
        )
    return tuple(rows), omitted


def project_publication_compose(
    commit_dir: Path,
    *,
    owner: str,
    repo: str,
    number: int,
    ref: str,
    sha: str,
) -> PublicationComposeProjection:
    review = commit_dir / "review"
    document = read_json(review / "findings.json") or {}
    human = read_json(review / "human-review.json") or {}
    testing = read_json(commit_dir / "testing" / "test-results.json") or {}
    functional_notes = str(testing.get("notes") or "").strip()
    summary_default = str(human.get("summary") or document.get("summary") or "Peer review.").strip()
    finding_rows, omitted = compose_finding_rows(commit_dir)
    receipt = read_json(review / "publication.json") or {}
    last_event = None
    if receipt.get("status") in {"success", "skipped"}:
        last_event = str(receipt.get("event") or "") or None

    def gate(event: str) -> tuple[bool, str]:
        allowed, reason = publication_eligibility(event, commit_dir, expected_sha=sha)
        return allowed, reason

    approve_allowed, approve_reason = gate("APPROVE")
    comment_allowed, comment_reason = gate("COMMENT")
    rc_allowed, rc_reason = gate("REQUEST_CHANGES")
    return PublicationComposeProjection(
        owner=owner,
        repo=repo,
        number=number,
        ref=ref,
        sha=sha,
        summary_default=summary_default,
        functional_notes=functional_notes,
        finding_rows=finding_rows,
        omitted_count=omitted,
        approve_allowed=approve_allowed,
        approve_reason=approve_reason,
        comment_allowed=comment_allowed,
        comment_reason=comment_reason,
        request_changes_allowed=rc_allowed,
        request_changes_reason=rc_reason,
        last_receipt_event=last_event,
    )


def build_compose_preview_markdown(
    projection: PublicationComposeProjection,
    *,
    summary: str,
    event: str,
    diff_index: set[tuple[str, int, str]],
    commit_dir: Path,
) -> str:
    review = commit_dir / "review"
    document = read_json(review / "findings.json") or {}
    human = read_json(review / "human-review.json") or {}
    findings = merged_publication_findings(commit_dir)
    try:
        payload = build_review_payload(
            sha=projection.sha,
            event=event,
            summary=summary,
            findings=findings,
            diff_index=diff_index,
        )
    except WorkflowError as exc:
        return f"# Publication preview\n\n**Blocked:** {exc}\n"
    lines = [
        f"# GitHub publication `{short_sha(projection.sha)}`",
        "",
        f"**Repository:** {projection.owner}/{projection.repo}#{projection.number}",
        f"**Event:** {event}",
        f"**Commit:** `{projection.sha}`",
        "",
        "## General comment",
        "",
        summary.strip() or "_Empty_",
        "",
    ]
    if projection.omitted_count:
        lines.append(f"_Omitted {projection.omitted_count} excluded automated finding(s)._")
        lines.append("")
    inline = payload.get("comments") or []
    lines.append(f"## Inline comments ({len(inline)})")
    lines.append("")
    if not inline:
        lines.append("_None on the diff._")
    else:
        for comment in inline:
            lines.append(f"- `{comment['path']}:{comment['line']}`")
            lines.append("")
            lines.append(str(comment.get("body") or "").strip())
            lines.append("")
    preview = review_preview(
        sha=projection.sha,
        document=document,
        findings=findings,
        diff_index=diff_index,
        human=human,
        payload=payload,
    )
    lines.append("---")
    lines.append("")
    lines.append(preview)
    return "\n".join(lines).rstrip() + "\n"
