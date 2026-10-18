"""Read-only automated review preparation model (P6, scenario D)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from review_ticket.storage import Store, read_json
from review_ticket.util import parse_pr_ref, require_issue_key, short_sha

PrepareStatus = Literal["current", "missing", "stale", "failed", "busy"]


@dataclass(frozen=True)
class PreparePrRow:
    ref: str
    owner: str
    repo: str
    number: int
    head_sha: str
    status: PrepareStatus
    status_label: str
    action_label: str
    detail: str
    generation_error: str | None
    import_context_path: str | None


@dataclass(frozen=True)
class PrepareProjection:
    issue: str
    rows: tuple[PreparePrRow, ...]


def project_automated_prepare(store: Store, issue: str) -> PrepareProjection:
    issue_key = require_issue_key(issue)
    session = read_json(store.issue_dir(issue_key) / "session.json") or {}
    active_prs = list(session.get("active_prs") or [])
    pr_shas: dict[str, str] = dict(session.get("pr_shas") or {})
    rows: list[PreparePrRow] = []
    for ref in active_prs:
        identity = parse_pr_ref(ref)
        owner, repo, number = identity
        head_sha = str(pr_shas.get(ref) or "")
        row = _prepare_row(store, issue_key, ref, owner, repo, number, head_sha)
        rows.append(row)
    return PrepareProjection(issue=issue_key, rows=tuple(rows))


def _prepare_row(
    store: Store,
    issue: str,
    ref: str,
    owner: str,
    repo: str,
    number: int,
    head_sha: str,
) -> PreparePrRow:
    if not head_sha:
        return PreparePrRow(
            ref=ref,
            owner=owner,
            repo=repo,
            number=number,
            head_sha="",
            status="missing",
            status_label="Missing",
            action_label="Generate",
            detail="No stored SHA for this pull request.",
            generation_error=None,
            import_context_path=None,
        )
    commit_dir = store.commit_dir(issue, owner, repo, number, head_sha)
    review_dir = commit_dir / "review"
    findings_path = review_dir / "findings.json"
    gen_status = read_json(review_dir / "generation-status.json") or {}
    import_path = None
    context_prompt = review_dir / "context" / "prompt.md"
    if context_prompt.exists():
        import_path = str(context_prompt)

    if gen_status.get("status") == "failed":
        error = str(gen_status.get("error") or "Generation failed.")
        return PreparePrRow(
            ref=ref,
            owner=owner,
            repo=repo,
            number=number,
            head_sha=head_sha,
            status="failed",
            status_label="Failed",
            action_label="Retry",
            detail=error,
            generation_error=error,
            import_context_path=import_path,
        )

    if findings_path.exists():
        return PreparePrRow(
            ref=ref,
            owner=owner,
            repo=repo,
            number=number,
            head_sha=head_sha,
            status="current",
            status_label="Current",
            action_label="View",
            detail=f"Automated findings exist for HEAD {short_sha(head_sha)}.",
            generation_error=None,
            import_context_path=None,
        )

    stale_sha = _find_stale_findings_sha(store, issue, owner, repo, number, head_sha)
    if stale_sha:
        return PreparePrRow(
            ref=ref,
            owner=owner,
            repo=repo,
            number=number,
            head_sha=head_sha,
            status="stale",
            status_label="Stale",
            action_label="Generate",
            detail=(
                f"No review for HEAD {short_sha(head_sha)}. "
                f"Older findings exist at {short_sha(stale_sha)}."
            ),
            generation_error=None,
            import_context_path=None,
        )

    return PreparePrRow(
        ref=ref,
        owner=owner,
        repo=repo,
        number=number,
        head_sha=head_sha,
        status="missing",
        status_label="Missing",
        action_label="Generate",
        detail=f"No automated review found for HEAD {short_sha(head_sha)}.",
        generation_error=None,
        import_context_path=import_path if context_prompt.exists() else None,
    )


def _find_stale_findings_sha(
    store: Store,
    issue: str,
    owner: str,
    repo: str,
    number: int,
    head_sha: str,
) -> str | None:
    commits = store.pr_dir(issue, owner, repo, number) / "commits"
    if not commits.exists():
        return None
    for path in sorted(item for item in commits.iterdir() if item.is_dir()):
        if path.name == head_sha:
            continue
        if (path / "review" / "findings.json").exists():
            return path.name
    return None


def write_generation_status(
    store: Store,
    issue: str,
    identity: tuple[str, str, int],
    sha: str,
    *,
    status: str,
    error: str | None = None,
) -> None:
    from review_ticket.util import iso_now

    review_dir = store.commit_dir(issue, identity[0], identity[1], identity[2], sha) / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, str] = {"status": status, "recorded_at": iso_now()}
    if error:
        payload["error"] = error
    from review_ticket.storage import write_json

    write_json(review_dir / "generation-status.json", payload)


def clear_generation_status(store: Store, issue: str, identity: tuple[str, str, int], sha: str) -> None:
    path = store.commit_dir(issue, identity[0], identity[1], identity[2], sha) / "review" / "generation-status.json"
    if path.exists():
        path.unlink()
