"""Deterministic review policy. Human judgment stays outside these functions."""

from __future__ import annotations

from dataclasses import dataclass

from review_ticket.models import Outcome

OUTCOME_SEVERITY: dict[Outcome, int] = {
    Outcome.BLOCKED: 0,
    Outcome.WAITING: 1,
    Outcome.ACTION_REQUIRED: 2,
    Outcome.REVIEW_DECISION: 3,
    Outcome.READY: 4,
    Outcome.COMPLETE: 5,
}


def outcome_is_worse(left: Outcome, right: Outcome) -> bool:
    return OUTCOME_SEVERITY[left] < OUTCOME_SEVERITY[right]


@dataclass
class Check:
    name: str
    bucket: str
    state: str = ""
    link: str = ""
    required: bool = False
    kind: str = "other"


@dataclass
class Readiness:
    outcome: Outcome
    summary: str
    recommendation: str | None = None
    pending: list[str] | None = None
    failed: list[str] | None = None
    missing: list[str] | None = None


def classify_check_name(name: str, analyzer_checks: list[str]) -> str:
    folded = name.casefold()
    for analyzer in analyzer_checks:
        if analyzer.casefold() in folded:
            if "codeql" in analyzer.casefold() or "codeql" in folded:
                return "codeql"
            if "bugbot" in analyzer.casefold() or "bugbot" in folded:
                return "bugbot"
            return "analyzer"
    if "codeql" in folded:
        return "codeql"
    if "bugbot" in folded:
        return "bugbot"
    return "other"


def bucket_of(raw: dict) -> str:
    bucket = str(raw.get("bucket") or "").lower()
    if bucket in {"pass", "fail", "pending", "skipping", "cancel"}:
        return bucket
    state = str(raw.get("state") or raw.get("conclusion") or raw.get("status") or "").upper()
    if state in {"SUCCESS", "NEUTRAL", "SKIPPED", "COMPLETED"} and str(raw.get("conclusion") or state).upper() != "FAILURE":
        conclusion = str(raw.get("conclusion") or state).upper()
        if conclusion in {"FAILURE", "TIMED_OUT", "STARTUP_FAILURE", "CANCELLED"}:
            return "cancel" if conclusion == "CANCELLED" else "fail"
        if conclusion == "SKIPPED" or state == "SKIPPED":
            return "skipping"
        if conclusion in {"", "SUCCESS", "NEUTRAL", "COMPLETED"}:
            return "pass"
    if state in {"FAILURE", "ERROR", "TIMED_OUT", "STARTUP_FAILURE"}:
        return "fail"
    if state in {"CANCELLED"}:
        return "cancel"
    if state in {"PENDING", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED", "EXPECTED", "STALE"}:
        return "pending"
    status = str(raw.get("status") or "").upper()
    if status in {"QUEUED", "IN_PROGRESS", "PENDING", "WAITING"}:
        return "pending"
    return "pending"


def evaluate_readiness(
    checks: list[Check],
    *,
    missing_analyzers: list[str],
    service_unavailable: str | None,
    accepted_missing_checks: bool,
    accepted_missing_analyzers: bool,
    in_progress_status: str,
) -> Readiness:
    if service_unavailable:
        return Readiness(
            outcome=Outcome.BLOCKED,
            summary=service_unavailable,
            recommendation=None,
        )
    pending = [check.name for check in checks if check.required and check.bucket == "pending"]
    if pending:
        return Readiness(
            outcome=Outcome.WAITING,
            summary="Required checks are still running: " + ", ".join(pending) + ".",
            pending=pending,
        )
    failed = [check.name for check in checks if check.required and check.bucket in {"fail", "cancel"}]
    if failed:
        return Readiness(
            outcome=Outcome.ACTION_REQUIRED,
            summary="Required checks failed: " + ", ".join(failed) + ".",
            recommendation=in_progress_status,
            failed=failed,
        )
    missing_required = [check.name for check in checks if check.required and check.bucket == "missing"]
    if missing_required and not accepted_missing_checks:
        return Readiness(
            outcome=Outcome.REVIEW_DECISION,
            summary="Required checks were not reported: " + ", ".join(missing_required) + ".",
            missing=missing_required,
        )
    if missing_analyzers and not accepted_missing_analyzers:
        return Readiness(
            outcome=Outcome.REVIEW_DECISION,
            summary="Analyzer checks were not reported: " + ", ".join(missing_analyzers) + ".",
            missing=missing_analyzers,
        )
    return Readiness(outcome=Outcome.READY, summary="Required checks passed.")


def evaluate_analyzers(
    findings: list[dict],
    decision: str | None,
    *,
    in_progress_status: str,
) -> tuple[Outcome, str, str | None]:
    unaddressed = [item for item in findings if item.get("attention") == "unaddressed"]
    dispositioned = [item for item in findings if item.get("attention") == "dispositioned"]
    resolved = [item for item in findings if item.get("attention") == "resolved"]
    if decision == "return":
        return (
            Outcome.ACTION_REQUIRED,
            "Reviewer chose to return the issue for analyzer triage.",
            in_progress_status,
        )
    if decision == "override":
        return (
            Outcome.READY,
            "Reviewer overrode outstanding analyzer findings.",
            None,
        )
    if unaddressed and decision != "override":
        return (
            Outcome.ACTION_REQUIRED,
            f"{len(unaddressed)} analyzer finding(s) have no developer disposition.",
            in_progress_status,
        )
    if decision == "accept_dispositions":
        return (
            Outcome.READY,
            "Reviewer accepted developer dispositions. Resolved threads are context, not proof.",
            None,
        )
    if dispositioned or resolved:
        return (
            Outcome.REVIEW_DECISION,
            "Analyzer findings have developer attention. Acknowledge them before continuing. "
            "A resolved thread is not proof the code is correct.",
            None,
        )
    return (Outcome.READY, "No outstanding Bugbot or CodeQL findings.", None)


def testing_outcome(
    result: str,
    kind: str | None,
    *,
    in_progress_status: str,
) -> tuple[Outcome, str, str | None]:
    if result == "pass":
        return (Outcome.READY, "Recorded functional tests passed.", None)
    if result == "blocked" or kind == "environment":
        return (
            Outcome.BLOCKED,
            "Testing stopped because the environment or tooling failed. The implementation was not marked defective.",
            None,
        )
    if result == "fail" and kind == "implementation":
        return (
            Outcome.ACTION_REQUIRED,
            "Functional testing found an implementation failure.",
            in_progress_status,
        )
    return (
        Outcome.REVIEW_DECISION,
        "Record whether the failure is an implementation defect or an environment problem.",
        None,
    )


def suggest_event(findings: list[dict]) -> str:
    accepted = [item for item in findings if item.get("decision", "accept") != "reject"]
    if any(item.get("must_fix") for item in accepted):
        return "REQUEST_CHANGES"
    return "COMMENT"


def disposition_checklist(facts: dict) -> list[dict]:
    items = [
        (
            "sha",
            "Reviewed SHA matches the pull request HEAD.",
            bool(facts.get("sha_matches")),
        ),
        (
            "checks",
            "Required GitHub checks passed.",
            bool(facts.get("checks_passed")),
        ),
        (
            "analyzers",
            "Bugbot and CodeQL findings are addressed or explicitly overridden.",
            bool(facts.get("analyzers_clear")),
        ),
        (
            "must_fix",
            "No unresolved must-fix findings remain in the accepted review.",
            not facts.get("open_must_fix"),
        ),
        (
            "human",
            "A human reviewed the automated findings.",
            bool(facts.get("human_review")),
        ),
        (
            "testing",
            "Required local testing passed.",
            bool(facts.get("testing_passed")),
        ),
        (
            "evidence",
            "Testing evidence is for this SHA and records the Docker image identity.",
            bool(facts.get("evidence_matches")),
        ),
    ]
    return [{"id": key, "detail": detail, "ok": ok} for key, detail, ok in items]
