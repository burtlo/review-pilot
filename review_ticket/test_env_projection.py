"""Read-only test environment status for the TUI (P10)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from review_ticket.storage import read_json


@dataclass(frozen=True)
class TestEnvironmentProjection:
    sha: str
    profile_present: bool
    profile_path: str | None
    compose_path: str | None
    image: str | None
    digest: str | None
    digest_matches_sha: bool
    digest_uncertain: bool
    launched: bool
    launched_at: str | None
    blocked_reason: str | None
    cli_prepare: str
    cli_fetch: str
    cli_launch: str


def project_test_environment(
    commit_dir: Path,
    *,
    sha: str,
    issue: str,
    pr_ref: str,
) -> TestEnvironmentProjection:
    testing = commit_dir / "testing"
    profile_dir = testing / "profile"
    profile_path = profile_dir / "profile.json"
    compose_path = profile_dir / "docker-compose.yml"
    profile = read_json(profile_path) or {}
    environment = read_json(testing / "environment.json") or {}
    digest = environment.get("digest")
    env_sha = environment.get("sha")
    digest_matches = bool(digest and env_sha == sha)
    uncertain = bool(digest and env_sha != sha)
    blocked = None
    if uncertain:
        blocked = "Fetched digest belongs to a different SHA and cannot be used as evidence."
    elif not profile and not digest:
        blocked = "Prepare a virtualization profile before fetch or launch."
    launched = bool(environment.get("launched_at"))
    return TestEnvironmentProjection(
        sha=sha,
        profile_present=profile_path.exists(),
        profile_path=str(profile_path) if profile_path.exists() else None,
        compose_path=str(compose_path) if compose_path.exists() else None,
        image=profile.get("image") or environment.get("image"),
        digest=digest,
        digest_matches_sha=digest_matches,
        digest_uncertain=uncertain,
        launched=launched,
        launched_at=environment.get("launched_at"),
        blocked_reason=blocked,
        cli_prepare=f"review-ticket {issue} test prepare --pr {pr_ref} --sha {sha}",
        cli_fetch=f"review-ticket {issue} test fetch --pr {pr_ref} --sha {sha}",
        cli_launch=f"review-ticket {issue} test launch --pr {pr_ref} --sha {sha}",
    )


def format_test_environment_markdown(projection: TestEnvironmentProjection) -> str:
    lines = [
        f"# Test environment `{projection.sha[:12]}`",
        "",
        f"Profile: **{'present' if projection.profile_present else 'missing'}**",
    ]
    if projection.profile_path:
        lines.append(f"Config: `{projection.profile_path}`")
    if projection.compose_path:
        lines.append(f"Compose: `{projection.compose_path}`")
    lines.extend(
        [
            "",
            f"Image: `{projection.image or '—'}`",
            f"Digest: `{projection.digest or '—'}`",
            f"Digest matches SHA: **{str(projection.digest_matches_sha).lower()}**",
            f"Launched: **{str(projection.launched).lower()}**",
        ]
    )
    if projection.launched_at:
        lines.append(f"Launched at: {projection.launched_at}")
    if projection.digest_uncertain:
        lines.append("")
        lines.append("**BLOCKED:** Digest was fetched for another SHA.")
    elif projection.blocked_reason:
        lines.append("")
        lines.append(f"**BLOCKED:** {projection.blocked_reason}")
    lines.extend(
        [
            "",
            "## CLI (outside the TUI)",
            "",
            f"- `{projection.cli_prepare}`",
            f"- `{projection.cli_fetch}`",
            f"- `{projection.cli_launch}`",
        ]
    )
    return "\n".join(lines) + "\n"
