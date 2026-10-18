#!/usr/bin/env python3
"""Headless review-ticket reviewer adapter (invokes Cursor agent, writes findings JSON)."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

# Allow running as `python scripts/review_ticket_reviewer.py` without installing the package.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from review_ticket.logutil import configure_logging_from_env
from review_ticket.tls_env import apply_zscaler_tls_env

_LOG = logging.getLogger("review_ticket.adapter")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the configured Cursor reviewer agent for review-ticket.")
    parser.add_argument("--context", required=True, help="Review context directory (contains prompt.md).")
    parser.add_argument("--output", required=True, help="Path for findings JSON.")
    parser.add_argument("--checkout", required=True, help="Detached worktree at the reviewed SHA.")
    parser.add_argument("--repository", required=True, help="owner/repo for the active PR.")
    parser.add_argument("--sha", required=True, help="Reviewed commit SHA.")
    parser.add_argument("--issue", required=True, help="Jira issue key.")
    parser.add_argument(
        "--agent",
        default="reviewer",
        help="Cursor agent id from .cursor/agents/ (default: reviewer).",
    )
    return parser.parse_args(argv)


def _agent_prompt(args: argparse.Namespace) -> str:
    context = Path(args.context).resolve()
    output = Path(args.output).resolve()
    checkout = Path(args.checkout).resolve()
    skill = (
        "peer-review-ui-admin"
        if args.agent == "ui-admin-reviewer"
        else "peer-review"
    )
    return f"""You are the `{args.agent}` agent for review-ticket (headless run).

Follow the project skill `{skill}` in this repository (headless review-ticket section) and `.cursor/agents/{args.agent}.md`.

Issue: {args.issue}
Repository (GitHub): {args.repository}
SHA: {args.sha}
Review context directory: {context}
Full Repository Path (code under review): {checkout}

Read `{context / "prompt.md"}` and all sibling context files (`diff.patch`, `jira.md`, `standards.md`, `analyzers.md`, etc.).
Inspect `{checkout}` as the repository at the reviewed SHA (read `AGENTS.md` and repo `.cursor/skills/` when reviewing UI.Admin).

Write the review result as JSON to this exact path (create parent directories if needed):
{output}

Apply the same rigor as interactive peer review; output is JSON only — no markdown `# Summary` report, no GitHub publish. The file must pass review-ticket `normalize_findings`.
"""


def _extract_json_blob(text: str) -> dict | list:
    stripped = text.strip()
    if not stripped:
        raise ValueError("empty agent response")
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}|\[[\s\S]*\]", stripped)
        if not match:
            raise
        return json.loads(match.group(0))


def _write_payload(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _use_async_bridge() -> bool:
    """Sync cursor-sdk Bridge.launch fails on native Windows (WinError 10038)."""
    override = os.environ.get("REVIEW_TICKET_REVIEWER_ASYNC", "").strip().lower()
    if override in {"0", "false", "no"}:
        return False
    if override in {"1", "true", "yes"}:
        return True
    return sys.platform == "win32"


def _local_agent_options() -> Any:
    from cursor_sdk import LocalAgentOptions

    return LocalAgentOptions(
        cwd=str(REPO_ROOT),
        setting_sources=["project", "user"],
    )


def _agent_options(api_key: str, model: str) -> Any:
    from cursor_sdk import AgentOptions

    local = _local_agent_options()
    return AgentOptions(api_key=api_key, model=model, local=local)


def _apply_run_result(result: Any, output: Path) -> None:
    if result.status == "error":
        raise SystemExit(f"Cursor agent run failed (run id: {result.id})")

    _LOG.info("Cursor agent finished (run id: %s)", result.id)
    if output.exists():
        _LOG.debug("findings already written to %s", output)
        return

    text = (result.result or "").strip()
    if not text:
        raise SystemExit(f"Agent finished but did not write {output} and returned no text.")
    payload = _extract_json_blob(text)
    _write_payload(output, payload)


async def _run_cursor_agent_async(prompt: str, api_key: str, model: str) -> Any:
    from cursor_sdk import CursorAgentError
    from cursor_sdk.asyncio import AsyncAgent, AsyncClient

    local = _local_agent_options()
    options = _agent_options(api_key, model)
    bridge_url = os.environ.get("CURSOR_SDK_BRIDGE_URL")
    bridge_token = os.environ.get("CURSOR_SDK_BRIDGE_TOKEN") or os.environ.get(
        "CURSOR_SDK_BRIDGE_AUTH_TOKEN"
    )

    try:
        if bridge_url and bridge_token:
            _LOG.debug("connecting to existing SDK bridge at %s", bridge_url)
            client = AsyncClient.connect(bridge_url, bridge_token)
            async with client:
                return await AsyncAgent.prompt(prompt, options, client=client)
        _LOG.debug("launching SDK bridge (async) for workspace %s", REPO_ROOT)
        async with await AsyncClient.launch_bridge(workspace=str(REPO_ROOT), local=local) as client:
            return await AsyncAgent.prompt(prompt, options, client=client)
    except CursorAgentError as exc:
        raise SystemExit(f"Cursor agent failed: {exc}") from exc


def _run_stub(args: argparse.Namespace) -> None:
    _LOG.info("stub reviewer (no Cursor SDK)")
    raw = os.environ.get("REVIEW_TICKET_REVIEWER_STUB_JSON")
    if raw:
        payload = json.loads(raw)
    else:
        payload = {
            "summary": f"Stub review for {args.repository} @ {args.sha[:8]}.",
            "approval_recommendation": "comment",
            "findings": [],
        }
    _write_payload(Path(args.output), payload)


def _run_cursor_agent(args: argparse.Namespace) -> None:
    _LOG.info("starting Cursor agent %s for %s", args.agent, args.repository)
    _LOG.debug(
        "context=%s checkout=%s output=%s issue=%s sha=%s",
        args.context,
        args.checkout,
        args.output,
        args.issue,
        args.sha,
    )
    try:
        from cursor_sdk import Agent, CursorAgentError
    except ImportError as exc:
        raise SystemExit(
            "cursor-sdk is not installed. Run: python -m pip install cursor-sdk\n"
            "Or set REVIEW_TICKET_REVIEWER_STUB=1 for a no-agent smoke run."
        ) from exc

    api_key = os.environ.get("CURSOR_API_KEY")
    if not api_key:
        raise SystemExit("CURSOR_API_KEY is required for headless reviewer runs.")

    model = os.environ.get("REVIEW_TICKET_REVIEWER_MODEL", "composer-2.5")
    prompt = _agent_prompt(args)
    output = Path(args.output)

    if _use_async_bridge():
        _LOG.info("using async SDK bridge (required on native Windows)")
        result = asyncio.run(_run_cursor_agent_async(prompt, api_key, model))
    else:
        try:
            result = Agent.prompt(prompt, _agent_options(api_key, model))
        except CursorAgentError as exc:
            raise SystemExit(f"Cursor agent failed to start: {exc}") from exc

    _apply_run_result(result, output)


def main(argv: list[str] | None = None) -> int:
    configure_logging_from_env()
    cert_env = apply_zscaler_tls_env()
    if cert_env:
        _LOG.info("using ZScaler CA from ZSCALER_CERT_PATH for Node/Python TLS")
        _LOG.debug("NODE_EXTRA_CA_CERTS=%s", cert_env.get("NODE_EXTRA_CA_CERTS"))
    args = _parse_args(argv)
    if os.environ.get("REVIEW_TICKET_REVIEWER_STUB", "").strip().lower() in {"1", "true", "yes"}:
        _run_stub(args)
        return 0
    _run_cursor_agent(args)
    if not Path(args.output).is_file():
        raise SystemExit(f"Reviewer did not create {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
