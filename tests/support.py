"""Fixture GitHub and Jira responses for workflow tests."""

from __future__ import annotations

import io
import json
from pathlib import Path

from review_ticket.config import Config
from review_ticket.runner import CommandResult, ScriptedRunner
from review_ticket.workflow import App

ISSUE = "DOTNETIOT-1234"
SHA1 = "a" * 40
SHA2 = "b" * 40
BASE = "c" * 40

DIFF = "\n".join(
    [
        "diff --git a/src/Example.cs b/src/Example.cs",
        "--- a/src/Example.cs",
        "+++ b/src/Example.cs",
        "@@ -140,3 +140,5 @@",
        " " + "    public void Save(Item item)",
        " " + "    {",
        "+        if (item.Quantity < 0)",
        "+            throw new InvalidOperationException();",
        " " + "        store.Save(item);",
        "",
    ]
)


def check(name: str, bucket: str, state: str) -> dict:
    return {
        "name": name,
        "bucket": bucket,
        "state": state,
        "link": f"https://example.test/{name}",
        "workflow": name,
        "description": "",
    }


def passing_checks() -> list[dict]:
    return [
        check("build", "pass", "SUCCESS"),
        check("Bugbot", "pass", "SUCCESS"),
        check("CodeQL", "pass", "SUCCESS"),
    ]


def jira_document(notes: str | None, status: str = "Peer Review") -> dict:
    description = "## Acceptance Criteria\n\n- Negative quantities are rejected\n"
    if notes is not None:
        description += f"\n## Testing Notes\n\n{notes}\n"
    return {
        "key": ISSUE,
        "fields": {
            "summary": "Reject negative quantities",
            "status": {"name": status},
            "description": description,
        },
    }


def pr_document(sha: str) -> dict:
    return {
        "number": 87,
        "title": "Reject negative quantities",
        "url": "https://github.com/acme/widgets/pull/87",
        "state": "OPEN",
        "isDraft": False,
        "headRefName": "feature",
        "headRefOid": sha,
        "baseRefName": "main",
        "baseRefOid": BASE,
        "body": "Fixes DOTNETIOT-1234",
    }


def search_document() -> list[dict]:
    return [
        {
            "number": 87,
            "title": "Reject negative quantities",
            "url": "https://github.com/acme/widgets/pull/87",
            "repository": {"nameWithOwner": "acme/widgets"},
            "state": "open",
        }
    ]


def review_threads(nodes: list[dict] | None = None) -> dict:
    return {
        "data": {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                        "nodes": nodes or [],
                    }
                }
            }
        }
    }


def bugbot_thread(*, reply: str | None = None, resolved: bool = False) -> dict:
    comments = [
        {
            "databaseId": 1,
            "url": "https://github.com/acme/widgets/pull/87#discussion_r1",
            "body": "Bugbot: quantity is not validated.",
            "createdAt": "2026-10-01T00:00:00Z",
            "author": {"login": "cursor[bot]"},
            "commit": {"oid": SHA1},
        }
    ]
    if reply:
        comments.append(
            {
                "databaseId": 2,
                "url": "https://github.com/acme/widgets/pull/87#discussion_r2",
                "body": reply,
                "createdAt": "2026-10-02T00:00:00Z",
                "author": {"login": "dev"},
                "commit": {"oid": SHA1},
            }
        )
    return {
        "id": "PRRT_1",
        "isResolved": resolved,
        "isOutdated": False,
        "path": "src/Example.cs",
        "line": 142,
        "comments": {"nodes": comments},
    }


class World:
    def __init__(self) -> None:
        self.issue = jira_document(notes=None)
        self.comments: list = []
        self.head_sha = SHA1
        self.required_checks = passing_checks()
        self.all_checks = passing_checks()
        self.threads = review_threads()
        self.alerts: list = []
        self.alerts_code = 0
        self.alerts_stderr = ""
        self.remote_reviews: list = []
        self.transition_code = 0
        self.digest = "sha256:" + "a" * 64
        self.reviewer_output = {
            "summary": "Quantity is not validated on every path.",
            "approval_recommendation": "request_changes",
            "findings": [],
        }

    def handle(self, argv: list[str], cwd: str | None, data: str | None, env: dict | None) -> CommandResult:
        joined = " ".join(argv)
        if argv[0] == "acli" and "view" in argv:
            return self._ok(argv, self.issue)
        if argv[0] == "acli" and "comment" in argv and "list" in argv:
            return self._ok(argv, self.comments)
        if argv[0] == "acli" and "comment" in argv and "create" in argv:
            return self._ok(argv, {"id": "10001"})
        if argv[0] == "acli" and "transition" in argv:
            if self.transition_code:
                return CommandResult(argv, self.transition_code, "", "transition failed")
            return self._ok(argv, {"ok": True})
        if argv[0] == "gh" and "search" in argv:
            return self._ok(argv, search_document())
        if argv[0] == "gh" and "checks" in argv:
            payload = self.required_checks if "--required" in argv else self.all_checks
            return CommandResult(argv, self._check_code(payload), json.dumps(payload), "")
        if argv[0] == "gh" and "view" in argv:
            return self._ok(argv, pr_document(self.head_sha))
        if argv[0] == "gh" and "clone" in argv:
            return self._ok(argv, "")
        if argv[0] == "gh" and "comment" in argv and "--body-file" in argv:
            return CommandResult(argv, 0, "https://github.com/acme/widgets/pull/87#issuecomment-7\n", "")
        if "graphql" in argv:
            return self._ok(argv, self.threads)
        if "code-scanning/alerts" in joined:
            if self.alerts_code:
                return CommandResult(argv, self.alerts_code, "", self.alerts_stderr or "HTTP 403")
            return self._ok(argv, self.alerts)
        if "--method" in argv and "POST" in argv and "/reviews" in joined:
            return self._ok(
                argv,
                {
                    "id": 4242,
                    "html_url": "https://github.com/acme/widgets/pull/87#pullrequestreview-4242",
                    "state": "CHANGES_REQUESTED",
                    "commit_id": self.head_sha,
                },
            )
        if any(part.endswith("/comments") for part in argv):
            return self._ok(argv, [{"id": 7, "html_url": "https://github.com/acme/widgets/pull/87#discussion_r7"}])
        if any(part.endswith("/reviews") for part in argv):
            return self._ok(argv, self.remote_reviews)
        if argv[0] == "git" and "rev-parse" in argv:
            return CommandResult(argv, 0, self.head_sha + "\n", "")
        if argv[0] == "git" and "diff" in argv:
            return CommandResult(argv, 0, DIFF, "")
        if argv[0] == "git":
            return self._ok(argv, "")
        if argv[0] == "docker" and "pull" in argv:
            return self._ok(argv, "pulled\n")
        if argv[0] == "docker" and "inspect" in argv:
            return self._ok(argv, [f"ghcr.io/acme/widgets@{self.digest}"])
        if argv[0] == "docker" and "compose" in argv:
            if "down" in argv:
                raise AssertionError("virtualization must not destroy environments with compose down")
            return self._ok(argv, "")
        if argv[0] == "reviewer":
            Path(argv[-1]).write_text(json.dumps(self.reviewer_output), encoding="utf-8")
            return self._ok(argv, "")
        raise AssertionError(f"unexpected command: {joined}")

    def _check_code(self, checks: list[dict]) -> int:
        buckets = [item.get("bucket") for item in checks]
        if "pending" in buckets:
            return 8
        if "fail" in buckets or "cancel" in buckets:
            return 1
        return 0

    def _ok(self, argv: list[str], payload) -> CommandResult:
        if isinstance(payload, str):
            stdout = payload
        else:
            stdout = json.dumps(payload)
        return CommandResult(list(argv), 0, stdout, "")


def make_app(tmp_path: Path, world: World | None = None, **config_kwargs) -> tuple[App, ScriptedRunner, World]:
    world = world or World()
    runner = ScriptedRunner()
    runner.when(lambda argv: True, world.handle)
    config = Config(
        reviews_dir=tmp_path / "reviews",
        cache_dir=tmp_path / "cache",
        reviewer_command=config_kwargs.pop("reviewer_command", "reviewer {context} {output}"),
        **config_kwargs,
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    app = App(
        config=config,
        runner=runner,
        interactive=False,
        stdout=stdout,
        stderr=stderr,
        cwd=tmp_path,
    )
    return app, runner, world


def posts(runner: ScriptedRunner) -> list[list[str]]:
    return [
        call
        for call in runner.calls
        if "--method" in call and "POST" in call and any("/reviews" in part for part in call)
    ]


def transitions(runner: ScriptedRunner) -> list[list[str]]:
    return [call for call in runner.calls if call and call[0] == "acli" and "transition" in call]
