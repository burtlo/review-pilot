"""File storage grouped by Jira issue, pull request, and commit."""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterator

from review_ticket.util import iso_now, pr_slug, require_issue_key


@contextlib.contextmanager
def _exclusive_file_lock(handle) -> Iterator[None]:
    if sys.platform == "win32":
        import msvcrt

        fileno = handle.fileno()
        handle.seek(0)
        msvcrt.locking(fileno, msvcrt.LK_LOCK, 1)
        handle.seek(0, os.SEEK_END)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(fileno, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def write_json(path: Path, payload: Any) -> None:
    write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def read_json(path: Path) -> Any | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(payload, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        with _exclusive_file_lock(handle):
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


class Store:
    def __init__(self, reviews_dir: Path) -> None:
        self.root = reviews_dir

    def issue_dir(self, issue: str) -> Path:
        return self.root / require_issue_key(issue)

    def issue_actions(self, issue: str) -> Path:
        return self.issue_dir(issue) / "actions.jsonl"

    def pr_dir(self, issue: str, owner: str, repo: str, number: int) -> Path:
        return self.issue_dir(issue) / "prs" / pr_slug(owner, repo, number)

    def commit_dir(self, issue: str, owner: str, repo: str, number: int, sha: str) -> Path:
        if not sha or "/" in sha or sha.startswith("."):
            raise ValueError(f"Refusing commit directory for SHA {sha!r}.")
        return self.pr_dir(issue, owner, repo, number) / "commits" / sha

    def ensure_session(self, issue: str) -> dict[str, Any]:
        path = self.issue_dir(issue) / "session.json"
        existing = read_json(path)
        if existing:
            existing.setdefault("decisions", {})
            existing.setdefault("pr_candidates", [])
            existing.setdefault("active_prs", [])
            existing.setdefault("pr_shas", {})
            if existing.get("pr_scope") is None:
                existing["pr_scope"] = "all"
            existing.setdefault("cached_step_ids", [])
            if existing.get("active_pr") and not existing.get("active_prs"):
                existing["active_prs"] = [existing["active_pr"]]
            return existing
        session = {
            "issue": require_issue_key(issue),
            "active_pr": None,
            "active_sha": None,
            "active_prs": [],
            "pr_shas": {},
            "pr_scope": "all",
            "cached_step_ids": [],
            "current_step": "jira-issue",
            "outcome": None,
            "last_completed_step": None,
            "last_updated": iso_now(),
            "recommendation": None,
            "decisions": {},
            "pr_candidates": [],
        }
        self.save_session(session)
        return session

    def save_session(self, session: dict[str, Any]) -> None:
        session["last_updated"] = iso_now()
        write_json(self.issue_dir(session["issue"]) / "session.json", session)

    def record_action(self, issue: str, entry: dict[str, Any], *, sha_dir: Path | None = None) -> None:
        append_jsonl(self.issue_actions(issue), entry)
        if sha_dir is not None:
            append_jsonl(sha_dir / "actions.jsonl", entry)

    def successful_action(self, issue: str, key: str) -> dict[str, Any] | None:
        for entry in read_jsonl(self.issue_actions(issue)):
            if entry.get("key") == key and entry.get("status") == "success":
                return entry
        return None
