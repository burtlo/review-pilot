"""P3: PR readiness gate over stored reports, and the filtered return draft."""

from __future__ import annotations

import asyncio
from pathlib import Path

from review_ticket.reports import ReadinessAttention, readiness_return_draft
from review_ticket.storage import read_json, write_json, write_text
from review_ticket.tui import ReviewTicketApp
from review_ticket.tui.readiness_screen import ReadinessScreen, project_readiness
from review_ticket.workflow import decide_analyzers
from textual.widgets import Button, Static, TextArea

from tests.support import ISSUE, make_app, posts

SHA_428 = "a428" + ("a" * 36)
SHA_429 = "b429" + ("b" * 36)
SHA_430 = "c430" + ("c" * 36)
REF_428 = "acme/widgets#428"
REF_429 = "acme/gadgets#429"
REF_430 = "acme/tools#430"
_RESOLVED_ID = "bugbot:clean-resolved"
_RESOLVED_BODY = "Resolved thread on the clean pull request."
_OPEN_BODY = "potential null reference"
_RUN_TEST_SIZE = (110, 52)


def _pr_slug(ref: str) -> str:
    owner, rest = ref.split("/", 1)
    repo, number = rest.split("#", 1)
    return f"{owner}-{repo}-pr-{number}"


def _commit(tmp_path: Path, ref: str, sha: str) -> Path:
    return tmp_path / "reviews" / ISSUE / "prs" / _pr_slug(ref) / "commits" / sha


def _passing_checks(sha: str) -> dict:
    return {
        "sha": sha,
        "checks": [
            {
                "name": "build",
                "required": True,
                "bucket": "pass",
                "state": "SUCCESS",
                "link": "https://example.test/build",
            }
        ],
        "outcome": "READY",
        "summary": "Required checks passed.",
    }


def _write_findings(commit: Path, findings: list[dict]) -> None:
    write_json(commit / "bugbot-findings.json", {"sha": commit.name, "findings": findings})
    write_json(commit / "codeql-findings.json", {"sha": commit.name, "findings": []})


def _seed_scenario_c(tmp_path: Path, *, decisions: dict | None = None, checks_outcome: str | None = None) -> None:
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": REF_428,
            "active_sha": SHA_428,
            "active_prs": [REF_428, REF_429, REF_430],
            "pr_shas": {REF_428: SHA_428, REF_429: SHA_429, REF_430: SHA_430},
            "pr_scope": "all",
            "current_step": "analyzer-findings",
            "outcome": "ACTION_REQUIRED",
            "decisions": decisions or {},
        },
    )
    rows = (
        (REF_428, SHA_428, 428, "https://github.com/acme/widgets/pull/428"),
        (REF_429, SHA_429, 429, "https://github.com/acme/gadgets/pull/429"),
        (REF_430, SHA_430, 430, "https://github.com/acme/tools/pull/430"),
    )
    for ref, sha, number, url in rows:
        owner, rest = ref.split("/", 1)
        repo, _number = rest.split("#", 1)
        write_json(
            root / "prs" / _pr_slug(ref) / "pr.json",
            {"url": url, "number": number, "owner": owner, "repo": repo},
        )
        commit = _commit(tmp_path, ref, sha)
        commit.mkdir(parents=True, exist_ok=True)
        payload = _passing_checks(sha)
        if ref == REF_429 and checks_outcome:
            payload["outcome"] = checks_outcome
            payload["checks"] = [
                {
                    "name": "build",
                    "required": True,
                    "bucket": "pending" if checks_outcome == "WAITING" else "pass",
                    "state": "IN_PROGRESS" if checks_outcome == "WAITING" else "SUCCESS",
                    "link": "",
                }
            ]
        write_json(commit / "github-checks.json", payload)
        if ref == REF_428:
            _write_findings(
                commit,
                [
                    {
                        "id": _RESOLVED_ID,
                        "source": "bugbot",
                        "path": "src/Clean.cs",
                        "line": 4,
                        "body": _RESOLVED_BODY,
                        "attention": "resolved",
                        "url": "https://github.com/acme/widgets/pull/428#discussion_r1",
                    }
                ],
            )
        elif ref == REF_429:
            _write_findings(
                commit,
                [
                    {
                        "id": "bugbot:open-429",
                        "source": "bugbot",
                        "path": "src/Foo.cs",
                        "line": 134,
                        "body": _OPEN_BODY,
                        "attention": "unaddressed",
                        "url": "https://github.com/acme/gadgets/pull/429#discussion_r9",
                    }
                ],
            )
        else:
            _write_findings(commit, [])
    write_text(
        root / "readiness.md",
        "\n".join(
            [
                "# Pull request readiness",
                "",
                "## acme/widgets#428 — READY",
                "",
                "Build succeeded",
                "",
                "## acme/gadgets#429 — READY",
                "",
                "Build succeeded",
                "",
                "## acme/tools#430 — READY",
                "",
                "Build succeeded",
                "",
            ]
        ),
    )


def _plain(widget: Static) -> str:
    content = widget.content
    return content if isinstance(content, str) else str(content)


def _mount(tmp_path: Path):
    app, runner, _world = make_app(tmp_path)
    tui = ReviewTicketApp(store=app.store, issue=ISSUE, workflow_app=app, revise=False)
    return app, runner, tui


def test_two_ready_prs_do_not_hide_one_open_bugbot(tmp_path):
    _seed_scenario_c(
        tmp_path,
        decisions={"analyzers": {SHA_428: {"choice": "accept_dispositions", "notes": "", "at": "t"}}},
    )
    app, _runner, _tui = _mount(tmp_path)
    view = project_readiness(app.store, ISSUE, in_progress_status="In Progress")
    by_number = {row.number: row for row in view.rows}
    assert by_number[428].satisfied is True
    assert by_number[430].satisfied is True
    assert by_number[429].satisfied is False
    assert by_number[429].analyzer_label == "Bugbot 1 OPEN"
    assert view.approve_enabled is False
    assert view.overall == "ACTION_REQUIRED"
    assert "Build succeeded" in view.detail
    assert "#428" in view.detail or "widgets#428" in view.detail


def test_filtered_draft_differs_from_cli_return_text(tmp_path):
    """CLI ``--return`` still lists every stored finding. The TUI draft does not."""

    _seed_scenario_c(
        tmp_path,
        decisions={"analyzers": {SHA_428: {"choice": "accept_dispositions", "notes": "", "at": "t"}}},
    )
    app, runner, _world = make_app(tmp_path)
    decide_analyzers(app, ISSUE, "return", "", revise=True, resume_after=False)
    full = (tmp_path / "reviews" / ISSUE / "return-comment.md").read_text(encoding="utf-8")
    filtered = readiness_return_draft(
        issue=ISSUE,
        attention=[
            ReadinessAttention(
                number=428,
                sha=SHA_428,
                findings=(
                    {
                        "id": _RESOLVED_ID,
                        "source": "bugbot",
                        "path": "src/Clean.cs",
                        "line": 4,
                        "body": _RESOLVED_BODY,
                        "attention": "resolved",
                    },
                ),
            ),
            ReadinessAttention(
                number=429,
                sha=SHA_429,
                findings=(
                    {
                        "id": "bugbot:open-429",
                        "source": "bugbot",
                        "path": "src/Foo.cs",
                        "line": 134,
                        "body": _OPEN_BODY,
                        "attention": "unaddressed",
                    },
                ),
            ),
            ReadinessAttention(number=430, sha=SHA_430, findings=()),
        ],
    )
    assert runner.calls == []
    assert full != filtered
    assert "Bugbot or CodeQL findings still need a developer disposition." in full
    assert "Peer review is returning" in full
    assert _RESOLVED_ID in full
    assert _RESOLVED_BODY in full
    assert _OPEN_BODY in full
    assert "Bugbot or CodeQL findings still need a developer disposition." not in filtered
    assert _RESOLVED_ID not in filtered
    assert _RESOLVED_BODY not in filtered
    assert "428" not in filtered
    assert "430" not in filtered
    assert "PR #429" in filtered
    assert SHA_429 in filtered
    assert "src/Foo.cs:134" in filtered
    assert _OPEN_BODY in filtered
    assert "build" not in filtered.lower()
    assert "succeeded" not in filtered.lower()


def test_waiting_hides_approve_and_construction_does_not_call_runner(tmp_path):
    _seed_scenario_c(tmp_path, checks_outcome="WAITING")
    _app, runner, tui = _mount(tmp_path)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            assert runner.calls == []
            tui.push_screen(ReadinessScreen(tui.store, ISSUE, tui.workflow_app))
            await pilot.pause()
            assert runner.calls == []
            screen = tui.screen
            assert isinstance(screen, ReadinessScreen)
            summary = _plain(screen.query_one("#readiness-summary", Static))
            assert "Overall: WAITING" in summary
            assert "PR #429" in summary
            assert SHA_429 in summary
            approve = screen.query_one("#approve-btn", Button)
            reject = screen.query_one("#reject-btn", Button)
            refresh = screen.query_one("#refresh-btn", Button)
            assert approve.display is False
            assert reject.display is False
            assert refresh.display is True
            assert runner.calls == []

    asyncio.run(_run())


def test_refresh_calls_assess_and_the_runner(tmp_path):
    _seed_scenario_c(tmp_path, checks_outcome="WAITING")
    _app, runner, tui = _mount(tmp_path)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            tui.push_screen(ReadinessScreen(tui.store, ISSUE, tui.workflow_app))
            await pilot.pause()
            assert runner.calls == []
            await pilot.click("#refresh-btn")
            await pilot.pause()
            assert runner.calls
            assert any(call and call[0] in {"acli", "gh"} for call in runner.calls)

    asyncio.run(_run())


def test_scenario_c_reject_draft_names_only_the_blocker(tmp_path):
    _seed_scenario_c(
        tmp_path,
        decisions={"analyzers": {SHA_428: {"choice": "accept_dispositions", "notes": "", "at": "t"}}},
    )
    _app, runner, tui = _mount(tmp_path)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            tui.push_screen(ReadinessScreen(tui.store, ISSUE, tui.workflow_app))
            await pilot.pause()
            assert runner.calls == []
            screen = tui.screen
            summary = _plain(screen.query_one("#readiness-summary", Static))
            assert "Overall: ACTION REQUIRED" in summary
            assert "PR #428" in summary
            assert "PR #429" in summary
            assert "PR #430" in summary
            assert "Bugbot 1 OPEN" in summary
            assert "Analyzers PASS" in summary
            detail = screen.query_one("#detail-md").source
            assert "Build succeeded" in detail
            approve = screen.query_one("#approve-btn", Button)
            assert approve.display is True
            assert approve.disabled is True
            await pilot.click("#reject-btn")
            await pilot.pause()
            draft = screen.query_one("#draft-editor", TextArea).text
            assert "PR #429" in draft
            assert SHA_429 in draft
            assert "src/Foo.cs:134" in draft
            assert _OPEN_BODY in draft
            assert "428" not in draft
            assert "430" not in draft
            assert "Build succeeded" not in draft
            assert "build" not in draft.lower()
            assert _RESOLVED_BODY not in draft
            assert screen.query_one("#readiness-summary").display is False
            assert screen.query_one("#detail-scroll").display is True
            assert runner.calls == []
            await pilot.click("#save-btn")
            await pilot.pause()
            saved = (tmp_path / "reviews" / ISSUE / "return-comment.md").read_text(encoding="utf-8")
            assert saved == draft
            assert runner.calls == []
            assert posts(runner) == []
            session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
            assert session["decisions"]["analyzers"][SHA_429]["choice"] == "return"
            assert session["decisions"]["analyzers"][SHA_428]["choice"] == "accept_dispositions"

    asyncio.run(_run())


def test_ready_gate_approve_records_locally_without_github_review(tmp_path):
    _seed_scenario_c(
        tmp_path,
        decisions={
            "analyzers": {
                SHA_428: {"choice": "accept_dispositions", "notes": "", "at": "t"},
                SHA_429: {"choice": "override", "notes": "false positive", "at": "t"},
            }
        },
    )
    app, runner, tui = _mount(tmp_path)
    view = project_readiness(app.store, ISSUE, in_progress_status="In Progress")
    assert view.approve_enabled is True
    assert all(row.satisfied for row in view.rows)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            tui.push_screen(ReadinessScreen(tui.store, ISSUE, tui.workflow_app))
            await pilot.pause()
            assert runner.calls == []
            approve = tui.screen.query_one("#approve-btn", Button)
            assert approve.disabled is False
            await pilot.click("#approve-btn")
            await pilot.pause()
            session = read_json(tmp_path / "reviews" / ISSUE / "session.json")
            assert session["decisions"]["readiness"]["choice"] == "approve"
            assert runner.calls == []
            assert posts(runner) == []

    asyncio.run(_run())


def test_missing_checks_exception_enables_approve(tmp_path):
    root = tmp_path / "reviews" / ISSUE
    sha = "d" * 40
    ref = "acme/widgets#87"
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": ref,
            "active_sha": sha,
            "active_prs": [ref],
            "pr_shas": {ref: sha},
            "current_step": "github-readiness",
            "decisions": {"missing_checks": {sha: {"choice": "accept", "at": "t"}}},
        },
    )
    commit = _commit(tmp_path, ref, sha)
    commit.mkdir(parents=True, exist_ok=True)
    write_json(
        commit / "github-checks.json",
        {
            "sha": sha,
            "outcome": "REVIEW_DECISION",
            "summary": "Required checks were not reported: build.",
            "checks": [{"name": "build", "required": True, "bucket": "missing", "state": ""}],
        },
    )
    _write_findings(commit, [])
    app, _runner, _tui = _mount(tmp_path)
    view = project_readiness(app.store, ISSUE, in_progress_status="In Progress")
    assert view.rows[0].satisfied is True
    assert view.approve_enabled is True
    assert "acknowledged" in view.rows[0].checks_label


def test_unaddressed_finding_stays_blocked_after_accept_dispositions(tmp_path):
    _seed_scenario_c(
        tmp_path,
        decisions={"analyzers": {SHA_429: {"choice": "accept_dispositions", "notes": "", "at": "t"}}},
    )
    app, _runner, _tui = _mount(tmp_path)
    view = project_readiness(app.store, ISSUE, in_progress_status="In Progress")
    blocker = next(row for row in view.rows if row.number == 429)
    assert blocker.satisfied is False
    assert view.approve_enabled is False


def test_no_pull_request_shows_select_guidance(tmp_path):
    root = tmp_path / "reviews" / ISSUE
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": None,
            "active_sha": None,
            "active_prs": [],
            "pr_shas": {},
            "current_step": "github-readiness",
            "outcome": "ACTION_REQUIRED",
            "next_command": f"review-ticket {ISSUE} pr select owner/repo#number",
            "decisions": {},
        },
    )
    _app, runner, tui = _mount(tmp_path)

    async def _run() -> None:
        async with tui.run_test(size=_RUN_TEST_SIZE) as pilot:
            await pilot.pause()
            tui.push_screen(ReadinessScreen(tui.store, ISSUE, tui.workflow_app))
            await pilot.pause()
            assert runner.calls == []
            summary = _plain(tui.screen.query_one("#readiness-summary", Static))
            assert "No open pull request" in summary
            assert f"review-ticket {ISSUE} pr select owner/repo#number" in summary
            assert "PR #" not in summary
            assert tui.screen.query_one("#approve-btn", Button).display is False
            assert tui.screen.query_one("#reject-btn", Button).display is False

    asyncio.run(_run())
