"""Read-only test environment / virtualization model (spec §11)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from review_ticket.policy import manual_review_is_complete
from review_ticket.storage import Store, read_json

ShaEvidence = Literal["matched", "mismatch", "unknown"]


def _display_path(store: Store, path: Path) -> str:
    reviews = store.root.resolve()
    try:
        return str(path.resolve().relative_to(reviews))
    except ValueError:
        return str(path)
ProfileStatus = Literal["missing", "available"]
LaunchStatus = Literal["not_launched", "launched", "uncertain"]


@dataclass(frozen=True)
class TestEnvironmentProjection:
    issue: str
    ref: str
    owner: str
    repo: str
    number: int
    sha: str
    code_review_complete: bool
    profile_status: ProfileStatus
    profile_image: str | None
    digest: str | None
    digest_provenance: ShaEvidence
    sha_match_label: str
    launch_status: LaunchStatus
    launch_label: str
    environment_outcome: str
    blocked_message: str | None
    config_path: str | None
    config_path_display: str
    cli_prepare: str
    cli_fetch: str
    cli_launch: str
    prepare_enabled: bool
    fetch_enabled: bool
    launch_enabled: bool
    read_only: bool
    read_only_reason: str | None


def project_test_environment(
    store: Store,
    issue: str,
    *,
    owner: str,
    repo: str,
    number: int,
    sha: str,
    ref: str | None = None,
) -> TestEnvironmentProjection:
    ref = ref or f"{owner}/{repo}#{number}"
    commit_dir = store.commit_dir(issue, owner, repo, number, sha)
    testing_dir = commit_dir / "testing"
    profile_path = testing_dir / "profile" / "profile.json"
    compose_path = testing_dir / "profile" / "docker-compose.yml"
    environment_path = testing_dir / "environment.json"
    profile = read_json(profile_path)
    environment = read_json(environment_path)
    manual = read_json(commit_dir / "review" / "manual-review.json")

    profile_status: ProfileStatus = "available" if profile else "missing"
    profile_image = str(profile.get("image") or "").strip() or None if profile else None

    digest: str | None = None
    digest_provenance: ShaEvidence = "unknown"
    if environment:
        env_sha = str(environment.get("sha") or "")
        if env_sha and env_sha == sha and environment.get("digest"):
            digest = str(environment.get("digest"))
            digest_provenance = "matched"
        elif env_sha and env_sha != sha:
            digest_provenance = "mismatch"
        elif environment.get("digest"):
            digest_provenance = "unknown"

    if digest_provenance == "matched":
        sha_match_label = "SHA-matched"
    elif digest_provenance == "mismatch":
        sha_match_label = "Digest recorded for another SHA — not evidence for this commit"
    else:
        sha_match_label = "Unknown until image is fetched for this SHA"

    launch_status: LaunchStatus = "not_launched"
    launch_label = "Not launched"
    if digest_provenance == "matched" and environment:
        launched_at = environment.get("launched_at")
        launched_digest = environment.get("launched_digest")
        if launched_at and launched_digest == environment.get("digest"):
            launch_status = "launched"
            launch_label = f"Launched ({launched_at})"
        elif launched_at and launched_digest and launched_digest != environment.get("digest"):
            launch_status = "uncertain"
            launch_label = "Launch may be stale — digest changed after launch"

    config_rel = _display_path(store, compose_path) if compose_path.is_file() else None
    config_display = config_rel or "—"

    prefix = f"review-ticket {issue}"
    cli_prepare = f"{prefix} test prepare"
    cli_fetch = f"{prefix} test fetch"
    cli_launch = f"{prefix} test launch"

    read_only = False
    read_only_reason: str | None = None

    if profile_status == "missing" or digest_provenance != "matched" or not digest:
        environment_outcome = "BLOCKED"
    else:
        environment_outcome = "READY"

    return TestEnvironmentProjection(
        issue=issue,
        ref=ref,
        owner=owner,
        repo=repo,
        number=number,
        sha=sha,
        code_review_complete=manual_review_is_complete(manual, sha),
        profile_status=profile_status,
        profile_image=profile_image,
        digest=digest,
        digest_provenance=digest_provenance,
        sha_match_label=sha_match_label,
        launch_status=launch_status,
        launch_label=launch_label,
        environment_outcome=environment_outcome,
        blocked_message=None,
        config_path=str(compose_path) if compose_path.is_file() else None,
        config_path_display=config_display,
        cli_prepare=cli_prepare,
        cli_fetch=cli_fetch,
        cli_launch=cli_launch,
        prepare_enabled=not read_only,
        fetch_enabled=not read_only and profile_status == "available",
        launch_enabled=not read_only and digest_provenance == "matched" and bool(digest),
        read_only=read_only,
        read_only_reason=read_only_reason,
    )


def apply_read_only(
    projection: TestEnvironmentProjection,
    *,
    historical: bool,
    head_stale: bool,
) -> TestEnvironmentProjection:
    if not historical and not head_stale:
        return projection
    reason = (
        "Historical SHA — environment actions are read-only."
        if historical
        else "HEAD moved — refresh before preparing or launching for the new SHA."
    )
    return replace(
        projection,
        read_only=True,
        read_only_reason=reason,
        prepare_enabled=False,
        fetch_enabled=False,
        launch_enabled=False,
    )


def with_blocked_message(
    projection: TestEnvironmentProjection,
    message: str,
) -> TestEnvironmentProjection:
    return replace(
        projection,
        environment_outcome="BLOCKED",
        blocked_message=message,
    )


def format_environment_detail(projection: TestEnvironmentProjection) -> str:
    lines = [
        f"Code review: {'Complete' if projection.code_review_complete else 'Not complete'}",
        "",
        f"Test profile: {'Available' if projection.profile_status == 'available' else 'Missing'}",
    ]
    if projection.profile_image:
        lines.append(f"Docker image: {projection.profile_image}")
    else:
        lines.append("Docker image: —")
    if projection.digest:
        lines.append(f"Image digest: {projection.digest}")
    else:
        lines.append("Image digest: —")
    lines.append(f"SHA match: {projection.sha_match_label}")
    lines.append(f"Environment: {projection.launch_label}")
    lines.append(f"Outcome: {projection.environment_outcome}")
    if projection.blocked_message:
        lines.append(f"Blocked: {projection.blocked_message}")
    lines.append("")
    lines.append(f"Config: {projection.config_path_display}")
    lines.append("")
    lines.append("Or run externally:")
    lines.append(f"  {projection.cli_prepare}")
    lines.append(f"  {projection.cli_fetch}")
    lines.append(f"  {projection.cli_launch}")
    if projection.read_only_reason:
        lines.append("")
        lines.append(projection.read_only_reason)
    return "\n".join(lines)
