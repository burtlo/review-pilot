"""Read-only GitHub review composition model (spec §13)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from review_ticket.findings import assemble_publication_findings, build_review_payload
from review_ticket.policy import functional_testing_passed, manual_review_is_complete
from review_ticket.storage import Store, read_json
from review_ticket.util import fingerprint, short_sha


def blocker_confirmed_on_any_track(
    *,
    human_review: dict[str, Any] | None,
    manual_review: dict[str, Any] | None,
    test_results: dict[str, Any] | None,
) -> bool:
    """True when Request Changes is allowed before later tracks finish."""
    if isinstance(human_review, dict):
        disposition = str(human_review.get("disposition") or human_review.get("event") or "").upper()
        if disposition == "REQUEST_CHANGES" and human_review.get("blocker_confirmed"):
            return True
    if isinstance(manual_review, dict):
        disposition = str(manual_review.get("disposition") or "").upper()
        if disposition == "REQUEST_CHANGES" and manual_review.get("p9_handoff"):
            return True
    if isinstance(test_results, dict):
        disposition = str(test_results.get("disposition") or "").upper()
        if disposition == "REQUEST_CHANGES" and test_results.get("p9_handoff"):
            return True
    return False


@dataclass(frozen=True)
class ComposeFindingRow:
    finding_id: str
    kind: str
    title: str
    selected: bool
    omitted: bool
    omit_reason: str | None


@dataclass(frozen=True)
class ComposeOutcomeButtons:
    approve_enabled: bool
    comment_enabled: bool
    request_changes_enabled: bool
    approve_reason: str | None
    comment_reason: str | None
    request_changes_reason: str | None


@dataclass(frozen=True)
class ComposeProjection:
    owner: str
    repo: str
    number: int
    sha: str
    read_only: bool
    read_only_reason: str | None
    summary: str
    event: str
    rows: tuple[ComposeFindingRow, ...]
    selected_count: int
    omitted_count: int
    buttons: ComposeOutcomeButtons
    payload: dict[str, Any]
    payload_fingerprint: str
    preview_text: str


def _default_summary(
    human: dict[str, Any],
    document: dict[str, Any],
    test_results: dict[str, Any] | None,
) -> str:
    draft = str(human.get("summary") or document.get("summary") or "").strip()
    notes = str((test_results or {}).get("notes") or "").strip()
    if notes and notes not in draft:
        if draft:
            return f"{draft}\n\n## Functional testing\n\n{notes}"
        return notes
    return draft or "Peer review."


def _selection_from_draft(draft: dict[str, Any] | None, rows: list[ComposeFindingRow]) -> dict[str, bool]:
    if not draft:
        return {row.finding_id: row.selected for row in rows if not row.omitted}
    raw = draft.get("selection")
    if not isinstance(raw, dict):
        return {row.finding_id: not row.omitted for row in rows}
    return {row.finding_id: bool(raw.get(row.finding_id, not row.omitted)) for row in rows}


def project_github_compose(
    store: Store,
    issue: str,
    owner: str,
    repo: str,
    number: int,
    sha: str,
    *,
    diff_index: set[tuple[str, int, str]],
    stale: bool = False,
    historical: bool = False,
) -> ComposeProjection:
    commit_dir = store.commit_dir(issue, owner, repo, number, sha)
    review_dir = commit_dir / "review"
    document = read_json(review_dir / "findings.json") or {}
    human = read_json(review_dir / "human-review.json") or {}
    manual = read_json(review_dir / "manual-review.json")
    testing_dir = commit_dir / "testing"
    test_results = read_json(testing_dir / "test-results.json")
    environment = read_json(testing_dir / "environment.json")
    draft = read_json(review_dir / "publication-draft.json")
    if draft and draft.get("sha") != sha:
        draft = None

    selected_findings, omitted_findings = assemble_publication_findings(
        document,
        human,
        manual,
        selection=None,
    )
    provisional_rows: list[ComposeFindingRow] = []
    for finding in selected_findings:
        kind = "Manual" if finding.get("source") == "manual" else "Automated"
        provisional_rows.append(
            ComposeFindingRow(
                finding_id=str(finding["id"]),
                kind=kind,
                title=str(finding.get("title") or finding["id"]),
                selected=True,
                omitted=False,
                omit_reason=None,
            )
        )
    for finding in omitted_findings:
        kind = "Manual" if finding.get("source") == "manual" else "Automated"
        provisional_rows.append(
            ComposeFindingRow(
                finding_id=str(finding.get("id") or ""),
                kind=kind,
                title=str(finding.get("title") or finding.get("id") or "finding"),
                selected=False,
                omitted=True,
                omit_reason=str(finding.get("_omit_reason") or "omitted"),
            )
        )

    selection = _selection_from_draft(draft, provisional_rows)
    selected_findings, omitted_findings = assemble_publication_findings(
        document,
        human,
        manual,
        selection=selection,
    )
    rows: list[ComposeFindingRow] = []
    for finding in selected_findings:
        kind = "Manual" if finding.get("source") == "manual" else "Automated"
        rows.append(
            ComposeFindingRow(
                finding_id=str(finding["id"]),
                kind=kind,
                title=str(finding.get("title") or finding["id"]),
                selected=True,
                omitted=False,
                omit_reason=None,
            )
        )
    for finding in omitted_findings:
        kind = "Manual" if finding.get("source") == "manual" else "Automated"
        rows.append(
            ComposeFindingRow(
                finding_id=str(finding.get("id") or ""),
                kind=kind,
                title=str(finding.get("title") or finding.get("id") or "finding"),
                selected=False,
                omitted=True,
                omit_reason=str(finding.get("_omit_reason") or "omitted"),
            )
        )

    summary = str((draft or {}).get("summary") or _default_summary(human, document, test_results))
    event = str((draft or {}).get("event") or human.get("event") or "COMMENT").upper()
    if event not in {"APPROVE", "COMMENT", "REQUEST_CHANGES"}:
        event = "COMMENT"

    manual_complete = manual_review_is_complete(manual, sha)
    functional_pass = functional_testing_passed(test_results, sha, environment)
    blocker = blocker_confirmed_on_any_track(
        human_review=human,
        manual_review=manual,
        test_results=test_results,
    )
    buttons = ComposeOutcomeButtons(
        approve_enabled=manual_complete and functional_pass,
        comment_enabled=manual_complete,
        request_changes_enabled=blocker,
        approve_reason=None
        if manual_complete and functional_pass
        else "Approve needs completed manual review and a passing functional test for this SHA.",
        comment_reason=None if manual_complete else "Comment needs completed manual code review for this SHA.",
        request_changes_reason=None
        if blocker
        else "Request Changes needs a confirmed blocker on automated, manual, or functional track.",
    )

    payload = build_review_payload(
        sha=sha,
        event=event,
        summary=summary,
        findings=selected_findings,
        diff_index=diff_index,
    )
    digest = fingerprint(payload)
    preview_text = format_publication_preview_text(
        owner=owner,
        repo=repo,
        number=number,
        sha=sha,
        event=event,
        summary=summary,
        payload=payload,
        omitted=omitted_findings,
    )

    read_only = stale or historical
    read_only_reason = None
    if historical:
        read_only_reason = "Historical SHA — publication is read-only."
    elif stale:
        read_only_reason = "HEAD moved — refresh before publishing."

    return ComposeProjection(
        owner=owner,
        repo=repo,
        number=number,
        sha=sha,
        read_only=read_only,
        read_only_reason=read_only_reason,
        summary=summary,
        event=event,
        rows=tuple(rows),
        selected_count=len(selected_findings),
        omitted_count=len(omitted_findings),
        buttons=buttons,
        payload=payload,
        payload_fingerprint=digest,
        preview_text=preview_text,
    )


def format_publication_preview_text(
    *,
    owner: str,
    repo: str,
    number: int,
    sha: str,
    event: str,
    summary: str,
    payload: dict[str, Any],
    omitted: list[dict[str, Any]],
) -> str:
    lines = [
        f"Repository: {owner}/{repo}",
        f"Pull request: #{number}",
        f"Reviewed SHA: {sha} ({short_sha(sha)})",
        f"Outcome: {event}",
        f"Inline comments: {len(payload.get('comments') or [])}",
        "",
        "General comment:",
        summary.rstrip(),
        "",
    ]
    for comment in payload.get("comments") or []:
        lines.append(f"Inline: {comment['path']}:{comment['line']} ({comment['side']})")
        lines.append(str(comment.get("body") or "").rstrip())
        lines.append("")
    if omitted:
        lines.append("Omitted findings (not published):")
        for finding in omitted:
            label = finding.get("title") or finding.get("id")
            reason = finding.get("_omit_reason") or "omitted"
            lines.append(f"- [{finding.get('source') or 'automated'}] {label} — {reason}")
        lines.append("")
    lines.append(f"Body fingerprint: {fingerprint(payload)}")
    return "\n".join(lines).rstrip() + "\n"
