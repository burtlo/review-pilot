"""Markdown reports stored next to the JSON artifacts."""

from __future__ import annotations

from typing import Any


def issue_report(issue: dict[str, Any]) -> str:
    comments = issue.get("comments") or []
    rendered_comments = "\n\n".join(
        f"### {item.get('author') or 'comment'} {item.get('created') or ''}\n\n{item.get('body') or ''}".rstrip()
        for item in comments
    ) or "_No comments retrieved._"
    testing = issue.get("testing_notes") or "_No testing notes were found._"
    acceptance = issue.get("acceptance_criteria") or "_No acceptance criteria section was found._"
    return f"""# {issue.get('key')} — {issue.get('summary') or 'Untitled'}

Status: **{issue.get('status') or 'unknown'}**

{issue.get('url') or ''}

## Description

{issue.get('description') or '_No description._'}

## Acceptance criteria

{acceptance}

## Testing notes

{testing}

## Comments

{rendered_comments}
"""


def testing_notes_decision_preview(issue: dict[str, Any], *, report_path: str) -> str:
    testing = issue.get("testing_notes") or "_No testing notes were found._"
    acceptance = issue.get("acceptance_criteria") or "_No acceptance criteria section was found._"
    return f"""# Review testing notes — {issue.get('key')}

{issue.get('summary') or 'Untitled'} ({issue.get('status') or 'unknown'})
{issue.get('url') or ''}

## Acceptance criteria

{acceptance}

## Testing notes

{testing}

Full issue context: {report_path}
"""


def format_checks_table(checks: list[dict[str, Any]]) -> str:
    rows = ["| Check | Required | Status | State | Link |", "| --- | --- | --- | --- | --- |"]
    for check in checks:
        bucket = check.get("bucket") or ""
        status = _check_status_label(bucket)
        rows.append(
            "| {name} | {required} | {status} | {state} | {link} |".format(
                name=check.get("name") or "",
                required="yes" if check.get("required") else "no",
                status=status,
                state=check.get("state") or "",
                link=check.get("link") or "",
            )
        )
    return "\n".join(rows) if checks else "_No checks were reported._"


def _check_status_label(bucket: str) -> str:
    if bucket == "pass":
        return "pass"
    if bucket == "pending":
        return "pending"
    if bucket in {"fail", "cancel"}:
        return "fail"
    if bucket == "missing":
        return "missing"
    return bucket or "unknown"


def summarize_checks(checks: list[dict[str, Any]]) -> str:
    required = [item for item in checks if item.get("required")]
    if not required:
        optional = len(checks)
        return f"no required checks ({optional} other check(s) listed)" if optional else "no checks reported"
    pending = [item["name"] for item in required if item.get("bucket") == "pending"]
    failed = [item["name"] for item in required if item.get("bucket") in {"fail", "cancel"}]
    missing = [item["name"] for item in required if item.get("bucket") == "missing"]
    if pending:
        return "required waiting: " + ", ".join(pending)
    if failed:
        return "required failed: " + ", ".join(failed)
    if missing:
        return "required not reported: " + ", ".join(missing)
    return f"all {len(required)} required check(s) passed"


def summarize_findings(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return "no Bugbot or CodeQL threads"
    counts: dict[str, int] = {}
    for item in findings:
        attention = str(item.get("attention") or "unknown")
        counts[attention] = counts.get(attention, 0) + 1
    parts = [f"{count} {label}" for label, count in sorted(counts.items())]
    return ", ".join(parts)


def multi_pr_analyzer_report(sections: list[dict[str, Any]]) -> str:
    lines = ["# Analyzer review", "", "## Overview", ""]
    lines.append(
        "| Pull request | Link | CI (required) | Analyzer step | Findings |"
    )
    lines.append("| --- | --- | --- | --- | --- |")
    for section in sections:
        ref = section["pr_ref"]
        url = section.get("pr_url") or ""
        link_cell = f"[{ref}]({url})" if url else ref
        lines.append(
            "| {ref} | {link} | {checks} | {outcome} | {findings} |".format(
                ref=ref,
                link=link_cell,
                checks=section.get("checks_summary") or "",
                outcome=section.get("outcome") or "",
                findings=section.get("findings_summary") or "",
            )
        )
    lines.append("")
    for section in sections:
        ref = section["pr_ref"]
        url = section.get("pr_url") or ""
        lines.append(f"## {ref}")
        lines.append("")
        if url:
            lines.append(url)
            lines.append("")
        readiness = section.get("readiness_summary") or ""
        if readiness:
            lines.append(f"**Readiness:** {readiness}")
            lines.append("")
        lines.append("### CI checks")
        lines.append("")
        lines.append(section.get("checks_table") or "_No checks were stored._")
        lines.append("")
        lines.append("### Analyzer findings")
        lines.append("")
        lines.append((section.get("detail_markdown") or "").strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def multi_pr_readiness_report(sections: list[tuple[str, str, str]]) -> str:
    """sections: (pr_ref, outcome, markdown body without top-level title)."""
    lines = ["# Pull request readiness", ""]
    for ref, outcome, body in sections:
        lines.append(f"## {ref} — {outcome}")
        lines.append("")
        lines.append(body.strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def readiness_report(
    *,
    pr: dict[str, Any],
    checks: list[dict[str, Any]],
    outcome: str,
    summary: str,
) -> str:
    rows = ["| Check | Required | Bucket | State | Link |", "| --- | --- | --- | --- | --- |"]
    for check in checks:
        rows.append(
            "| {name} | {required} | {bucket} | {state} | {link} |".format(
                name=check.get("name") or "",
                required="yes" if check.get("required") else "no",
                bucket=check.get("bucket") or "",
                state=check.get("state") or "",
                link=check.get("link") or "",
            )
        )
    draft = "yes" if pr.get("draft") else "no"
    body = "\n".join(rows) if checks else "_No checks were reported._"
    return f"""# Readiness {pr.get('owner')}/{pr.get('repo')}#{pr.get('number')}

Outcome: **{outcome}**

{summary}

- Head: `{pr.get('head_branch')}` `{pr.get('head_sha')}`
- Base: `{pr.get('base_branch')}` `{pr.get('base_sha')}`
- Draft: {draft}
- URL: {pr.get('url') or ''}

{body}
"""


def analyzer_report(findings: list[dict[str, Any]], *, unavailable: str = "") -> str:
    lines = ["# Analyzer findings", ""]
    if unavailable:
        lines.append(f"Code scanning: {unavailable}")
        lines.append("")
    if not findings:
        lines.append("_No Bugbot or CodeQL findings were collected._")
        return "\n".join(lines) + "\n"
    for finding in findings:
        lines.append(f"## {finding.get('id')} ({finding.get('source')}, {finding.get('attention')})")
        lines.append("")
        where = finding.get("path") or "unknown file"
        if finding.get("line"):
            where = f"{where}:{finding['line']}"
        lines.append(f"Location: `{where}`")
        if finding.get("url"):
            lines.append(f"Link: {finding['url']}")
        if finding.get("commit"):
            lines.append(f"Commit: `{finding['commit']}`")
        lines.append("")
        lines.append(finding.get("body") or "")
        if finding.get("disposition"):
            lines.append("")
            lines.append("Developer disposition:")
            lines.append("")
            lines.append(finding["disposition"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _finding_on_diff(finding: dict[str, Any], diff_index: set[tuple[str, int, str]]) -> bool:
    path = finding.get("path")
    line = finding.get("line")
    side = finding.get("side") or "RIGHT"
    return bool(path) and isinstance(line, int) and (path, line, side) in diff_index


def publish_preview_counts_for_findings(
    findings: list[dict[str, Any]],
    diff_index: set[tuple[str, int, str]],
    *,
    human: dict[str, Any] | None = None,
) -> tuple[int, int]:
    """Inline vs summary-only counts for accepted findings (matches build_review_payload)."""
    if human and human.get("rejected_review"):
        return 0, 0
    inline = 0
    summary_only = 0
    decisions = (human or {}).get("findings") if human else None
    for finding in findings:
        if human:
            decision = (decisions or {}).get(finding["id"]) or {}
            if decision.get("decision") == "reject":
                continue
            if decision.get("decision") != "accept":
                continue
        elif finding.get("decision") == "reject":
            continue
        if _finding_on_diff(finding, diff_index):
            inline += 1
        else:
            summary_only += 1
    return inline, summary_only


def review_preview(
    *,
    sha: str,
    document: dict[str, Any],
    findings: list[dict[str, Any]],
    diff_index: set[tuple[str, int, str]],
    human: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    lines = [f"# Review preview `{sha}`", ""]
    summary = (human or {}).get("summary") or document.get("summary") or ""
    if summary.strip():
        lines.extend(["## Summary", "", summary.rstrip(), ""])
    if human and human.get("rejected_review"):
        lines.extend(
            [
                "## Publish preview",
                "",
                "The automated review was **rejected**. Nothing will be published.",
                "",
            ]
        )
    else:
        inline, summary_only = publish_preview_counts_for_findings(findings, diff_index, human=human)
        if payload:
            inline = len(payload.get("comments") or [])
        event = (payload or {}).get("event") or (human or {}).get("event") or ""
        lines.extend(["## Publish preview", ""])
        if event:
            lines.append(f"GitHub review event: **{event}**")
            lines.append("")
        lines.append(f"- **{inline}** inline comment(s) on the diff")
        lines.append(f"- **{summary_only}** finding(s) in the review summary only")
        if not human:
            lines.append("")
            lines.append(
                "_Counts assume all findings are accepted until you record a human review "
                "(`review apply` or `review interactive`)._"
            )
        lines.append("")
    lines.extend(["## Findings", ""])
    if not findings:
        lines.append("_No findings were recorded._")
    else:
        decisions = (human or {}).get("findings") if human else None
        for finding in findings:
            fid = finding.get("id") or ""
            title = finding.get("title") or "Untitled"
            if human and human.get("rejected_review"):
                triage = "n/a"
            elif human:
                entry = (decisions or {}).get(fid) or {}
                triage = entry.get("decision") or "undecided"
            else:
                triage = "pending"
            must = "must-fix" if finding.get("must_fix") else "suggestion"
            priority = finding.get("priority") or "medium"
            where = finding.get("path") or "general"
            if finding.get("line"):
                where = f"{where}:{finding['line']}"
            placement = (
                "inline on diff"
                if _finding_on_diff(finding, diff_index)
                else "summary only (off diff or no line)"
            )
            if triage == "reject":
                placement = "will not publish"
            lines.append(f"### {fid} {title}")
            lines.append("")
            lines.append(f"- Triage: **{triage}** · {must} · {priority}")
            lines.append(f"- Location: `{where}` · {placement}")
            explanation = finding.get("explanation") or ""
            if human and not human.get("rejected_review"):
                entry = (decisions or {}).get(fid) or {}
                if entry.get("explanation"):
                    explanation = str(entry["explanation"])
            if explanation.strip():
                lines.append("")
                lines.append(explanation.rstrip())
            if finding.get("suggested_change"):
                lines.extend(["", "Suggested change:", "", "```", str(finding["suggested_change"]).rstrip(), "```"])
            lines.append("")
    lines.extend(
        [
            "## File-based triage",
            "",
            "Without the interactive TUI, edit decisions in `human-review.json` and run "
            "`review apply --file human-review.json`, or use `review apply` flags. "
            "`reviewer-report.md` is the automated reviewer narrative; this file focuses on "
            "publish placement and triage status.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def reviewer_report(document: dict[str, Any], findings: list[dict[str, Any]], reconciliation: list[dict[str, Any]]) -> str:
    lines = ["# Automated review", ""]
    if document.get("summary"):
        lines.extend([document["summary"].rstrip(), ""])
    recommendation = document.get("approval_recommendation") or ""
    if recommendation:
        lines.extend([f"Approval recommendation: **{recommendation}**", ""])
    lines.append("## Findings")
    lines.append("")
    if not findings:
        lines.append("_The reviewer reported no findings._")
    for finding in findings:
        where = finding.get("path") or "general"
        if finding.get("line"):
            where = f"{where}:{finding['line']}"
        lines.append(
            f"### {finding['id']} {finding['title']} "
            f"({finding['priority']}, must-fix={str(finding['must_fix']).lower()})"
        )
        lines.append("")
        lines.append(f"Location: `{where}` side `{finding.get('side')}`")
        lines.append("")
        lines.append(finding["explanation"].rstrip())
        if finding.get("suggested_change"):
            lines.extend(["", "Suggested change:", "", "```", str(finding["suggested_change"]).rstrip(), "```"])
        lines.append("")
    if reconciliation:
        lines.extend(["## Previous findings", ""])
        for row in reconciliation:
            lines.append(
                f"- {row['previous_id']} {row.get('title') or ''}: {row['status']}"
                + (f" → {row['current_id']}" if row.get("current_id") else "")
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def return_comment(*, issue: str, reason: str, notes: str, links: list[str] | None = None) -> str:
    extra = ""
    if links:
        extra = "\n\n## Findings\n\n" + "\n".join(f"- {link}" for link in links)
    reviewer = f"\n\n## Reviewer notes\n\n{notes.strip()}" if notes.strip() else ""
    return (
        f"Peer review is returning {issue} to In Progress.\n\n"
        f"{reason.strip()}"
        f"{extra}"
        f"{reviewer}\n"
    )


def test_plan(
    *,
    issue: dict[str, Any],
    sha: str,
    findings: list[dict[str, Any]],
    prior_failures: list[str],
) -> str:
    criteria = issue.get("acceptance_criteria") or "_No acceptance criteria were recorded._"
    finding_lines = [
        f"- {item.get('id')} {item.get('title')} (`{item.get('path') or 'general'}`)"
        for item in findings
        if item.get("decision", "accept") != "reject"
    ] or ["- No review findings were carried into this plan."]
    failures = [f"- {item}" for item in prior_failures] or ["- None recorded."]
    return f"""# Test plan {issue.get('key')} @ `{sha}`

Scenarios below are a starting point for the human tester. They are not a pass by themselves.

## Acceptance criteria

{criteria}

## Review findings to exercise

{chr(10).join(finding_lines)}

## Prior functional failures

{chr(10).join(failures)}

## Exploratory notes

- Compare the current behavior with the acceptance criteria, not only with the previous review.
- Record environment failures separately from implementation failures.
"""


def test_results_markdown(result: dict[str, Any]) -> str:
    evidence = result.get("evidence") or []
    evidence_lines = [f"- `{item}`" for item in evidence] or ["- None."]
    scenarios = result.get("scenarios") or []
    scenario_lines = [f"- {item}" for item in scenarios] or ["- None recorded."]
    return f"""# Test results `{result.get('sha')}`

Result: **{result.get('result')}**
Failure kind: {result.get('failure_kind') or 'n/a'}
Image: `{result.get('image') or ''}`
Digest: `{result.get('digest') or ''}`

## Scenarios

{chr(10).join(scenario_lines)}

## Notes

{result.get('notes') or '_No notes._'}

## Evidence

{chr(10).join(evidence_lines)}
"""


def functional_comment(result: dict[str, Any], *, pr_url: str = "") -> str:
    lines = [
        f"## Functional testing `{result.get('sha', '')[:12]}`",
        "",
        f"Result: **{result.get('result')}**",
    ]
    if result.get("failure_kind"):
        lines.append(f"Classification: {result['failure_kind']}")
    if result.get("digest"):
        lines.append(f"Image digest: `{result['digest']}`")
    lines.extend(["", "### Notes", "", result.get("notes") or "_No notes._", "", "### Scenarios", ""])
    for scenario in result.get("scenarios") or []:
        lines.append(f"- {scenario}")
    if not result.get("scenarios"):
        lines.append("- None recorded.")
    lines.extend(["", "### Evidence", ""])
    for item in result.get("evidence") or []:
        suffix = str(item).rsplit(".", 1)[-1].lower()
        if suffix in {"png", "jpg", "jpeg", "gif", "webp"}:
            lines.append(f"![evidence]({item})")
        elif suffix in {"mp4", "mov", "webm"}:
            lines.append(f"[video]({item})")
        else:
            lines.append(f"- `{item}`")
    if pr_url:
        lines.extend(["", pr_url])
    return "\n".join(lines).rstrip() + "\n"


def disposition_report(checklist: list[dict[str, Any]], *, sha: str) -> str:
    lines = [f"# Disposition `{sha}`", ""]
    for item in checklist:
        mark = "pass" if item["ok"] else "fail"
        lines.append(f"- [{mark}] {item['detail']}")
    lines.append("")
    return "\n".join(lines)


def reviewer_prompt(*, issue: str, sha: str, output_path: str) -> str:
    return f"""# Reviewer context for {issue} @ {sha}

Review the full pull request at this SHA. A re-review is not limited to the diff since the previous SHA.
Use the Jira acceptance criteria, testing notes, diff, coding standards, analyzer dispositions, and previous findings in this directory.

Write a JSON file to `{output_path}` with this shape:

```json
{{
  "summary": "Overall assessment",
  "approval_recommendation": "approve | comment | request_changes",
  "findings": [
    {{
      "id": "F001",
      "priority": "high",
      "must_fix": true,
      "path": "src/Example.cs",
      "line": 142,
      "side": "RIGHT",
      "title": "Missing validation",
      "explanation": "This path permits an invalid state.",
      "suggested_change": "optional replacement text",
      "reconciles": "F001",
      "reconciliation_status": "resolved | still_present | partially_resolved | no_longer_applicable | requires_additional_verification"
    }}
  ]
}}
```

Findings that do not belong on a changed line must still be included. Leave path or line empty rather than inventing a location.
Do not publish to GitHub. This command only records the local review.
"""
