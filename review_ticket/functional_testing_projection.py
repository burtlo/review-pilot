"""Read-only functional testing screen model (spec §12)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from review_ticket.storage import Store, read_json


@dataclass(frozen=True)
class FunctionalTestingProjection:
    issue: str
    ref: str
    owner: str
    repo: str
    number: int
    sha: str
    image: str | None
    digest: str | None
    environment_state: str
    test_plan_label: str
    test_plan_path: str | None
    read_only: bool
    read_only_reason: str | None


def project_functional_testing(
    store: Store,
    issue: str,
    *,
    owner: str,
    repo: str,
    number: int,
    sha: str,
    ref: str | None = None,
    historical: bool = False,
    head_stale: bool = False,
) -> FunctionalTestingProjection:
    ref = ref or f"{owner}/{repo}#{number}"
    commit_dir = store.commit_dir(issue, owner, repo, number, sha)
    testing_dir = commit_dir / "testing"
    environment = read_json(testing_dir / "environment.json") or {}
    plan_path = testing_dir / "test-plan.md"
    digest = str(environment.get("digest") or "").strip() or None
    image = str(environment.get("image") or "").strip() or None
    if environment.get("launched_at"):
        env_state = "Running"
    elif digest and environment.get("sha") == sha:
        env_state = "Image ready"
    elif read_json(testing_dir / "profile" / "profile.json"):
        env_state = "Profile only"
    else:
        env_state = "Not prepared"
    plan_label = "Available" if plan_path.is_file() else "Missing"
    read_only = historical or head_stale
    reason = None
    if historical:
        reason = "Historical SHA — evidence is read-only."
    elif head_stale:
        reason = "HEAD moved — refresh before new work."
    return FunctionalTestingProjection(
        issue=issue,
        ref=ref,
        owner=owner,
        repo=repo,
        number=number,
        sha=sha,
        image=image,
        digest=digest,
        environment_state=env_state,
        test_plan_label=plan_label,
        test_plan_path=_display_path(store, plan_path) if plan_path.is_file() else None,
        read_only=read_only,
        read_only_reason=reason,
    )


def format_functional_environment_block(projection: FunctionalTestingProjection) -> str:
    lines = [
        "**Environment**",
        f"Image: `{projection.image or '—'}`",
        f"Digest: `{projection.digest or '—'}`",
        f"State: {projection.environment_state}",
        f"Test plan: {projection.test_plan_label}",
    ]
    if projection.test_plan_path:
        lines.append(f"Plan file: `{projection.test_plan_path}`")
    return "\n".join(lines)


def _display_path(store: Store, path: Path) -> str:
    reviews = store.root.resolve()
    try:
        return str(path.resolve().relative_to(reviews))
    except ValueError:
        return str(path)
