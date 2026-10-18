"""Structured reviewer findings and GitHub review payloads."""

from __future__ import annotations

from typing import Any

from review_ticket.models import WorkflowError


PRIORITIES = {"high", "medium", "low"}
SIDES = {"RIGHT", "LEFT"}
RECONCILIATION = {
    "resolved",
    "still_present",
    "partially_resolved",
    "no_longer_applicable",
    "requires_additional_verification",
}


def normalize_findings(payload: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if isinstance(payload, list):
        document = {"summary": "", "findings": payload}
    elif isinstance(payload, dict):
        document = payload
    else:
        raise WorkflowError("Reviewer output must be a JSON object or a list of findings.")
    raw_findings = document.get("findings", [])
    if not isinstance(raw_findings, list):
        raise WorkflowError("Reviewer output field 'findings' must be a list.")
    findings: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_findings, start=1):
        if not isinstance(raw, dict):
            raise WorkflowError(f"Finding {index} is not an object.")
        title = str(raw.get("title") or "").strip()
        explanation = str(raw.get("explanation") or raw.get("body") or "").strip()
        if not title or not explanation:
            raise WorkflowError(f"Finding {index} needs a title and an explanation.")
        priority = str(raw.get("priority") or "medium").lower()
        if priority not in PRIORITIES:
            raise WorkflowError(f"Finding {title!r} has unknown priority {priority!r}.")
        side = str(raw.get("side") or "RIGHT").upper()
        if side not in SIDES:
            raise WorkflowError(f"Finding {title!r} has unknown side {side!r}.")
        line = raw.get("line")
        if line is not None and not isinstance(line, int):
            raise WorkflowError(f"Finding {title!r} line must be an integer.")
        start_line = raw.get("start_line")
        if start_line is not None and not isinstance(start_line, int):
            raise WorkflowError(f"Finding {title!r} start_line must be an integer.")
        status = raw.get("reconciliation_status")
        if status is not None and status not in RECONCILIATION:
            raise WorkflowError(f"Finding {title!r} has unknown reconciliation status {status!r}.")
        finding = {
            "id": str(raw.get("id") or f"F{index:03d}"),
            "priority": priority,
            "must_fix": bool(raw.get("must_fix", False)),
            "path": raw.get("path") or None,
            "line": line,
            "start_line": start_line,
            "side": side,
            "title": title,
            "explanation": explanation,
            "suggested_change": raw.get("suggested_change") or None,
            "reconciles": raw.get("reconciles") or None,
            "reconciliation_status": status,
        }
        findings.append(finding)
    return document, findings


def suggestion_ok(suggestion: str | None) -> bool:
    if not suggestion or not str(suggestion).strip():
        return False
    if "```" in suggestion:
        return False
    return True


def render_finding_body(finding: dict[str, Any]) -> str:
    priority = finding.get("priority", "medium")
    label = "Must-fix" if finding.get("must_fix") else "Suggestion"
    body = f"**{finding['title']}** ({label}, {priority})\n\n{finding['explanation'].rstrip()}\n"
    if finding.get("path") and suggestion_ok(finding.get("suggested_change")) and finding.get("_inline"):
        change = str(finding["suggested_change"]).strip("\n")
        body += f"\n```suggestion\n{change}\n```\n"
    return body


def build_review_payload(
    *,
    sha: str,
    event: str,
    summary: str,
    findings: list[dict[str, Any]],
    diff_index: set[tuple[str, int, str]],
) -> dict[str, Any]:
    if event not in {"COMMENT", "APPROVE", "REQUEST_CHANGES"}:
        raise WorkflowError(f"Unsupported GitHub review event {event!r}.")
    comments: list[dict[str, Any]] = []
    general: list[dict[str, Any]] = []
    accepted_must_fix = False
    for finding in findings:
        if finding.get("decision") == "reject":
            continue
        if finding.get("must_fix"):
            accepted_must_fix = True
        path = finding.get("path")
        line = finding.get("line")
        side = finding.get("side") or "RIGHT"
        inline = bool(path) and isinstance(line, int) and (path, line, side) in diff_index
        prepared = dict(finding)
        prepared["_inline"] = inline
        body = render_finding_body(prepared)
        if inline:
            comment: dict[str, Any] = {
                "path": path,
                "line": line,
                "side": side,
                "body": body,
            }
            start_line = finding.get("start_line")
            if isinstance(start_line, int) and start_line != line and (path, start_line, side) in diff_index:
                comment["start_line"] = start_line
                comment["start_side"] = side
            comments.append(comment)
        else:
            general.append(finding)
    if event == "APPROVE" and accepted_must_fix:
        raise WorkflowError("Refusing to approve while accepted must-fix findings remain.")
    general_text = _general_section(general)
    full_body = summary.strip()
    if general_text:
        full_body = (full_body + "\n\n" + general_text).strip()
    if not full_body:
        full_body = "Peer review notes."
    return {
        "commit_id": sha,
        "body": full_body + "\n",
        "event": event,
        "comments": comments,
    }


def _general_section(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return ""
    lines = ["## Findings outside the diff", ""]
    for finding in findings:
        where = finding.get("path") or "general"
        if finding.get("line"):
            where = f"{where}:{finding['line']}"
        label = "must-fix" if finding.get("must_fix") else "suggestion"
        lines.append(f"### {finding.get('id', '')} {finding['title']} ({label})")
        lines.append("")
        lines.append(finding["explanation"].rstrip())
        lines.append("")
        lines.append(f"Location: `{where}`")
        if finding.get("suggested_change"):
            lines.append("")
            lines.append("Suggested change:")
            lines.append("")
            lines.append("```")
            lines.append(str(finding["suggested_change"]).rstrip())
            lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip()


def reconcile(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify earlier findings. Unmentioned findings stay unverified."""

    linked: dict[str, dict[str, Any]] = {}
    for finding in current:
        target = finding.get("reconciles")
        if target:
            linked[str(target)] = finding
    rows: list[dict[str, Any]] = []
    current_ids = {finding["id"] for finding in current}
    for prior in previous:
        prior_id = prior["id"]
        match = linked.get(prior_id)
        if match is not None:
            status = match.get("reconciliation_status") or "still_present"
            current_id = match["id"]
        elif prior_id in current_ids:
            status = "still_present"
            current_id = prior_id
        else:
            status = "requires_additional_verification"
            current_id = None
        if status not in RECONCILIATION:
            status = "requires_additional_verification"
        rows.append(
            {
                "previous_id": prior_id,
                "title": prior.get("title"),
                "status": status,
                "current_id": current_id,
            }
        )
    return rows


def apply_human_decisions(
    findings: list[dict[str, Any]],
    human: dict[str, Any],
) -> list[dict[str, Any]]:
    decisions = human.get("findings") or {}
    if not isinstance(decisions, dict):
        raise WorkflowError("human review 'findings' must be an object keyed by finding id.")
    merged: list[dict[str, Any]] = []
    for finding in findings:
        decision = decisions.get(finding["id"])
        if not isinstance(decision, dict) or decision.get("decision") not in {"accept", "reject"}:
            raise WorkflowError(
                f"Finding {finding['id']} has no accept/reject decision. "
                "Decide each finding before publication."
            )
        item = dict(finding)
        item["decision"] = decision["decision"]
        if "must_fix" in decision:
            item["must_fix"] = bool(decision["must_fix"])
        if decision.get("explanation"):
            item["explanation"] = str(decision["explanation"])
        if "suggested_change" in decision:
            item["suggested_change"] = decision["suggested_change"]
        merged.append(item)
    for index, added in enumerate(human.get("added") or [], start=1):
        if not isinstance(added, dict):
            raise WorkflowError("Added findings must be objects.")
        _document, normalized = normalize_findings({"findings": [added]})
        item = normalized[0]
        if not added.get("id"):
            item["id"] = f"M{index:03d}"
        item["decision"] = "accept"
        item["source"] = "human"
        merged.append(item)
    return merged


def normalize_inline_comment_body(body: str) -> str:
    """Collapse whitespace for duplicate inline comment detection (spec §10.1)."""
    return " ".join(str(body or "").split())


def _automated_inline_body(finding: dict[str, Any]) -> str:
    return normalize_inline_comment_body(str(finding.get("explanation") or finding.get("body") or ""))


def manual_finding_duplicates_automated(
    manual: dict[str, Any],
    selected_automated: list[dict[str, Any]],
) -> bool:
    path = manual.get("path")
    line = manual.get("line")
    if not path or not isinstance(line, int):
        return False
    body = normalize_inline_comment_body(str(manual.get("text") or ""))
    if not body:
        return False
    for finding in selected_automated:
        if finding.get("decision") == "reject":
            continue
        if finding.get("path") != path or finding.get("line") != line:
            continue
        if _automated_inline_body(finding) == body:
            return True
    return False


def manual_findings_for_publication(
    manual_findings: list[dict[str, Any]],
    *,
    selected_automated: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Manual inline findings to include in a publication preview (duplicates removed)."""
    rows: list[dict[str, Any]] = []
    for item in manual_findings:
        if not isinstance(item, dict):
            continue
        if manual_finding_duplicates_automated(item, selected_automated):
            continue
        rows.append(item)
    return rows


def manual_finding_as_review_row(row: dict[str, Any], *, index: int) -> dict[str, Any]:
    """Shape a manual finding like an automated row for build_review_payload."""
    return {
        "id": str(row.get("finding_id") or f"M{index:03d}"),
        "title": "Manual finding",
        "explanation": str(row.get("text") or "").strip(),
        "must_fix": bool(row.get("blocking")),
        "path": row.get("path"),
        "line": row.get("line"),
        "side": "RIGHT",
        "priority": "medium",
        "decision": "accept",
        "source": "manual",
    }


def assemble_publication_findings(
    document: dict[str, Any],
    human: dict[str, Any],
    manual_review: dict[str, Any] | None,
    *,
    selection: dict[str, bool] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Selected and omitted findings for GitHub publication (automated + manual)."""
    if human.get("rejected_review"):
        automated: list[dict[str, Any]] = []
    else:
        automated = apply_human_decisions(document.get("findings") or [], human)
    accepted_auto = [item for item in automated if item.get("decision") != "reject"]
    manual_rows = manual_findings_for_publication(
        list((manual_review or {}).get("findings") or []),
        selected_automated=accepted_auto,
    )
    manual_as_findings = [
        manual_finding_as_review_row(row, index=index) for index, row in enumerate(manual_rows, start=1)
    ]
    candidates = automated + manual_as_findings
    selected: list[dict[str, Any]] = []
    omitted: list[dict[str, Any]] = []
    for finding in candidates:
        fid = str(finding.get("id") or "")
        if finding.get("decision") == "reject":
            omitted.append({**finding, "_omit_reason": "excluded during automated triage"})
            continue
        if selection is not None and fid and not selection.get(fid, True):
            omitted.append({**finding, "_omit_reason": "not selected for publication"})
            continue
        selected.append(finding)
    return selected, omitted
