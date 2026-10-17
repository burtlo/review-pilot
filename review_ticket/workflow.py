"""Manual peer-review steps. External mutations stay behind an authorization gate."""

from __future__ import annotations

import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from review_ticket.adapters import (
    create_review,
    docker_compose_up,
    docker_pull,
    fetch_jira,
    get_checks,
    get_code_scanning_alerts,
    get_head_sha,
    get_pr,
    get_review_threads,
    list_review_comments,
    list_reviews,
    post_jira_comment,
    post_pr_comment,
    run_external,
    search_prs,
    transition_jira,
)
from review_ticket.authorize import authorize
from review_ticket.checkout import ensure_checkout, git_diff
from review_ticket.config import Config
from review_ticket.findings import (
    apply_human_decisions,
    build_review_payload,
    normalize_findings,
    reconcile,
)
from review_ticket.models import Outcome, StepResult, ToolError, WorkflowError
from review_ticket.policy import (
    Check,
    Readiness,
    bucket_of,
    classify_check_name,
    disposition_checklist,
    evaluate_analyzers,
    evaluate_readiness,
    suggest_event as policy_suggest_event,
    testing_outcome,
)
from review_ticket.reports import (
    analyzer_report,
    disposition_report,
    functional_comment,
    issue_report,
    readiness_report,
    return_comment,
    reviewer_prompt,
    reviewer_report,
    test_plan,
    test_results_markdown,
)
from review_ticket.runner import Runner
from review_ticket.storage import Store, read_json, write_json, write_text
from review_ticket.textutil import parse_unified_diff
from review_ticket.util import (
    find_pr_urls,
    fingerprint,
    iso_now,
    parse_json_output,
    parse_pr_ref,
    require_issue_key,
    sha256_text,
    short_sha,
)

GITHUB_STATE = {
    "APPROVE": "APPROVED",
    "REQUEST_CHANGES": "CHANGES_REQUESTED",
    "COMMENT": "COMMENTED",
}
PROFILE_KEYS = ("version", "issue", "repository", "pr", "branch", "sha", "image", "ports", "project_name")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm"}


@dataclass
class App:
    config: Config
    runner: Runner
    interactive: bool = False
    input_fn: Callable[[str], str] | None = None
    stdout: TextIO | None = None
    stderr: TextIO | None = None
    cwd: Path | None = None

    def __post_init__(self) -> None:
        self.store = Store(self.config.reviews_dir)
        self.stdout = self.stdout or sys.stdout
        self.stderr = self.stderr or sys.stderr
        self.cwd = self.cwd or Path.cwd()

    def write(self, text: str) -> None:
        assert self.stdout is not None
        self.stdout.write(text)

    def error(self, text: str) -> None:
        assert self.stderr is not None
        self.stderr.write(text if text.endswith("\n") else text + "\n")


def resume(app: App, issue: str) -> StepResult:
    issue = require_issue_key(issue)
    session = app.store.ensure_session(issue)
    steps = (
        step_jira,
        step_pull_request,
        step_checks,
        step_analyzers,
        step_automated_review,
        step_publication,
        step_virtualization,
        step_testing,
        step_disposition,
    )
    try:
        for step in steps:
            result = step(app, session)
            if result is not None:
                return finish(app, session, result)
    except ToolError as exc:
        return finish(app, session, _blocked(session.get("current_step") or "jira-issue", str(exc)))
    return finish(
        app,
        session,
        StepResult(step="disposition", outcome=Outcome.COMPLETE, summary="Review session is idle."),
    )


def show_status(app: App, issue: str) -> StepResult:
    issue = require_issue_key(issue)
    path = app.store.issue_dir(issue) / "session.json"
    if not path.exists():
        result = StepResult(
            step="jira-issue",
            outcome=Outcome.READY,
            summary="No review session exists yet.",
            next_command=f"review-ticket {issue}",
        )
        _render(app, {"issue": issue, "active_pr": None, "active_sha": None}, result)
        return result
    session = read_json(path)
    result = StepResult(
        step=session.get("current_step") or "jira-issue",
        outcome=Outcome(session["outcome"]) if session.get("outcome") else Outcome.READY,
        summary="Stored session. Run without a subcommand to refresh external checks.",
        recommendation=session.get("recommendation"),
        next_command=session.get("next_command"),
    )
    _render(app, session, result)
    return result


def decide_notes(app: App, issue: str, choice: str, notes: str, *, revise: bool) -> StepResult:
    issue = require_issue_key(issue)
    if choice not in {"accept", "reject"}:
        raise WorkflowError("Testing-note decision must be accept or reject.")
    session = app.store.ensure_session(issue)
    normalized = refresh_issue(app, session)
    value = {
        "choice": choice,
        "notes": notes,
        "notes_hash": sha256_text(normalized.get("testing_notes") or ""),
        "at": iso_now(),
    }
    put_decision(session, "testing_notes", value, revise=revise)
    _append_note(app, issue, notes)
    if choice == "reject":
        draft = _write_return_draft(
            app,
            issue,
            reason="The testing notes are missing or not adequate for peer review.",
            notes=notes,
            links=[],
        )
        session["return_draft"] = str(draft)
    app.store.save_session(session)
    return resume(app, issue)


def assess(
    app: App,
    issue: str,
    *,
    accept_missing_checks: bool = False,
    accept_missing_analyzers: bool = False,
) -> StepResult:
    result = resume(app, issue)
    if not accept_missing_checks and not accept_missing_analyzers:
        return result
    session = app.store.ensure_session(require_issue_key(issue))
    sha = session.get("active_sha")
    if not sha:
        return result
    if accept_missing_checks:
        put_decision(
            session,
            "missing_checks",
            {"choice": "accept", "at": iso_now()},
            sha=sha,
            revise=True,
        )
    if accept_missing_analyzers:
        put_decision(
            session,
            "missing_analyzers",
            {"choice": "accept", "at": iso_now()},
            sha=sha,
            revise=True,
        )
    app.store.save_session(session)
    return resume(app, issue)


def decide_analyzers(app: App, issue: str, choice: str, notes: str, *, revise: bool) -> StepResult:
    issue = require_issue_key(issue)
    if choice not in {"return", "accept_dispositions", "override"}:
        raise WorkflowError("Analyzer decision must be return, accept_dispositions, or override.")
    if choice == "override" and not notes.strip():
        raise WorkflowError("An override needs --notes explaining why unaddressed findings can proceed.")
    session = app.store.ensure_session(issue)
    identity = _require_identity(session)
    sha = session.get("active_sha")
    if not sha:
        raise WorkflowError("Analyzer decisions need a captured pull request SHA. Run assess first.")
    put_decision(
        session,
        "analyzers",
        {"choice": choice, "notes": notes, "at": iso_now()},
        sha=sha,
        revise=revise,
    )
    _append_note(app, issue, notes)
    if choice == "return":
        findings = _load_analyzer_findings(app, issue, identity, sha)
        links = [item["url"] for item in findings if item.get("url")]
        titles = [f"{item['id']} {item.get('path') or ''} — {item.get('body', '')[:180]}" for item in findings]
        draft = _write_return_draft(
            app,
            issue,
            reason="Bugbot or CodeQL findings still need a developer disposition.\n\n" + "\n".join(titles),
            notes=notes,
            links=links,
        )
        session["return_draft"] = str(draft)
    app.store.save_session(session)
    return resume(app, issue)


def select_pr(app: App, issue: str, ref: str) -> StepResult:
    issue = require_issue_key(issue)
    owner, repo, number = parse_pr_ref(ref)
    session = app.store.ensure_session(issue)
    session["active_pr"] = f"{owner}/{repo}#{number}"
    session["active_sha"] = None
    app.store.save_session(session)
    return resume(app, issue)


def run_review(app: App, issue: str, *, revise: bool) -> StepResult:
    issue = require_issue_key(issue)
    session = app.store.ensure_session(issue)
    for step in (step_jira, step_pull_request, step_checks, step_analyzers):
        result = step(app, session)
        if result is not None:
            return finish(app, session, result)
    return finish(app, session, _execute_reviewer(app, session, revise=revise, imported=None))


def import_review(app: App, issue: str, file: Path, *, revise: bool) -> StepResult:
    issue = require_issue_key(issue)
    session = app.store.ensure_session(issue)
    for step in (step_jira, step_pull_request, step_checks, step_analyzers):
        result = step(app, session)
        if result is not None:
            return finish(app, session, result)
    payload = json.loads(file.read_text(encoding="utf-8"))
    return finish(app, session, _execute_reviewer(app, session, revise=revise, imported=payload))


def apply_review(app: App, issue: str, human: dict[str, Any], *, revise: bool) -> StepResult:
    issue = require_issue_key(issue)
    session = _require_review_session(app, issue)
    identity = _require_identity(session)
    sha = session["active_sha"]
    review_dir = _review_dir(app, issue, identity, sha)
    document = read_json(review_dir / "findings.json")
    if not document:
        raise WorkflowError("No automated findings are stored. Run run-review or import-review first.")
    existing = read_json(review_dir / "human-review.json")
    if existing and not revise:
        raise WorkflowError("A human review is already recorded. Pass --revise to replace it.")
    if human.get("rejected_review"):
        human.setdefault("findings", {})
        human.setdefault("added", [])
    else:
        apply_human_decisions(document.get("findings") or [], human)
    write_json(review_dir / "human-review.json", human)
    if not human.get("rejected_review"):
        merged = apply_human_decisions(document.get("findings") or [], human)
        event = human.get("event") or policy_suggest_event(merged)
        summary = human.get("summary") or document.get("summary") or "Peer review."
        payload = build_review_payload(
            sha=sha,
            event=event,
            summary=summary,
            findings=merged,
            diff_index=_diff_index(app, issue, identity, sha),
        )
        write_json(review_dir / "proposed-review.json", payload)
    put_decision(session, "human_review", {"choice": "recorded", "at": iso_now()}, sha=sha, revise=revise)
    app.store.save_session(session)
    return resume(app, issue)


def publish_review(app: App, issue: str, *, yes: bool, event: str | None, skip: bool) -> StepResult:
    issue = require_issue_key(issue)
    session = _require_review_session(app, issue)
    identity = _require_identity(session)
    owner, repo, number = identity
    sha = session["active_sha"]
    review_dir = _review_dir(app, issue, identity, sha)
    document = read_json(review_dir / "findings.json")
    human = read_json(review_dir / "human-review.json")
    if not document or not human:
        raise WorkflowError("Publish needs automated findings and a recorded human review.")
    if human.get("rejected_review") and not skip:
        raise WorkflowError("The automated review was rejected. Nothing will be published.")
    publication_path = review_dir / "publication.json"
    existing = read_json(publication_path)
    merged = [] if human.get("rejected_review") else apply_human_decisions(document.get("findings") or [], human)
    chosen = event or human.get("event") or (policy_suggest_event(merged) if merged else "COMMENT")
    summary = human.get("summary") or document.get("summary") or "Peer review."
    payload = build_review_payload(
        sha=sha,
        event=chosen,
        summary=summary,
        findings=merged,
        diff_index=_diff_index(app, issue, identity, sha),
    )
    digest = fingerprint(payload)
    if existing and existing.get("status") == "success" and existing.get("fingerprint") == digest:
        return finish(app, session, _after_publication(app, issue, sha, existing, skipped=True))
    if skip:
        preview = f"Skip GitHub publication for {owner}/{repo}#{number} at {short_sha(sha)} with event {chosen}."
        authorize(preview=preview, yes=yes, interactive=app.interactive, prompt=app.input_fn, write=app.write)
        receipt = {
            "status": "skipped",
            "fingerprint": digest,
            "sha": sha,
            "event": chosen,
            "published_at": iso_now(),
        }
        write_json(publication_path, receipt)
        _journal(app, issue, _commit_dir(app, issue, identity, sha), "github.review", digest, "success", receipt, sha)
        return finish(app, session, _after_publication(app, issue, sha, receipt, skipped=False))

    live = get_head_sha(app.runner, app.config, owner, repo, number)
    if live != sha:
        return finish(
            app,
            session,
            StepResult(
                step="human-review",
                outcome=Outcome.BLOCKED,
                summary=(
                    f"Refusing to publish. Pull request HEAD is {short_sha(live)}, "
                    f"but this review snapshot is {short_sha(sha)}."
                ),
                next_command=f"review-ticket {issue}",
            ),
        )
    remote = _matching_remote_review(app, owner, repo, number, payload)
    if remote is not None:
        receipt = _receipt_from_remote(remote, digest, sha, chosen)
        write_json(publication_path, receipt)
        return finish(app, session, _after_publication(app, issue, sha, receipt, skipped=True))

    preview = _publication_preview(owner, repo, number, payload)
    authorize(preview=preview, yes=yes, interactive=app.interactive, prompt=app.input_fn, write=app.write)
    payload_path = review_dir / "publish-payload.json"
    write_json(payload_path, payload)
    try:
        created = create_review(app.runner, app.config, owner, repo, number, payload_path)
    except ToolError as exc:
        _journal(
            app,
            issue,
            _commit_dir(app, issue, identity, sha),
            "github.review",
            digest,
            "failure",
            {"error": str(exc)},
            sha,
        )
        return finish(app, session, _blocked("human-review", str(exc)))
    review_id = created.get("id")
    try:
        comments = (
            list_review_comments(app.runner, app.config, owner, repo, number, int(review_id))
            if review_id is not None
            else []
        )
    except ToolError:
        comments = []
    receipt = {
        "status": "success",
        "fingerprint": digest,
        "sha": sha,
        "event": chosen,
        "github_review_id": review_id,
        "html_url": created.get("html_url"),
        "comment_ids": [item.get("id") for item in comments],
        "comment_urls": [item.get("html_url") or item.get("url") for item in comments],
        "published_at": iso_now(),
    }
    write_json(publication_path, receipt)
    _journal(app, issue, _commit_dir(app, issue, identity, sha), "github.review", digest, "success", receipt, sha)
    return finish(app, session, _after_publication(app, issue, sha, receipt, skipped=False))


def prepare_profile(app: App, issue: str) -> StepResult:
    issue = require_issue_key(issue)
    session = _require_review_session(app, issue)
    identity = _require_identity(session)
    sha = session["active_sha"]
    pr = _load_pr(app, issue, identity)
    profile_dir = _commit_dir(app, issue, identity, sha) / "testing" / "profile"
    desired = _desired_profile(app, issue, pr, sha)
    action = _write_profile(app, profile_dir, desired, issue=issue, sha=sha, branch=pr["head_branch"])
    summary = {
        "created": "Created the virtualization profile.",
        "reused": "Reused the existing virtualization profile.",
        "regenerated": "Regenerated the virtualization profile for the current configuration.",
    }[action]
    return finish(
        app,
        session,
        StepResult(
            step="virtualization",
            outcome=Outcome.READY,
            summary=summary + " Fetch the image before testing so a stale image is not reused.",
            next_command=f"review-ticket {issue} test fetch",
            report_path=str(profile_dir / "profile.json"),
            details={"profile_action": action, "completed_step": "virtualization"},
        ),
    )


def fetch_image(app: App, issue: str) -> StepResult:
    issue = require_issue_key(issue)
    session = _require_review_session(app, issue)
    identity = _require_identity(session)
    sha = session["active_sha"]
    profile_dir = _commit_dir(app, issue, identity, sha) / "testing" / "profile"
    profile_path = profile_dir / "profile.json"
    profile = read_json(profile_path)
    if not profile:
        raise WorkflowError("No virtualization profile exists. Run test prepare first.")
    previous = read_json(_commit_dir(app, issue, identity, sha) / "testing" / "environment.json") or {}
    try:
        digest = docker_pull(app.runner, app.config, profile["image"])
    except ToolError as exc:
        return finish(app, session, _blocked("virtualization", str(exc)))
    changed = bool(previous.get("digest") and previous.get("digest") != digest)
    environment = {
        "sha": sha,
        "image": profile["image"],
        "digest": digest,
        "previous_digest": previous.get("digest"),
        "changed": changed,
        "fetched_at": iso_now(),
    }
    testing_dir = _commit_dir(app, issue, identity, sha) / "testing"
    write_json(testing_dir / "environment.json", environment)
    profile["image_digest"] = digest
    write_json(profile_path, profile)
    summary = f"Fetched {profile['image']} ({digest})."
    if changed:
        summary += f" This digest differs from the previously fetched image {previous.get('digest')}."
    elif previous.get("digest"):
        summary += " The digest matches the previously fetched image."
    return finish(
        app,
        session,
        StepResult(
            step="virtualization",
            outcome=Outcome.READY,
            summary=summary,
            next_command=f"review-ticket {issue} test launch",
            report_path=str(testing_dir / "environment.json"),
            details={"digest": digest, "previous_digest": previous.get("digest"), "changed": changed},
        ),
    )


def launch_environment(app: App, issue: str) -> StepResult:
    issue = require_issue_key(issue)
    session = _require_review_session(app, issue)
    identity = _require_identity(session)
    sha = session["active_sha"]
    testing_dir = _commit_dir(app, issue, identity, sha) / "testing"
    profile = read_json(testing_dir / "profile" / "profile.json")
    environment = read_json(testing_dir / "environment.json")
    if not profile:
        raise WorkflowError("No virtualization profile exists. Run test prepare first.")
    if not environment or environment.get("sha") != sha or not environment.get("digest"):
        raise WorkflowError("Fetch the Docker image for this SHA before launching. An older image is not evidence.")
    compose = testing_dir / "profile" / "docker-compose.yml"
    try:
        docker_compose_up(app.runner, app.config, profile["project_name"], compose)
    except ToolError as exc:
        return finish(app, session, _blocked("virtualization", str(exc)))
    return finish(
        app,
        session,
        StepResult(
            step="virtualization",
            outcome=Outcome.READY,
            summary=f"Launched project {profile['project_name']} from {environment['digest']}.",
            next_command=f"review-ticket {issue} test record --result pass",
            details={"project": profile["project_name"], "digest": environment["digest"]},
        ),
    )


def write_test_plan_command(app: App, issue: str) -> StepResult:
    issue = require_issue_key(issue)
    session = _require_review_session(app, issue)
    path = _ensure_test_plan(app, session)
    return finish(
        app,
        session,
        StepResult(
            step="functional-testing",
            outcome=Outcome.READY,
            summary="Wrote the test plan. Run the scenarios you consider necessary, then record the result.",
            next_command=f"review-ticket {issue} test record --result pass",
            report_path=str(path),
        ),
    )


def record_tests(
    app: App,
    issue: str,
    *,
    result: str,
    kind: str | None,
    notes: str,
    scenarios: list[str],
    evidence: list[str],
    revise: bool,
) -> StepResult:
    issue = require_issue_key(issue)
    if result not in {"pass", "fail", "blocked"}:
        raise WorkflowError("Test result must be pass, fail, or blocked.")
    if result == "fail" and kind not in {"implementation", "environment"}:
        raise WorkflowError("A failing test needs --kind implementation or --kind environment.")
    if result == "blocked":
        kind = kind or "environment"
    if result == "pass":
        kind = None
    session = _require_review_session(app, issue)
    identity = _require_identity(session)
    sha = session["active_sha"]
    testing_dir = _commit_dir(app, issue, identity, sha) / "testing"
    existing = read_json(testing_dir / "test-results.json")
    if existing and not revise:
        raise WorkflowError("Test results already exist for this SHA. Pass --revise to replace them.")
    environment = read_json(testing_dir / "environment.json") or {}
    stored_evidence = _store_evidence(testing_dir, evidence)
    payload = {
        "sha": sha,
        "image": environment.get("image"),
        "digest": environment.get("digest"),
        "result": result,
        "failure_kind": kind,
        "notes": notes,
        "scenarios": scenarios,
        "evidence": stored_evidence,
        "recorded_at": iso_now(),
    }
    write_json(testing_dir / "test-results.json", payload)
    write_text(testing_dir / "test-results.md", test_results_markdown(payload))
    comment = functional_comment(payload)
    write_text(testing_dir / "comment.md", comment)
    put_decision(
        session,
        "testing",
        {"choice": result, "kind": kind, "at": iso_now()},
        sha=sha,
        revise=revise,
    )
    _append_note(app, issue, notes)
    outcome, summary, recommendation = testing_outcome(result, kind, in_progress_status=app.config.in_progress_status)
    next_command = f"review-ticket {issue} disposition --choice approve"
    if outcome == Outcome.ACTION_REQUIRED:
        next_command = f"review-ticket {issue} jira transition --status {json_quote(app.config.in_progress_status)}"
    elif outcome == Outcome.BLOCKED:
        next_command = f"review-ticket {issue} test fetch"
    return finish(
        app,
        session,
        StepResult(
            step="functional-testing",
            outcome=outcome,
            summary=summary,
            recommendation=recommendation,
            next_command=next_command,
            report_path=str(testing_dir / "test-results.md"),
            details={"completed_step": "functional-testing"} if outcome == Outcome.READY else {},
        ),
    )


def post_comment(
    app: App,
    issue: str,
    *,
    body_file: Path | None,
    body: str | None,
    attachments: list[str],
    yes: bool,
) -> StepResult:
    issue = require_issue_key(issue)
    session = _require_review_session(app, issue)
    identity = _require_identity(session)
    owner, repo, number = identity
    sha = session.get("active_sha")
    sha_dir = _commit_dir(app, issue, identity, sha) if sha else None
    if body_file is None and body is not None:
        body_file = app.store.issue_dir(issue) / "pr-comment.md"
        write_text(body_file, body if body.endswith("\n") else body + "\n")
    if body_file is None or not body_file.exists():
        raise WorkflowError("A pull request comment needs --body-file or --body.")
    text = body_file.read_text(encoding="utf-8")
    material = {
        "issue": issue,
        "pr": session.get("active_pr"),
        "sha": sha,
        "body": sha256_text(text),
        "attachments": attachments,
    }
    key = fingerprint({"kind": "github.comment", **material})
    if app.store.successful_action(issue, key):
        return finish(
            app,
            session,
            StepResult(
                step="functional-testing",
                outcome=Outcome.READY,
                summary="This pull request comment was already published. It was not posted again.",
                jira_mutated=False,
            ),
        )
    preview = (
        f"Post a pull request comment on {owner}/{repo}#{number}.\n"
        f"Body file: {body_file}\n"
        f"Attachments: {', '.join(attachments) if attachments else '(none)'}\n\n"
        f"{text.rstrip()}\n"
    )
    authorize(preview=preview, yes=yes, interactive=app.interactive, prompt=app.input_fn, write=app.write)
    try:
        receipt = post_pr_comment(app.runner, app.config, owner, repo, number, body_file, attachments)
    except ToolError as exc:
        _journal(app, issue, sha_dir, "github.comment", key, "failure", {"error": str(exc)}, sha or "")
        return finish(app, session, _blocked("functional-testing", str(exc)))
    receipt_path = None
    if sha_dir is not None:
        receipt_path = sha_dir / "testing" / "publication.json"
        write_json(receipt_path, {"status": "success", "key": key, "receipt": receipt, "at": iso_now()})
    _journal(app, issue, sha_dir, "github.comment", key, "success", receipt, sha or "")
    return finish(
        app,
        session,
        StepResult(
            step="functional-testing",
            outcome=Outcome.READY,
            summary="Published the pull request comment.",
            report_path=str(receipt_path) if receipt_path else None,
            details={"url": receipt.get("url")},
        ),
    )


def jira_comment(app: App, issue: str, *, body_file: Path | None, body: str | None, yes: bool) -> StepResult:
    issue = require_issue_key(issue)
    session = app.store.ensure_session(issue)
    if body_file is None and body is not None:
        body_file = app.store.issue_dir(issue) / "jira-comment.md"
        write_text(body_file, body if body.endswith("\n") else body + "\n")
    if body_file is None or not body_file.exists():
        raise WorkflowError("A Jira comment needs --body-file or --body.")
    text = body_file.read_text(encoding="utf-8")
    sha = session.get("active_sha") or ""
    key = fingerprint({"kind": "jira.comment", "issue": issue, "sha": sha, "body": sha256_text(text)})
    if app.store.successful_action(issue, key):
        return finish(
            app,
            session,
            StepResult(
                step=session.get("current_step") or "jira-issue",
                outcome=Outcome.READY,
                summary="This Jira comment was already posted. It was not posted again.",
            ),
        )
    preview = f"Comment on {issue}.\n\n{text.rstrip()}\n"
    authorize(preview=preview, yes=yes, interactive=app.interactive, prompt=app.input_fn, write=app.write)
    sha_dir = _maybe_commit_dir(app, session)
    try:
        receipt = post_jira_comment(app.runner, app.config, issue, body_file)
    except ToolError as exc:
        _journal(app, issue, sha_dir, "jira.comment", key, "failure", {"error": str(exc)}, sha)
        return finish(app, session, _blocked(session.get("current_step") or "jira-issue", str(exc)))
    _journal(app, issue, sha_dir, "jira.comment", key, "success", receipt, sha)
    return finish(
        app,
        session,
        StepResult(
            step=session.get("current_step") or "jira-issue",
            outcome=Outcome.READY,
            summary=f"Posted a comment on {issue}.",
            jira_mutated=True,
        ),
    )


def jira_transition(app: App, issue: str, status: str, *, yes: bool) -> StepResult:
    issue = require_issue_key(issue)
    session = app.store.ensure_session(issue)
    sha = session.get("active_sha") or ""
    key = fingerprint({"kind": "jira.transition", "issue": issue, "status": status, "sha": sha})
    if app.store.successful_action(issue, key):
        return finish(
            app,
            session,
            StepResult(
                step=session.get("current_step") or "jira-issue",
                outcome=Outcome.COMPLETE,
                summary=f"{issue} was already transitioned to {status} for this SHA. Not sent again.",
                jira_mutated=True,
                details={"completed_step": session.get("current_step")},
            ),
        )
    preview = f"Transition {issue} to {status}."
    if sha:
        preview += f"\nReview SHA: {sha}"
    authorize(preview=preview + "\n", yes=yes, interactive=app.interactive, prompt=app.input_fn, write=app.write)
    sha_dir = _maybe_commit_dir(app, session)
    try:
        receipt = transition_jira(app.runner, app.config, issue, status)
    except ToolError as exc:
        _journal(app, issue, sha_dir, "jira.transition", key, "failure", {"error": str(exc), "status": status}, sha)
        return finish(app, session, _blocked(session.get("current_step") or "jira-issue", str(exc)))
    _journal(app, issue, sha_dir, "jira.transition", key, "success", {"status": status, "receipt": receipt}, sha)
    return finish(
        app,
        session,
        StepResult(
            step=session.get("current_step") or "disposition",
            outcome=Outcome.COMPLETE,
            summary=f"Transitioned {issue} to {status}.",
            jira_mutated=True,
            details={"completed_step": "disposition"},
        ),
    )


def draft_bug(app: App, issue: str, *, summary: str, body: str, yes: bool) -> StepResult:
    issue = require_issue_key(issue)
    session = app.store.ensure_session(issue)
    identity = _selected(session)
    sha = session.get("active_sha")
    draft = {
        "source_issue": issue,
        "summary": summary,
        "body": body,
        "pr": session.get("active_pr"),
        "sha": sha,
        "created_at": iso_now(),
    }
    if identity and sha:
        path = _commit_dir(app, issue, identity, sha) / "testing" / "defect-draft.json"
    else:
        path = app.store.issue_dir(issue) / "defect-draft.json"
    write_json(path, draft)
    if not app.config.bug_writer_command:
        return finish(
            app,
            session,
            StepResult(
                step="functional-testing",
                outcome=Outcome.REVIEW_DECISION,
                summary=(
                    "Saved a defect draft for the bug writer skill. "
                    "Set bug_writer_command to invoke it. No Jira issue was created."
                ),
                report_path=str(path),
                next_command=f"review-ticket {issue} bug --summary {json_quote(summary)} --yes",
            ),
        )
    preview = f"Invoke the bug writer for a follow-up to {issue}.\n\n# {summary}\n\n{body}\n"
    authorize(preview=preview, yes=yes, interactive=app.interactive, prompt=app.input_fn, write=app.write)
    mapping = {
        "issue": issue,
        "summary": summary,
        "draft": str(path),
        "sha": sha or "",
        "pr": session.get("active_pr") or "",
    }
    result = run_external(app.runner, app.config.bug_writer_command, mapping)
    sha_dir = _maybe_commit_dir(app, session)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _journal(app, issue, sha_dir, "jira.bug", fingerprint(draft), "failure", {"error": detail}, sha or "")
        return finish(app, session, _blocked("functional-testing", detail or "Bug writer command failed."))
    receipt = {"stdout": result.stdout.strip(), "draft": str(path)}
    _journal(app, issue, sha_dir, "jira.bug", fingerprint(draft), "success", receipt, sha or "")
    return finish(
        app,
        session,
        StepResult(
            step="functional-testing",
            outcome=Outcome.READY,
            summary="Bug writer command finished.",
            jira_mutated=True,
            report_path=str(path),
        ),
    )


def record_disposition(
    app: App,
    issue: str,
    *,
    choice: str,
    notes: str,
    override: bool,
    revise: bool,
) -> StepResult:
    issue = require_issue_key(issue)
    if choice not in {"approve", "leave", "return"}:
        raise WorkflowError("Disposition must be approve, leave, or return.")
    session = app.store.ensure_session(issue)
    # Refresh external facts before trusting an earlier pass.
    for step in (step_jira, step_pull_request, step_checks, step_analyzers):
        result = step(app, session)
        if result is not None:
            return finish(app, session, result)
    identity = _require_identity(session)
    sha = session["active_sha"]
    checklist = _build_checklist(app, session)
    failing = [item for item in checklist if not item["ok"]]
    if choice == "approve" and failing and not override:
        raise WorkflowError(
            "The disposition checklist is incomplete. Return the issue, leave it in Peer Review, "
            "or pass --override with --notes."
        )
    if override and not notes.strip():
        raise WorkflowError("A disposition override needs --notes.")
    put_decision(
        session,
        "disposition",
        {"choice": choice, "notes": notes, "override": override, "at": iso_now()},
        sha=sha,
        revise=revise,
    )
    _append_note(app, issue, notes)
    path = _commit_dir(app, issue, identity, sha) / "disposition.json"
    write_json(
        path,
        {
            "choice": choice,
            "notes": notes,
            "override": override,
            "sha": sha,
            "checklist": checklist,
            "at": iso_now(),
        },
    )
    write_text(_commit_dir(app, issue, identity, sha) / "disposition.md", disposition_report(checklist, sha=sha))
    if choice == "leave":
        return finish(
            app,
            session,
            StepResult(
                step="disposition",
                outcome=Outcome.COMPLETE,
                summary="Left the issue in Peer Review. No Jira transition was requested.",
                report_path=str(path),
                details={"completed_step": "disposition"},
            ),
        )
    if choice == "return":
        return finish(
            app,
            session,
            StepResult(
                step="disposition",
                outcome=Outcome.ACTION_REQUIRED,
                summary="Disposition recorded. Authorize the transition when the Jira comment is ready.",
                recommendation=app.config.in_progress_status,
                next_command=(
                    f"review-ticket {issue} jira transition --status {json_quote(app.config.in_progress_status)} --yes"
                ),
                report_path=str(path),
            ),
        )
    return finish(
        app,
        session,
        StepResult(
            step="disposition",
            outcome=Outcome.READY,
            summary="Approval recorded. Authorize the Jira transition to advance the issue.",
            recommendation=app.config.approved_status,
            next_command=f"review-ticket {issue} jira transition --status {json_quote(app.config.approved_status)} --yes",
            report_path=str(path),
            details={"completed_step": "disposition"},
        ),
    )


def step_jira(app: App, session: dict[str, Any]) -> StepResult | None:
    issue = session["issue"]
    try:
        normalized = refresh_issue(app, session)
    except ToolError as exc:
        return _blocked("jira-issue", str(exc))
    if not app.config.accepts_peer_review_status(normalized.get("status") or ""):
        status = normalized.get("status") or "unknown"
        if _transition_recorded(app, issue, status, session.get("active_sha") or ""):
            return StepResult(
                step="jira-issue",
                outcome=Outcome.COMPLETE,
                summary=f"{issue} is {status}.",
                jira_mutated=True,
                details={"completed_step": "disposition"},
            )
        return StepResult(
            step="jira-issue",
            outcome=Outcome.ACTION_REQUIRED,
            summary=(
                f"{issue} is {status}. This workflow starts when the issue is in "
                f"{app.config.peer_review_status_label()}."
            ),
            next_command=f"review-ticket {issue} status",
        )
    notes = normalized.get("testing_notes") or ""
    notes_hash = sha256_text(notes)
    decision = get_decision(session, "testing_notes")
    if decision and decision.get("notes_hash") != notes_hash:
        session["decisions"].setdefault("testing_notes_history", []).append(
            {**decision, "invalidated_at": iso_now()}
        )
        session["decisions"].pop("testing_notes", None)
        decision = None
        app.store.save_session(session)
    report = str(app.store.issue_dir(issue) / "issue-report.md")
    if decision is None and app.interactive and notes.strip():
        prompted = _prompt_notes(app)
        if prompted:
            put_decision(
                session,
                "testing_notes",
                {"choice": prompted, "notes": "", "notes_hash": notes_hash, "at": iso_now()},
            )
            app.store.save_session(session)
            decision = get_decision(session, "testing_notes")
    if decision is None:
        if not notes.strip():
            draft = _write_return_draft(
                app,
                issue,
                reason="No testing notes were found on the Jira issue.",
                notes="",
                links=[],
            )
            return StepResult(
                step="jira-issue",
                outcome=Outcome.ACTION_REQUIRED,
                summary="Testing notes are missing. The default recommendation is to return the issue.",
                recommendation=app.config.in_progress_status,
                next_command=f"review-ticket {issue} notes --reject",
                report_path=str(draft),
            )
        return StepResult(
            step="jira-issue",
            outcome=Outcome.REVIEW_DECISION,
            summary="Testing notes are ready for a reviewer decision.",
            next_command=f"review-ticket {issue} notes --accept",
            report_path=report,
            details={"testing_notes": notes},
        )
    if decision.get("choice") == "reject":
        draft = session.get("return_draft") or str(app.store.issue_dir(issue) / "return-comment.md")
        return StepResult(
            step="jira-issue",
            outcome=Outcome.ACTION_REQUIRED,
            summary="Testing notes were rejected. Review the draft, then authorize the Jira comment and transition.",
            recommendation=app.config.in_progress_status,
            next_command=f"review-ticket {issue} jira comment --body-file {draft} --yes",
            report_path=str(draft),
        )
    session["last_completed_step"] = "jira-issue"
    app.store.save_session(session)
    return None


def step_pull_request(app: App, session: dict[str, Any]) -> StepResult | None:
    issue = session["issue"]
    normalized = read_json(app.store.issue_dir(issue) / "issue.json") or {}
    try:
        candidates = discover_prs(app, issue, normalized)
    except ToolError as exc:
        return _blocked("github-readiness", str(exc))
    session["pr_candidates"] = [f"{item['owner']}/{item['repo']}#{item['number']}" for item in candidates]
    selected = _selected(session)
    if selected is None:
        if not candidates:
            return StepResult(
                step="github-readiness",
                outcome=Outcome.ACTION_REQUIRED,
                summary=_no_pr_summary(app, issue),
                recommendation=app.config.in_progress_status,
                next_command=f"review-ticket {issue} pr select owner/repo#number",
            )
        if len(candidates) > 1:
            listed = ", ".join(session["pr_candidates"])
            return StepResult(
                step="github-readiness",
                outcome=Outcome.REVIEW_DECISION,
                summary=f"Multiple open pull requests reference {issue}: {listed}.",
                next_command=f"review-ticket {issue} pr select {session['pr_candidates'][0]}",
            )
        only = candidates[0]
        selected = (only["owner"], only["repo"], only["number"])
        session["active_pr"] = f"{only['owner']}/{only['repo']}#{only['number']}"
    owner, repo, number = selected
    try:
        pr = get_pr(app.runner, app.config, owner, repo, number)
    except ToolError as exc:
        return _blocked("github-readiness", str(exc))
    if not pr.get("head_sha"):
        return _blocked("github-readiness", "The pull request has no head SHA.")
    previous = session.get("active_sha")
    sha = pr["head_sha"]
    if previous and previous != sha:
        prior = session.setdefault("previous_shas", [])
        if previous not in prior:
            prior.append(previous)
    session["active_pr"] = f"{owner}/{repo}#{number}"
    session["active_sha"] = sha
    pr_dir = app.store.pr_dir(issue, owner, repo, number)
    write_json(pr_dir / "pr.json", pr)
    snapshot = {
        "issue": issue,
        "repository": f"{owner}/{repo}",
        "pr": number,
        "sha": sha,
        "base_sha": pr.get("base_sha"),
        "head_branch": pr.get("head_branch"),
        "base_branch": pr.get("base_branch"),
        "draft": pr.get("draft"),
        "url": pr.get("url"),
        "captured_at": iso_now(),
        "supersedes": previous if previous and previous != sha else None,
    }
    write_json(app.store.commit_dir(issue, owner, repo, number, sha) / "snapshot.json", snapshot)
    app.store.save_session(session)
    return None


def step_checks(app: App, session: dict[str, Any]) -> StepResult | None:
    issue = session["issue"]
    identity = _require_identity(session)
    owner, repo, number = identity
    sha = session["active_sha"]
    try:
        required_raw, all_raw = get_checks(app.runner, app.config, owner, repo, number)
    except ToolError as exc:
        message = str(exc)
        if exc.unavailable:
            message = "GitHub checks are unavailable. This is an environment problem, not a developer defect. " + message
        return _blocked("github-readiness", message)
    checks, missing_analyzers = normalize_checks(required_raw, all_raw, app.config)
    accepted_checks = (get_decision(session, "missing_checks", sha) or {}).get("choice") == "accept"
    accepted_analyzers = (get_decision(session, "missing_analyzers", sha) or {}).get("choice") == "accept"
    readiness = evaluate_readiness(
        checks,
        missing_analyzers=missing_analyzers,
        service_unavailable=None,
        accepted_missing_checks=accepted_checks,
        accepted_missing_analyzers=accepted_analyzers,
        in_progress_status=app.config.in_progress_status,
    )
    if readiness.outcome == Outcome.READY and not any(check.required for check in checks) and not accepted_checks:
        readiness = Readiness(
            outcome=Outcome.REVIEW_DECISION,
            summary="No required checks were reported. Confirm branch protection before continuing.",
            missing=["required checks"],
        )
    pr = _load_pr(app, issue, identity)
    commit_dir = app.store.commit_dir(issue, owner, repo, number, sha)
    serialized = [asdict(check) for check in checks]
    write_json(
        commit_dir / "github-checks.json",
        {
            "sha": sha,
            "required_raw": required_raw,
            "all_raw": all_raw,
            "checks": serialized,
            "outcome": readiness.outcome.value,
            "summary": readiness.summary,
        },
    )
    report = commit_dir / "readiness.md"
    write_text(
        report,
        readiness_report(pr=pr, checks=serialized, outcome=readiness.outcome.value, summary=readiness.summary),
    )
    if readiness.outcome != Outcome.READY:
        next_command = f"review-ticket {issue} assess"
        if readiness.outcome == Outcome.REVIEW_DECISION:
            if missing_analyzers and not accepted_analyzers:
                next_command = f"review-ticket {issue} assess --accept-missing-analyzers"
            else:
                next_command = f"review-ticket {issue} assess --accept-missing-checks"
        elif readiness.outcome == Outcome.ACTION_REQUIRED:
            next_command = (
                f"review-ticket {issue} jira transition --status {json_quote(app.config.in_progress_status)} --yes"
            )
        return StepResult(
            step="github-readiness",
            outcome=readiness.outcome,
            summary=readiness.summary,
            recommendation=readiness.recommendation,
            next_command=next_command,
            report_path=str(report),
        )
    session["last_completed_step"] = "github-readiness"
    app.store.save_session(session)
    return None


def step_analyzers(app: App, session: dict[str, Any]) -> StepResult | None:
    issue = session["issue"]
    identity = _require_identity(session)
    owner, repo, number = identity
    sha = session["active_sha"]
    pr = _load_pr(app, issue, identity)
    try:
        threads = get_review_threads(app.runner, app.config, owner, repo, number)
    except ToolError as exc:
        message = str(exc)
        if exc.unavailable:
            message = "GitHub review threads are unavailable. The developer was not blamed. " + message
        return _blocked("analyzer-findings", message)
    ref = f"refs/heads/{pr.get('head_branch') or ''}"
    try:
        alerts = get_code_scanning_alerts(app.runner, app.config, owner, repo, ref)
    except ToolError as exc:
        return _blocked("analyzer-findings", str(exc))
    checks = (read_json(_commit_dir(app, issue, identity, sha) / "github-checks.json") or {}).get("checks") or []
    codeql_ran = any(item.get("kind") == "codeql" for item in checks)
    if alerts.unavailable and codeql_ran:
        return _blocked(
            "analyzer-findings",
            "Code scanning is unavailable, so CodeQL findings cannot be collected. "
            "The developer was not blamed. " + alerts.message,
        )
    bugbot, codeql = classify_analyzer_findings(threads, alerts.items, app.config)
    findings = bugbot + codeql
    commit_dir = _commit_dir(app, issue, identity, sha)
    write_json(commit_dir / "bugbot-findings.json", {"sha": sha, "findings": bugbot})
    write_json(commit_dir / "codeql-findings.json", {"sha": sha, "findings": codeql, "unavailable": alerts.message})
    report = commit_dir / "analyzers.md"
    unavailable = "" if codeql_ran or not alerts.unavailable else alerts.message or "Code scanning was not available."
    write_text(report, analyzer_report(findings, unavailable=unavailable))
    decision = (get_decision(session, "analyzers", sha) or {}).get("choice")
    outcome, summary, recommendation = evaluate_analyzers(
        findings,
        decision,
        in_progress_status=app.config.in_progress_status,
    )
    if outcome != Outcome.READY:
        if any(item.get("attention") == "unaddressed" for item in findings) and decision != "override":
            next_command = f"review-ticket {issue} analyzers --return"
        else:
            next_command = f"review-ticket {issue} analyzers --accept-dispositions"
        return StepResult(
            step="analyzer-findings",
            outcome=outcome,
            summary=summary,
            recommendation=recommendation,
            next_command=next_command,
            report_path=str(report),
        )
    session["last_completed_step"] = "analyzer-findings"
    app.store.save_session(session)
    return None


def step_automated_review(app: App, session: dict[str, Any]) -> StepResult | None:
    issue = session["issue"]
    identity = _require_identity(session)
    review_dir = _review_dir(app, issue, identity, session["active_sha"])
    if read_json(review_dir / "findings.json"):
        session["last_completed_step"] = "automated-review"
        app.store.save_session(session)
        return None
    pr = _load_pr(app, issue, identity)
    summary = "Ready for the automated reviewer."
    if pr.get("draft"):
        summary += " The pull request is still a draft."
    return StepResult(
        step="automated-review",
        outcome=Outcome.READY,
        summary=summary,
        next_command=f"review-ticket {issue} run-review",
        details={"completed_step": "analyzer-findings"},
    )


def step_publication(app: App, session: dict[str, Any]) -> StepResult | None:
    issue = session["issue"]
    identity = _require_identity(session)
    sha = session["active_sha"]
    review_dir = _review_dir(app, issue, identity, sha)
    human = read_json(review_dir / "human-review.json")
    if not human:
        return StepResult(
            step="human-review",
            outcome=Outcome.REVIEW_DECISION,
            summary="Accept, reject, or edit the automated findings before publication.",
            next_command=f"review-ticket {issue} review apply --accept-all",
            report_path=str(review_dir / "reviewer-report.md"),
        )
    if human.get("rejected_review"):
        return StepResult(
            step="human-review",
            outcome=Outcome.REVIEW_DECISION,
            summary="The automated review was rejected locally and has not been published.",
            next_command=f"review-ticket {issue} run-review --revise",
            report_path=str(review_dir / "findings.json"),
        )
    publication = read_json(review_dir / "publication.json")
    if not publication:
        return StepResult(
            step="human-review",
            outcome=Outcome.REVIEW_DECISION,
            summary="The local review is ready to publish. GitHub has not been changed.",
            next_command=f"review-ticket {issue} publish-review --yes",
            report_path=str(review_dir / "proposed-review.json"),
        )
    return _publication_gate(app, issue, sha, publication)


def step_virtualization(app: App, session: dict[str, Any]) -> StepResult | None:
    issue = session["issue"]
    identity = _require_identity(session)
    sha = session["active_sha"]
    testing_dir = _commit_dir(app, issue, identity, sha) / "testing"
    profile = read_json(testing_dir / "profile" / "profile.json")
    if not profile:
        return StepResult(
            step="virtualization",
            outcome=Outcome.READY,
            summary="Prepare an isolated virtualization profile for this SHA.",
            next_command=f"review-ticket {issue} test prepare",
            details={"completed_step": "human-review"},
        )
    environment = read_json(testing_dir / "environment.json")
    if not environment or environment.get("sha") != sha or not environment.get("digest"):
        return StepResult(
            step="virtualization",
            outcome=Outcome.READY,
            summary=(
                "The profile exists. Fetch the Docker image for this SHA before testing. "
                "An image recorded for another commit is not evidence for this one."
            ),
            next_command=f"review-ticket {issue} test fetch",
            report_path=str(testing_dir / "profile" / "profile.json"),
        )
    session["last_completed_step"] = "virtualization"
    app.store.save_session(session)
    return None


def step_testing(app: App, session: dict[str, Any]) -> StepResult | None:
    issue = session["issue"]
    identity = _require_identity(session)
    sha = session["active_sha"]
    testing_dir = _commit_dir(app, issue, identity, sha) / "testing"
    _ensure_test_plan(app, session)
    results = read_json(testing_dir / "test-results.json")
    if not results:
        return StepResult(
            step="functional-testing",
            outcome=Outcome.READY,
            summary="Functional testing is human-directed. Record a pass, an implementation failure, or an environment block.",
            next_command=f"review-ticket {issue} test record --result pass",
            report_path=str(testing_dir / "test-plan.md"),
        )
    if results.get("sha") != sha:
        return StepResult(
            step="functional-testing",
            outcome=Outcome.REVIEW_DECISION,
            summary="Stored test results belong to a different SHA and are not evidence for this commit.",
            next_command=f"review-ticket {issue} test record --result pass --revise",
        )
    outcome, summary, recommendation = testing_outcome(
        results.get("result") or "",
        results.get("failure_kind"),
        in_progress_status=app.config.in_progress_status,
    )
    if outcome != Outcome.READY:
        next_command = f"review-ticket {issue} test record --result pass --revise"
        if outcome == Outcome.ACTION_REQUIRED:
            next_command = (
                f"review-ticket {issue} jira transition --status {json_quote(app.config.in_progress_status)} --yes"
            )
        return StepResult(
            step="functional-testing",
            outcome=outcome,
            summary=summary,
            recommendation=recommendation,
            next_command=next_command,
            report_path=str(testing_dir / "test-results.md"),
        )
    session["last_completed_step"] = "functional-testing"
    app.store.save_session(session)
    return None


def step_disposition(app: App, session: dict[str, Any]) -> StepResult | None:
    issue = session["issue"]
    identity = _require_identity(session)
    sha = session["active_sha"]
    decision = get_decision(session, "disposition", sha)
    checklist = _build_checklist(app, session)
    path = _commit_dir(app, issue, identity, sha) / "disposition.md"
    write_text(path, disposition_report(checklist, sha=sha))
    if decision and decision.get("choice") == "approve":
        if _transition_recorded(app, issue, app.config.approved_status, sha):
            return StepResult(
                step="disposition",
                outcome=Outcome.COMPLETE,
                summary=f"{issue} was advanced to {app.config.approved_status}.",
                jira_mutated=True,
                report_path=str(path),
                details={"completed_step": "disposition"},
            )
        return StepResult(
            step="disposition",
            outcome=Outcome.READY,
            summary="Approval is recorded. Authorize the Jira transition to advance the issue.",
            recommendation=app.config.approved_status,
            next_command=f"review-ticket {issue} jira transition --status {json_quote(app.config.approved_status)} --yes",
            report_path=str(path),
        )
    if decision and decision.get("choice") == "leave":
        return StepResult(
            step="disposition",
            outcome=Outcome.COMPLETE,
            summary="The reviewer left the issue in Peer Review.",
            report_path=str(path),
            details={"completed_step": "disposition"},
        )
    if decision and decision.get("choice") == "return":
        if _transition_recorded(app, issue, app.config.in_progress_status, sha):
            return StepResult(
                step="disposition",
                outcome=Outcome.COMPLETE,
                summary=f"{issue} was returned to {app.config.in_progress_status}.",
                jira_mutated=True,
                details={"completed_step": "disposition"},
            )
        return StepResult(
            step="disposition",
            outcome=Outcome.ACTION_REQUIRED,
            summary="Return is recorded. Authorize the Jira transition.",
            recommendation=app.config.in_progress_status,
            next_command=(
                f"review-ticket {issue} jira transition --status {json_quote(app.config.in_progress_status)} --yes"
            ),
            report_path=str(path),
        )
    failing = [item["detail"] for item in checklist if not item["ok"]]
    summary = "Final disposition is ready for a reviewer decision."
    if failing:
        summary = "Disposition checklist still has gaps: " + "; ".join(failing)
    return StepResult(
        step="disposition",
        outcome=Outcome.REVIEW_DECISION,
        summary=summary,
        next_command=f"review-ticket {issue} disposition --choice approve",
        report_path=str(path),
    )


def _no_pr_summary(app: App, issue: str) -> str:
    repo = app.config.github_repo
    if repo:
        return (
            f"No open pull request references {issue} in {repo}. "
            "Check github_repo in .review-ticket.yaml or run pr select."
        )
    return f"No open pull request references {issue}."


def discover_prs(app: App, issue: str, normalized: dict[str, Any]) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    text = "\n".join(
        [
            normalized.get("description") or "",
            normalized.get("testing_notes") or "",
            "\n".join(comment.get("body") or "" for comment in normalized.get("comments") or []),
        ]
    )
    for owner, repo, number in find_pr_urls(text):
        found.append(
            {
                "owner": owner,
                "repo": repo,
                "number": number,
                "title": "",
                "url": f"https://github.com/{owner}/{repo}/pull/{number}",
                "state": "open",
            }
        )
    found.extend(search_prs(app.runner, app.config, issue))
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int]] = set()
    for item in found:
        key = (item["owner"], item["repo"], int(item["number"]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def normalize_checks(
    required_raw: list[dict[str, Any]],
    all_raw: list[dict[str, Any]],
    config: Config,
) -> tuple[list[Check], list[str]]:
    required_names = {str(item.get("name")) for item in required_raw if item.get("name")}
    by_name: dict[str, dict[str, Any]] = {}
    for item in list(all_raw) + list(required_raw):
        name = str(item.get("name") or "")
        if name:
            by_name[name] = item
    checks: list[Check] = []
    for name, item in by_name.items():
        kind = classify_check_name(name, config.analyzer_checks)
        required = name in required_names or name in config.required_checks
        if config.require_analyzers and kind in {"bugbot", "codeql", "analyzer"}:
            required = True
        checks.append(
            Check(
                name=name,
                bucket=bucket_of(item),
                state=str(item.get("state") or ""),
                link=str(item.get("link") or ""),
                required=required,
                kind=kind,
            )
        )
    for name in config.required_checks:
        if name not in by_name:
            checks.append(
                Check(
                    name=name,
                    bucket="missing",
                    required=True,
                    kind=classify_check_name(name, config.analyzer_checks),
                )
            )
    missing_analyzers: list[str] = []
    if config.require_analyzers:
        for analyzer in config.analyzer_checks:
            if not any(analyzer.casefold() in check.name.casefold() for check in checks):
                missing_analyzers.append(analyzer)
    return checks, missing_analyzers


def classify_analyzer_findings(
    threads: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    config: Config,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bugbot: list[dict[str, Any]] = []
    codeql: list[dict[str, Any]] = []
    for thread in threads:
        finding = _thread_finding(thread, config)
        if finding is None:
            continue
        if finding["source"] == "bugbot":
            bugbot.append(finding)
        else:
            codeql.append(finding)
    for alert in alerts:
        tool = str((alert.get("tool") or {}).get("name") or "")
        if tool.casefold() != "codeql":
            continue
        codeql.append(_alert_finding(alert))
    return bugbot, codeql


def refresh_issue(app: App, session: dict[str, Any]) -> dict[str, Any]:
    issue = session["issue"]
    raw, normalized = fetch_jira(app.runner, app.config, issue)
    directory = app.store.issue_dir(issue)
    write_json(directory / "issue-raw.json", raw)
    write_json(directory / "issue.json", normalized)
    write_text(directory / "issue-report.md", issue_report(normalized))
    return normalized


def finish(app: App, session: dict[str, Any], result: StepResult) -> StepResult:
    session["current_step"] = result.step
    session["outcome"] = result.outcome.value
    session["recommendation"] = result.recommendation
    session["next_command"] = result.next_command
    if result.details.get("completed_step"):
        session["last_completed_step"] = result.details["completed_step"]
    app.store.save_session(session)
    _render(app, session, result)
    return result


def get_decision(session: dict[str, Any], name: str, sha: str | None = None) -> dict[str, Any] | None:
    decisions = session.get("decisions") or {}
    if sha is None:
        value = decisions.get(name)
        return value if isinstance(value, dict) and "choice" in value else None
    bucket = decisions.get(name) or {}
    if not isinstance(bucket, dict):
        return None
    value = bucket.get(sha)
    return value if isinstance(value, dict) else None


def put_decision(
    session: dict[str, Any],
    name: str,
    value: dict[str, Any],
    *,
    sha: str | None = None,
    revise: bool = False,
) -> None:
    decisions = session.setdefault("decisions", {})
    if sha is None:
        existing = decisions.get(name)
        if isinstance(existing, dict) and "choice" in existing and not revise and existing.get("choice") != value.get("choice"):
            raise WorkflowError(
                f"Decision '{name}' is already {existing.get('choice')}. Pass --revise to change it."
            )
        decisions[name] = value
        return
    bucket = decisions.setdefault(name, {})
    if not isinstance(bucket, dict) or "choice" in bucket:
        bucket = {}
        decisions[name] = bucket
    existing = bucket.get(sha)
    if isinstance(existing, dict) and not revise and existing.get("choice") != value.get("choice"):
        raise WorkflowError(
            f"Decision '{name}' for {sha[:12]} is already {existing.get('choice')}. Pass --revise to change it."
        )
    bucket[sha] = value


def _execute_reviewer(app: App, session: dict[str, Any], *, revise: bool, imported: Any | None) -> StepResult:
    issue = session["issue"]
    identity = _require_identity(session)
    sha = session["active_sha"]
    review_dir = _review_dir(app, issue, identity, sha)
    if any((review_dir / name).exists() for name in ("findings.json", "human-review.json")) and not revise:
        raise WorkflowError("A review already exists for this SHA. Pass --revise to archive it and run again.")
    if revise:
        _archive_review(review_dir)
    diff_text = _ensure_diff(app, session)
    index = parse_unified_diff(diff_text)
    write_json(review_dir / "diff-lines.json", sorted([list(item) for item in index]))
    output = review_dir / "reviewer-output.json"
    context = _write_context(app, session, diff_text, output)
    if imported is None:
        if not app.config.reviewer_command:
            return StepResult(
                step="automated-review",
                outcome=Outcome.REVIEW_DECISION,
                summary=(
                    "Review context is ready. No reviewer_command is configured. "
                    "Run the reviewer skill against the context, then import its JSON."
                ),
                next_command=f"review-ticket {issue} import-review --file PATH",
                report_path=str(context / "prompt.md"),
            )
        mapping = {
            "context": str(context),
            "output": str(output),
            "issue": issue,
            "sha": sha,
            "checkout": str(_commit_dir(app, issue, identity, sha) / "checkout"),
            "repository": f"{identity[0]}/{identity[1]}",
        }
        result = run_external(app.runner, app.config.reviewer_command, mapping)
        if output.exists():
            imported = json.loads(output.read_text(encoding="utf-8"))
        elif result.stdout.strip():
            try:
                imported = parse_json_output(result.stdout)
            except Exception as exc:  # noqa: BLE001 - surface the reviewer output problem
                return _blocked("automated-review", f"Reviewer output was not JSON: {exc}")
        if result.returncode != 0 and imported is None:
            detail = (result.stderr or result.stdout or "reviewer command failed").strip()
            return _blocked("automated-review", detail)
    if imported is None:
        return _blocked("automated-review", f"The reviewer did not write {output}.")
    try:
        document, findings = normalize_findings(imported)
    except WorkflowError as exc:
        return _blocked("automated-review", str(exc))
    previous = _previous_finding_rows(app, issue, identity, sha)
    reconciliation = reconcile([row for batch in previous for row in batch["findings"]], findings)
    stored = {
        "summary": document.get("summary") or "",
        "approval_recommendation": document.get("approval_recommendation") or "",
        "findings": findings,
    }
    write_json(review_dir / "findings.json", stored)
    write_json(review_dir / "reconciliation.json", reconciliation)
    write_text(review_dir / "reviewer-report.md", reviewer_report(stored, findings, reconciliation))
    proposed = build_review_payload(
        sha=sha,
        event=policy_suggest_event(findings),
        summary=stored["summary"] or "Automated review.",
        findings=findings,
        diff_index=index,
    )
    write_json(review_dir / "proposed-review.json", proposed)
    session["last_completed_step"] = "automated-review"
    return StepResult(
        step="human-review",
        outcome=Outcome.REVIEW_DECISION,
        summary="Automated review is stored locally. Decide each finding before publication.",
        next_command=f"review-ticket {issue} review apply --accept-all",
        report_path=str(review_dir / "reviewer-report.md"),
        details={"completed_step": "automated-review"},
    )


def _ensure_diff(app: App, session: dict[str, Any]) -> str:
    issue = session["issue"]
    identity = _require_identity(session)
    sha = session["active_sha"]
    commit_dir = _commit_dir(app, issue, identity, sha)
    existing = commit_dir / "diff.patch"
    if existing.exists() and (commit_dir / "review" / "diff-lines.json").exists():
        return existing.read_text(encoding="utf-8")
    pr = _load_pr(app, issue, identity)
    checkout = commit_dir / "checkout"
    ensure_checkout(
        app.runner,
        app.config,
        owner=identity[0],
        repo=identity[1],
        sha=sha,
        dest=checkout,
    )
    diff_text = git_diff(app.runner, app.config.git_bin, checkout, pr.get("base_sha") or "", sha)
    write_text(existing, diff_text)
    snapshot_path = commit_dir / "snapshot.json"
    snapshot = read_json(snapshot_path) or {}
    snapshot["checkout_path"] = str(checkout)
    snapshot["verified_sha"] = sha
    write_json(snapshot_path, snapshot)
    return diff_text


def _write_context(app: App, session: dict[str, Any], diff_text: str, output: Path) -> Path:
    issue = session["issue"]
    identity = _require_identity(session)
    sha = session["active_sha"]
    context = _review_dir(app, issue, identity, sha) / "context"
    normalized = read_json(app.store.issue_dir(issue) / "issue.json") or {}
    write_text(
        context / "jira.md",
        f"# {normalized.get('key')}\n\n{normalized.get('summary') or ''}\n\n"
        f"## Acceptance criteria\n\n{normalized.get('acceptance_criteria') or ''}\n\n"
        f"## Description\n\n{normalized.get('description') or ''}\n",
    )
    write_text(context / "testing-notes.md", (normalized.get("testing_notes") or "") + "\n")
    write_text(context / "diff.patch", diff_text)
    write_text(context / "standards.md", _standards_text(app))
    analyzers = _load_analyzer_findings(app, issue, identity, sha)
    write_text(context / "analyzers.md", analyzer_report(analyzers))
    previous = _previous_finding_rows(app, issue, identity, sha)
    write_json(context / "previous-findings.json", previous)
    write_text(context / "prompt.md", reviewer_prompt(issue=issue, sha=sha, output_path=str(output)))
    return context


def _standards_text(app: App) -> str:
    parts: list[str] = []
    assert app.cwd is not None
    for raw in app.config.standards:
        path = Path(raw)
        if not path.is_absolute():
            path = app.cwd / path
        if path.exists():
            parts.append(f"# {path}\n\n{path.read_text(encoding='utf-8')}")
        else:
            parts.append(f"# {path}\n\n(not found)\n")
    return "\n\n".join(parts)


def _previous_finding_rows(app: App, issue: str, identity: tuple[str, str, int], sha: str) -> list[dict[str, Any]]:
    owner, repo, number = identity
    commits = app.store.pr_dir(issue, owner, repo, number) / "commits"
    rows: list[dict[str, Any]] = []
    if not commits.exists():
        return rows
    for path in sorted(item for item in commits.iterdir() if item.is_dir()):
        if path.name == sha:
            continue
        document = read_json(path / "review" / "findings.json")
        if not document:
            continue
        rows.append(
            {
                "sha": path.name,
                "findings": document.get("findings") or [],
                "human": read_json(path / "review" / "human-review.json"),
            }
        )
    return rows


def _diff_index(app: App, issue: str, identity: tuple[str, str, int], sha: str) -> set[tuple[str, int, str]]:
    review_dir = _review_dir(app, issue, identity, sha)
    stored = read_json(review_dir / "diff-lines.json")
    if isinstance(stored, list):
        return {(item[0], int(item[1]), item[2]) for item in stored}
    diff_path = _commit_dir(app, issue, identity, sha) / "diff.patch"
    if diff_path.exists():
        return parse_unified_diff(diff_path.read_text(encoding="utf-8"))
    raise WorkflowError("No diff index is stored for this SHA. Run run-review again.")


def _build_checklist(app: App, session: dict[str, Any]) -> list[dict[str, Any]]:
    issue = session["issue"]
    identity = _require_identity(session)
    sha = session["active_sha"]
    commit_dir = _commit_dir(app, issue, identity, sha)
    checks = (read_json(commit_dir / "github-checks.json") or {}).get("outcome") == "READY"
    analyzers = get_decision(session, "analyzers", sha)
    findings = _load_analyzer_findings(app, issue, identity, sha)
    unaddressed = any(item.get("attention") == "unaddressed" for item in findings)
    analyzers_clear = not unaddressed and (
        not any(item.get("attention") in {"dispositioned", "resolved"} for item in findings)
        or (analyzers or {}).get("choice") in {"accept_dispositions", "override"}
    )
    if (analyzers or {}).get("choice") == "override":
        analyzers_clear = True
    human = read_json(commit_dir / "review" / "human-review.json") or {}
    machine = (read_json(commit_dir / "review" / "findings.json") or {}).get("findings") or []
    open_must_fix = False
    if human and not human.get("rejected_review"):
        try:
            merged = apply_human_decisions(machine, human)
        except WorkflowError:
            merged = []
        open_must_fix = any(item.get("must_fix") and item.get("decision") != "reject" for item in merged)
    publication = read_json(commit_dir / "review" / "publication.json") or {}
    human_done = bool(human) and not human.get("rejected_review") and publication.get("status") in {"success", "skipped"}
    results = read_json(commit_dir / "testing" / "test-results.json") or {}
    environment = read_json(commit_dir / "testing" / "environment.json") or {}
    testing_passed = results.get("result") == "pass" and results.get("sha") == sha
    evidence = (
        testing_passed
        and results.get("digest")
        and results.get("digest") == environment.get("digest")
        and environment.get("sha") == sha
    )
    return disposition_checklist(
        {
            "sha_matches": True,
            "checks_passed": checks,
            "analyzers_clear": analyzers_clear,
            "open_must_fix": open_must_fix,
            "human_review": human_done,
            "testing_passed": testing_passed,
            "evidence_matches": bool(evidence),
        }
    )


def _after_publication(app: App, issue: str, sha: str, receipt: dict[str, Any], *, skipped: bool) -> StepResult:
    event = receipt.get("event")
    prefix = "GitHub review was already published." if skipped and receipt.get("status") == "success" else "Recorded the GitHub review."
    if event == "REQUEST_CHANGES":
        return StepResult(
            step="human-review",
            outcome=Outcome.ACTION_REQUIRED,
            summary=prefix + " Must-fix feedback was published. Authorize returning the issue when ready.",
            recommendation=app.config.in_progress_status,
            next_command=f"review-ticket {issue} jira transition --status {json_quote(app.config.in_progress_status)} --yes",
            details={"completed_step": "human-review", "github_review_id": receipt.get("github_review_id")},
        )
    summary = prefix + " The issue stays in Peer Review."
    if event == "APPROVE":
        summary = prefix + " Continue with local testing. A GitHub approval is not a Jira transition."
    return StepResult(
        step="virtualization",
        outcome=Outcome.READY,
        summary=summary,
        next_command=f"review-ticket {issue} test prepare",
        details={"completed_step": "human-review", "github_review_id": receipt.get("github_review_id"), "sha": sha},
    )


def _publication_gate(app: App, issue: str, sha: str, publication: dict[str, Any]) -> StepResult | None:
    event = publication.get("event")
    if event == "REQUEST_CHANGES":
        if _transition_recorded(app, issue, app.config.in_progress_status, sha):
            return StepResult(
                step="human-review",
                outcome=Outcome.COMPLETE,
                summary=f"{issue} was returned to {app.config.in_progress_status}.",
                jira_mutated=True,
                details={"completed_step": "human-review"},
            )
        return StepResult(
            step="human-review",
            outcome=Outcome.ACTION_REQUIRED,
            summary="Changes were requested. Authorize the Jira transition when the comment is enough.",
            recommendation=app.config.in_progress_status,
            next_command=f"review-ticket {issue} jira transition --status {json_quote(app.config.in_progress_status)} --yes",
        )
    return None


def _matching_remote_review(
    app: App,
    owner: str,
    repo: str,
    number: int,
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    expected = GITHUB_STATE[payload["event"]]
    for review in list_reviews(app.runner, app.config, owner, repo, number):
        if (
            review.get("commit_id") == payload["commit_id"]
            and review.get("body") == payload["body"]
            and review.get("state") == expected
        ):
            return review
    return None


def _receipt_from_remote(review: dict[str, Any], digest: str, sha: str, event: str) -> dict[str, Any]:
    return {
        "status": "success",
        "fingerprint": digest,
        "sha": sha,
        "event": event,
        "github_review_id": review.get("id"),
        "html_url": review.get("html_url"),
        "comment_ids": [],
        "comment_urls": [],
        "published_at": iso_now(),
        "adopted_existing": True,
    }


def _publication_preview(owner: str, repo: str, number: int, payload: dict[str, Any]) -> str:
    lines = [
        f"Publish a GitHub review on {owner}/{repo}#{number}.",
        f"Event: {payload['event']}",
        f"Commit: {payload['commit_id']}",
        f"Inline comments: {len(payload.get('comments') or [])}",
        "",
        payload["body"].rstrip(),
        "",
    ]
    for comment in payload.get("comments") or []:
        lines.append(f"- {comment['path']}:{comment['line']} ({comment['side']})")
    return "\n".join(lines) + "\n"


def _desired_profile(app: App, issue: str, pr: dict[str, Any], sha: str) -> dict[str, Any]:
    image = app.config.image or f"ghcr.io/{pr['owner']}/{pr['repo']}:{pr.get('head_branch') or 'latest'}"
    project = re.sub(r"[^a-z0-9-]+", "-", f"review-{issue}-{pr['number']}".lower()).strip("-")
    return {
        "version": 1,
        "issue": issue,
        "repository": f"{pr['owner']}/{pr['repo']}",
        "pr": pr["number"],
        "branch": pr.get("head_branch"),
        "sha": sha,
        "image": image,
        "ports": list(app.config.ports),
        "project_name": project,
    }


def _write_profile(app: App, profile_dir: Path, desired: dict[str, Any], *, issue: str, sha: str, branch: str) -> str:
    path = profile_dir / "profile.json"
    current = read_json(path)
    if app.config.virt_prepare_command and not _profile_matches(current, desired):
        mapping = {
            "profile": str(profile_dir),
            "issue": issue,
            "sha": sha,
            "branch": branch,
            "image": desired["image"],
        }
        result = run_external(app.runner, app.config.virt_prepare_command, mapping)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise ToolError(detail or "Virtualization prepare command failed.", returncode=result.returncode)
        current = read_json(path)
    if _profile_matches(current, desired):
        return "reused"
    action = "regenerated" if current else "created"
    profile_dir.mkdir(parents=True, exist_ok=True)
    write_json(path, desired)
    write_text(profile_dir / "docker-compose.yml", _compose_yaml(desired))
    return action


def _profile_matches(current: dict[str, Any] | None, desired: dict[str, Any]) -> bool:
    if not current:
        return False
    return {key: current.get(key) for key in PROFILE_KEYS} == {key: desired.get(key) for key in PROFILE_KEYS}


def _compose_yaml(profile: dict[str, Any]) -> str:
    lines = ["services:", "  app:", f"    image: {profile['image']}", "    ports:"]
    for port in profile.get("ports") or []:
        lines.append(f'      - "{port}"')
    return "\n".join(lines) + "\n"


def _ensure_test_plan(app: App, session: dict[str, Any]) -> Path:
    issue = session["issue"]
    identity = _require_identity(session)
    sha = session["active_sha"]
    testing_dir = _commit_dir(app, issue, identity, sha) / "testing"
    path = testing_dir / "test-plan.md"
    normalized = read_json(app.store.issue_dir(issue) / "issue.json") or {}
    findings = (read_json(_review_dir(app, issue, identity, sha) / "findings.json") or {}).get("findings") or []
    prior: list[str] = []
    commits = app.store.pr_dir(issue, *identity) / "commits"
    if commits.exists():
        for directory in commits.iterdir():
            if not directory.is_dir() or directory.name == sha:
                continue
            previous = read_json(directory / "testing" / "test-results.json") or {}
            if previous.get("result") == "fail":
                prior.append(f"{directory.name[:12]}: {previous.get('notes') or previous.get('failure_kind')}")
    write_text(path, test_plan(issue=normalized, sha=sha, findings=findings, prior_failures=prior))
    return path


def _store_evidence(testing_dir: Path, paths: list[str]) -> list[str]:
    stored: list[str] = []
    for raw in paths:
        source = Path(raw)
        if not source.is_file():
            raise WorkflowError(f"Evidence file does not exist: {source}")
        suffix = source.suffix.lower()
        if suffix in IMAGE_SUFFIXES:
            bucket = "screenshots"
        elif suffix in VIDEO_SUFFIXES:
            bucket = "videos"
        else:
            bucket = "logs"
        dest_dir = testing_dir / "evidence" / bucket
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / source.name
        dest.write_bytes(source.read_bytes())
        stored.append(str(dest))
    return stored


def _thread_finding(thread: dict[str, Any], config: Config) -> dict[str, Any] | None:
    nodes = ((thread.get("comments") or {}).get("nodes")) or thread.get("comments") or []
    if isinstance(nodes, dict):
        nodes = nodes.get("nodes") or []
    if not nodes:
        return None
    first = nodes[0]
    login = _login(first)
    body = str(first.get("body") or "")
    source = _analyzer_source(login, body, config)
    if source is None:
        return None
    humans = [node for node in nodes[1:] if not _is_bot(_login(node), config)]
    if humans:
        attention = "dispositioned"
        resolution = "dispositioned"
        disposition = str(humans[-1].get("body") or "")
    elif thread.get("isResolved"):
        attention = "resolved"
        resolution = "resolved"
        disposition = None
    elif thread.get("isOutdated"):
        attention = "resolved"
        resolution = "outdated"
        disposition = None
    else:
        attention = "unaddressed"
        resolution = "unresolved"
        disposition = None
    commit = ((first.get("commit") or {}).get("oid")) if isinstance(first.get("commit"), dict) else None
    return {
        "source": source,
        "id": f"{source}:{thread.get('id')}",
        "path": thread.get("path"),
        "line": thread.get("line"),
        "url": first.get("url"),
        "body": body,
        "resolution": resolution,
        "attention": attention,
        "disposition": disposition,
        "commit": commit,
    }


def _alert_finding(alert: dict[str, Any]) -> dict[str, Any]:
    state = str(alert.get("state") or "")
    if state == "open":
        attention = "unaddressed"
    elif state == "dismissed":
        attention = "dispositioned"
    else:
        attention = "resolved"
    instance = alert.get("most_recent_instance") or {}
    location = instance.get("location") or {}
    message = instance.get("message")
    if isinstance(message, dict):
        message = message.get("text")
    rule = alert.get("rule") or {}
    body = str(message or rule.get("description") or rule.get("id") or "CodeQL alert")
    return {
        "source": "codeql",
        "id": f"codeql:{alert.get('number')}",
        "path": location.get("path"),
        "line": location.get("start_line"),
        "url": alert.get("html_url"),
        "body": body,
        "resolution": state,
        "attention": attention,
        "disposition": alert.get("dismissed_reason"),
        "commit": instance.get("commit_sha"),
    }


def _analyzer_source(login: str, body: str, config: Config) -> str | None:
    if _matches(login, config.codeql_authors) or "codeql" in login.casefold():
        return "codeql"
    if _matches(login, config.bugbot_authors) or "bugbot" in login.casefold():
        return "bugbot"
    head = body.lstrip()[:80].casefold()
    if head.startswith("<!-- bugbot") or head.startswith("bugbot"):
        return "bugbot"
    return None


def _matches(login: str, names: list[str]) -> bool:
    folded = login.casefold()
    return any(folded == name.casefold() for name in names)


def _is_bot(login: str, config: Config) -> bool:
    folded = login.casefold()
    if folded.endswith("[bot]"):
        return True
    return _matches(login, config.bugbot_authors + config.codeql_authors)


def _login(comment: dict[str, Any]) -> str:
    author = comment.get("author")
    if isinstance(author, dict):
        return str(author.get("login") or "")
    return str(author or "")


def _load_analyzer_findings(app: App, issue: str, identity: tuple[str, str, int], sha: str) -> list[dict[str, Any]]:
    commit_dir = _commit_dir(app, issue, identity, sha)
    bugbot = (read_json(commit_dir / "bugbot-findings.json") or {}).get("findings") or []
    codeql = (read_json(commit_dir / "codeql-findings.json") or {}).get("findings") or []
    return list(bugbot) + list(codeql)


def _load_pr(app: App, issue: str, identity: tuple[str, str, int]) -> dict[str, Any]:
    path = app.store.pr_dir(issue, *identity) / "pr.json"
    pr = read_json(path)
    if not pr:
        raise WorkflowError("Pull request details are not stored yet.")
    return pr


def _selected(session: dict[str, Any]) -> tuple[str, str, int] | None:
    active = session.get("active_pr")
    if not active:
        return None
    return parse_pr_ref(active)


def _require_identity(session: dict[str, Any]) -> tuple[str, str, int]:
    identity = _selected(session)
    if identity is None or not session.get("active_sha"):
        raise WorkflowError("This command needs a selected pull request and SHA. Run the review entry point first.")
    return identity


def _require_review_session(app: App, issue: str) -> dict[str, Any]:
    session = app.store.ensure_session(issue)
    _require_identity(session)
    return session


def _commit_dir(app: App, issue: str, identity: tuple[str, str, int], sha: str) -> Path:
    return app.store.commit_dir(issue, identity[0], identity[1], identity[2], sha)


def _maybe_commit_dir(app: App, session: dict[str, Any]) -> Path | None:
    identity = _selected(session)
    sha = session.get("active_sha")
    if identity is None or not sha:
        return None
    return _commit_dir(app, session["issue"], identity, sha)


def _review_dir(app: App, issue: str, identity: tuple[str, str, int], sha: str) -> Path:
    return _commit_dir(app, issue, identity, sha) / "review"


def _write_return_draft(app: App, issue: str, *, reason: str, notes: str, links: list[str]) -> Path:
    path = app.store.issue_dir(issue) / "return-comment.md"
    write_text(path, return_comment(issue=issue, reason=reason, notes=notes, links=links))
    return path


def _append_note(app: App, issue: str, text: str) -> None:
    if not text.strip():
        return
    path = app.store.issue_dir(issue) / "reviewer-notes.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Reviewer notes\n"
    write_text(path, existing.rstrip() + f"\n\n## {iso_now()}\n\n{text.strip()}\n")


def _archive_review(review_dir: Path) -> None:
    names = [
        "findings.json",
        "reviewer-report.md",
        "proposed-review.json",
        "human-review.json",
        "reconciliation.json",
        "reviewer-output.json",
        "publish-payload.json",
    ]
    if not any((review_dir / name).exists() for name in names):
        return
    attempts = review_dir / "attempts"
    attempts.mkdir(parents=True, exist_ok=True)
    count = len([item for item in attempts.iterdir() if item.is_dir()])
    dest = attempts / f"{count + 1:03d}"
    dest.mkdir()
    for name in names:
        source = review_dir / name
        if source.exists():
            source.replace(dest / name)


def _transition_recorded(app: App, issue: str, status: str, sha: str) -> bool:
    key = fingerprint({"kind": "jira.transition", "issue": issue, "status": status, "sha": sha})
    return app.store.successful_action(issue, key) is not None


def _journal(
    app: App,
    issue: str,
    sha_dir: Path | None,
    kind: str,
    key: str,
    status: str,
    receipt: dict[str, Any],
    sha: str,
) -> None:
    app.store.record_action(
        issue,
        {
            "at": iso_now(),
            "kind": kind,
            "key": key,
            "status": status,
            "issue": issue,
            "sha": sha,
            "receipt": receipt,
        },
        sha_dir=sha_dir,
    )


def _blocked(step: str, message: str) -> StepResult:
    return StepResult(step=step, outcome=Outcome.BLOCKED, summary=message, recommendation=None)


def _prompt_notes(app: App) -> str | None:
    reader = app.input_fn or input
    answer = reader("Accept testing notes? [a]ccept / [r]eject / [q]uit: ").strip().lower()
    if answer in {"a", "accept"}:
        return "accept"
    if answer in {"r", "reject"}:
        return "reject"
    return None


def _render(app: App, session: dict[str, Any], result: StepResult) -> None:
    lines = [f"issue: {session.get('issue')}"]
    if session.get("active_pr"):
        lines.append(f"pr: {session['active_pr']} @ {short_sha(session.get('active_sha') or '')}")
    lines.extend([f"step: {result.step}", f"outcome: {result.outcome.value}", "", result.summary])
    if result.recommendation:
        lines.append(f"recommendation: {result.recommendation}")
    if not result.jira_mutated and result.outcome in {Outcome.WAITING, Outcome.ACTION_REQUIRED, Outcome.BLOCKED}:
        lines.append("No Jira transition was performed.")
    if result.next_command:
        lines.append(f"next: {result.next_command}")
    if result.report_path:
        lines.append(f"report: {result.report_path}")
    app.write("\n".join(lines).rstrip() + "\n")


def json_quote(value: str) -> str:
    if re.search(r"\s", value):
        return "'" + value.replace("'", "'\\''") + "'"
    return value
