"""P10: headless test environment screen."""

from __future__ import annotations

import asyncio
from pathlib import Path

from review_ticket.environment_projection import project_test_environment
from review_ticket.storage import read_json, write_json
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.environment_screen import EnvironmentScreen
from review_ticket.tui.functional_testing_screen import FunctionalTestingScreen
from textual.widgets import ListView, Static
from tests.support import ISSUE, SHA1, SHA2, make_app
from tests.test_acceptance import _commit, _seed_pr
from tests.test_status_projection import REF_B, _commit_dir, _seed_checks, _seed_findings, _seed_three_pr_session, _store

PILOT_SIZE = (120, 48)


def _seed_manual_complete(commit_dir: Path) -> None:
    commit_dir.mkdir(parents=True, exist_ok=True)
    _seed_checks(commit_dir)
    _seed_findings(commit_dir)
    review = commit_dir / "review"
    write_json(
        review / "human-review.json",
        {
            "rejected_review": False,
            "findings": {"F001": {"decision": "accept", "must_fix": False}},
            "added": [],
            "recorded_at": "2026-10-18T11:00:00Z",
        },
    )
    write_json(
        review / "manual-review.json",
        {
            "sha": commit_dir.name,
            "completed": True,
            "disposition": "APPROVE",
            "notes": "Looks good.",
            "findings": [],
            "recorded_at": "2026-10-18T12:00:00Z",
        },
    )


def _seed_environment_fixture(tmp_path: Path) -> None:
    _seed_pr(tmp_path, SHA1)
    commit = _commit(tmp_path, SHA1)
    _seed_manual_complete(commit)


async def _open_environment_from_hub(pilot, pr_index: int = 0) -> None:
    await pilot.pause()
    await pilot.click("#hub-btn")
    await pilot.pause()
    pr_list = pilot.app.screen.query_one("#pr-list", ListView)
    pr_list.index = pr_index
    await pilot.pause()
    track_list = pilot.app.screen.query_one("#track-list", ListView)
    track_list.focus()
    track_list.index = 2
    await pilot.pause()
    children = list(track_list.children)
    if len(children) > 2:
        await pilot.click(children[2])
    await pilot.pause()


def test_environment_mount_does_not_call_docker(tmp_path):
    _seed_environment_fixture(tmp_path)
    workflow, runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            app.push_screen(
                EnvironmentScreen(
                    _store(tmp_path),
                    workflow,
                    issue=ISSUE,
                    ref="acme/widgets#87",
                    owner="acme",
                    repo="widgets",
                    number=87,
                    sha=SHA1,
                    stored_sha=SHA1,
                )
            )
            await pilot.pause()
            assert isinstance(app.screen, EnvironmentScreen)
            detail = app.screen.query_one("#detail", Static).render()
            detail = str(detail)
            assert "Test profile: Missing" in detail
            assert "Outcome: BLOCKED" in detail
            assert runner.calls == []

    asyncio.run(_run())


def test_prepare_fetch_launch_on_button_press(tmp_path):
    _seed_environment_fixture(tmp_path)
    workflow, runner, world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)
    testing = _commit(tmp_path, SHA1) / "testing"

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            app.push_screen(
                EnvironmentScreen(
                    _store(tmp_path),
                    workflow,
                    issue=ISSUE,
                    ref="acme/widgets#87",
                    owner="acme",
                    repo="widgets",
                    number=87,
                    sha=SHA1,
                    stored_sha=SHA1,
                )
            )
            await pilot.pause()
            await pilot.click("#btn-prepare")
            await pilot.pause()
            await pilot.pause()
            assert (testing / "profile" / "profile.json").is_file()
            before_fetch = len(runner.calls)
            await pilot.click("#btn-fetch")
            await pilot.pause()
            await pilot.pause()
            assert any(call[0] == "docker" and "pull" in call for call in runner.calls[before_fetch:])
            env = read_json(testing / "environment.json")
            assert env["sha"] == SHA1
            assert env["digest"] == world.digest
            before_launch = len(runner.calls)
            await pilot.click("#btn-launch")
            await pilot.pause()
            await pilot.pause()
            compose_calls = [
                call for call in runner.calls[before_launch:] if call[0] == "docker" and "compose" in call
            ]
            assert compose_calls
            assert "down" not in " ".join(compose_calls[0])
            env = read_json(testing / "environment.json")
            assert env.get("launched_at")

    asyncio.run(_run())


def test_fetch_failure_renders_blocked_not_request_changes(tmp_path):
    _seed_environment_fixture(tmp_path)
    workflow, runner, world = make_app(tmp_path)
    world.docker_pull_code = 1
    world.docker_pull_stderr = "daemon not running"
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            app.push_screen(
                EnvironmentScreen(
                    _store(tmp_path),
                    workflow,
                    issue=ISSUE,
                    ref="acme/widgets#87",
                    owner="acme",
                    repo="widgets",
                    number=87,
                    sha=SHA1,
                    stored_sha=SHA1,
                )
            )
            await pilot.pause()
            await pilot.click("#btn-prepare")
            await pilot.pause()
            await pilot.pause()
            await pilot.click("#btn-fetch")
            await pilot.pause()
            await pilot.pause()
            detail = str(app.screen.query_one("#detail", Static).render())
            assert "Outcome: BLOCKED" in detail
            assert "daemon not running" in detail
            assert "Request Changes" not in detail
            assert not (_commit(tmp_path, SHA1) / "review" / "publication.json").exists()

    asyncio.run(_run())


def test_profile_without_digest_renders_blocked_on_mount(tmp_path):
    _seed_environment_fixture(tmp_path)
    workflow, runner, _world = make_app(tmp_path)
    testing = _commit(tmp_path, SHA1) / "testing"
    profile_dir = testing / "profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        profile_dir / "profile.json",
        {"image": "ghcr.io/acme/widgets:feature", "project_name": "widgets-test"},
    )
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            app.push_screen(
                EnvironmentScreen(
                    _store(tmp_path),
                    workflow,
                    issue=ISSUE,
                    ref="acme/widgets#87",
                    owner="acme",
                    repo="widgets",
                    number=87,
                    sha=SHA1,
                    stored_sha=SHA1,
                )
            )
            await pilot.pause()
            detail = str(app.screen.query_one("#detail", Static).render())
            assert "Test profile: Available" in detail
            assert "Image digest: —" in detail
            assert "Unknown until image is fetched for this SHA" in detail
            assert "Outcome: BLOCKED" in detail
            assert runner.calls == []

    asyncio.run(_run())


def test_launch_compose_failure_renders_blocked(tmp_path):
    _seed_environment_fixture(tmp_path)
    workflow, runner, world = make_app(tmp_path)
    world.docker_compose_code = 1
    world.docker_compose_stderr = "service failed to start"
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            app.push_screen(
                EnvironmentScreen(
                    _store(tmp_path),
                    workflow,
                    issue=ISSUE,
                    ref="acme/widgets#87",
                    owner="acme",
                    repo="widgets",
                    number=87,
                    sha=SHA1,
                    stored_sha=SHA1,
                )
            )
            await pilot.pause()
            await pilot.click("#btn-prepare")
            await pilot.pause()
            await pilot.pause()
            await pilot.click("#btn-fetch")
            await pilot.pause()
            await pilot.pause()
            await pilot.click("#btn-launch")
            await pilot.pause()
            await pilot.pause()
            detail = str(app.screen.query_one("#detail", Static).render())
            assert "Outcome: BLOCKED" in detail
            assert "service failed to start" in detail
            assert "Request Changes" not in detail

    asyncio.run(_run())


def test_digest_for_other_sha_not_shown_as_evidence(tmp_path):
    _seed_environment_fixture(tmp_path)
    testing = _commit(tmp_path, SHA1) / "testing"
    testing.mkdir(parents=True, exist_ok=True)
    write_json(
        testing / "environment.json",
        {
            "sha": SHA2,
            "image": "ghcr.io/acme/widgets:feature",
            "digest": "sha256:" + "f" * 64,
            "fetched_at": "2026-10-18T00:00:00Z",
        },
    )
    store = _store(tmp_path)
    projection = project_test_environment(
        store,
        ISSUE,
        owner="acme",
        repo="widgets",
        number=87,
        sha=SHA1,
    )
    assert projection.digest is None
    assert "another SHA" in projection.sha_match_label
    assert projection.environment_outcome == "BLOCKED"


def test_hub_routes_functional_track_to_functional_testing(tmp_path):
    _seed_three_pr_session(tmp_path)
    commit = _commit_dir(tmp_path, REF_B, SHA2)
    _seed_manual_complete(commit)
    workflow, runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            await _open_environment_from_hub(pilot, pr_index=1)
            assert isinstance(app.screen, FunctionalTestingScreen)
            assert runner.calls == []

    asyncio.run(_run())


def test_launch_without_fetch_is_refused(tmp_path):
    _seed_environment_fixture(tmp_path)
    workflow, runner, _world = make_app(tmp_path)
    app = ReviewTicketApp(store=_store(tmp_path), issue=ISSUE, workflow_app=workflow)

    async def _run() -> None:
        async with app.run_test(size=PILOT_SIZE) as pilot:
            app.push_screen(
                EnvironmentScreen(
                    _store(tmp_path),
                    workflow,
                    issue=ISSUE,
                    ref="acme/widgets#87",
                    owner="acme",
                    repo="widgets",
                    number=87,
                    sha=SHA1,
                    stored_sha=SHA1,
                )
            )
            await pilot.pause()
            await pilot.click("#btn-prepare")
            await pilot.pause()
            await pilot.pause()
            launch = app.screen.query_one("#btn-launch")
            assert launch.disabled is True
            await pilot.click("#btn-launch")
            await pilot.pause()
            assert not any(call[0] == "docker" and "compose" in call for call in runner.calls)

    asyncio.run(_run())
