"""Isolated checkout of the reviewed SHA. Never switches the caller's worktree."""

from __future__ import annotations

import logging
import shlex
from pathlib import Path

_LOG = logging.getLogger("review_ticket.checkout")

from review_ticket.config import Config
from review_ticket.models import ToolError
from review_ticket.runner import Runner


def _run(runner: Runner, argv: list[str], *, cwd: Path | None = None) -> str:
    result = runner.run(argv, cwd=str(cwd) if cwd else None)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ToolError(
            f"Command failed ({result.returncode}): {' '.join(argv)}\n{detail}",
            returncode=result.returncode,
        )
    return result.stdout.strip()


def rev_parse(runner: Runner, git: str, repo: Path) -> str:
    return _run(runner, [git, "rev-parse", "HEAD"], cwd=repo)


def add_worktree(runner: Runner, git: str, source: Path, dest: Path, sha: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(runner, [git, "worktree", "add", "--detach", str(dest), sha], cwd=source)


def ensure_checkout(
    runner: Runner,
    config: Config,
    *,
    owner: str,
    repo: str,
    sha: str,
    dest: Path,
) -> Path:
    """Check out ``sha`` in ``dest``. Reuse the directory when it already matches."""

    git = config.git_bin
    if dest.exists():
        head = rev_parse(runner, git, dest)
        if head != sha:
            raise ToolError(
                f"Checkout at {dest} is {head}, not the review snapshot {sha}. "
                "Refusing to overwrite it."
            )
        return dest
    mapping = {
        "owner": owner,
        "repo": repo,
        "sha": sha,
        "dest": str(dest),
        "repository": f"{owner}/{repo}",
    }
    if config.checkout_command:
        _LOG.debug("checkout_command for %s -> %s", mapping["repository"], mapping["dest"])
        argv = _format_command(config.checkout_command, mapping)
        _run(runner, argv)
    else:
        _LOG.debug("default gh clone + worktree for %s @ %s", mapping["repository"], sha)
        cache = config.cache_dir / "repos" / owner / repo
        if not (cache / ".git").exists():
            cache.parent.mkdir(parents=True, exist_ok=True)
            _run(runner, [config.gh_bin, "repo", "clone", f"{owner}/{repo}", str(cache)])
        _run(runner, [git, "fetch", "origin", sha], cwd=cache)
        add_worktree(runner, git, cache, dest, sha)
    head = rev_parse(runner, git, dest)
    if head != sha:
        raise ToolError(f"Checkout verification failed. Expected {sha}, found {head}.")
    return dest


def git_diff(runner: Runner, git: str, checkout: Path, base_sha: str, sha: str) -> str:
    result = runner.run(
        [git, "diff", "--unified=3", f"{base_sha}...{sha}"],
        cwd=str(checkout),
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise ToolError(f"git diff failed: {detail}", returncode=result.returncode)
    return result.stdout


def _format_command(template: str, mapping: dict[str, str]) -> list[str]:
    parts = shlex.split(template)
    rendered: list[str] = []
    used = False
    for part in parts:
        updated = part
        for key, value in mapping.items():
            token = "{" + key + "}"
            if token in updated:
                used = True
                updated = updated.replace(token, value)
        rendered.append(updated)
    if not used:
        rendered.extend([mapping["repository"], mapping["sha"], mapping["dest"]])
    return rendered
