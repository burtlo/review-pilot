"""Command line entry for the manual peer-review workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from review_ticket.config import Config, load_config
from review_ticket.logutil import configure_logging
from review_ticket.models import AuthorizationDenied, Outcome, StepResult, WorkflowError
from review_ticket.runner import Runner, SubprocessRunner
from review_ticket.storage import read_json
from review_ticket.util import require_issue_key
from review_ticket.workflow import (
    App,
    apply_review,
    assess,
    decide_analyzers,
    decide_notes,
    draft_bug,
    fetch_image,
    import_review,
    jira_comment,
    jira_transition,
    launch_environment,
    post_comment,
    prepare_profile,
    publish_review,
    record_disposition,
    record_tests,
    resume,
    run_review,
    select_all_prs,
    select_pr,
    show_status,
    write_test_plan_command,
)


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner | None = None,
    config: Config | None = None,
    interactive: bool | None = None,
    stdout=None,
    stderr=None,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        require_issue_key(args.issue)
    except ValueError as exc:
        print(str(exc), file=stderr or sys.stderr)
        return 2
    resolved_config = config or load_config()
    configure_logging(resolved_config.log_level, stream=stderr or sys.stderr)
    app = App(
        config=resolved_config,
        runner=runner or SubprocessRunner(),
        interactive=sys.stdin.isatty() if interactive is None else interactive,
        refresh=bool(getattr(args, "refresh", False)),
        stdout=stdout,
        stderr=stderr,
    )
    try:
        result = dispatch(app, args)
    except AuthorizationDenied as exc:
        app.error(str(exc))
        return 3
    except (WorkflowError, OSError, json.JSONDecodeError) as exc:
        app.error(str(exc))
        return 2
    if isinstance(result, StepResult) and result.outcome == Outcome.BLOCKED:
        return 2
    return 0


def dispatch(app: App, args: argparse.Namespace) -> StepResult:
    issue = args.issue
    command = args.command
    if command is None:
        return resume(app, issue)
    if command == "status":
        return show_status(app, issue)
    if command == "assess":
        return assess(
            app,
            issue,
            accept_missing_checks=args.accept_missing_checks,
            accept_missing_analyzers=args.accept_missing_analyzers,
        )
    if command == "notes":
        choice = "accept" if args.accept else "reject"
        return decide_notes(app, issue, choice, args.notes or "", revise=args.revise)
    if command == "run-review":
        return run_review(app, issue, revise=args.revise)
    if command == "import-review":
        return import_review(app, issue, Path(args.file), revise=args.revise)
    if command == "attach":
        return run_review_attach(app, issue, revise=args.revise)
    if command == "review":
        return _review(app, issue, args)
    if command == "publish-review":
        return publish_review(app, issue, yes=args.yes, event=args.event, skip=args.skip)
    if command == "analyzers":
        if args.accept_dispositions:
            choice = "accept_dispositions"
        elif args.override:
            choice = "override"
        else:
            choice = "return"
        return decide_analyzers(app, issue, choice, args.notes or "", revise=args.revise)
    if command == "pr":
        return _pr(app, issue, args)
    if command == "jira":
        return _jira(app, issue, args)
    if command == "test":
        return _test(app, issue, args)
    if command == "bug":
        body = _body(args)
        return draft_bug(app, issue, summary=args.summary, body=body, yes=args.yes)
    if command == "disposition":
        return record_disposition(
            app,
            issue,
            choice=args.choice,
            notes=args.notes or "",
            override=args.override,
            revise=args.revise,
        )
    raise WorkflowError(f"Unknown command {command}.")


def run_review_attach(app: App, issue: str, *, revise: bool) -> StepResult:
    if not app.interactive:
        raise WorkflowError(
            "attach requires an interactive terminal (TTY). "
            "Use `notes`, `jira comment`, `jira transition`, or `review apply --file` instead."
        )
    issue = require_issue_key(issue)
    session_path = app.store.issue_dir(issue) / "session.json"
    session = read_json(session_path)
    if not session:
        raise WorkflowError(
            f"No review session exists for {issue}. Run `review-ticket {issue}` first."
        )

    from review_ticket.tui import ReviewTicketApp

    ReviewTicketApp(
        store=app.store,
        issue=issue,
        workflow_app=app,
        revise=revise,
    ).run()
    return StepResult(
        step="human-review",
        outcome=Outcome.COMPLETE,
        summary="Review attach session closed.",
    )


def _review(app: App, issue: str, args: argparse.Namespace) -> StepResult:
    if args.review_cmd == "show":
        return show_status(app, issue)
    if args.file and (args.accept_all or args.finding or args.reject_automated):
        raise WorkflowError("Use either --file or the individual review flags, not both.")
    if args.file:
        human = json.loads(Path(args.file).read_text(encoding="utf-8"))
    else:
        human = _human_from_flags(app, issue, args)
    return apply_review(app, issue, human, revise=args.revise)


def _human_from_flags(app: App, issue: str, args: argparse.Namespace) -> dict:
    if args.reject_automated:
        return {
            "rejected_review": True,
            "findings": {},
            "added": [],
            "event": args.event,
            "summary": args.summary,
        }
    document = _findings_document(app, issue)
    decisions: dict[str, dict] = {}
    if args.accept_all:
        for finding in document.get("findings") or []:
            decisions[finding["id"]] = {"decision": "accept", "must_fix": bool(finding.get("must_fix"))}
    for item in args.finding or []:
        finding_id, choice = _split_flag(item, "--finding")
        if choice not in {"accept", "reject"}:
            raise WorkflowError("--finding values must be accept or reject.")
        decisions.setdefault(finding_id, {})["decision"] = choice
    for item in args.must_fix or []:
        finding_id, raw = _split_flag(item, "--must-fix")
        if raw.lower() not in {"true", "false"}:
            raise WorkflowError("--must-fix values must be true or false.")
        decisions.setdefault(finding_id, {})["must_fix"] = raw.lower() == "true"
    for item in args.explanation or []:
        finding_id, text = _split_flag(item, "--explanation")
        decisions.setdefault(finding_id, {})["explanation"] = text
    added = []
    if args.add_json:
        added.append(json.loads(Path(args.add_json).read_text(encoding="utf-8")))
    if not decisions and not added:
        raise WorkflowError("Record a human review with --accept-all, --finding, --file, or --reject-automated.")
    return {
        "rejected_review": False,
        "findings": decisions,
        "added": added,
        "event": args.event,
        "summary": args.summary,
    }


def _findings_document(app: App, issue: str) -> dict:
    session_path = app.store.issue_dir(issue) / "session.json"
    session = read_json(session_path)
    if not session or not session.get("active_pr") or not session.get("active_sha"):
        raise WorkflowError("No active review snapshot exists yet.")
    from review_ticket.util import parse_pr_ref

    owner, repo, number = parse_pr_ref(session["active_pr"])
    path = (
        app.store.commit_dir(issue, owner, repo, number, session["active_sha"])
        / "review"
        / "findings.json"
    )
    document = read_json(path)
    if not document:
        raise WorkflowError("No automated findings are stored.")
    return document


def _pr(app: App, issue: str, args: argparse.Namespace) -> StepResult:
    if args.pr_cmd == "select-all":
        return select_all_prs(app, issue)
    if args.pr_cmd == "select":
        return select_pr(app, issue, args.pr_ref)
    return post_comment(
        app,
        issue,
        body_file=Path(args.body_file) if args.body_file else None,
        body=args.body,
        attachments=args.attach or [],
        yes=args.yes,
    )


def _jira(app: App, issue: str, args: argparse.Namespace) -> StepResult:
    if args.jira_cmd == "transition":
        return jira_transition(app, issue, args.status, yes=args.yes)
    return jira_comment(
        app,
        issue,
        body_file=Path(args.body_file) if args.body_file else None,
        body=args.body,
        yes=args.yes,
    )


def _test(app: App, issue: str, args: argparse.Namespace) -> StepResult:
    if args.test_cmd == "prepare":
        return prepare_profile(app, issue)
    if args.test_cmd == "fetch":
        return fetch_image(app, issue)
    if args.test_cmd == "launch":
        return launch_environment(app, issue)
    if args.test_cmd == "plan":
        return write_test_plan_command(app, issue)
    if args.test_cmd == "record":
        return record_tests(
            app,
            issue,
            result=args.result,
            kind=args.kind,
            notes=args.notes or "",
            scenarios=args.scenario or [],
            evidence=args.evidence or [],
            revise=args.revise,
        )
    return post_comment(
        app,
        issue,
        body_file=Path(args.body_file) if args.body_file else None,
        body=args.body,
        attachments=args.attach or [],
        yes=args.yes,
    )


def _body(args: argparse.Namespace) -> str:
    if args.body_file:
        return Path(args.body_file).read_text(encoding="utf-8")
    return args.body or ""


def _split_flag(value: str, flag: str) -> tuple[str, str]:
    if "=" not in value:
        raise WorkflowError(f"{flag} expects ID=value.")
    finding_id, rest = value.split("=", 1)
    if not finding_id or not rest:
        raise WorkflowError(f"{flag} expects ID=value.")
    return finding_id, rest


def _add_refresh_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Bypass cache_steps and re-fetch Jira/GitHub data for this command.",
    )


def _add_refresh_to_subparsers(parser: argparse.ArgumentParser) -> None:
    for action in parser._actions:
        if not isinstance(action, argparse._SubParsersAction):
            continue
        for sub_parser in action.choices.values():
            _add_refresh_flag(sub_parser)
            _add_refresh_to_subparsers(sub_parser)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="review-ticket",
        description="Manual peer review from a Jira issue through GitHub feedback and local testing.",
    )
    parser.add_argument("issue", help="Jira issue id, for example DOTNETIOT-1234")
    _add_refresh_flag(parser)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", help="Show the stored session without contacting Jira or GitHub")
    assess_parser = sub.add_parser("assess", help="Refresh readiness and analyzer state")
    assess_parser.add_argument("--accept-missing-checks", action="store_true")
    assess_parser.add_argument("--accept-missing-analyzers", action="store_true")

    notes = sub.add_parser("notes", help="Accept or reject developer testing notes")
    group = notes.add_mutually_exclusive_group(required=True)
    group.add_argument("--accept", action="store_true")
    group.add_argument("--reject", action="store_true")
    notes.add_argument("--notes", default="")
    notes.add_argument("--revise", action="store_true")

    run = sub.add_parser("run-review", help="Check out the SHA and invoke the configured reviewer")
    run.add_argument("--revise", action="store_true")
    imported = sub.add_parser("import-review", help="Import reviewer JSON into the current SHA")
    imported.add_argument("--file", required=True)
    imported.add_argument("--revise", action="store_true")

    attach = sub.add_parser("attach", help="Open the Textual review UI")
    attach.add_argument("--revise", action="store_true")

    review = sub.add_parser("review", help="Inspect or record the human review")
    review_sub = review.add_subparsers(dest="review_cmd", required=True)
    review_sub.add_parser("show")
    apply_parser = review_sub.add_parser("apply")
    apply_parser.add_argument("--file")
    apply_parser.add_argument("--accept-all", action="store_true")
    apply_parser.add_argument("--finding", action="append", default=[])
    apply_parser.add_argument("--must-fix", action="append", default=[])
    apply_parser.add_argument("--explanation", action="append", default=[])
    apply_parser.add_argument("--add-json")
    apply_parser.add_argument("--event", choices=["COMMENT", "APPROVE", "REQUEST_CHANGES"])
    apply_parser.add_argument("--summary")
    apply_parser.add_argument("--reject-automated", action="store_true")
    apply_parser.add_argument("--revise", action="store_true")

    publish = sub.add_parser("publish-review", help="Publish the approved local review to GitHub")
    publish.add_argument("--yes", action="store_true")
    publish.add_argument("--event", choices=["COMMENT", "APPROVE", "REQUEST_CHANGES"])
    publish.add_argument("--skip", action="store_true")

    analyzers = sub.add_parser("analyzers", help="Decide how to treat Bugbot and CodeQL findings")
    analyzer_group = analyzers.add_mutually_exclusive_group(required=True)
    analyzer_group.add_argument("--return", action="store_true")
    analyzer_group.add_argument("--accept-dispositions", action="store_true")
    analyzer_group.add_argument("--override", action="store_true")
    analyzers.add_argument("--notes", default="")
    analyzers.add_argument("--revise", action="store_true")

    pr = sub.add_parser("pr", help="Select a pull request or post a general comment")
    pr_sub = pr.add_subparsers(dest="pr_cmd", required=True)
    pr_sub.add_parser("select-all", help="Track every open pull request discovered for this issue")
    select = pr_sub.add_parser("select", help="Track a single pull request")
    select.add_argument("pr_ref")
    comment = pr_sub.add_parser("comment")
    _add_comment_flags(comment)

    jira = sub.add_parser("jira", help="Comment on or transition the Jira issue")
    jira_sub = jira.add_subparsers(dest="jira_cmd", required=True)
    jira_comment_parser = jira_sub.add_parser("comment")
    jira_comment_parser.add_argument("--body-file")
    jira_comment_parser.add_argument("--body")
    jira_comment_parser.add_argument("--yes", action="store_true")
    transition = jira_sub.add_parser("transition")
    transition.add_argument("--status", required=True)
    transition.add_argument("--yes", action="store_true")

    test = sub.add_parser("test", help="Prepare, fetch, launch, or record virtualization testing")
    test_sub = test.add_subparsers(dest="test_cmd", required=True)
    test_sub.add_parser("prepare")
    test_sub.add_parser("fetch")
    test_sub.add_parser("launch")
    test_sub.add_parser("plan")
    recorded = test_sub.add_parser("record")
    recorded.add_argument("--result", required=True, choices=["pass", "fail", "blocked"])
    recorded.add_argument("--kind", choices=["implementation", "environment"])
    recorded.add_argument("--notes", default="")
    recorded.add_argument("--scenario", action="append", default=[])
    recorded.add_argument("--evidence", action="append", default=[])
    recorded.add_argument("--revise", action="store_true")
    test_comment = test_sub.add_parser("comment")
    _add_comment_flags(test_comment)

    bug = sub.add_parser("bug", help="Draft a follow-up defect for the bug writer skill")
    bug.add_argument("--summary", required=True)
    bug.add_argument("--body-file")
    bug.add_argument("--body", default="")
    bug.add_argument("--yes", action="store_true")

    disposition = sub.add_parser(
        "disposition",
        help="Record the final human disposition. This does not transition Jira.",
    )
    disposition.add_argument("--choice", required=True, choices=["approve", "leave", "return"])
    disposition.add_argument("--notes", default="")
    disposition.add_argument("--override", action="store_true")
    disposition.add_argument("--revise", action="store_true")
    _add_refresh_to_subparsers(parser)
    return parser


def _add_comment_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--body-file")
    parser.add_argument("--body")
    parser.add_argument("--attach", action="append", default=[])
    parser.add_argument("--yes", action="store_true")
