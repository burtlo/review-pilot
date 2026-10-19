from pathlib import Path

from review_ticket.cli import main
from review_ticket.workflow import resume
from review_ticket.models import Outcome
from review_ticket.storage import read_json, write_json
from tests.support import (
    ISSUE,
    SHA1,
    SHA2,
    World,
    bugbot_thread,
    iris_pr19_review_threads,
    check,
    jira_document,
    make_app,
    passing_checks,
    posts,
    pr_document,
    review_threads,
    transitions,
)


def test_interactive_resume_defers_testing_notes_to_attach(tmp_path):
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document("Ran the cart tests and recorded the result.")
    app.interactive = True
    result = resume(app, ISSUE)
    output = app.stdout.getvalue()
    assert result.outcome == Outcome.REVIEW_DECISION
    assert f"next: review-ticket {ISSUE} attach" in output
    assert "Accept testing notes?" not in output


def test_multiple_discovered_prs_are_tracked_automatically(tmp_path):
    app, _runner, world = make_app(tmp_path)
    doc = jira_document("Ran the cart tests and recorded the result.")
    doc["fields"]["description"] += (
        "\nhttps://github.com/acme/widgets/pull/87\n"
        "https://github.com/acme/other/pull/88\n"
    )
    world.issue = doc
    world.required_checks = passing_checks()
    world.all_checks = passing_checks()
    code = _run(app, [ISSUE, "notes", "--accept"])
    assert code == 0
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    assert sorted(session["active_prs"]) == ["acme/other#88", "acme/widgets#87"]
    assert session["pr_shas"]["acme/widgets#87"] == SHA1
    assert session["pr_shas"]["acme/other#88"] == SHA1


def test_pr_select_limits_scope_to_one_pr(tmp_path):
    app, _runner, world = make_app(tmp_path)
    doc = jira_document("Ran the cart tests and recorded the result.")
    doc["fields"]["description"] += (
        "\nhttps://github.com/acme/widgets/pull/87\n"
        "https://github.com/acme/other/pull/88\n"
    )
    world.issue = doc
    world.required_checks = passing_checks()
    world.all_checks = passing_checks()
    assert _run(app, [ISSUE, "notes", "--accept"]) == 0
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    assert len(session["active_prs"]) == 2

    assert _run(app, [ISSUE, "pr", "select", "acme/widgets#87"]) == 0
    session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    assert session["pr_scope"] == "single"
    assert session["active_prs"] == ["acme/widgets#87"]


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
    assert "jira transition" in output
    assert "In Progress" in output.split("next:")[-1]
    assert transitions(runner) == []
    stored = read_json(_commit(tmp_path, SHA1) / "bugbot-findings.json")
    assert stored["findings"][0]["attention"] == "unaddressed"
    assert stored["findings"][0]["url"].startswith("https://github.com/")


def test_iris_pr19_unresolved_bugbot_suggests_return_to_in_progress(tmp_path):
    app, runner, world = make_app(tmp_path)
    _ready_issue(world)
    world.threads = iris_pr19_review_threads()
    world.issue = jira_document(
        "Ran the cart tests and recorded the result.",
        status="Ready for Peer Review",
    )
    world.issue["fields"]["description"] += (
        "\nhttps://github.com/kwik-trip-iot/KT.Shared.EmailProcessor.Iris/pull/19\n"
    )
    code = _run(app, [ISSUE, "notes", "--accept"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "outcome: ACTION_REQUIRED" in output
    assert "recommendation: In Progress" in output
    assert "jira transition" in output
    stored = read_json(tmp_path / "reviews" / ISSUE / "prs" / "acme-widgets-pr-87" / "commits" / SHA1 / "bugbot-findings.json")
    assert stored["findings"]
    assert any(item.get("attention") == "unaddressed" for item in stored["findings"])
    assert transitions(runner) == []


def test_code_scanning_api_404_does_not_block_when_codeql_check_passed(tmp_path):
    app, runner, world = make_app(tmp_path)
    _ready_issue(world)
    world.threads = review_threads()
    world.alerts_code = 1
    world.alerts_stderr = "gh: Not Found (HTTP 404)"
    code = _run(app, [ISSUE, "notes", "--accept"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "outcome: BLOCKED" not in output
    assert "HTTP 404" not in output.split("outcome:")[0]
    stored = read_json(_commit(tmp_path, SHA1) / "codeql-findings.json")
    assert stored.get("unavailable")


def test_status_output_includes_jira_and_pr_urls(tmp_path):
    app, _runner, world = make_app(tmp_path)
    _ready_issue(world)
    world.issue = jira_document("Ran the cart tests and recorded the result.")
    world.issue["fields"]["description"] = (
        (world.issue["fields"]["description"] or "")
        + "\nhttps://github.com/acme/widgets/pull/87\n"
    )
    _run(app, [ISSUE, "notes", "--accept"])
    app.stdout.truncate(0)
    app.stdout.seek(0)
    code = _run(app, [ISSUE, "status"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "jira:" in output
    assert "https://github.com/acme/widgets/pull/87" in output


def test_status_shows_jira_url_from_cached_raw_when_issue_url_empty(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    issue_dir = tmp_path / "reviews" / ISSUE
    issue_dir.mkdir(parents=True)
    write_json(issue_dir / "issue.json", {"key": ISSUE, "url": ""})
    write_json(
        issue_dir / "issue-raw.json",
        {
            "view": {
                "key": ISSUE,
                "self": "https://jira.example.test/rest/api/3/issue/963386",
            }
        },
    )
    session = app.store.ensure_session(ISSUE)
    session["active_pr"] = "acme/widgets#87"
    session["active_sha"] = SHA1
    session["active_prs"] = ["acme/widgets#87"]
    session["pr_shas"] = {"acme/widgets#87": SHA1}
    app.store.save_session(session)
    pr_dir = issue_dir / "prs" / "acme-widgets-pr-87"
    write_json(pr_dir / "pr.json", pr_document(SHA1))
    app.stdout.truncate(0)
    app.stdout.seek(0)
    code = _run(app, [ISSUE, "status"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "jira: https://jira.example.test/browse/DOTNETIOT-1234" in output


def test_analyzer_accept_dispositions_records_every_tracked_sha(tmp_path):
    app, _runner, _world = make_app(tmp_path)
    session = app.store.ensure_session(ISSUE)
    session["active_prs"] = ["acme/widgets#87", "acme/other#88"]
    session["active_pr"] = "acme/widgets#87"
    session["active_sha"] = SHA1
    session["pr_shas"] = {"acme/widgets#87": SHA1, "acme/other#88": SHA2}
    session["pr_scope"] = "all"
    app.store.save_session(session)
    from review_ticket.workflow import decide_analyzers

    decide_analyzers(app, ISSUE, "accept_dispositions", "", revise=False)
    stored = read_json(tmp_path / "reviews" / ISSUE / "session.json")
    bucket = stored["decisions"]["analyzers"]
    assert bucket[SHA1]["choice"] == "accept_dispositions"
    assert bucket[SHA2]["choice"] == "accept_dispositions"


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


def test_run_review_uses_ui_admin_reviewer_for_mapped_repository(tmp_path):
    from review_ticket.config import ReviewerProfile

    app, runner, world = make_app(
        tmp_path,
        reviewer_command="reviewer {context} {output} {agent}",
        reviewer_by_repository={
            "acme/widgets": ReviewerProfile(agent="ui-admin-reviewer"),
        },
    )
    _ready_issue(world)
    world.reviewer_output = {
        "summary": "UI admin review.",
        "approval_recommendation": "approve",
        "findings": [],
    }
    _run(app, [ISSUE, "notes", "--accept"])
    code = _run(app, [ISSUE, "run-review"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "reviewer: agent=ui-admin-reviewer (acme/widgets)" in output
    reviewer_calls = [call for call in runner.calls if call and call[0] == "reviewer"]
    assert len(reviewer_calls) == 1
    assert "ui-admin-reviewer" in " ".join(reviewer_calls[0])


def test_run_review_handoff_when_reviewer_command_unset(tmp_path):
    app, runner, world = make_app(tmp_path, reviewer_command=None)
    _ready_issue(world)
    _run(app, [ISSUE, "notes", "--accept"])
    code = _run(app, [ISSUE, "run-review"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "outcome: REVIEW_DECISION" in output
    assert "import-review" in output
    assert "context:" in output
    assert "prompt.md" in output
    assert "reviewer_command: unset" in output
    assert not any(call and call[0] == "reviewer" for call in runner.calls)


def test_automated_review_ready_handoff_lists_context_and_chain(tmp_path):
    app, _runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    _ready_issue(world)
    _run(app, [ISSUE, "notes", "--accept"])
    code = _run(app, [ISSUE, "analyzers", "--accept-dispositions"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "step: automated-review" in output
    assert "outcome: READY" in output
    assert "context:" in output and "prompt.md" in output
    assert "reviewer_command: configured" in output
    assert "chain:" in output
    assert "run-review" in output
    assert f"{ISSUE} attach" in output
    assert "review attach" not in output
    assert "test prepare" in output


def test_run_review_next_command_is_review_attach(tmp_path):
    app, _runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    _ready_issue(world)
    world.reviewer_output = {
        "summary": "Looks good.",
        "approval_recommendation": "approve",
        "findings": [],
    }
    _run(app, [ISSUE, "notes", "--accept"])
    code = _run(app, [ISSUE, "run-review"])
    output = app.stdout.getvalue()
    assert code == 0
    assert f"next: review-ticket {ISSUE} attach" in output
    assert "reviewer_command: configured" in output


def test_review_handoff_multi_pr_hint(tmp_path):
    app, _runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
    doc = jira_document("Ran the cart tests and recorded the result.")
    doc["fields"]["description"] += (
        "\nhttps://github.com/acme/widgets/pull/87\n"
        "https://github.com/acme/other/pull/88\n"
    )
    world.issue = doc
    world.required_checks = passing_checks()
    world.all_checks = passing_checks()
    world.threads = review_threads()
    world.head_sha = SHA1
    _run(app, [ISSUE, "notes", "--accept"])
    code = _run(app, [ISSUE, "analyzers", "--accept-dispositions"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "hint:" in output
    assert "pr select" in output


def test_reviewer_places_must_fix_inline_and_keeps_general_findings(tmp_path):
    app, runner, world = make_app(tmp_path, reviewer_command="reviewer {context} {output}")
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
    from review_ticket.util import fingerprint

    app, runner, world = make_app(tmp_path)
    _seed_publishable(tmp_path, sha=SHA1)
    world.head_sha = SHA1
    assert _run(app, [ISSUE, "publish-review", "--yes"]) == 0
    assert len(posts(runner)) == 1
    review_dir = _commit(tmp_path, SHA1) / "review"
    receipt = read_json(review_dir / "publication.json")
    payload = read_json(review_dir / "publish-payload.json")
    assert receipt["github_review_id"] == 4242
    assert receipt["fingerprint"] == fingerprint(payload)
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
            "track_disposition": "REQUEST_CHANGES",
            "track_disposition_confirmed": True,
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
