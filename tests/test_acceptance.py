from pathlib import Path

from review_ticket.cli import main
from review_ticket.models import Outcome
from review_ticket.storage import read_json, write_json
from tests.support import (
    ISSUE,
    SHA1,
    SHA2,
    World,
    bugbot_thread,
    check,
    jira_document,
    make_app,
    passing_checks,
    posts,
    pr_document,
    review_threads,
    transitions,
)


def test_missing_testing_notes_recommend_in_progress_and_stop(tmp_path):
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document(notes=None)
    code = _run(app, [ISSUE])
    output = app.stdout.getvalue()
    assert code == 0
    assert "outcome: ACTION_REQUIRED" in output
    assert "recommendation: In Progress" in output
    assert "No Jira transition was performed." in output
    assert transitions(runner) == []
    assert (tmp_path / "reviews" / ISSUE / "issue-report.md").exists()


def test_pending_checks_stop_without_jira_mutation(tmp_path):
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document("Ran the cart tests and recorded the result.")
    world.required_checks = [
        check("build", "pending", "IN_PROGRESS"),
        check("Bugbot", "pass", "SUCCESS"),
        check("CodeQL", "pass", "SUCCESS"),
    ]
    world.all_checks = world.required_checks
    code = _run(app, [ISSUE, "notes", "--accept"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "outcome: WAITING" in output
    assert "No Jira transition was performed." in output
    assert transitions(runner) == []
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    assert session["active_sha"] == SHA1


def test_failed_required_check_recommends_in_progress(tmp_path):
    app, runner, world = make_app(tmp_path)
    world.issue = jira_document("Ran the cart tests and recorded the result.")
    world.required_checks = [
        check("build", "fail", "FAILURE"),
        check("Bugbot", "pass", "SUCCESS"),
        check("CodeQL", "pass", "SUCCESS"),
    ]
    world.all_checks = world.required_checks
    code = _run(app, [ISSUE, "notes", "--accept"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "outcome: ACTION_REQUIRED" in output
    assert "recommendation: In Progress" in output
    assert "No Jira transition was performed." in output
    assert transitions(runner) == []


def test_unaddressed_bugbot_finding_recommends_in_progress(tmp_path):
    app, runner, world = make_app(tmp_path)
    _ready_issue(world)
    world.threads = review_threads([bugbot_thread()])
    code = _run(app, [ISSUE, "notes", "--accept"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "outcome: ACTION_REQUIRED" in output
    assert "recommendation: In Progress" in output
    assert transitions(runner) == []
    stored = read_json(_commit(tmp_path, SHA1) / "bugbot-findings.json")
    assert stored["findings"][0]["attention"] == "unaddressed"
    assert stored["findings"][0]["url"].startswith("https://github.com/")


def test_dispositioned_bugbot_finding_can_proceed_after_review(tmp_path):
    app, runner, world = make_app(tmp_path)
    _ready_issue(world)
    world.threads = review_threads([bugbot_thread(reply="False positive: the caller validates quantity.")])
    code = _run(app, [ISSUE, "notes", "--accept"])
    assert code == 0
    assert "outcome: REVIEW_DECISION" in app.stdout.getvalue()
    assert transitions(runner) == []
    code = _run(app, [ISSUE, "analyzers", "--accept-dispositions"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "outcome: READY" in output
    assert "run-review" in output


def test_reviewer_places_must_fix_inline_and_keeps_general_findings(tmp_path):
    app, runner, world = make_app(tmp_path)
    _ready_issue(world)
    world.reviewer_output = {
        "summary": "Quantity is not validated on every path.",
        "approval_recommendation": "request_changes",
        "findings": [
            {
                "id": "F001",
                "priority": "high",
                "must_fix": True,
                "path": "src/Example.cs",
                "line": 142,
                "side": "RIGHT",
                "title": "Missing validation",
                "explanation": "This path permits an invalid state.",
                "suggested_change": "if (item.Quantity < 0) throw new InvalidOperationException();",
            },
            {
                "id": "F002",
                "priority": "medium",
                "must_fix": False,
                "path": "src/Example.cs",
                "line": 10,
                "side": "RIGHT",
                "title": "Unrelated helper",
                "explanation": "This behavior lives outside the diff.",
            },
            {
                "id": "F003",
                "priority": "low",
                "must_fix": False,
                "title": "Release note",
                "explanation": "Mention the validation in the changelog.",
            },
        ],
    }
    _run(app, [ISSUE, "notes", "--accept"])
    code = _run(app, [ISSUE, "run-review"])
    assert code == 0
    proposed = read_json(_commit(tmp_path, SHA1) / "review" / "proposed-review.json")
    assert proposed["event"] == "REQUEST_CHANGES"
    assert len(proposed["comments"]) == 1
    assert proposed["comments"][0]["line"] == 142
    assert "```suggestion" in proposed["comments"][0]["body"]
    assert "Unrelated helper" in proposed["body"]
    assert "Release note" in proposed["body"]
    assert "checkout" in " ".join(" ".join(call) for call in runner.calls)


def test_publish_rejects_stale_sha_and_does_not_post(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_publishable(tmp_path, sha=SHA1)
    world.head_sha = SHA2
    code = _run(app, [ISSUE, "publish-review", "--yes"])
    output = app.stdout.getvalue()
    assert code == 2
    assert "outcome: BLOCKED" in output
    assert "Refusing to publish" in output
    assert posts(runner) == []
    assert not (_commit(tmp_path, SHA1) / "review" / "publication.json").exists()


def test_repeat_publication_does_not_create_a_second_review(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_publishable(tmp_path, sha=SHA1)
    world.head_sha = SHA1
    assert _run(app, [ISSUE, "publish-review", "--yes"]) == 0
    assert len(posts(runner)) == 1
    receipt = read_json(_commit(tmp_path, SHA1) / "review" / "publication.json")
    assert receipt["github_review_id"] == 4242
    assert _run(app, [ISSUE, "publish-review", "--yes"]) == 0
    assert len(posts(runner)) == 1
    assert "already published" in app.stdout.getvalue()


def test_new_sha_preserves_the_previous_commit_directory(tmp_path):
    app, runner, world = make_app(tmp_path)
    _ready_issue(world)
    _run(app, [ISSUE, "notes", "--accept"])
    marker = _commit(tmp_path, SHA1) / "snapshot.json"
    assert marker.exists()
    original = marker.read_text(encoding="utf-8")
    world.head_sha = SHA2
    code = _run(app, [ISSUE])
    assert code == 0
    assert marker.read_text(encoding="utf-8") == original
    assert (_commit(tmp_path, SHA2) / "snapshot.json").exists()
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    assert session["active_sha"] == SHA2
    assert SHA1 in session["previous_shas"]


def test_profile_prepare_is_idempotent_and_not_destructive(tmp_path):
    app, runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    assert _run(app, [ISSUE, "test", "prepare"]) == 0
    profile = _commit(tmp_path, SHA1) / "testing" / "profile" / "profile.json"
    compose = _commit(tmp_path, SHA1) / "testing" / "profile" / "docker-compose.yml"
    first_profile = profile.read_bytes()
    first_compose = compose.read_bytes()
    before = len(runner.calls)
    assert _run(app, [ISSUE, "test", "prepare"]) == 0
    assert profile.read_bytes() == first_profile
    assert compose.read_bytes() == first_compose
    assert "Reused the existing virtualization profile." in app.stdout.getvalue()
    assert runner.calls[before:] == []
    assert not any("down" in call for call in runner.calls)


def test_image_fetch_records_a_changed_digest(tmp_path):
    app, _runner, world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    _run(app, [ISSUE, "test", "prepare"])
    world.digest = "sha256:" + "a" * 64
    assert _run(app, [ISSUE, "test", "fetch"]) == 0
    world.digest = "sha256:" + "b" * 64
    assert _run(app, [ISSUE, "test", "fetch"]) == 0
    environment = read_json(_commit(tmp_path, SHA1) / "testing" / "environment.json")
    assert environment["digest"] == "sha256:" + "b" * 64
    assert environment["previous_digest"] == "sha256:" + "a" * 64
    assert environment["changed"] is True
    assert environment["sha"] == SHA1
    assert "differs" in app.stdout.getvalue()
    profile = read_json(_commit(tmp_path, SHA1) / "testing" / "profile" / "profile.json")
    assert profile["image_digest"] == environment["digest"]


def test_pull_request_comment_attaches_screenshot_and_video(tmp_path):
    app, runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    shot = tmp_path / "shot.png"
    video = tmp_path / "run.webm"
    shot.write_bytes(b"png")
    video.write_bytes(b"webm")
    body = tmp_path / "comment.md"
    body.write_text(
        "Expected the cart to reject a negative quantity.\n\n"
        "Actual: the cart saved it.\n\n"
        "![cart](shot.png)\n\n"
        "[walkthrough](run.webm)\n",
        encoding="utf-8",
    )
    denied = _run(
        app,
        [ISSUE, "pr", "comment", "--body-file", str(body), "--attach", str(shot), "--attach", str(video)],
    )
    assert denied == 3
    assert not any("comment" in call and "--body-file" in call for call in runner.calls if call[0] == "gh")
    code = _run(
        app,
        [
            ISSUE,
            "pr",
            "comment",
            "--body-file",
            str(body),
            "--attach",
            str(shot),
            "--attach",
            str(video),
            "--yes",
        ],
    )
    assert code == 0
    comment_calls = [call for call in runner.calls if call[0] == "gh" and "comment" in call]
    assert len(comment_calls) == 1
    argv = comment_calls[0]
    assert "--body-file" in argv
    assert argv[argv.index("--body-file") + 1] == str(body)
    assert argv.count("--attach") == 2
    assert str(shot) in argv
    assert str(video) in argv
    receipt = read_json(_commit(tmp_path, SHA1) / "testing" / "publication.json")
    assert receipt["status"] == "success"


def test_failed_jira_transition_does_not_republish_the_review(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_publishable(tmp_path, sha=SHA1)
    world.head_sha = SHA1
    assert _run(app, [ISSUE, "publish-review", "--yes"]) == 0
    assert len(posts(runner)) == 1
    world.transition_code = 1
    code = _run(app, [ISSUE, "jira", "transition", "--status", "In Progress", "--yes"])
    assert code == 2
    assert "outcome: BLOCKED" in app.stdout.getvalue()
    receipt = read_json(_commit(tmp_path, SHA1) / "review" / "publication.json")
    assert receipt["status"] == "success"
    assert receipt["github_review_id"] == 4242
    assert _run(app, [ISSUE, "publish-review", "--yes"]) == 0
    assert len(posts(runner)) == 1
    assert len(transitions(runner)) == 1
    assert _run(app, [ISSUE, "jira", "transition", "--status", "In Progress", "--yes"]) == 2
    assert len(transitions(runner)) == 2
    assert len(posts(runner)) == 1


def test_external_mutations_require_explicit_authorization(tmp_path):
    app, runner, world = make_app(tmp_path)
    _seed_publishable(tmp_path, sha=SHA1)
    world.head_sha = SHA1
    assert _run(app, [ISSUE, "jira", "comment", "--body", "Please add testing notes."]) == 3
    assert _run(app, [ISSUE, "jira", "transition", "--status", "In Progress"]) == 3
    assert _run(app, [ISSUE, "publish-review"]) == 3
    assert transitions(runner) == []
    assert posts(runner) == []
    assert not any(call[0] == "acli" and "create" in call for call in runner.calls)


def test_passing_checks_are_not_reused_for_a_new_sha(tmp_path):
    app, _runner, world = make_app(tmp_path)
    _ready_issue(world)
    _run(app, [ISSUE, "notes", "--accept"])
    assert read_json(_commit(tmp_path, SHA1) / "github-checks.json")["outcome"] == "READY"
    world.head_sha = SHA2
    world.required_checks = [
        check("build", "fail", "FAILURE"),
        check("Bugbot", "pass", "SUCCESS"),
        check("CodeQL", "pass", "SUCCESS"),
    ]
    world.all_checks = world.required_checks
    _run(app, [ISSUE])
    assert read_json(_commit(tmp_path, SHA1) / "github-checks.json")["outcome"] == "READY"
    assert read_json(_commit(tmp_path, SHA2) / "github-checks.json")["outcome"] == "ACTION_REQUIRED"
    assert "outcome: ACTION_REQUIRED" in app.stdout.getvalue()


def _run(app, argv: list[str]) -> int:
    app.stdout.seek(0)
    app.stdout.truncate()
    app.stderr.seek(0)
    app.stderr.truncate()
    return main(argv, runner=app.runner, config=app.config, interactive=False, stdout=app.stdout, stderr=app.stderr)


def _ready_issue(world: World) -> None:
    world.issue = jira_document("Ran the cart tests and recorded the result.")
    world.required_checks = passing_checks()
    world.all_checks = passing_checks()
    world.threads = review_threads()
    world.head_sha = SHA1


def _commit(tmp_path: Path, sha: str) -> Path:
    return tmp_path / "reviews" / ISSUE / "prs" / "acme-widgets-pr-87" / "commits" / sha


def _seed_pr(tmp_path: Path, sha: str) -> None:
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": "acme/widgets#87",
            "active_sha": sha,
            "current_step": "virtualization",
            "outcome": "READY",
            "last_completed_step": "human-review",
            "last_updated": "2026-10-17T00:00:00Z",
            "recommendation": None,
            "decisions": {},
            "pr_candidates": ["acme/widgets#87"],
            "next_command": None,
        },
    )
    write_json(root / "issue.json", jira_document("Ran the cart tests and recorded the result."))
    write_json(root / "prs" / "acme-widgets-pr-87" / "pr.json", _normalized_pr(sha))


def _seed_publishable(tmp_path: Path, sha: str) -> None:
    _seed_pr(tmp_path, sha)
    review = _commit(tmp_path, sha) / "review"
    write_json(
        review / "findings.json",
        {
            "summary": "Please validate quantity.",
            "approval_recommendation": "request_changes",
            "findings": [
                {
                    "id": "F001",
                    "priority": "high",
                    "must_fix": True,
                    "path": "src/Example.cs",
                    "line": 142,
                    "side": "RIGHT",
                    "title": "Missing validation",
                    "explanation": "This path permits an invalid state.",
                    "suggested_change": "if (item.Quantity < 0) throw new InvalidOperationException();",
                }
            ],
        },
    )
    write_json(
        review / "human-review.json",
        {
            "rejected_review": False,
            "findings": {"F001": {"decision": "accept", "must_fix": True}},
            "added": [],
            "event": "REQUEST_CHANGES",
            "summary": "Please validate quantity.",
        },
    )
    write_json(review / "diff-lines.json", [["src/Example.cs", 142, "RIGHT"]])
    write_json(_commit(tmp_path, sha) / "snapshot.json", {"sha": sha})


def _normalized_pr(sha: str) -> dict:
    raw = pr_document(sha)
    return {
        "owner": "acme",
        "repo": "widgets",
        "number": 87,
        "title": raw["title"],
        "url": raw["url"],
        "state": raw["state"],
        "draft": False,
        "head_branch": "feature",
        "head_sha": sha,
        "base_branch": "main",
        "base_sha": raw["baseRefOid"],
        "body": raw["body"],
    }


def test_environment_failure_is_blocked_without_blaming_the_change(tmp_path):
    app, runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    code = _run(
        app,
        [ISSUE, "test", "record", "--result", "blocked", "--notes", "The Docker daemon was not running."],
    )
    output = app.stdout.getvalue()
    assert code == 2
    assert "outcome: BLOCKED" in output
    assert "In Progress" not in output
    assert "No Jira transition was performed." in output
    assert transitions(runner) == []
    stored = read_json(_commit(tmp_path, SHA1) / "testing" / "test-results.json")
    assert stored["failure_kind"] == "environment"
    assert stored["sha"] == SHA1


def test_bug_writer_draft_stays_local_until_a_command_is_configured(tmp_path):
    app, runner, _world = make_app(tmp_path)
    _seed_pr(tmp_path, SHA1)
    code = _run(app, [ISSUE, "bug", "--summary", "Cart accepts a negative quantity", "--body", "Save -1 and reload."])
    output = app.stdout.getvalue()
    assert code == 0
    assert "No Jira issue was created." in output
    draft = read_json(_commit(tmp_path, SHA1) / "testing" / "defect-draft.json")
    assert draft["summary"] == "Cart accepts a negative quantity"
    assert draft["sha"] == SHA1
    assert not any(call[0] == "acli" and "create" in call for call in runner.calls)
