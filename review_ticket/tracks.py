"""Three-track review artifacts and publication eligibility (P4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from review_ticket.storage import read_json

TRACK_NOT_STARTED = "not_started"
TRACK_IN_PROGRESS = "in_progress"
TRACK_COMPLETE_LOCALLY = "complete_locally"
TRACK_PUBLICATION_PENDING = "publication_pending"
TRACK_PUBLISHED = "published"
TRACK_STALE = "stale"
TRACK_HISTORICAL = "historical"
TRACK_BLOCKED = "blocked"
TRACK_RETURNED = "returned"


def _review_dir(commit_dir: Path) -> Path:
    return commit_dir / "review"


def _testing_dir(commit_dir: Path) -> Path:
    return commit_dir / "testing"


def automated_track_status(commit_dir: Path) -> str:
    review = _review_dir(commit_dir)
    findings = read_json(review / "findings.json")
    human = read_json(review / "human-review.json")
    if not findings:
        return TRACK_NOT_STARTED
    if not human:
        return TRACK_IN_PROGRESS
    if human.get("rejected_review"):
        return TRACK_BLOCKED
    return TRACK_COMPLETE_LOCALLY


def manual_track_status(commit_dir: Path) -> str:
    manual = read_json(_review_dir(commit_dir) / "manual-review.json") or {}
    if not manual:
        return TRACK_NOT_STARTED
    if manual.get("completed"):
        return TRACK_COMPLETE_LOCALLY
    return TRACK_IN_PROGRESS


def functional_track_status(commit_dir: Path, *, expected_sha: str) -> str:
    results = read_json(_testing_dir(commit_dir) / "test-results.json") or {}
    if not results:
        return TRACK_NOT_STARTED
    if results.get("sha") != expected_sha:
        return TRACK_STALE
    result = results.get("result") or ""
    if result == "pass":
        return TRACK_COMPLETE_LOCALLY
    if result == "blocked" or results.get("failure_kind") == "environment":
        return TRACK_BLOCKED
    if result == "fail":
        return TRACK_RETURNED
    return TRACK_IN_PROGRESS


def publication_track_status(commit_dir: Path) -> str:
    review = _review_dir(commit_dir)
    publication = read_json(review / "publication.json") or {}
    if publication.get("status") in {"success", "skipped"}:
        if publication.get("event") == "REQUEST_CHANGES":
            return TRACK_RETURNED
        return TRACK_PUBLISHED
    automated = automated_track_status(commit_dir)
    if automated == TRACK_COMPLETE_LOCALLY:
        return TRACK_PUBLICATION_PENDING
    return TRACK_NOT_STARTED


def track_status_snapshot(commit_dir: Path, *, expected_sha: str) -> dict[str, str]:
    return {
        "automated": automated_track_status(commit_dir),
        "manual": manual_track_status(commit_dir),
        "functional": functional_track_status(commit_dir, expected_sha=expected_sha),
        "publication": publication_track_status(commit_dir),
    }


def historical_track_snapshot(commit_dir: Path, *, archived_sha: str) -> dict[str, str]:
    """Track labels for a superseded commit directory (read-only history)."""
    snapshot = track_status_snapshot(commit_dir, expected_sha=archived_sha)
    return {key: TRACK_HISTORICAL if value != TRACK_NOT_STARTED else TRACK_NOT_STARTED for key, value in snapshot.items()}


def commit_dir_has_review_artifacts(commit_dir: Path) -> bool:
    review = _review_dir(commit_dir)
    testing = _testing_dir(commit_dir)
    paths = (
        review / "findings.json",
        review / "human-review.json",
        review / "manual-review.json",
        review / "publication.json",
        testing / "test-results.json",
    )
    return any(path.exists() for path in paths)


def manual_review_complete(commit_dir: Path) -> bool:
    return manual_track_status(commit_dir) == TRACK_COMPLETE_LOCALLY


def functional_testing_passed(commit_dir: Path, *, expected_sha: str) -> bool:
    results = read_json(_testing_dir(commit_dir) / "test-results.json") or {}
    return results.get("result") == "pass" and results.get("sha") == expected_sha


def confirmed_blocker_on_track(commit_dir: Path) -> bool:
    """True when a review track recorded a confirmed Request Changes blocker."""
    human = read_json(_review_dir(commit_dir) / "human-review.json") or {}
    if human.get("track_disposition") == "REQUEST_CHANGES" and human.get("track_disposition_confirmed"):
        return True
    manual = read_json(_review_dir(commit_dir) / "manual-review.json") or {}
    if manual.get("disposition") == "REQUEST_CHANGES":
        return True
    results = read_json(_testing_dir(commit_dir) / "test-results.json") or {}
    if results.get("disposition") == "REQUEST_CHANGES":
        return True
    return False


def publication_eligibility(
    event: str,
    commit_dir: Path,
    *,
    expected_sha: str,
) -> tuple[bool, str]:
    """Return (allowed, reason) for publishing the given GitHub review event."""
    normalized = (event or "COMMENT").upper()
    manual = manual_review_complete(commit_dir)
    tests_passed = functional_testing_passed(commit_dir, expected_sha=expected_sha)
    if normalized == "APPROVE":
        if not manual:
            return False, "GitHub Approve requires completed manual code review for this SHA."
        if not tests_passed:
            return False, "GitHub Approve requires a recorded functional test pass for this SHA."
        return True, ""
    if normalized == "COMMENT":
        if not manual:
            return False, "GitHub Comment requires completed manual code review for this SHA."
        return True, ""
    if normalized == "REQUEST_CHANGES":
        human = read_json(_review_dir(commit_dir) / "human-review.json") or {}
        if human.get("rejected_review"):
            return False, "The automated review was rejected locally."
        if not confirmed_blocker_on_track(commit_dir):
            return False, "Request Changes requires a confirmed blocker on a review track."
        return True, ""
    return False, f"Unknown review event {event}."


def append_publication_receipt(review_dir: Path, receipt: dict[str, Any]) -> None:
    from review_ticket.storage import write_json
    from review_ticket.util import iso_now

    enriched = dict(receipt)
    enriched.setdefault("recorded_at", iso_now())
    write_json(review_dir / "publication.json", enriched)
    history_path = review_dir / "publications.jsonl"
    line = __import__("json").dumps(enriched, sort_keys=True) + "\n"
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(line)
