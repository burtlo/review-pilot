"""P11: record_tests extended payload."""

from review_ticket.storage import read_json, write_json
from tests.support import ISSUE, SHA1, make_app
from review_ticket.tracks import TRACK_STALE, functional_testing_passed, track_status_snapshot
from tests.support import SHA2, posts
from tests.test_acceptance import _commit, _run, _seed_pr, _seed_publishable


def test_pass_plus_comment_stores_both_fields(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    _run(app, [ISSUE, "test", "prepare"])
    _run(app, [ISSUE, "test", "fetch"])
    write_json(
        _commit(tmp_path, SHA1) / "testing" / "environment.json",
        {"sha": SHA1, "image": "img", "digest": "sha256:abc"},
    )
    assert (
        _run(
            app,
            [
                ISSUE,
                "test",
                "record",
                "--result",
                "pass",
                "--disposition",
                "comment",
                "--steps",
                "Open app",
                "--observed",
                "Works",
                "--expected",
                "Works",
            ],
        )
        == 0
    )
    payload = read_json(_commit(tmp_path, SHA1) / "testing" / "test-results.json")
    assert payload["result"] == "pass"
    assert payload["disposition"] == "COMMENT"
    assert payload["steps"] == "Open app"


def test_blocked_cannot_select_request_changes(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    code = _run(
        app,
        [
            ISSUE,
            "test",
            "record",
            "--result",
            "blocked",
            "--disposition",
            "request_changes",
        ],
    )
    assert code != 0


def test_fail_request_changes_stores_steps_without_publish(tmp_path):
    app, runner, _world = make_app(tmp_path)
    _seed_publishable(tmp_path, SHA1)
    assert (
        _run(
            app,
            [
                ISSUE,
                "test",
                "record",
                "--result",
                "fail",
                "--kind",
                "implementation",
                "--disposition",
                "request_changes",
                "--steps",
                "Add item with quantity -1",
                "--observed",
                "Cart accepted it",
                "--expected",
                "Validation error",
            ],
        )
        == 0
    )
    payload = read_json(_commit(tmp_path, SHA1) / "testing" / "test-results.json")
    assert payload["disposition"] == "REQUEST_CHANGES"
    assert payload["steps"] == "Add item with quantity -1"
    assert not (_commit(tmp_path, SHA1) / "review" / "publication.json").exists()
    assert posts(runner) == []


def test_pass_on_wrong_sha_is_not_current_evidence(tmp_path):
    commit = _commit(tmp_path, SHA1)
    write_json(
        commit / "testing" / "test-results.json",
        {"sha": SHA2, "result": "pass", "digest": "sha256:abc"},
    )
    assert not functional_testing_passed(commit, expected_sha=SHA1)
    snapshot = track_status_snapshot(commit, expected_sha=SHA1)
    assert snapshot["functional"] == TRACK_STALE


def test_second_record_requires_revise(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    assert _run(app, [ISSUE, "test", "record", "--result", "pass"]) == 0
    assert _run(app, [ISSUE, "test", "record", "--result", "pass"]) != 0
    assert _run(app, [ISSUE, "test", "record", "--result", "pass", "--revise"]) == 0
