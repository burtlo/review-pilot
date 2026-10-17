"""Thin adapters over acli, gh, and docker. No workflow policy lives here."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from review_ticket.config import Config
from review_ticket.models import ToolError
from review_ticket.runner import CommandResult, Runner
from review_ticket.textutil import (
    adf_to_text,
    extract_section,
    normalize_comments,
    testing_notes_from_fields,
)
from review_ticket.util import parse_json_output

THREADS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes {
          id
          isResolved
          isOutdated
          path
          line
          comments(first: 50) {
            nodes {
              databaseId
              url
              body
              createdAt
              author { login }
              commit { oid }
            }
          }
        }
      }
    }
  }
}
""".strip()


@dataclass
class ServiceResult:
    items: list[dict[str, Any]] = field(default_factory=list)
    unavailable: bool = False
    message: str = ""


def _result_error(result: CommandResult, *, unavailable: bool = False) -> ToolError:
    detail = (result.stderr or result.stdout or "").strip()
    return ToolError(
        f"Command failed ({result.returncode}): {' '.join(result.argv)}\n{detail}",
        unavailable=unavailable,
        returncode=result.returncode,
    )


def _json_command(runner: Runner, argv: list[str], *, allow: tuple[int, ...] = (0,)) -> Any:
    result = runner.run(argv)
    if result.returncode not in allow:
        blob = f"{result.stderr}\n{result.stdout}".lower()
        unavailable = any(
            token in blob
            for token in ("http 403", "http 404", "http 503", "advanced security", "unavailable")
        )
        raise _result_error(result, unavailable=unavailable)
    if not result.stdout.strip():
        return None
    try:
        return parse_json_output(result.stdout)
    except json.JSONDecodeError as exc:
        raise ToolError(f"Could not parse JSON from {' '.join(argv)}: {exc}") from exc


def fetch_jira(runner: Runner, config: Config, issue: str) -> tuple[dict[str, Any], dict[str, Any]]:
    view = _json_command(
        runner,
        [config.acli_bin, "jira", "workitem", "view", issue, "--json", "--fields", "*all"],
    )
    comments_payload = _json_command(
        runner,
        [
            config.acli_bin,
            "jira",
            "workitem",
            "comment",
            "list",
            "--key",
            issue,
            "--json",
            "--paginate",
        ],
    )
    raw = {"view": view, "comments": comments_payload}
    return raw, normalize_issue(issue, view, comments_payload)


def normalize_issue(issue: str, view: Any, comments_payload: Any) -> dict[str, Any]:
    document = _unwrap_issue(view)
    fields = document.get("fields") if isinstance(document.get("fields"), dict) else document
    if not isinstance(fields, dict):
        raise ToolError("acli returned a Jira payload that is not an object.")
    description = adf_to_text(fields.get("description")).strip()
    status = fields.get("status")
    if isinstance(status, dict):
        status_name = str(status.get("name") or "")
    else:
        status_name = str(status or "")
    comments = normalize_comments(comments_payload)
    if not comments and isinstance(fields.get("comment"), (dict, list)):
        comments = normalize_comments(fields.get("comment"))
    testing = testing_notes_from_fields(fields, description)
    if not testing:
        for comment in comments:
            for heading in ("Testing Notes", "Test Notes"):
                section = extract_section(comment["body"], heading)
                if section:
                    testing = section
                    break
            if testing:
                break
    acceptance = ""
    for heading in ("Acceptance Criteria", "Acceptance criteria"):
        acceptance = extract_section(description, heading)
        if acceptance:
            break
    return {
        "key": str(document.get("key") or issue),
        "summary": str(fields.get("summary") or ""),
        "status": status_name,
        "description": description,
        "acceptance_criteria": acceptance,
        "testing_notes": testing.strip(),
        "comments": comments,
        "url": str(document.get("url") or fields.get("url") or ""),
    }


def _unwrap_issue(view: Any) -> dict[str, Any]:
    if isinstance(view, list):
        if not view:
            raise ToolError("acli returned no Jira work item.")
        view = view[0]
    if not isinstance(view, dict):
        raise ToolError("acli Jira view was not a JSON object.")
    for key in ("workItem", "issue", "data"):
        if isinstance(view.get(key), dict):
            return view[key]
    return view


def post_jira_comment(runner: Runner, config: Config, issue: str, body_file: Path) -> dict[str, Any]:
    payload = _json_command(
        runner,
        [
            config.acli_bin,
            "jira",
            "workitem",
            "comment",
            "create",
            "--key",
            issue,
            "--body-file",
            str(body_file),
            "--json",
        ],
    )
    return payload if isinstance(payload, dict) else {"raw": payload}


def transition_jira(runner: Runner, config: Config, issue: str, status: str) -> dict[str, Any]:
    payload = _json_command(
        runner,
        [
            config.acli_bin,
            "jira",
            "workitem",
            "transition",
            "--key",
            issue,
            "--status",
            status,
            "--yes",
            "--json",
        ],
    )
    return payload if isinstance(payload, dict) else {"raw": payload, "status": status}


def search_prs(runner: Runner, config: Config, issue: str) -> list[dict[str, Any]]:
    payload = _json_command(
        runner,
        [
            config.gh_bin,
            "search",
            "prs",
            issue,
            "--state",
            "open",
            "--json",
            "number,title,url,repository,state",
        ],
        allow=(0, 1),
    )
    items = payload if isinstance(payload, list) else []
    found: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            owner, repo = _repo_from_item(item)
        except ToolError:
            continue
        found.append(
            {
                "owner": owner,
                "repo": repo,
                "number": int(item["number"]),
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "state": str(item.get("state") or "open"),
            }
        )
    if config.github_repo:
        listed = _json_command(
            runner,
            [
                config.gh_bin,
                "pr",
                "list",
                "--repo",
                config.github_repo,
                "--search",
                issue,
                "--state",
                "open",
                "--json",
                "number,title,url,headRefName,headRefOid,baseRefName,isDraft,state",
            ],
            allow=(0, 1),
        )
        owner, repo = config.github_repo.split("/", 1)
        for item in listed or []:
            if not isinstance(item, dict):
                continue
            found.append(
                {
                    "owner": owner,
                    "repo": repo,
                    "number": int(item["number"]),
                    "title": str(item.get("title") or ""),
                    "url": str(item.get("url") or ""),
                    "state": str(item.get("state") or "open"),
                }
            )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for item in found:
        key = (item["owner"], item["repo"], item["number"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _repo_from_item(item: dict[str, Any]) -> tuple[str, str]:
    repository = item.get("repository")
    if isinstance(repository, str) and "/" in repository:
        owner, name = repository.split("/", 1)
        return owner, name
    if isinstance(repository, dict):
        name_with_owner = repository.get("nameWithOwner") or ""
        if "/" in name_with_owner:
            owner, name = name_with_owner.split("/", 1)
            return owner, name
    raise ToolError("GitHub search result did not include a repository.")


def get_pr(runner: Runner, config: Config, owner: str, repo: str, number: int) -> dict[str, Any]:
    payload = _json_command(
        runner,
        [
            config.gh_bin,
            "pr",
            "view",
            str(number),
            "--repo",
            f"{owner}/{repo}",
            "--json",
            "number,title,url,state,isDraft,headRefName,headRefOid,baseRefName,baseRefOid,body",
        ],
    )
    if not isinstance(payload, dict):
        raise ToolError("gh pr view did not return an object.")
    return {
        "owner": owner,
        "repo": repo,
        "number": int(payload.get("number") or number),
        "title": str(payload.get("title") or ""),
        "url": str(payload.get("url") or ""),
        "state": str(payload.get("state") or ""),
        "draft": bool(payload.get("isDraft")),
        "head_branch": str(payload.get("headRefName") or ""),
        "head_sha": str(payload.get("headRefOid") or ""),
        "base_branch": str(payload.get("baseRefName") or ""),
        "base_sha": str(payload.get("baseRefOid") or ""),
        "body": str(payload.get("body") or ""),
    }


def get_head_sha(runner: Runner, config: Config, owner: str, repo: str, number: int) -> str:
    return get_pr(runner, config, owner, repo, number)["head_sha"]


def get_checks(
    runner: Runner,
    config: Config,
    owner: str,
    repo: str,
    number: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fields = "name,bucket,state,link,workflow,description"
    required = _check_command(runner, config, owner, repo, number, fields, required=True)
    everything = _check_command(runner, config, owner, repo, number, fields, required=False)
    return required, everything


def _check_command(
    runner: Runner,
    config: Config,
    owner: str,
    repo: str,
    number: int,
    fields: str,
    *,
    required: bool,
) -> list[dict[str, Any]]:
    argv = [
        config.gh_bin,
        "pr",
        "checks",
        str(number),
        "--repo",
        f"{owner}/{repo}",
        "--json",
        fields,
    ]
    if required:
        argv.append("--required")
    result = runner.run(argv)
    # gh uses 0 pass, 1 fail, 8 pending. Empty output means no checks reported.
    if result.returncode not in (0, 1, 8):
        raise _result_error(result)
    if not result.stdout.strip():
        return []
    try:
        payload = parse_json_output(result.stdout)
    except json.JSONDecodeError as exc:
        raise ToolError(f"Could not parse gh pr checks JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise ToolError("gh pr checks JSON was not a list.")
    return [item for item in payload if isinstance(item, dict)]


def get_review_threads(
    runner: Runner,
    config: Config,
    owner: str,
    repo: str,
    number: int,
) -> list[dict[str, Any]]:
    threads: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(10):
        argv = [
            config.gh_bin,
            "api",
            "graphql",
            "-f",
            f"query={THREADS_QUERY}",
            "-F",
            f"owner={owner}",
            "-F",
            f"name={repo}",
            "-F",
            f"number={number}",
        ]
        if cursor:
            argv.extend(["-F", f"cursor={cursor}"])
        payload = _json_command(runner, argv)
        if not isinstance(payload, dict):
            raise ToolError("GitHub GraphQL response was not an object.")
        if payload.get("errors"):
            message = json.dumps(payload["errors"])
            raise ToolError(f"GitHub GraphQL error: {message}", unavailable=True)
        connection = (
            payload.get("data", {})
            .get("repository", {})
            .get("pullRequest", {})
            .get("reviewThreads", {})
        )
        nodes = connection.get("nodes") or []
        threads.extend(node for node in nodes if isinstance(node, dict))
        page = connection.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        cursor = page.get("endCursor")
    return threads


def get_code_scanning_alerts(
    runner: Runner,
    config: Config,
    owner: str,
    repo: str,
    ref: str,
) -> ServiceResult:
    collected: list[dict[str, Any]] = []
    for state in ("open", "dismissed", "fixed"):
        argv = [
            config.gh_bin,
            "api",
            "--paginate",
            f"repos/{owner}/{repo}/code-scanning/alerts",
            "-f",
            f"state={state}",
            "-f",
            f"ref={ref}",
        ]
        result = runner.run(argv)
        if result.returncode != 0:
            blob = f"{result.stderr}\n{result.stdout}".lower()
            if any(token in blob for token in ("http 403", "http 404", "http 503", "advanced security", "unavailable")):
                return ServiceResult(
                    unavailable=True,
                    message=(result.stderr or result.stdout or "Code scanning is unavailable.").strip(),
                )
            raise _result_error(result)
        if not result.stdout.strip():
            continue
        try:
            payload = parse_json_output(result.stdout)
        except json.JSONDecodeError as exc:
            raise ToolError(f"Could not parse code scanning alerts: {exc}") from exc
        if isinstance(payload, dict) and payload.get("message"):
            return ServiceResult(unavailable=True, message=str(payload["message"]))
        if isinstance(payload, list):
            collected.extend(item for item in payload if isinstance(item, dict))
    return ServiceResult(items=collected)


def list_reviews(runner: Runner, config: Config, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
    payload = _json_command(
        runner,
        [config.gh_bin, "api", "--paginate", f"repos/{owner}/{repo}/pulls/{number}/reviews"],
        allow=(0,),
    )
    if payload is None:
        return []
    if not isinstance(payload, list):
        raise ToolError("GitHub review list was not a JSON array.")
    return payload


def create_review(
    runner: Runner,
    config: Config,
    owner: str,
    repo: str,
    number: int,
    payload_path: Path,
) -> dict[str, Any]:
    payload = _json_command(
        runner,
        [
            config.gh_bin,
            "api",
            "--method",
            "POST",
            f"repos/{owner}/{repo}/pulls/{number}/reviews",
            "--input",
            str(payload_path),
        ],
    )
    if not isinstance(payload, dict):
        raise ToolError("GitHub did not return a review object.")
    return payload


def list_review_comments(
    runner: Runner,
    config: Config,
    owner: str,
    repo: str,
    number: int,
    review_id: int,
) -> list[dict[str, Any]]:
    payload = _json_command(
        runner,
        [
            config.gh_bin,
            "api",
            "--paginate",
            f"repos/{owner}/{repo}/pulls/{number}/reviews/{review_id}/comments",
        ],
    )
    return payload if isinstance(payload, list) else []


def post_pr_comment(
    runner: Runner,
    config: Config,
    owner: str,
    repo: str,
    number: int,
    body_file: Path,
    attachments: list[str],
) -> dict[str, Any]:
    argv = [
        config.gh_bin,
        "pr",
        "comment",
        str(number),
        "--repo",
        f"{owner}/{repo}",
        "--body-file",
        str(body_file),
    ]
    for attachment in attachments:
        argv.extend(["--attach", attachment])
    result = runner.run(argv)
    if result.returncode != 0:
        raise _result_error(result)
    stdout = result.stdout.strip()
    receipt: dict[str, Any] = {"stdout": stdout}
    if stdout.startswith("{") or stdout.startswith("["):
        try:
            parsed = parse_json_output(stdout)
            if isinstance(parsed, dict):
                receipt = parsed
        except json.JSONDecodeError:
            pass
    if "url" not in receipt and stdout.startswith("http"):
        receipt["url"] = stdout.splitlines()[-1].strip()
    return receipt


def docker_pull(runner: Runner, config: Config, image: str) -> str:
    if config.virt_fetch_command:
        result = runner.run(_command_with_image(config.virt_fetch_command, image))
        if result.returncode != 0:
            raise _result_error(result)
        for line in reversed((result.stdout or "").splitlines()):
            if line.startswith("digest="):
                return line.split("=", 1)[1].strip()
        text = (result.stdout or "").strip()
        if text:
            return text.splitlines()[-1].strip()
        raise ToolError("Image fetch command did not report a digest.")
    pull = runner.run([config.docker_bin, "pull", image])
    if pull.returncode != 0:
        raise _result_error(pull)
    inspect = runner.run(
        [config.docker_bin, "image", "inspect", image, "--format", "{{json .RepoDigests}}"]
    )
    if inspect.returncode != 0:
        raise _result_error(inspect)
    try:
        digests = parse_json_output(inspect.stdout)
    except json.JSONDecodeError as exc:
        raise ToolError(f"Could not parse docker image digests: {exc}") from exc
    if isinstance(digests, list) and digests:
        ref = str(digests[0])
        return ref.split("@", 1)[1] if "@" in ref else ref
    raise ToolError(f"Docker did not report a digest for {image}.")


def docker_compose_up(runner: Runner, config: Config, project: str, compose_file: Path) -> None:
    if config.virt_launch_command:
        argv = shlex_command(
            config.virt_launch_command,
            {"project": project, "compose": str(compose_file)},
        )
        result = runner.run(argv)
        if result.returncode != 0:
            raise _result_error(result)
        return
    result = runner.run(
        [
            config.docker_bin,
            "compose",
            "-p",
            project,
            "-f",
            str(compose_file),
            "up",
            "-d",
        ]
    )
    if result.returncode != 0:
        raise _result_error(result)


def shlex_command(template: str, mapping: dict[str, str]) -> list[str]:
    import shlex

    rendered: list[str] = []
    for part in shlex.split(template):
        updated = part
        for key, value in mapping.items():
            updated = updated.replace("{" + key + "}", value)
        rendered.append(updated)
    return rendered


def _command_with_image(template: str, image: str) -> list[str]:
    argv = shlex_command(template, {"image": image})
    if "{image}" not in template:
        argv.append(image)
    return argv


def run_external(runner: Runner, command: str, mapping: dict[str, str]) -> CommandResult:
    argv = shlex_command(command, mapping)
    unused = not any("{" + key + "}" in command for key in mapping)
    if unused:
        argv.extend(mapping[key] for key in ("context", "output") if key in mapping)
    return runner.run(argv)
