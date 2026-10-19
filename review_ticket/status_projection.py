"""Read-only status screen model from on-disk review artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from review_ticket.inline_review import files_changed_url, is_full_sha
from review_ticket.policy import classify_track_status
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
class HistoricalSnapshot:
    """An earlier SHA retained after HEAD moved. Read-only for later screens."""

    sha: str
    superseded_by: str
    read_only: bool
    tracks: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class PrFreshness:
    """Stale versus current for one pull request.

    ``current`` describes the stored HEAD. ``stale`` is true when that PR has
    historical SHAs. This is separate from ``SnapshotSelection.stale``, which
    means the open findings file is not the stored SHA.
    """

    ref: str
    current_sha: str
    current: bool
    stale: bool
    historical: tuple[HistoricalSnapshot, ...]
    tracks: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ArtifactTimestamps:
    """Known timestamp fields from on-disk artifacts for one commit."""

    captured_at: str | None
    checks_captured_at: str | None
    curated_at: str | None
    manual_recorded_at: str | None
    testing_recorded_at: str | None
    published_at: str | None


@dataclass(frozen=True)
class PublicationReceipt:
    """GitHub publication from review/publication.json only — not local disposition."""

    event: str | None
    status: str | None
    published_at: str | None


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
    freshness: PrFreshness
    tracks: tuple[tuple[str, str], ...]
    publication: PublicationReceipt | None
    timestamps: ArtifactTimestamps


@dataclass(frozen=True)
class StatusProjection:
    issue: str
    issue_title: str | None
    session_exists: bool
    missing_session_message: str | None
    session_last_updated: str | None
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
            issue_title=None,
            session_exists=False,
            missing_session_message="No review session exists yet.",
            session_last_updated=None,
            current_step=None,
            last_completed_step=None,
            outcome=None,
            next_command=None,
            pr_rows=(),
        )
    session = read_json(session_path) or {}
    issue_doc = read_json(store.issue_dir(issue_key) / "issue.json") or {}
    issue_title = str(issue_doc.get("summary") or issue_doc.get("title") or "").strip() or None
    freshness_by_ref = {item.ref: item for item in project_pr_freshness(store, issue_key)}
    refs = _active_pr_refs(session)
    pr_rows: list[PrStatusRow] = []
    for ref in refs:
        owner, repo, number = parse_pr_ref(ref)
        stored_sha = _stored_sha(session, ref)
        identity = (owner, repo, number)
        open_sha, stale = _select_open_snapshot(store, issue_key, identity, stored_sha)
        freshness = freshness_by_ref[ref]
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
                freshness=freshness,
                tracks=freshness.tracks,
                publication=_publication_receipt(store, issue_key, identity, stored_sha),
                timestamps=_artifact_timestamps(store, issue_key, identity, stored_sha),
            )
        )
    return StatusProjection(
        issue=issue_key,
        issue_title=issue_title,
        session_exists=True,
        missing_session_message=None,
        session_last_updated=str(session.get("last_updated") or "") or None,
        current_step=session.get("current_step"),
        last_completed_step=session.get("last_completed_step"),
        outcome=session.get("outcome"),
        next_command=session.get("next_command"),
        pr_rows=tuple(pr_rows),
    )


def project_pr_freshness(store: Store, issue: str) -> tuple[PrFreshness, ...]:
    """Local stale-versus-current rows for later hub and status screens.

    Does not call GitHub or Jira. A findings file that is not the stored SHA
    is not, by itself, a HEAD move.
    """

    issue_key = require_issue_key(issue)
    session_path = store.issue_dir(issue_key) / "session.json"
    if not session_path.exists():
        return ()
    session = read_json(session_path) or {}
    rows: list[PrFreshness] = []
    for ref in _active_pr_refs(session):
        owner, repo, number = parse_pr_ref(ref)
        current_sha = _stored_sha(session, ref)
        identity = (owner, repo, number)
        historical = _historical_snapshots(store, issue_key, identity, session, ref, current_sha)
        rows.append(
            PrFreshness(
                ref=ref,
                current_sha=current_sha,
                current=True,
                stale=bool(historical),
                historical=tuple(historical),
                tracks=_track_pairs(store, issue_key, identity, current_sha, current_sha),
            )
        )
    return tuple(rows)


def format_pr_freshness(item: PrFreshness) -> str:
    """One line: the stored HEAD is current, and older SHAs are stale."""

    head = short_sha(item.current_sha) if item.current_sha else "unknown"
    if not item.historical:
        return f"current {head}"
    older = ", ".join(f"{short_sha(entry.sha)} stale" for entry in item.historical)
    return f"current {head}; {older}"


def snapshot_is_historical(item: PrFreshness | None, sha: str) -> bool:
    if item is None or not sha:
        return False
    return any(entry.sha == sha and entry.read_only for entry in item.historical)


def pr_url_for_ref(store: Store, issue: str, ref: str) -> str:
    try:
        owner, repo, number = parse_pr_ref(ref)
    except ValueError:
        return ""
    session = read_json(store.issue_dir(issue) / "session.json") or {}
    sha = _stored_sha(session, ref)
    if is_full_sha(sha):
        return files_changed_url(owner, repo, number, issue, sha)
    pr = read_json(store.pr_dir(issue, owner, repo, number) / "pr.json") or {}
    url = str(pr.get("url") or "").strip()
    if url:
        return url
    return files_changed_url(owner, repo, number, issue, "")


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


def _historical_snapshots(
    store: Store,
    issue: str,
    identity: tuple[str, str, int],
    session: dict[str, Any],
    ref: str,
    current_sha: str,
) -> list[HistoricalSnapshot]:
    found: dict[str, str] = {}
    history = session.get("sha_history") or {}
    if isinstance(history, dict):
        for item in history.get(ref) or []:
            if isinstance(item, dict) and item.get("historical") and item.get("sha"):
                found[str(item["sha"])] = str(item.get("superseded_by") or current_sha)
    owner, repo, number = identity
    commits = store.pr_dir(issue, owner, repo, number) / "commits"
    if commits.exists():
        for path in commits.iterdir():
            if not path.is_dir():
                continue
            marker = read_json(path / "historical.json")
            if isinstance(marker, dict) and marker.get("historical") and marker.get("sha"):
                found[str(marker["sha"])] = str(marker.get("superseded_by") or current_sha)
    found.pop(current_sha, None)
    snapshots: list[HistoricalSnapshot] = []
    for sha, superseded_by in sorted(found.items()):
        snapshots.append(
            HistoricalSnapshot(
                sha=sha,
                superseded_by=superseded_by,
                read_only=True,
                tracks=_track_pairs(store, issue, identity, sha, current_sha),
            )
        )
    return snapshots


def _track_pairs(
    store: Store,
    issue: str,
    identity: tuple[str, str, int],
    sha: str,
    current_sha: str | None,
) -> tuple[tuple[str, str], ...]:
    if not sha:
        return ()
    owner, repo, number = identity
    commit = store.commit_dir(issue, owner, repo, number, sha)
    review = commit / "review"
    testing = commit / "testing"
    status = classify_track_status(
        sha=sha,
        current_sha=current_sha,
        findings=read_json(review / "findings.json"),
        human_review=read_json(review / "human-review.json"),
        manual_review=read_json(review / "manual-review.json"),
        test_results=read_json(testing / "test-results.json"),
        publication=read_json(review / "publication.json"),
        environment=read_json(testing / "environment.json"),
    )
    return tuple(status.items())


def _publication_receipt(
    store: Store,
    issue: str,
    identity: tuple[str, str, int],
    sha: str,
) -> PublicationReceipt | None:
    if not sha:
        return None
    owner, repo, number = identity
    payload = read_json(store.commit_dir(issue, owner, repo, number, sha) / "review" / "publication.json")
    if not payload:
        return None
    event = payload.get("event")
    status = payload.get("status")
    published_at = payload.get("published_at")
    return PublicationReceipt(
        event=str(event) if event is not None else None,
        status=str(status) if status is not None else None,
        published_at=str(published_at) if published_at is not None else None,
    )


def _artifact_timestamps(
    store: Store,
    issue: str,
    identity: tuple[str, str, int],
    sha: str,
) -> ArtifactTimestamps:
    if not sha:
        return ArtifactTimestamps(None, None, None, None, None, None)
    owner, repo, number = identity
    commit = store.commit_dir(issue, owner, repo, number, sha)
    review = commit / "review"
    snapshot = read_json(commit / "snapshot.json") or {}
    checks = read_json(commit / "github-checks.json") or {}
    human = read_json(review / "human-review.json") or {}
    manual = read_json(review / "manual-review.json") or {}
    testing = read_json(commit / "testing" / "test-results.json") or {}
    publication = read_json(review / "publication.json") or {}

    def _at(document: dict, key: str) -> str | None:
        value = document.get(key)
        return str(value) if value else None

    return ArtifactTimestamps(
        captured_at=_at(snapshot, "captured_at"),
        checks_captured_at=_at(checks, "captured_at"),
        curated_at=_at(human, "recorded_at"),
        manual_recorded_at=_at(manual, "recorded_at"),
        testing_recorded_at=_at(testing, "recorded_at"),
        published_at=_at(publication, "published_at"),
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
