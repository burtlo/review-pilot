"""P10: test environment workflow hooks."""

from review_ticket.storage import read_json, write_json
from review_ticket.test_env_projection import format_test_environment_markdown, project_test_environment
from tests.support import ISSUE, SHA1, make_app
from tests.test_acceptance import _commit, _run, _seed_pr


def test_digest_for_other_sha_is_uncertain(tmp_path):
    _seed_pr(tmp_path, SHA1)
    commit = _commit(tmp_path, SHA1)
    write_json(
        commit / "testing" / "environment.json",
        {"sha": "x" * 40, "digest": "sha256:dead"},
    )
    projection = project_test_environment(
        commit,
        sha=SHA1,
        issue=ISSUE,
        pr_ref="acme/widgets#87",
    )
    md = format_test_environment_markdown(projection)
    assert projection.digest_uncertain is True
    assert "another SHA" in md


def test_launch_tool_error_surfaces_blocked(tmp_path):
    app, _runner, world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    _run(app, [ISSUE, "test", "prepare"])
    _run(app, [ISSUE, "test", "fetch"])
    world.compose_up_code = 1
    code = _run(app, [ISSUE, "test", "launch"])
    assert code == 2
    assert "outcome: BLOCKED" in app.stdout.getvalue()


def test_prepare_fetch_launch_workflow_without_mount(tmp_path):
    app, runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    before = len(runner.calls)
    assert _run(app, [ISSUE, "test", "prepare"]) == 0
    assert _run(app, [ISSUE, "test", "fetch"]) == 0
    assert _run(app, [ISSUE, "test", "launch"]) == 0
    environment = read_json(_commit(tmp_path, SHA1) / "testing" / "environment.json")
    assert environment.get("launched_at")
    assert len(runner.calls) > before
