"""P10: test environment projection."""

from review_ticket.test_env_projection import project_test_environment
from tests.support import ISSUE, SHA1, make_app
from tests.test_acceptance import _commit, _seed_pr


def test_projection_does_not_invoke_runner(tmp_path):
    app, runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    before = len(runner.calls)
    project_test_environment(
        _commit(tmp_path, SHA1),
        sha=SHA1,
        issue=ISSUE,
        pr_ref="acme/widgets#87",
    )
    assert len(runner.calls) == before


def test_missing_profile_blocked(tmp_path):
    _seed_pr(tmp_path, SHA1)
    commit = _commit(tmp_path, SHA1)
    projection = project_test_environment(
        commit,
        sha=SHA1,
        issue=ISSUE,
        pr_ref="acme/widgets#87",
    )
    assert projection.profile_present is False
    assert projection.blocked_reason is not None
