"""P11: functional testing payload and record_tests workflow."""

from __future__ import annotations

from review_ticket.policy import (
    TRACK_COMPLETE_LOCALLY,
    TRACK_IN_PROGRESS,
    TRACK_RETURNED,
    functional_testing_passed,
)
from review_ticket.storage import read_json
from review_ticket.workflow import read_track_status, record_tests
from tests.support import ISSUE, SHA1, make_app
from tests.test_acceptance import _commit, _run, _seed_pr


def test_pass_and_comment_stores_both_fields(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    code = _run(
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
            "Add item and checkout",
            "--observed",
            "Cart total correct",
            "--expected",
            "Total matches line items",
            "--plan-reference",
            "AC-3",
            "--notes",
            "Minor layout nit only.",
        ],
    )
    assert code == 0
    stored = read_json(_commit(tmp_path, SHA1) / "testing" / "test-results.json")
    assert stored["result"] == "pass"
    assert stored["disposition"] == "COMMENT"
    assert stored["steps"] == "Add item and checkout"
    assert stored["observed"] == "Cart total correct"
    assert stored["expected"] == "Total matches line items"
    assert stored["plan_reference"] == "AC-3"
    assert stored.get("tested_at")
    assert stored.get("recorded_at")
    assert stored.get("completed") is True


def test_fail_request_changes_stores_steps_without_publication(tmp_path):
    app, runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    shot = tmp_path / "cart.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n")
    code = _run(
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
            "request-changes",
            "--steps",
            "Save negative quantity",
            "--notes",
            "Cart accepts -1",
            "--evidence",
            str(shot),
        ],
    )
    assert code == 0
    stored = read_json(_commit(tmp_path, SHA1) / "testing" / "test-results.json")
    assert stored["result"] == "fail"
    assert stored["failure_kind"] == "implementation"
    assert stored["disposition"] == "REQUEST_CHANGES"
    assert stored["steps"] == "Save negative quantity"
    assert stored["evidence"] and stored["evidence"][0].endswith("cart.png")
    assert not (_commit(tmp_path, SHA1) / "review" / "publication.json").exists()
    assert runner.calls == []


def test_blocked_does_not_persist_request_changes_disposition(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    record_tests(
        app,
        ISSUE,
        result="blocked",
        kind=None,
        notes="Docker daemon down",
        scenarios=[],
        evidence=[],
        revise=False,
        disposition="REQUEST_CHANGES",
    )
    stored = read_json(_commit(tmp_path, SHA1) / "testing" / "test-results.json")
    assert stored["result"] == "blocked"
    assert stored["failure_kind"] == "environment"
    assert stored.get("disposition") is None
    assert stored.get("p9_handoff") is not True


def test_cli_record_pass_defaults_optional_fields(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    code = _run(app, [ISSUE, "test", "record", "--result", "pass"])
    assert code == 0
    stored = read_json(_commit(tmp_path, SHA1) / "testing" / "test-results.json")
    assert stored["result"] == "pass"
    assert stored["steps"] == ""
    assert stored["observed"] == ""
    assert stored["expected"] == ""
    assert stored["plan_reference"] == ""
    assert stored.get("disposition") is None


def test_refetch_invalidates_stored_pass(tmp_path):
    app, _runner, world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    digest_a = "sha256:" + "a" * 64
    digest_b = "sha256:" + "b" * 64
    testing = _commit(tmp_path, SHA1) / "testing"
    assert _run(app, [ISSUE, "test", "prepare"]) == 0
    world.digest = digest_a
    assert _run(app, [ISSUE, "test", "fetch"]) == 0
    assert _run(app, [ISSUE, "test", "record", "--result", "pass"]) == 0
    stored = read_json(testing / "test-results.json")
    environment = read_json(testing / "environment.json")
    assert stored["digest"] == digest_a
    assert functional_testing_passed(stored, SHA1, environment) is True
    status = read_track_status(app, ISSUE, ("acme", "widgets", 87), SHA1, current_sha=SHA1)
    assert status["functional"] == TRACK_COMPLETE_LOCALLY

    world.digest = digest_b
    assert _run(app, [ISSUE, "test", "fetch"]) == 0
    environment = read_json(testing / "environment.json")
    assert environment["digest"] == digest_b
    assert functional_testing_passed(stored, SHA1, environment) is False
    status = read_track_status(app, ISSUE, ("acme", "widgets", 87), SHA1, current_sha=SHA1)
    assert status["functional"] == TRACK_IN_PROGRESS


def test_fail_request_changes_survives_digest_refetch(tmp_path):
    app, _runner, world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    digest_a = "sha256:" + "a" * 64
    digest_b = "sha256:" + "b" * 64
    testing = _commit(tmp_path, SHA1) / "testing"
    assert _run(app, [ISSUE, "test", "prepare"]) == 0
    world.digest = digest_a
    assert _run(app, [ISSUE, "test", "fetch"]) == 0
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
                "request-changes",
                "--steps",
                "Save negative quantity",
            ],
        )
        == 0
    )
    stored = read_json(testing / "test-results.json")
    assert stored["digest"] == digest_a
    assert stored["disposition"] == "REQUEST_CHANGES"

    world.digest = digest_b
    assert _run(app, [ISSUE, "test", "fetch"]) == 0
    status = read_track_status(app, ISSUE, ("acme", "widgets", 87), SHA1, current_sha=SHA1)
    assert status["functional"] == TRACK_RETURNED
    assert functional_testing_passed(stored, SHA1, read_json(testing / "environment.json")) is False


def test_record_refuses_second_save_without_revise(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    assert _run(app, [ISSUE, "test", "record", "--result", "pass"]) == 0
    code = _run(app, [ISSUE, "test", "record", "--result", "pass"])
    assert code != 0
    assert "revise" in app.stderr.getvalue().lower() or "revise" in app.stdout.getvalue().lower()
