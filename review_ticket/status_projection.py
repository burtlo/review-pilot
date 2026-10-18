"""Read-only status screen model from on-disk review artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from review_ticket.storage import Store, read_json
from review_ticket.track_projection import PrTrackProjection, project_pr_tracks
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
    head_moved: bool


@dataclass(frozen=True)
class ReviewProgress:
    kind: ReviewProgressKind
    label: str
    sha: str


@dataclass(frozen=True)
class PublicationReceipt:
    """Latest GitHub publication receipt on disk (``review/publication.json``)."""

    status: str | None
    event: str | None
    published_at: str | None
    recorded_at: str | None


@dataclass(frozen=True)
class ArtifactTimestamps:
    """Stored ``captured_at`` / ``recorded_at`` / ``published_at`` fields for one commit."""

    snapshot_captured_at: str | None = None
    tests_recorded_at: str | None = None
    publication_published_at: str | None = None
    publication_recorded_at: str | None = None


@dataclass(frozen=True)
class PrStatusRow:
    ref: str
    owner: str
    repo: str
    number: int
    pr_title: str | None
    stored_sha: str
    url: str
    progress: ReviewProgress
    checks: PrChecks
    snapshot: SnapshotSelection
    tracks: PrTrackProjection
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
    issue_title = _issue_title(store, issue_key)
    refs = _active_pr_refs(session)
    pr_rows: list[PrStatusRow] = []
    for ref in refs:
        owner, repo, number = parse_pr_ref(ref)
        stored_sha = _stored_sha(session, ref)
        identity = (owner, repo, number)
        commit_dir = (
            store.commit_dir(issue_key, owner, repo, number, stored_sha) if stored_sha else None
        )
        open_sha, stale = _select_open_snapshot(store, issue_key, identity, stored_sha)
        tracks = project_pr_tracks(store, issue_key, ref, session)
        pr_rows.append(
            PrStatusRow(
                ref=ref,
                owner=owner,
                repo=repo,
                number=number,
                pr_title=_pr_title(store, issue_key, identity),
                stored_sha=stored_sha,
                url=pr_url_for_ref(store, issue_key, ref),
                progress=_review_progress(store, issue_key, identity, stored_sha),
                checks=_load_checks(store, issue_key, identity, stored_sha),
                snapshot=SnapshotSelection(
                    stored_sha=stored_sha,
                    open_sha=open_sha,
                    stale=stale,
                    head_moved=tracks.head_moved,
                ),
                tracks=tracks,
                publication=_load_publication_receipt(commit_dir) if commit_dir else None,
                timestamps=_load_artifact_timestamps(commit_dir) if commit_dir else ArtifactTimestamps(),
            )
        )
    return StatusProjection(
        issue=issue_key,
        issue_title=issue_title,
        session_exists=True,
        missing_session_message=None,
        session_last_updated=_optional_str(session.get("last_updated")),
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


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _issue_title(store: Store, issue: str) -> str | None:
    payload = read_json(store.issue_dir(issue) / "issue.json") or {}
    return _optional_str(payload.get("summary") or payload.get("title"))


def _pr_title(store: Store, issue: str, identity: tuple[str, str, int]) -> str | None:
    owner, repo, number = identity
    payload = read_json(store.pr_dir(issue, owner, repo, number) / "pr.json") or {}
    return _optional_str(payload.get("title"))


def _load_publication_receipt(commit_dir: Path | None) -> PublicationReceipt | None:
    if commit_dir is None or not commit_dir.exists():
        return None
    payload = read_json(commit_dir / "review" / "publication.json") or {}
    if not payload:
        return None
    return PublicationReceipt(
        status=_optional_str(payload.get("status")),
        event=_optional_str(payload.get("event")),
        published_at=_optional_str(payload.get("published_at")),
        recorded_at=_optional_str(payload.get("recorded_at")),
    )


def _load_artifact_timestamps(commit_dir: Path) -> ArtifactTimestamps:
    snapshot = read_json(commit_dir / "snapshot.json") or {}
    tests = read_json(commit_dir / "testing" / "test-results.json") or {}
    publication = read_json(commit_dir / "review" / "publication.json") or {}
    return ArtifactTimestamps(
        snapshot_captured_at=_optional_str(snapshot.get("captured_at")),
        tests_recorded_at=_optional_str(tests.get("recorded_at")),
        publication_published_at=_optional_str(publication.get("published_at")),
        publication_recorded_at=_optional_str(publication.get("recorded_at")),
    )


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
