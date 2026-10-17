"""Local configuration. External tools stay external."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    reviews_dir: Path
    cache_dir: Path
    peer_review_status: str = "Peer Review"
    in_progress_status: str = "In Progress"
    approved_status: str = "Done"
    required_checks: list[str] = field(default_factory=list)
    analyzer_checks: list[str] = field(default_factory=lambda: ["Bugbot", "CodeQL"])
    require_analyzers: bool = True
    bugbot_authors: list[str] = field(
        default_factory=lambda: ["cursor[bot]", "bugbot", "cursor-bugbot[bot]"]
    )
    codeql_authors: list[str] = field(
        default_factory=lambda: ["github-advanced-security[bot]", "github-code-scanning[bot]"]
    )
    reviewer_command: str | None = None
    bug_writer_command: str | None = None
    checkout_command: str | None = None
    virt_prepare_command: str | None = None
    virt_fetch_command: str | None = None
    virt_launch_command: str | None = None
    image: str | None = None
    ports: list[str] = field(default_factory=lambda: ["8080:8080"])
    standards: list[str] = field(default_factory=list)
    github_repo: str | None = None
    acli_bin: str = "acli"
    gh_bin: str = "gh"
    docker_bin: str = "docker"
    git_bin: str = "git"

    def status_matches(self, actual: str, expected: str) -> bool:
        return actual.casefold() == expected.casefold()


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]  # type: ignore[arg-type]


def config_from_mapping(data: dict, *, cwd: Path) -> Config:
    def path_value(key: str, default: Path) -> Path:
        raw = data.get(key)
        if not raw:
            return default
        path = Path(str(raw))
        return path if path.is_absolute() else cwd / path

    reviews = path_value("reviews_dir", cwd / "reviews")
    env_reviews = os.environ.get("REVIEW_TICKET_REVIEWS_DIR")
    if env_reviews:
        reviews = Path(env_reviews)
        if not reviews.is_absolute():
            reviews = cwd / reviews
    cache = path_value("cache_dir", Path.home() / ".cache" / "review-ticket")
    config = Config(reviews_dir=reviews, cache_dir=cache)
    if "peer_review_status" in data:
        config.peer_review_status = str(data["peer_review_status"])
    if "in_progress_status" in data:
        config.in_progress_status = str(data["in_progress_status"])
    if "approved_status" in data:
        config.approved_status = str(data["approved_status"])
    if "required_checks" in data:
        config.required_checks = _as_list(data["required_checks"])
    if "analyzer_checks" in data:
        config.analyzer_checks = _as_list(data["analyzer_checks"])
    if "require_analyzers" in data:
        config.require_analyzers = bool(data["require_analyzers"])
    if "bugbot_authors" in data:
        config.bugbot_authors = _as_list(data["bugbot_authors"])
    if "codeql_authors" in data:
        config.codeql_authors = _as_list(data["codeql_authors"])
    if "ports" in data:
        config.ports = _as_list(data["ports"])
    if "standards" in data:
        config.standards = _as_list(data["standards"])
    for key in (
        "reviewer_command",
        "bug_writer_command",
        "checkout_command",
        "virt_prepare_command",
        "virt_fetch_command",
        "virt_launch_command",
        "image",
        "github_repo",
        "acli_bin",
        "gh_bin",
        "docker_bin",
        "git_bin",
    ):
        env_key = {
            "reviewer_command": "REVIEWER_COMMAND",
            "bug_writer_command": "BUG_WRITER_COMMAND",
        }.get(key)
        if env_key and os.environ.get(env_key):
            setattr(config, key, os.environ[env_key])
        elif key in data and data[key] not in (None, ""):
            setattr(config, key, str(data[key]))
    return config


def load_config(cwd: Path | None = None) -> Config:
    root = cwd or Path.cwd()
    path = root / ".review-ticket.json"
    data: dict = {}
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
    return config_from_mapping(data, cwd=root)
