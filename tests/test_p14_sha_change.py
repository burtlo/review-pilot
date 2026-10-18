"""P14: SHA change, historical tracks, and publication guards."""

from __future__ import annotations

from pathlib import Path

from review_ticket.storage import Store, read_json, write_json
from review_ticket.status_projection import project_review_status
from review_ticket.track_projection import project_pr_tracks
from review_ticket.tracks import TRACK_COMPLETE_LOCALLY, TRACK_HISTORICAL, TRACK_NOT_STARTED
from review_ticket.workflow import _sync_pull_request
from tests.support import ISSUE, SHA1, SHA2, jira_document, make_app, pr_document
from tests.test_acceptance import _commit, _run, _seed_publishable

REF_A = "acme/widgets#87"
REF_B = "acme/other#88"


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "reviews")


def _pr_slug(ref: str) -> str:
    owner, rest = ref.split("/", 1)
    repo, number = rest.split("#", 1)
    return f"{owner}-{repo}-pr-{number}"


def _commit_dir(tmp_path: Path, ref: str, sha: str) -> Path:
    return tmp_path / "reviews" / ISSUE / "prs" / _pr_slug(ref) / "commits" / sha


def _seed_two_pr_session(tmp_path: Path) -> None:
    root = tmp_path / "reviews" / ISSUE
    write_json(root / "issue.json", jira_document("Ran tests."))
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": REF_A,
            "active_sha": SHA1,
            "active_prs": [REF_A, REF_B],
            "pr_shas": {REF_A: SHA1, REF_B: SHA1},
            "decisions": {
                "testing_notes": {"choice": "accept", "notes_hash": "abc"},
            },
        },
    )
    for ref in (REF_A, REF_B):
        owner, rest = ref.split("/", 1)
        repo, number = rest.split("#", 1)
        write_json(
            root / "prs" / _pr_slug(ref) / "pr.json",
            {
                "owner": owner,
                "repo": repo,
                "number": int(number),
                "head_sha": SHA1,
                "url": f"https://github.com/{owner}/{repo}/pull/{number}",
            },
        )
        commit = _commit_dir(tmp_path, ref, SHA1)
        commit.mkdir(parents=True, exist_ok=True)
        write_json(commit / "snapshot.json", {"sha": SHA1})
        review = commit / "review"
        review.mkdir(exist_ok=True)
        write_json(
            review / "findings.json",
            {"summary": "s", "findings": [{"id": "F001", "title": "t", "explanation": "e"}]},
        )
        write_json(review / "human-review.json", {"rejected_review": False, "findings": {}})
        write_json(review / "manual-review.json", {"completed": True, "notes": "ok", "findings": []})
        write_json(
            commit / "testing" / "test-results.json",
            {"sha": SHA1, "result": "pass", "digest": "sha256:abc"},
        )
        write_json(review / "publication.json", {"status": "success", "event": "APPROVE", "sha": SHA1})


def test_sync_pull_request_records_supersedes_and_preserves_old_dir(tmp_path):
    app, _runner, world = make_app(tmp_path)
    _seed_two_pr_session(tmp_path)
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
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
    assert (_commit_dir(tmp_path, REF_A, SHA1) / "review" / "findings.json").exists()
    snapshot = read_json(_commit_dir(tmp_path, REF_A, SHA2) / "snapshot.json")
    assert snapshot["supersedes"] == SHA1
    assert SHA1 in session["previous_shas"]


def test_track_projection_renews_current_and_marks_prior_historical(tmp_path):
    _seed_two_pr_session(tmp_path)
    store = _store(tmp_path)
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    session["pr_shas"][REF_A] = SHA2
    write_json(
        _commit_dir(tmp_path, REF_A, SHA2) / "snapshot.json",
        {"sha": SHA2, "supersedes": SHA1},
    )
    projection = project_pr_tracks(store, ISSUE, REF_A, session)
    assert projection.head_moved is True
    assert projection.supersedes_sha == SHA1
    assert projection.current_tracks["automated"] == TRACK_NOT_STARTED
    assert projection.current_tracks["publication"] == TRACK_NOT_STARTED
    assert len(projection.historical) == 1
    prior = projection.historical[0]
    assert prior.sha == SHA1
    assert prior.tracks["automated"] == TRACK_HISTORICAL
    assert prior.tracks["manual"] == TRACK_HISTORICAL
    assert prior.publication_event == "APPROVE"


def test_other_pr_and_testing_notes_unchanged_after_head_move(tmp_path):
    _seed_two_pr_session(tmp_path)
    store = _store(tmp_path)
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    session["pr_shas"][REF_A] = SHA2
    write_json(_commit_dir(tmp_path, REF_A, SHA2) / "snapshot.json", {"sha": SHA2, "supersedes": SHA1})
    other = project_pr_tracks(store, ISSUE, REF_B, session)
    assert other.head_moved is False
    assert other.current_tracks["automated"] == TRACK_COMPLETE_LOCALLY
    assert session["decisions"]["testing_notes"]["choice"] == "accept"


def test_status_projection_surfaces_head_moved_and_historical_tracks(tmp_path):
    _seed_two_pr_session(tmp_path)
    root = tmp_path / "reviews" / ISSUE
    session = read_json(root / "session.json")
    session["pr_shas"][REF_A] = SHA2
    write_json(root / "session.json", session)
    write_json(_commit_dir(tmp_path, REF_A, SHA2) / "snapshot.json", {"sha": SHA2, "supersedes": SHA1})
    store = _store(tmp_path)
    row = next(r for r in project_review_status(store, ISSUE).pr_rows if r.ref == REF_A)
    assert row.snapshot.head_moved is True
    assert row.tracks.historical[0].tracks["publication"] == TRACK_HISTORICAL


def test_publish_refuses_inline_findings_not_on_new_diff(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    commit_b = _commit(tmp_path, SHA2)
    commit_b.mkdir(parents=True, exist_ok=True)
    write_json(commit_b / "snapshot.json", {"sha": SHA2, "supersedes": SHA1})
    review_b = commit_b / "review"
    review_b.mkdir(parents=True, exist_ok=True)
    for name in ("findings.json", "human-review.json"):
        write_json(review_b / name, read_json(_commit(tmp_path, SHA1) / "review" / name))
    write_json(review_b / "diff-lines.json", [["src/Other.cs", 10, "RIGHT"]])
    root = tmp_path / "reviews" / ISSUE
    session = read_json(root / "session.json")
    session["active_sha"] = SHA2
    session["pr_shas"] = {"acme/widgets#87": SHA2}
    write_json(root / "session.json", session)
    write_json(
        review_b / "manual-review.json",
        {"completed": True, "notes": "looked", "findings": []},
    )
    write_json(
        commit_b / "testing" / "test-results.json",
        {"sha": SHA2, "result": "pass", "digest": "sha256:abc"},
    )
    world.head_sha = SHA2
    code = _run(app, [ISSUE, "publish-review", "--yes", "--sha", SHA2])
    output = app.stdout.getvalue()
    assert code == 2
    assert "outcome: BLOCKED" in output
    assert "not on the diff" in output
    assert not (review_b / "publication.json").exists()
