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
