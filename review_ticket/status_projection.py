"""Read-only status screen model from on-disk review artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from review_ticket.storage import Store, read_json
from review_ticket.util import parse_pr_ref, require_issue_key, short_sha

ReviewProgressKind = Literal["no_snapshot", "undecided", "recorded"]


@dataclass(frozen=True)
class CheckRow:
    name: str
    required: bool
    bucket: str
    state: str
    link: str


@dataclass(frozen=True)
class PrChecks:
    outcome: str | None
    summary: str | None
    rows: tuple[CheckRow, ...]


@dataclass(frozen=True)
class SnapshotSelection:
    stored_sha: str
    open_sha: str
    stale: bool


@dataclass(frozen=True)
class ReviewProgress:
    kind: ReviewProgressKind
    label: str
    sha: str


@dataclass(frozen=True)
class PrStatusRow:
    ref: str
    owner: str
    repo: str
    number: int
    stored_sha: str
    url: str
    progress: ReviewProgress
    checks: PrChecks
    snapshot: SnapshotSelection


@dataclass(frozen=True)
class StatusProjection:
    issue: str
    session_exists: bool
    missing_session_message: str | None
    current_step: str | None
    last_completed_step: str | None
    outcome: str | None
    next_command: str | None
    pr_rows: tuple[PrStatusRow, ...]


def project_review_status(store: Store, issue: str) -> StatusProjection:
    """Build the status screen model from ``session.json`` and stored PR artifacts."""
    issue_key = require_issue_key(issue)
    session_path = store.issue_dir(issue_key) / "session.json"
    if not session_path.exists():
        return StatusProjection(
            issue=issue_key,
            session_exists=False,
            missing_session_message="No review session exists yet.",
            current_step=None,
            last_completed_step=None,
            outcome=None,
            next_command=None,
            pr_rows=(),
        )
    session = read_json(session_path) or {}
    refs = _active_pr_refs(session)
    pr_rows: list[PrStatusRow] = []
    for ref in refs:
        owner, repo, number = parse_pr_ref(ref)
        stored_sha = _stored_sha(session, ref)
        identity = (owner, repo, number)
        open_sha, stale = _select_open_snapshot(store, issue_key, identity, stored_sha)
        pr_rows.append(
            PrStatusRow(
                ref=ref,
                owner=owner,
                repo=repo,
                number=number,
                stored_sha=stored_sha,
                url=pr_url_for_ref(store, issue_key, ref),
                progress=_review_progress(store, issue_key, identity, stored_sha),
                checks=_load_checks(store, issue_key, identity, stored_sha),
                snapshot=SnapshotSelection(stored_sha=stored_sha, open_sha=open_sha, stale=stale),
            )
        )
    return StatusProjection(
        issue=issue_key,
        session_exists=True,
        missing_session_message=None,
        current_step=session.get("current_step"),
        last_completed_step=session.get("last_completed_step"),
        outcome=session.get("outcome"),
        next_command=session.get("next_command"),
        pr_rows=tuple(pr_rows),
    )


def pr_url_for_ref(store: Store, issue: str, ref: str) -> str:
    try:
        owner, repo, number = parse_pr_ref(ref)
    except ValueError:
        return ""
    pr = read_json(store.pr_dir(issue, owner, repo, number) / "pr.json") or {}
    url = str(pr.get("url") or "").strip()
    if url:
        return url
    return f"https://github.com/{owner}/{repo}/pull/{number}"


def _active_pr_refs(session: dict[str, Any]) -> list[str]:
    refs = [str(item) for item in session.get("active_prs") or [] if item]
    if not refs and session.get("active_pr"):
        refs = [str(session["active_pr"])]
    return refs


def _stored_sha(session: dict[str, Any], ref: str) -> str:
    pr_shas: dict[str, str] = session.get("pr_shas") or {}
    sha = pr_shas.get(ref)
    if not sha and ref == session.get("active_pr"):
        sha = session.get("active_sha")
    return str(sha or "")


def _review_dir(store: Store, issue: str, identity: tuple[str, str, int], sha: str):
    owner, repo, number = identity
    return store.commit_dir(issue, owner, repo, number, sha) / "review"


def _review_progress(
    store: Store,
    issue: str,
    identity: tuple[str, str, int],
    stored_sha: str,
) -> ReviewProgress:
    short = short_sha(stored_sha) if stored_sha else ""
    review_dir = _review_dir(store, issue, identity, stored_sha)
    if not stored_sha or not (review_dir / "findings.json").exists():
        label = f"No snapshot at {short}" if short else "No snapshot"
        return ReviewProgress(kind="no_snapshot", label=label, sha=stored_sha)
    if not (review_dir / "human-review.json").exists():
        return ReviewProgress(kind="undecided", label=f"Undecided at {short}", sha=stored_sha)
    return ReviewProgress(
        kind="recorded",
        label=f"Human review recorded at {short}",
        sha=stored_sha,
    )


def _load_checks(
    store: Store,
    issue: str,
    identity: tuple[str, str, int],
    sha: str,
) -> PrChecks:
    if not sha:
        return PrChecks(outcome=None, summary=None, rows=())
    owner, repo, number = identity
    payload = read_json(store.commit_dir(issue, owner, repo, number, sha) / "github-checks.json")
    if not payload:
        return PrChecks(outcome=None, summary=None, rows=())
    rows: list[CheckRow] = []
    for item in payload.get("checks") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            CheckRow(
                name=str(item.get("name") or ""),
                required=bool(item.get("required")),
                bucket=str(item.get("bucket") or ""),
                state=str(item.get("state") or ""),
                link=str(item.get("link") or ""),
            )
        )
    outcome = payload.get("outcome")
    summary = payload.get("summary")
    return PrChecks(
        outcome=str(outcome) if outcome is not None else None,
        summary=str(summary) if summary is not None else None,
        rows=tuple(rows),
    )


def _select_open_snapshot(
    store: Store,
    issue: str,
    identity: tuple[str, str, int],
    stored_sha: str,
) -> tuple[str, bool]:
    if not stored_sha:
        return "", False
    owner, repo, number = identity
    stored_review = _review_dir(store, issue, identity, stored_sha)
    if (stored_review / "findings.json").exists():
        return stored_sha, False
    commits_root = store.pr_dir(issue, owner, repo, number) / "commits"
    alternatives: list[tuple[str, float]] = []
    if commits_root.exists():
        for path in commits_root.iterdir():
            if not path.is_dir() or path.name == stored_sha:
                continue
            findings_path = path / "review" / "findings.json"
            if findings_path.exists():
                alternatives.append((path.name, findings_path.stat().st_mtime))
    if len(alternatives) == 1:
        return alternatives[0][0], True
    if len(alternatives) > 1:
        open_sha = max(alternatives, key=lambda item: item[1])[0]
        return open_sha, True
    return stored_sha, False
