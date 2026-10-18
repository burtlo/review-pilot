"""Manual code review artifact helpers (P8)."""

from __future__ import annotations

from typing import Any

from review_ticket.findings import apply_human_decisions
from review_ticket.models import WorkflowError
from review_ticket.textutil import normalize_comment_body


def manual_finding_key(path: str | None, line: int | None, body: str) -> tuple[str, int, str]:
    return (str(path or ""), int(line or 0), normalize_comment_body(body))


def suppress_duplicate_manual_findings(
    manual_findings: list[dict[str, Any]],
    human_automated: dict[str, Any],
    machine_findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Drop manual rows that duplicate an included automated inline finding."""

    if human_automated.get("rejected_review"):
        accepted_keys: set[tuple[str, int, str]] = set()
    else:
        try:
            merged = apply_human_decisions(machine_findings, human_automated)
        except WorkflowError:
            merged = []
        accepted_keys = set()
        for finding in merged:
            if finding.get("decision") != "accept":
                continue
            path = finding.get("path")
            line = finding.get("line")
            body = str(finding.get("explanation") or finding.get("body") or "")
            if path and isinstance(line, int):
                accepted_keys.add(manual_finding_key(path, line, body))
    kept: list[dict[str, Any]] = []
    for row in manual_findings:
        path = row.get("path")
        line = row.get("line")
        body = str(row.get("text") or row.get("body") or "")
        key = manual_finding_key(path, line if isinstance(line, int) else None, body)
        if key in accepted_keys:
            continue
        kept.append(row)
    return kept


def manual_document_from_form(
    *,
    notes: str,
    findings: list[dict[str, Any]],
    disposition: str | None,
    completed: bool,
) -> dict[str, Any]:
    from review_ticket.util import iso_now

    if disposition:
        normalized = disposition.upper()
        if normalized not in {"APPROVE", "COMMENT", "REQUEST_CHANGES"}:
            raise WorkflowError("Disposition must be APPROVE, COMMENT, or REQUEST_CHANGES.")
    else:
        normalized = None
    return {
        "completed": completed,
        "notes": notes.strip(),
        "findings": findings,
        "disposition": normalized,
        "recorded_at": iso_now(),
    }
