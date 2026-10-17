"""Local configuration. External tools stay external."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_FILENAMES = (".review-ticket.yaml", ".review-ticket.yml", ".review-ticket.json")


@dataclass
class StatusSettings:
    """Jira workflow columns used by review-ticket."""

    ready_for_peer_review: list[str] = field(default_factory=lambda: ["Ready for Peer Review"])
    in_peer_review: list[str] = field(default_factory=lambda: ["Peer Review"])
    in_progress: str = "In Progress"
    approved: str = "Done"

    def status_matches(self, actual: str, expected: str) -> bool:
        return actual.casefold() == expected.casefold()

    def accepts_review_workflow(self, actual: str) -> bool:
        return any(
            self.status_matches(actual, name)
            for name in (*self.ready_for_peer_review, *self.in_peer_review)
        )

    def review_workflow_label(self) -> str:
        parts = [
            *self.ready_for_peer_review,
            *self.in_peer_review,
        ]
        if len(parts) == 1:
            return parts[0]
        return ", ".join(parts)


@dataclass
class Config:
    reviews_dir: Path
    cache_dir: Path
    status: StatusSettings = field(default_factory=StatusSettings)
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
    github_org: str | None = None
    github_user: str | None = None
    acli_bin: str = "acli"
    gh_bin: str = "gh"
    docker_bin: str = "docker"
    git_bin: str = "git"

    @property
    def in_progress_status(self) -> str:
        return self.status.in_progress

    @property
    def approved_status(self) -> str:
        return self.status.approved

    def status_matches(self, actual: str, expected: str) -> bool:
        return self.status.status_matches(actual, expected)

    def accepts_peer_review_status(self, actual: str) -> bool:
        return self.status.accepts_review_workflow(actual)

    def peer_review_status_label(self) -> str:
        return self.status.review_workflow_label()


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]  # type: ignore[arg-type]


def _apply_status_settings(config: Config, data: dict) -> None:
    status_data = data.get("status")
    if isinstance(status_data, dict):
        if "ready_for_peer_review" in status_data:
            config.status.ready_for_peer_review = _as_list(status_data["ready_for_peer_review"])
        if "in_peer_review" in status_data:
            config.status.in_peer_review = _as_list(status_data["in_peer_review"])
        if status_data.get("in_progress"):
            config.status.in_progress = str(status_data["in_progress"])
        if status_data.get("approved"):
            config.status.approved = str(status_data["approved"])
    if "peer_review_status" in data:
        subsection = status_data if isinstance(status_data, dict) else {}
        if "ready_for_peer_review" not in subsection and "in_peer_review" not in subsection:
            config.status.ready_for_peer_review = _as_list(data["peer_review_status"])
    if "in_progress_status" in data:
        config.status.in_progress = str(data["in_progress_status"])
    if "approved_status" in data:
        config.status.approved = str(data["approved_status"])


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
    _apply_status_settings(config, data)
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
        "github_org",
        "github_user",
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


def find_config_path(root: Path) -> Path | None:
    for name in CONFIG_FILENAMES:
        path = root / name
        if path.exists():
            return path
    return None


def load_config_mapping(root: Path) -> dict:
    path = find_config_path(root)
    if path is None:
        return {}
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        loaded = json.loads(text)
    else:
        try:
            loaded = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"Could not parse {path.name}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path.name} must contain a mapping at the top level.")
    return loaded


def load_config(cwd: Path | None = None) -> Config:
    root = cwd or Path.cwd()
    data = load_config_mapping(root)
    return config_from_mapping(data, cwd=root)
