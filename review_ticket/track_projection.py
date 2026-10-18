"""Per-PR three-track projection for current HEAD and superseded SHAs (P14)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from review_ticket.storage import Store, read_json
from review_ticket.tracks import (
    TRACK_HISTORICAL,
    TRACK_NOT_STARTED,
    commit_dir_has_review_artifacts,
    historical_track_snapshot,
    track_status_snapshot,
)
from review_ticket.util import parse_pr_ref


@dataclass(frozen=True)
class HistoricalTrackRow:
    sha: str
    tracks: dict[str, str]
    publication_event: str | None


@dataclass(frozen=True)
class PrTrackProjection:
    ref: str
    stored_sha: str
    head_moved: bool
    supersedes_sha: str | None
    current_tracks: dict[str, str]
    historical: tuple[HistoricalTrackRow, ...]


def project_pr_tracks(
    store: Store,
    issue: str,
    ref: str,
    session: dict,
) -> PrTrackProjection:
    owner, repo, number = parse_pr_ref(ref)
    identity = (owner, repo, number)
    stored_sha = _stored_sha(session, ref)
    supersedes = _supersedes_sha(store, issue, identity, stored_sha)
    head_moved = bool(supersedes)
    current_dir = store.commit_dir(issue, owner, repo, number, stored_sha) if stored_sha else None
    if current_dir and current_dir.exists():
        current_tracks = track_status_snapshot(current_dir, expected_sha=stored_sha)
    else:
        current_tracks = {
            "automated": TRACK_NOT_STARTED,
            "manual": TRACK_NOT_STARTED,
            "functional": TRACK_NOT_STARTED,
            "publication": TRACK_NOT_STARTED,
        }
    historical_rows: list[HistoricalTrackRow] = []
    if head_moved and supersedes:
        prior_dir = store.commit_dir(issue, owner, repo, number, supersedes)
        if prior_dir.exists() and commit_dir_has_review_artifacts(prior_dir):
            publication = read_json(prior_dir / "review" / "publication.json") or {}
            historical_rows.append(
                HistoricalTrackRow(
                    sha=supersedes,
                    tracks=historical_track_snapshot(prior_dir, archived_sha=supersedes),
                    publication_event=publication.get("event"),
                )
            )
    for sha, commit_dir in _other_artifact_commits(store, issue, identity, stored_sha, supersedes):
        if sha in {stored_sha, supersedes}:
            continue
        publication = read_json(commit_dir / "review" / "publication.json") or {}
        historical_rows.append(
            HistoricalTrackRow(
                sha=sha,
                tracks=historical_track_snapshot(commit_dir, archived_sha=sha),
                publication_event=publication.get("event"),
            )
        )
    return PrTrackProjection(
        ref=ref,
        stored_sha=stored_sha,
        head_moved=head_moved,
        supersedes_sha=supersedes,
        current_tracks=current_tracks,
        historical=tuple(historical_rows),
    )


def _stored_sha(session: dict, ref: str) -> str:
    pr_shas: dict[str, str] = session.get("pr_shas") or {}
    sha = pr_shas.get(ref)
    if not sha and ref == session.get("active_pr"):
        sha = session.get("active_sha")
    return str(sha or "")


def _supersedes_sha(
    store: Store,
    issue: str,
    identity: tuple[str, str, int],
    stored_sha: str,
) -> str | None:
    if not stored_sha:
        return None
    owner, repo, number = identity
    snapshot = read_json(store.commit_dir(issue, owner, repo, number, stored_sha) / "snapshot.json") or {}
    prior = snapshot.get("supersedes")
    if isinstance(prior, str) and prior.strip():
        return prior.strip()
    return None


def _other_artifact_commits(
    store: Store,
    issue: str,
    identity: tuple[str, str, int],
    stored_sha: str,
    supersedes: str | None,
) -> list[tuple[str, Path]]:
    owner, repo, number = identity
    commits_root = store.pr_dir(issue, owner, repo, number) / "commits"
    if not commits_root.exists():
        return []
    rows: list[tuple[str, Path]] = []
    for path in commits_root.iterdir():
        if not path.is_dir():
            continue
        sha = path.name
        if sha == stored_sha or sha == supersedes:
            continue
        if commit_dir_has_review_artifacts(path):
            rows.append((sha, path))
    rows.sort(key=lambda item: item[0])
    return rows
