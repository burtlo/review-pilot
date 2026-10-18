"""Local PR readiness / analyzer gate model (spec §6). No network I/O."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from review_ticket.config import Config
from review_ticket.models import Outcome
from review_ticket.policy import Check, evaluate_analyzers, evaluate_readiness, outcome_is_worse
from review_ticket.storage import Store, read_json
from review_ticket.status_projection import pr_url_for_ref
from review_ticket.util import parse_pr_ref, require_issue_key, short_sha


@dataclass(frozen=True)
class PrReadinessRow:
    ref: str
    sha: str
    url: str
    checks_outcome: Outcome
    checks_summary: str
    analyzer_outcome: Outcome
    analyzer_summary: str
    readiness_detail_path: str | None
    analyzers_detail_path: str | None
    gate_ready: bool
    needs_attention: bool


@dataclass(frozen=True)
class ReadinessAttentionItem:
    ref: str
    sha: str
    url: str
    lines: tuple[str, ...]
    links: tuple[str, ...]


@dataclass(frozen=True)
class ReadinessGateProjection:
    issue: str
    has_prs: bool
    no_pr_guidance: str | None
    ticket_outcome: Outcome
    ticket_summary: str
    gate_approvable: bool
    waiting: bool
    pr_rows: tuple[PrReadinessRow, ...]
    attention: tuple[ReadinessAttentionItem, ...]
    detail_markdown: str


def project_readiness_gate(store: Store, issue: str, config: Config) -> ReadinessGateProjection:
    issue_key = require_issue_key(issue)
    session_path = store.issue_dir(issue_key) / "session.json"
    session = read_json(session_path) or {}
    refs = _active_pr_refs(session)
    if not refs:
        guidance = _no_pr_guidance(config, issue_key)
        return ReadinessGateProjection(
            issue=issue_key,
            has_prs=False,
            no_pr_guidance=guidance,
            ticket_outcome=Outcome.ACTION_REQUIRED,
            ticket_summary=guidance,
            gate_approvable=False,
            waiting=False,
            pr_rows=(),
            attention=(),
            detail_markdown=f"## No pull request selected\n\n{guidance}\n",
        )

    rows: list[PrReadinessRow] = []
    attention: list[ReadinessAttentionItem] = []
    for ref in refs:
        owner, repo, number = parse_pr_ref(ref)
        sha = _stored_sha(session, ref)
        identity = (owner, repo, number)
        commit_dir = store.commit_dir(issue_key, owner, repo, number, sha) if sha else None
        checks_payload = read_json(commit_dir / "github-checks.json") if commit_dir else {}
        checks_outcome, checks_summary = _checks_view(session, checks_payload, config, sha)
        findings = _load_findings(commit_dir) if commit_dir else []
        analyzer_decision = (session.get("decisions") or {}).get("analyzers") or {}
        if isinstance(analyzer_decision, dict) and "choice" in analyzer_decision:
            decision = analyzer_decision.get("choice")
        else:
            decision = (analyzer_decision.get(sha) or {}).get("choice") if isinstance(analyzer_decision, dict) else None
        analyzer_outcome, analyzer_summary, _ = evaluate_analyzers(
            findings,
            decision,
            in_progress_status=config.in_progress_status,
        )
        gate_ready = _pr_gate_ready(session, sha, checks_outcome, analyzer_outcome, findings, decision)
        needs = not gate_ready and checks_outcome != Outcome.WAITING and checks_outcome != Outcome.BLOCKED
        readiness_path = str(commit_dir / "readiness.md") if commit_dir and (commit_dir / "readiness.md").exists() else None
        analyzers_path = str(commit_dir / "analyzers.md") if commit_dir and (commit_dir / "analyzers.md").exists() else None
        row = PrReadinessRow(
            ref=ref,
            sha=sha,
            url=pr_url_for_ref(store, issue_key, ref),
            checks_outcome=checks_outcome,
            checks_summary=checks_summary,
            analyzer_outcome=analyzer_outcome,
            analyzer_summary=analyzer_summary,
            readiness_detail_path=readiness_path,
            analyzers_detail_path=analyzers_path,
            gate_ready=gate_ready,
            needs_attention=needs,
        )
        rows.append(row)
        if needs:
            attention.append(_attention_item(row, findings, checks_outcome, analyzer_outcome))

    ticket_outcome = Outcome.READY
    ticket_summary = "All tracked pull requests passed readiness and analyzer checks."
    for row in rows:
        combined = _combined_outcome(row.checks_outcome, row.analyzer_outcome)
        if outcome_is_worse(combined, ticket_outcome):
            ticket_outcome = combined
            ticket_summary = f"{row.ref}: {row.checks_summary}; analyzers: {row.analyzer_summary}"
    waiting = any(row.checks_outcome == Outcome.WAITING for row in rows)
    if waiting:
        ticket_outcome = Outcome.WAITING
        ticket_summary = "Required checks are still running on at least one pull request."
    gate_approvable = bool(rows) and all(row.gate_ready for row in rows) and not waiting
    detail = _issue_detail_markdown(store, issue_key, rows)
    return ReadinessGateProjection(
        issue=issue_key,
        has_prs=True,
        no_pr_guidance=None,
        ticket_outcome=ticket_outcome,
        ticket_summary=ticket_summary,
        gate_approvable=gate_approvable,
        waiting=waiting,
        pr_rows=tuple(rows),
        attention=tuple(attention),
        detail_markdown=detail,
    )


def _active_pr_refs(session: dict[str, Any]) -> list[str]:
    refs = [str(item) for item in session.get("active_prs") or [] if item]
    if not refs and session.get("active_pr"):
        refs = [str(session["active_pr"])]
    return refs


def _stored_sha(session: dict[str, Any], ref: str) -> str:
    pr_shas: dict[str, str] = session.get("pr_shas") or {}
    sha = pr_shas.get(ref)
    if not sha and ref == session.get("active_pr"):
        sha = session.get("active_sha")
    return str(sha or "")


def _no_pr_guidance(config: Config, issue: str) -> str:
    repo = config.github_repo
    if repo:
        return (
            f"No open pull request references {issue} in {repo}. "
            f"Run `review-ticket {issue} pr select owner/repo#number` or update github_repo in .review-ticket.yaml."
        )
    return (
        f"No open pull request references {issue}. "
        f"Run `review-ticket {issue} pr select owner/repo#number` after linking a PR in Jira."
    )


def _checks_from_payload(payload: dict[str, Any], config: Config) -> tuple[list[Check], list[str]]:
    checks: list[Check] = []
    for item in payload.get("checks") or []:
        checks.append(
            Check(
                name=str(item.get("name") or ""),
                bucket=str(item.get("bucket") or "missing"),
                state=str(item.get("state") or ""),
                link=str(item.get("link") or ""),
                required=bool(item.get("required")),
                kind=str(item.get("kind") or "other"),
            )
        )
    required_names = {str(item.get("name") or "") for item in payload.get("required_raw") or []}
    for name in config.required_checks:
        if name not in {check.name for check in checks}:
            checks.append(
                Check(
                    name=name,
                    bucket="missing",
                    required=True,
                    kind="other",
                )
            )
    missing_analyzers: list[str] = []
    if config.require_analyzers:
        for analyzer in config.analyzer_checks:
            required_on_pr = any(analyzer.casefold() in req.casefold() for req in required_names)
            if not required_on_pr:
                continue
            if not any(analyzer.casefold() in check.name.casefold() for check in checks):
                missing_analyzers.append(analyzer)
    return checks, missing_analyzers


def _checks_view(
    session: dict[str, Any],
    payload: dict[str, Any],
    config: Config,
    sha: str,
) -> tuple[Outcome, str]:
    if not payload:
        return Outcome.REVIEW_DECISION, "Checks have not been captured for this SHA yet."
    stored = payload.get("outcome")
    if stored and not payload.get("checks"):
        return Outcome(str(stored)), str(payload.get("summary") or stored)
    checks, missing_analyzers = _checks_from_payload(payload, config)
    accepted_checks = _decision_accepted(session, "missing_checks", sha)
    accepted_analyzers = _decision_accepted(session, "missing_analyzers", sha)
    readiness = evaluate_readiness(
        checks,
        missing_analyzers=missing_analyzers,
        service_unavailable=None,
        accepted_missing_checks=accepted_checks,
        accepted_missing_analyzers=accepted_analyzers,
        in_progress_status=config.in_progress_status,
    )
    if readiness.outcome == Outcome.READY and not any(check.required for check in checks) and not accepted_checks:
        return (
            Outcome.REVIEW_DECISION,
            "No required checks were reported. Confirm branch protection before continuing.",
        )
    return readiness.outcome, readiness.summary


def _decision_accepted(session: dict[str, Any], name: str, sha: str) -> bool:
    bucket = (session.get("decisions") or {}).get(name)
    if not isinstance(bucket, dict):
        return False
    if bucket.get("choice") == "accept":
        return True
    entry = bucket.get(sha)
    return isinstance(entry, dict) and entry.get("choice") == "accept"


def _load_findings(commit_dir) -> list[dict[str, Any]]:
    bugbot = (read_json(commit_dir / "bugbot-findings.json") or {}).get("findings") or []
    codeql = (read_json(commit_dir / "codeql-findings.json") or {}).get("findings") or []
    return list(bugbot) + list(codeql)


def _pr_gate_ready(
    session: dict[str, Any],
    sha: str,
    checks_outcome: Outcome,
    analyzer_outcome: Outcome,
    findings: list[dict[str, Any]],
    analyzer_decision: str | None,
) -> bool:
    if checks_outcome == Outcome.WAITING or checks_outcome == Outcome.BLOCKED:
        return False
    if checks_outcome == Outcome.ACTION_REQUIRED:
        return False
    if checks_outcome == Outcome.REVIEW_DECISION:
        if not (_decision_accepted(session, "missing_checks", sha) or _decision_accepted(session, "missing_analyzers", sha)):
            return False
    if analyzer_outcome == Outcome.ACTION_REQUIRED:
        if analyzer_decision in {"override", "accept_dispositions"}:
            return True
        return False
    if analyzer_outcome == Outcome.REVIEW_DECISION:
        if analyzer_decision in {"accept_dispositions", "override"}:
            return True
        if _decision_accepted(session, "missing_analyzers", sha):
            return checks_outcome in {Outcome.READY, Outcome.REVIEW_DECISION}
        return False
    if analyzer_outcome == Outcome.BLOCKED:
        return False
    return checks_outcome in {Outcome.READY, Outcome.REVIEW_DECISION}


def _combined_outcome(left: Outcome, right: Outcome) -> Outcome:
    return left if outcome_is_worse(left, right) else right


def _attention_item(
    row: PrReadinessRow,
    findings: list[dict[str, Any]],
    checks_outcome: Outcome,
    analyzer_outcome: Outcome,
) -> ReadinessAttentionItem:
    lines: list[str] = []
    links: list[str] = []
    if checks_outcome not in {Outcome.READY, Outcome.WAITING}:
        lines.append(f"Checks ({checks_outcome.value}): {row.checks_summary}")
    unaddressed = [item for item in findings if item.get("attention") == "unaddressed"]
    for item in unaddressed:
        path = item.get("path") or "general"
        line = item.get("line")
        where = f"{path}:{line}" if line else str(path)
        body = str(item.get("body") or "").strip().splitlines()[0][:180]
        lines.append(f"- {item.get('source', 'analyzer')}: {body} ({where})")
        url = item.get("url")
        if url:
            links.append(str(url))
    if analyzer_outcome == Outcome.REVIEW_DECISION and not unaddressed:
        lines.append(f"Analyzers ({analyzer_outcome.value}): {row.analyzer_summary}")
    return ReadinessAttentionItem(
        ref=row.ref,
        sha=row.sha,
        url=row.url,
        lines=tuple(lines),
        links=tuple(links),
    )


def _issue_detail_markdown(store: Store, issue: str, rows: list[PrReadinessRow]) -> str:
    issue_dir = store.issue_dir(issue)
    combined_readiness = issue_dir / "readiness.md"
    combined_analyzers = issue_dir / "analyzers.md"
    parts: list[str] = []
    if combined_readiness.exists():
        parts.append(combined_readiness.read_text(encoding="utf-8").strip())
    elif combined_analyzers.exists():
        parts.append(combined_analyzers.read_text(encoding="utf-8").strip())
    else:
        for row in rows:
            parts.append(f"## {row.ref} `{short_sha(row.sha)}`")
            if row.readiness_detail_path:
                parts.append(Path(row.readiness_detail_path).read_text(encoding="utf-8").strip())
            if row.analyzers_detail_path:
                parts.append(Path(row.analyzers_detail_path).read_text(encoding="utf-8").strip())
    return "\n\n".join(part for part in parts if part).strip() + "\n"
