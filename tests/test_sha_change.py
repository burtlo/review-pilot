"""P14: one PR's new HEAD marks the old SHA historical and blocks a stale payload."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from review_ticket.policy import TRACK_COMPLETE_LOCALLY, TRACK_NOT_STARTED, TRACK_PUBLISHED, TRACK_STALE
from review_ticket.storage import read_json, read_jsonl, write_json
from review_ticket.status_projection import format_pr_freshness, project_pr_freshness, project_review_status
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.pr_screen import PrReviewScreen
from review_ticket.tui.readiness_screen import ReadinessScreen, format_readiness_summary, project_readiness
from review_ticket.tui.status_format import format_status_document
from review_ticket.workflow import Outcome, _sync_pull_request, publish_review, read_track_status
from textual.widgets import Button, Static

from tests.support import ISSUE, SHA1, SHA2, make_app, posts
from tests.test_acceptance import _commit, _normalized_pr, _seed_publishable
from tests.test_status_projection import _store

REF_A = "acme/widgets#87"
REF_B = "acme/other#88"
SHA_OTHER = "e" * 40
_INLINE = ("src/Example.cs", 142, "RIGHT")


def _slug(owner: str, repo: str, number: int) -> str:
    return f"{owner}-{repo}-pr-{number}"


def _tree(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _write_reviewed_commit(commit: Path, sha: str, *, event: str) -> None:
    review = commit / "review"
    review.mkdir(parents=True, exist_ok=True)
    write_json(
        review / "findings.json",
        {
            "sha": sha,
            "summary": "Please validate quantity.",
            "findings": [
                {
                    "id": "F001",
                    "priority": "high",
                    "must_fix": False,
                    "path": _INLINE[0],
                    "line": _INLINE[1],
                    "side": _INLINE[2],
                    "title": "Missing validation",
                    "explanation": "This path permits an invalid state.",
                }
            ],
        },
    )
    write_json(
        review / "human-review.json",
        {
            "sha": sha,
            "rejected_review": False,
            "findings": {"F001": {"decision": "accept", "must_fix": False}},
            "added": [],
            "event": event,
            "summary": "Recorded on this SHA.",
        },
    )
    write_json(
        review / "manual-review.json",
        {
            "sha": sha,
            "completed": True,
            "notes": f"Manual notes for {sha[:12]}.",
            "findings": [],
            "disposition": "APPROVE",
            "recorded_at": "2026-10-18T00:00:00Z",
        },
    )
    write_json(review / "diff-lines.json", [list(_INLINE)])
    receipt = {
        "status": "success",
        "fingerprint": f"fp-{sha[:8]}",
        "sha": sha,
        "event": event,
        "published_at": "2026-10-18T00:00:00Z",
    }
    write_json(review / "publication.json", receipt)
    (review / "publications.jsonl").write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    testing = commit / "testing"
    testing.mkdir(parents=True, exist_ok=True)
    functional_digest = "sha256:" + "a" * 64
    write_json(
        testing / "test-results.json",
        {"sha": sha, "result": "pass", "digest": functional_digest, "notes": f"Passed on {sha[:12]}."},
    )
    write_json(testing / "environment.json", {"sha": sha, "digest": functional_digest})
    write_json(commit / "snapshot.json", {"sha": sha, "captured_at": "2026-10-17T00:00:00Z"})


def _seed_two_prs(tmp_path: Path) -> None:
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "pr_scope": "single",
            "active_pr": REF_A,
            "active_sha": SHA1,
            "active_prs": [REF_A, REF_B],
            "pr_shas": {REF_A: SHA1, REF_B: SHA_OTHER},
            "previous_shas": [],
            "current_step": "virtualization",
            "outcome": "READY",
            "last_updated": "2026-10-17T00:00:00Z",
            "decisions": {
                "testing_notes": {
                    "choice": "accept",
                    "notes": "Ran the cart tests and recorded the result.",
                    "notes_hash": "stable",
                    "at": "2026-10-17T00:00:00Z",
                },
                "human_review": {
                    SHA1: {"choice": "recorded", "at": "2026-10-17T00:00:00Z"},
                    SHA_OTHER: {"choice": "recorded", "at": "2026-10-17T00:00:00Z"},
                },
            },
        },
    )
    write_json(root / "issue.json", {"summary": "Reject negative quantities"})
    write_json(root / "prs" / _slug("acme", "widgets", 87) / "pr.json", _normalized_pr(SHA1))
    write_json(
        root / "prs" / _slug("acme", "other", 88) / "pr.json",
        {**_normalized_pr(SHA_OTHER), "owner": "acme", "repo": "other", "number": 88},
    )
    _write_reviewed_commit(root / "prs" / _slug("acme", "widgets", 87) / "commits" / SHA1, SHA1, event="APPROVE")
    _write_reviewed_commit(
        root / "prs" / _slug("acme", "other", 88) / "commits" / SHA_OTHER,
        SHA_OTHER,
        event="COMMENT",
    )


def test_sync_pull_request_marks_only_the_changed_pr_historical(tmp_path):
    app, _runner, world = make_app(tmp_path)
    _seed_two_prs(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    old_commit = root / "prs" / _slug("acme", "widgets", 87) / "commits" / SHA1
    other_commit = root / "prs" / _slug("acme", "other", 88) / "commits" / SHA_OTHER
    old_snapshot = (old_commit / "snapshot.json").read_bytes()
    old_findings = (old_commit / "review" / "findings.json").read_bytes()
    old_manual = (old_commit / "review" / "manual-review.json").read_bytes()
    old_results = (old_commit / "testing" / "test-results.json").read_bytes()
    old_receipt = (old_commit / "review" / "publication.json").read_bytes()
    old_history = (old_commit / "review" / "publications.jsonl").read_bytes()
    other_before = _tree(other_commit)
    session = read_json(root / "session.json")
    world.head_sha = SHA2

    new_sha = _sync_pull_request(
        app,
        session,
        ISSUE,
        "acme",
        "widgets",
        87,
        previous_sha=SHA1,
    )
    assert new_sha == SHA2
    session["pr_shas"][REF_A] = new_sha
    session["active_sha"] = new_sha
    app.store.save_session(session)

    assert (old_commit / "snapshot.json").read_bytes() == old_snapshot
    assert (old_commit / "review" / "findings.json").read_bytes() == old_findings
    assert (old_commit / "review" / "manual-review.json").read_bytes() == old_manual
    assert (old_commit / "testing" / "test-results.json").read_bytes() == old_results
    assert (old_commit / "review" / "publication.json").read_bytes() == old_receipt
    assert (old_commit / "review" / "publications.jsonl").read_bytes() == old_history
    marker = read_json(old_commit / "historical.json")
    assert marker["historical"] is True
    assert marker["read_only"] is True
    assert marker["sha"] == SHA1
    assert marker["superseded_by"] == SHA2
    assert set(marker["tracks"]) == {"automated", "manual", "functional", "publication"}
    assert read_json(root / "prs" / _slug("acme", "widgets", 87) / "commits" / SHA2 / "snapshot.json")["supersedes"] == SHA1
    assert not (root / "prs" / _slug("acme", "widgets", 87) / "commits" / SHA2 / "review" / "publication.json").exists()

    saved = read_json(root / "session.json")
    assert saved["decisions"]["testing_notes"]["choice"] == "accept"
    assert saved["decisions"]["human_review"][SHA1]["choice"] == "recorded"
    assert saved["decisions"]["human_review"][SHA_OTHER]["choice"] == "recorded"
    assert SHA2 not in saved["decisions"]["human_review"]
    assert saved["pr_shas"][REF_B] == SHA_OTHER
    assert SHA1 in saved["previous_shas"]
    assert saved["sha_history"][REF_A][0]["sha"] == SHA1
    assert REF_B not in saved["sha_history"]
    assert _tree(other_commit) == other_before
    assert not (other_commit / "historical.json").exists()

    old_tracks = read_track_status(app, ISSUE, ("acme", "widgets", 87), SHA1)
    new_tracks = read_track_status(app, ISSUE, ("acme", "widgets", 87), SHA2)
    other_tracks = read_track_status(app, ISSUE, ("acme", "other", 88), SHA_OTHER)
    assert set(old_tracks.values()) == {TRACK_STALE}
    assert new_tracks["automated"] == TRACK_NOT_STARTED
    assert new_tracks["manual"] == TRACK_NOT_STARTED
    assert new_tracks["functional"] == TRACK_NOT_STARTED
    assert new_tracks["publication"] == TRACK_NOT_STARTED
    assert other_tracks["automated"] == TRACK_COMPLETE_LOCALLY
    assert other_tracks["functional"] == TRACK_COMPLETE_LOCALLY
    assert other_tracks["publication"] == TRACK_PUBLISHED

    freshness = {item.ref: item for item in project_pr_freshness(app.store, ISSUE)}
    changed = freshness[REF_A]
    assert changed.current is True
    assert changed.stale is True
    assert changed.current_sha == SHA2
    assert changed.historical[0].sha == SHA1
    assert changed.historical[0].read_only is True
    assert dict(changed.historical[0].tracks)["publication"] == TRACK_STALE
    assert dict(changed.tracks)["publication"] == TRACK_NOT_STARTED
    assert freshness[REF_B].stale is False
    assert freshness[REF_B].current_sha == SHA_OTHER
    changed_line = format_pr_freshness(changed)
    assert changed_line.startswith("current ")
    assert "stale" in changed_line
    assert "stale" not in format_pr_freshness(freshness[REF_B])

    document = format_status_document(project_review_status(app.store, ISSUE))
    assert "**Freshness:**" in document
    assert "current" in document
    assert "stale" in document
    view = project_readiness(app.store, ISSUE, in_progress_status=app.config.in_progress_status)
    summary = format_readiness_summary(view)
    assert "current" in summary
    assert "stale" in summary
    assert SHA2 in summary
    assert SHA_OTHER in summary


def test_publish_refuses_old_inline_comments_against_the_new_diff(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    root = tmp_path / "reviews" / ISSUE
    old_review = _commit(tmp_path, SHA1) / "review"
    new_review = _commit(tmp_path, SHA2) / "review"
    new_review.mkdir(parents=True, exist_ok=True)
    write_json(new_review / "findings.json", read_json(old_review / "findings.json"))
    human = read_json(old_review / "human-review.json")
    human["event"] = "COMMENT"
    write_json(new_review / "human-review.json", human)
    write_json(
        new_review / "manual-review.json",
        {
            "sha": SHA2,
            "completed": True,
            "notes": "Inspected on the new SHA.",
            "findings": [],
            "disposition": "COMMENT",
            "recorded_at": "2026-10-18T00:00:00Z",
        },
    )
    write_json(new_review / "diff-lines.json", [])
    session = read_json(root / "session.json")
    session["active_sha"] = SHA2
    session["pr_shas"] = {REF_A: SHA2}
    write_json(root / "session.json", session)
    world.head_sha = SHA2

    result = publish_review(app, ISSUE, yes=True, event="COMMENT", skip=False)
    assert result.outcome == Outcome.BLOCKED
    assert "Refusing to publish." in result.summary
    assert "Inline comment locations are not on the diff" in result.summary
    assert "src/Example.cs:142" in result.summary
    assert posts(runner) == []
    assert not (new_review / "publication.json").exists()
    assert read_json(old_review / "findings.json")["findings"][0]["path"] == "src/Example.cs"


def test_historical_snapshot_opens_read_only_without_replacing_the_stale_banner(tmp_path):
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": REF_A,
            "active_sha": SHA2,
            "active_prs": [REF_A],
            "pr_shas": {REF_A: SHA2},
            "current_step": "human-review",
            "outcome": "READY",
        },
    )
    write_json(root / "prs" / "acme-widgets-pr-87" / "pr.json", {"url": "https://github.com/acme/widgets/pull/87"})
    old = root / "prs" / "acme-widgets-pr-87" / "commits" / SHA1
    _write_reviewed_commit(old, SHA1, event="APPROVE")
    write_json(
        old / "historical.json",
        {
            "historical": True,
            "read_only": True,
            "sha": SHA1,
            "superseded_by": SHA2,
            "tracks": ["automated", "manual", "functional", "publication"],
        },
    )
    (root / "prs" / "acme-widgets-pr-87" / "commits" / SHA2).mkdir(parents=True, exist_ok=True)
    workflow, runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            assert runner.calls == []
            await pilot.press("enter")
            await pilot.pause()
            screen = app.screen
            assert isinstance(screen, PrReviewScreen)
            assert screen.sha == SHA1
            assert screen.stored_sha == SHA2
            assert screen.stale is True
            assert screen.historical is True
            stale = str(screen.query_one("#stale-banner", Static).render())
            assert "not the stored commit" in stale
            assert "run-review" in stale
            historical = str(screen.query_one("#historical-banner", Static).render())
            assert "Historical snapshot" in historical
            assert "Read-only" in historical
            assert "stale" in historical
            assert screen.query_one("#btn-save", Button).disabled is True
            assert screen.query_one("#explanation-edit").disabled is True
            await pilot.click("#btn-save")
            await pilot.pause()
            assert runner.calls == []

    asyncio.run(_run())
    stored_human = read_json(old / "review" / "human-review.json")
    assert stored_human["summary"] == "Recorded on this SHA."
    assert read_jsonl(old / "review" / "publications.jsonl")[0]["event"] == "APPROVE"


def test_readiness_paint_stays_local_and_shows_stale_versus_current(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_two_prs(tmp_path)
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    world.head_sha = SHA2
    new_sha = _sync_pull_request(app, session, ISSUE, "acme", "widgets", 87, previous_sha=SHA1)
    session["pr_shas"][REF_A] = new_sha
    session["active_sha"] = new_sha
    app.store.save_session(session)
    before = list(runner.calls)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app)

    async def _run() -> None:
        async with tui.run_test(size=(110, 40)) as pilot:
            await pilot.pause()
            assert runner.calls == before
            tui.push_screen(ReadinessScreen(tui.store, ISSUE, tui.workflow_app))
            await pilot.pause()
            assert runner.calls == before
            summary = str(tui.screen.query_one("#readiness-summary", Static).render())
            assert "current" in summary
            assert "stale" in summary
            assert SHA2 in summary
            assert SHA_OTHER in summary

    asyncio.run(_run())
    assert runner.calls == before
