"""Read-only automated review preparation model (Scenario D)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from review_ticket.storage import Store
from review_ticket.status_projection import project_review_status
from review_ticket.util import short_sha

PrepareReviewStatus = Literal["current", "missing", "stale"]


@dataclass(frozen=True)
class PreparePrRow:
    ref: str
    owner: str
    repo: str
    number: int
    head_sha: str
    status: PrepareReviewStatus
    status_label: str
    view_sha: str
    snapshot_stale: bool
    historical: bool
    view_enabled: bool
    generate_enabled: bool
    row_action: str


@dataclass(frozen=True)
class PrepareProjection:
    issue: str
    issue_title: str | None
    session_exists: bool
    missing_session_message: str | None
    rows: tuple[PreparePrRow, ...]


_STATUS_LABELS = {
    "current": "Current",
    "missing": "Missing",
    "stale": "Stale",
}


def project_automated_review_prepare(store: Store, issue: str) -> PrepareProjection:
    status = project_review_status(store, issue)
    if not status.session_exists:
        return PrepareProjection(
            issue=status.issue,
            issue_title=status.issue_title,
            session_exists=False,
            missing_session_message=status.missing_session_message,
            rows=(),
        )
    rows = tuple(_prepare_row(store, status.issue, row) for row in status.pr_rows)
    return PrepareProjection(
        issue=status.issue,
        issue_title=status.issue_title,
        session_exists=True,
        missing_session_message=None,
        rows=rows,
    )


def _prepare_row(store: Store, issue: str, row) -> PreparePrRow:
    head = row.stored_sha
    identity = (row.owner, row.repo, row.number)
    head_findings = _has_findings(store, issue, identity, head)
    if head_findings:
        status: PrepareReviewStatus = "current"
        view_sha = head
    elif row.snapshot.stale or row.freshness.stale or _other_sha_has_findings(store, issue, identity, head):
        status = "stale"
        view_sha = row.snapshot.open_sha or head
    else:
        status = "missing"
        view_sha = head

    label = _STATUS_LABELS[status]
    view_enabled = status == "current"
    generate_enabled = status in {"missing", "stale"}
    action = "View" if view_enabled else "Generate"
    return PreparePrRow(
        ref=row.ref,
        owner=row.owner,
        repo=row.repo,
        number=row.number,
        head_sha=head,
        status=status,
        status_label=label,
        view_sha=view_sha,
        snapshot_stale=row.snapshot.stale,
        historical=bool(head and view_sha != head),
        view_enabled=view_enabled,
        generate_enabled=generate_enabled,
        row_action=action,
    )


def _review_dir(store: Store, issue: str, identity: tuple[str, str, int], sha: str):
    owner, repo, number = identity
    return store.commit_dir(issue, owner, repo, number, sha) / "review"


def _has_findings(store: Store, issue: str, identity: tuple[str, str, int], sha: str) -> bool:
    if not sha:
        return False
    return (_review_dir(store, issue, identity, sha) / "findings.json").is_file()


def _other_sha_has_findings(
    store: Store,
    issue: str,
    identity: tuple[str, str, int],
    head_sha: str,
) -> bool:
    owner, repo, number = identity
    commits = store.pr_dir(issue, owner, repo, number) / "commits"
    if not commits.exists():
        return False
    for path in commits.iterdir():
        if not path.is_dir() or path.name == head_sha:
            continue
        if (path / "review" / "findings.json").is_file():
            return True
    return False


def format_prepare_row_label(row: PreparePrRow) -> str:
    head = short_sha(row.head_sha) if row.head_sha else "—"
    return f"#{row.number} {row.owner}/{row.repo} {head}  {row.status_label}"


def format_prepare_detail(row: PreparePrRow, *, error: str | None = None, import_hint: str | None = None) -> str:
    head = short_sha(row.head_sha) if row.head_sha else "unknown"
    lines = [f"Selected: PR #{row.number} ({row.owner}/{row.repo})", ""]
    if error:
        lines.append(f"Generation failed: {error}")
        lines.append("Select Generate to retry.")
        lines.append("")
    if row.status == "current":
        lines.append(f"Automated review is current for HEAD {head}.")
    elif row.status == "missing":
        lines.append(f"No automated review found for HEAD {head}.")
    elif row.status == "stale":
        reviewed = short_sha(row.view_sha) if row.view_sha else "another SHA"
        lines.append(f"Only an older automated review exists ({reviewed}); HEAD is {head}.")
    if import_hint:
        lines.append("")
        lines.append(import_hint)
    return "\n".join(lines)


def import_handoff_hint(issue: str, report_path: str | None) -> str:
    context = report_path or "review/context/prompt.md"
    return (
        "No reviewer_command is configured. Review context was written; findings.json was not created.\n"
        f"Context: {context}\n"
        f"Next: review-ticket {issue} import-review --file PATH"
    )


def context_bundle_path(store: Store, issue: str, identity: tuple[str, str, int], sha: str) -> str:
    owner, repo, number = identity
    commit = store.commit_dir(issue, owner, repo, number, sha)
    review = commit / "review"
    context = review / "context" / "prompt.md"
    if context.is_file():
        return str(context)
    return str(review / "context")
