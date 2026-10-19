"""P4: read-only status projection from session and store files."""

from __future__ import annotations

import os
import time
from pathlib import Path

from review_ticket.storage import Store, write_json
from review_ticket.policy import TRACK_COMPLETE_LOCALLY, TRACK_PUBLICATION_PENDING
from review_ticket.status_projection import project_review_status
from review_ticket.tui.status_format import format_status_document
from tests.support import ISSUE, SHA1, SHA2

SHA3 = "c" * 40
SHA_OLD = "d" * 40
SHA_NEWER = "e" * 40

REF_A = "acme/widgets#87"
REF_B = "acme/gadgets#12"
REF_C = "acme/tools#3"


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "reviews")


def _pr_slug(ref: str) -> str:
    owner, rest = ref.split("/", 1)
    repo, number = rest.split("#", 1)
    return f"{owner}-{repo}-pr-{number}"


def _commit_dir(tmp_path: Path, ref: str, sha: str) -> Path:
    return tmp_path / "reviews" / ISSUE / "prs" / _pr_slug(ref) / "commits" / sha


def _seed_findings(commit_dir: Path) -> None:
    review = commit_dir / "review"
    review.mkdir(parents=True, exist_ok=True)
    write_json(
        review / "findings.json",
        {
            "summary": "Review",
            "findings": [{"id": "F001", "title": "Issue", "explanation": "x"}],
        },
    )


def _seed_checks(commit_dir: Path, *, outcome: str = "READY") -> None:
    write_json(
        commit_dir / "github-checks.json",
        {
            "sha": commit_dir.name,
            "checks": [
                {
                    "name": "build",
                    "required": True,
                    "bucket": "pass",
                    "state": "SUCCESS",
                    "link": "https://example.test/build",
                }
            ],
            "outcome": outcome,
            "summary": "all required check(s) passed",
        },
    )


def _seed_three_pr_session(tmp_path: Path) -> None:
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": REF_A,
            "active_sha": SHA1,
            "active_prs": [REF_A, REF_B, REF_C],
            "pr_shas": {REF_A: SHA1, REF_B: SHA2, REF_C: SHA3},
            "current_step": "human-review",
            "last_completed_step": "analyzer-findings",
            "outcome": "REVIEW_DECISION",
            "next_command": f"review-ticket {ISSUE} attach",
            "last_updated": "2026-10-18T12:00:00Z",
        },
    )
    write_json(root / "issue.json", {"key": ISSUE, "summary": "Fix timezone handling"})
    for ref, sha, url in (
        (REF_A, SHA1, "https://github.com/acme/widgets/pull/87"),
        (REF_B, SHA2, "https://github.com/acme/gadgets/pull/12"),
        (REF_C, SHA3, "https://github.com/acme/tools/pull/3"),
    ):
        owner, rest = ref.split("/", 1)
        repo, number = rest.split("#", 1)
        write_json(
            root / "prs" / _pr_slug(ref) / "pr.json",
            {"url": url, "number": int(number)},
        )
        commit = _commit_dir(tmp_path, ref, sha)
        commit.mkdir(parents=True, exist_ok=True)
        _seed_checks(commit)
        if ref == REF_A:
            _seed_findings(commit)
            write_json(
                commit / "review" / "human-review.json",
                {
                    "rejected_review": False,
                    "findings": {},
                    "recorded_at": "2026-10-18T11:00:00Z",
                },
            )
            write_json(
                commit / "review" / "manual-review.json",
                {
                    "sha": sha,
                    "completed": True,
                    "disposition": "APPROVE",
                    "recorded_at": "2026-10-18T11:30:00Z",
                },
            )
            write_json(commit / "snapshot.json", {"sha": sha, "captured_at": "2026-10-18T10:00:00Z"})
        if ref == REF_B:
            _seed_findings(commit)


def test_missing_session_reports_issue_without_side_effects(tmp_path):
    store = _store(tmp_path)
    projection = project_review_status(store, ISSUE)
    assert projection.session_exists is False
    assert projection.issue == ISSUE
    assert projection.missing_session_message == "No review session exists yet."
    assert projection.pr_rows == ()
    assert not (tmp_path / "reviews" / ISSUE / "session.json").exists()


def test_three_pr_fixture_projects_rows_checks_and_progress(tmp_path):
    _seed_three_pr_session(tmp_path)
    store = _store(tmp_path)
    projection = project_review_status(store, ISSUE)
    assert projection.session_exists is True
    assert projection.current_step == "human-review"
    assert projection.last_completed_step == "analyzer-findings"
    assert projection.outcome == "REVIEW_DECISION"
    assert projection.next_command == f"review-ticket {ISSUE} attach"
    assert len(projection.pr_rows) == 3

    by_ref = {row.ref: row for row in projection.pr_rows}
    assert by_ref[REF_A].stored_sha == SHA1
    assert by_ref[REF_A].url == (
        "https://github.com/acme/widgets/pull/87/changes"
        f"?review_pilot_issue={ISSUE}&review_pilot_sha={SHA1}"
    )
    assert by_ref[REF_A].progress.kind == "recorded"
    assert SHA1[:12] in by_ref[REF_A].progress.label
    assert len(by_ref[REF_A].checks.rows) == 1
    assert by_ref[REF_A].checks.rows[0].name == "build"
    assert by_ref[REF_A].snapshot.stale is False

    assert by_ref[REF_B].progress.kind == "undecided"
    assert by_ref[REF_B].snapshot.open_sha == SHA2

    assert by_ref[REF_C].progress.kind == "no_snapshot"
    assert len(by_ref[REF_C].checks.rows) == 1

    assert projection.issue_title == "Fix timezone handling"
    assert projection.session_last_updated == "2026-10-18T12:00:00Z"
    tracks_a = dict(by_ref[REF_A].tracks)
    assert tracks_a["automated"] == TRACK_COMPLETE_LOCALLY
    assert tracks_a["manual"] == TRACK_COMPLETE_LOCALLY
    assert tracks_a["publication"] == TRACK_PUBLICATION_PENDING
    assert by_ref[REF_A].publication is None
    assert by_ref[REF_A].timestamps.captured_at == "2026-10-18T10:00:00Z"
    assert by_ref[REF_A].timestamps.curated_at == "2026-10-18T11:00:00Z"
    assert by_ref[REF_A].timestamps.manual_recorded_at == "2026-10-18T11:30:00Z"

    document = format_status_document(projection)
    assert "Published (Approve)" not in document
    assert "Publication pending" in document


def test_missing_github_checks_yields_empty_check_rows(tmp_path):
    _seed_three_pr_session(tmp_path)
    checks_path = _commit_dir(tmp_path, REF_C, SHA3) / "github-checks.json"
    checks_path.unlink()
    store = _store(tmp_path)
    row = next(r for r in project_review_status(store, ISSUE).pr_rows if r.ref == REF_C)
    assert row.checks.rows == ()
    assert row.checks.outcome is None


def test_stale_sha_selects_other_snapshot_and_keeps_stored_progress(tmp_path):
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": REF_A,
            "active_sha": SHA1,
            "active_prs": [REF_A],
            "pr_shas": {REF_A: SHA2},
            "current_step": "human-review",
            "outcome": "READY",
        },
    )
    write_json(root / "prs" / _pr_slug(REF_A) / "pr.json", {"url": "https://github.com/acme/widgets/pull/87"})
    stored_commit = _commit_dir(tmp_path, REF_A, SHA2)
    stored_commit.mkdir(parents=True, exist_ok=True)
    _seed_checks(stored_commit)
    older_commit = _commit_dir(tmp_path, REF_A, SHA_OLD)
    _seed_findings(older_commit)
    store = _store(tmp_path)
    row = project_review_status(store, ISSUE).pr_rows[0]
    assert row.stored_sha == SHA2
    assert row.snapshot.open_sha == SHA_OLD
    assert row.snapshot.stale is True
    assert row.progress.kind == "no_snapshot"


def test_multiple_alternate_snapshots_picks_newest_mtime(tmp_path):
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_prs": [REF_A],
            "pr_shas": {REF_A: SHA2},
            "current_step": "human-review",
            "outcome": "READY",
        },
    )
    write_json(root / "prs" / _pr_slug(REF_A) / "pr.json", {"url": "https://github.com/acme/widgets/pull/87"})
    _commit_dir(tmp_path, REF_A, SHA2).mkdir(parents=True, exist_ok=True)
    older = _commit_dir(tmp_path, REF_A, SHA_OLD)
    newer = _commit_dir(tmp_path, REF_A, SHA_NEWER)
    _seed_findings(older)
    _seed_findings(newer)
    os.utime(older / "review" / "findings.json", (time.time() - 100, time.time() - 100))
    os.utime(newer / "review" / "findings.json", (time.time(), time.time()))
    store = _store(tmp_path)
    row = project_review_status(store, ISSUE).pr_rows[0]
    assert row.snapshot.open_sha == SHA_NEWER
    assert row.snapshot.stale is True


def test_projection_does_not_write_store(tmp_path):
    _seed_three_pr_session(tmp_path)
    session_path = tmp_path / "reviews" / ISSUE / "session.json"
    before = session_path.read_bytes()
    mtime_before = session_path.stat().st_mtime
    store = _store(tmp_path)
    project_review_status(store, ISSUE)
    assert session_path.read_bytes() == before
    assert session_path.stat().st_mtime == mtime_before
