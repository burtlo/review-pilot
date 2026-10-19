"""Files changed deep links and the loopback snapshot bridge."""

from __future__ import annotations

import hmac
import json
import os
import re
from collections.abc import Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlsplit

from review_ticket.findings import _general_section, render_finding_body
from review_ticket.models import WorkflowError
from review_ticket.storage import Store, read_json
from review_ticket.textutil import parse_unified_diff
from review_ticket.util import parse_pr_ref

_FULL_SHA = re.compile(r"[0-9a-fA-F]{40}")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_SUGGESTION_FENCE = re.compile(r"```suggestion[^\n]*\n(.*?)```", re.DOTALL)
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_UNDER = re.compile(r"__(.+?)__", re.DOTALL)
_ITALIC = re.compile(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", re.DOTALL)

BRIDGE_TOKEN_ENV = "REVIEW_PILOT_BRIDGE_TOKEN"
DEFAULT_BRIDGE_PORT = 8765
LOOPBACK_HOST = "127.0.0.1"
_SIDES = {"RIGHT", "LEFT"}
_GENERAL_HEADER = "## Findings outside the diff"

SnapshotLoader = Callable[[str, str, int, str], dict[str, Any] | None]


def is_full_sha(sha: str) -> bool:
    """A reviewed SHA is forty hexadecimal characters. Shorter ids do not match."""

    return bool(_FULL_SHA.fullmatch(sha or ""))


def files_changed_url(owner: str, repo: str, number: int, issue: str, sha: str) -> str:
    """Open Files changed for a full SHA; otherwise return the conversation URL.

    The query is exactly ``review_pilot_issue`` and ``review_pilot_sha``. The pull
    request is identified by the path. This helper does not read or write ``pr.json``.
    """

    conversation = f"https://github.com/{owner}/{repo}/pull/{number}"
    if not is_full_sha(sha):
        return conversation
    query = urlencode((("review_pilot_issue", issue), ("review_pilot_sha", sha)))
    return f"{conversation}/changes?{query}"


def finding_marker_line(finding_id: str) -> str:
    """Visible scan key. Rendered comments keep this line; HTML comments do not."""

    return f"review-pilot finding {finding_id}"


def finding_marker_comment(finding_id: str) -> str:
    """Trailing raw-body copy. This comment is not the scan key."""

    return f"<!-- review-pilot:finding:{finding_id} -->"


def append_finding_marker(body: str, finding_id: str) -> str:
    """Append the visible marker and the HTML comment after the finding prose.

    Callers place this after ``render_finding_body`` or a general-section segment
    so the marker stays outside any suggestion fence.
    """

    text = (body or "").rstrip()
    return (
        f"{text}\n\n{finding_marker_line(finding_id)}\n{finding_marker_comment(finding_id)}\n"
    )


def scan_text(markdown: str) -> str:
    """Plain projection of a composer body for rendered-comment comparison.

    Emphasis markers and HTML comments are removed. A suggestion fence is replaced
    by its inner lines. The visible finding marker stays, because rendered text
    keeps that line. Remaining whitespace collapses to single spaces.
    """

    text = _SUGGESTION_FENCE.sub(lambda match: match.group(1).strip("\n"), markdown or "")
    text = _HTML_COMMENT.sub("", text)
    text = _BOLD.sub(r"\1", text)
    text = _BOLD_UNDER.sub(r"\1", text)
    previous = None
    while previous != text:
        previous = text
        text = _ITALIC.sub(r"\1", text)
    return " ".join(text.split())


def read_bridge_token(environ: Mapping[str, str] | None = None) -> str:
    """Return the bridge secret, or refuse to listen when it is empty."""

    env = os.environ if environ is None else environ
    token = str(env.get(BRIDGE_TOKEN_ENV, "")).strip()
    if not token:
        raise WorkflowError(f"{BRIDGE_TOKEN_ENV} is empty. Refusing to listen.")
    return token


def require_loopback(host: str) -> None:
    """The bridge binds 127.0.0.1 and no other address."""

    if host != LOOPBACK_HOST:
        raise WorkflowError(
            f"Refusing to bind {host!r}. The inline review bridge listens on {LOOPBACK_HOST} only."
        )


def bearer_matches(header: str | None, token: str) -> bool:
    """True when ``Authorization`` is ``Bearer`` plus the bridge token."""

    if not header or not token:
        return False
    prefix = "Bearer "
    if not header.startswith(prefix):
        return False
    presented = header[len(prefix) :]
    try:
        return hmac.compare_digest(presented, token)
    except (TypeError, ValueError):
        return False


def resolve_inline_review_target(
    store: Store,
    issue: str,
    *,
    pr: str | None,
    sha: str | None,
) -> tuple[str, str, int, str]:
    """Resolve the one pull request and reviewed SHA this process will serve."""

    session = read_json(store.issue_dir(issue) / "session.json") or {}
    ref = (pr or "").strip() or str(session.get("active_pr") or "").strip()
    if not ref:
        raise WorkflowError("No pull request selected. Pass --pr owner/repo#number.")
    try:
        owner, repo, number = parse_pr_ref(ref)
    except ValueError as exc:
        raise WorkflowError(str(exc)) from exc
    canonical = f"{owner}/{repo}#{number}"
    if sha and str(sha).strip():
        resolved = str(sha).strip()
    else:
        pr_shas = session.get("pr_shas") or {}
        resolved = str(pr_shas.get(canonical) or pr_shas.get(ref) or "")
        if not resolved and session.get("active_pr") in {canonical, ref}:
            resolved = str(session.get("active_sha") or "")
    if not resolved:
        raise WorkflowError(f"No reviewed SHA is stored for {canonical}. Pass --sha.")
    try:
        store.commit_dir(issue, owner, repo, number, resolved)
    except ValueError as exc:
        raise WorkflowError(str(exc)) from exc
    return owner, repo, number, resolved


def load_diff_index(commit_dir: Path) -> set[tuple[str, int, str]]:
    """Prefer ``review/diff-lines.json``. Fall back to ``diff.patch``."""

    review_dir = commit_dir / "review"
    stored = read_json(review_dir / "diff-lines.json")
    if isinstance(stored, list):
        index: set[tuple[str, int, str]] = set()
        for item in stored:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                try:
                    index.add((str(item[0]), int(item[1]), str(item[2])))
                except (TypeError, ValueError):
                    continue
        return index
    diff_path = commit_dir / "diff.patch"
    if diff_path.is_file():
        return parse_unified_diff(diff_path.read_text(encoding="utf-8"))
    return set()


def _on_diff(finding: dict[str, Any], diff_index: set[tuple[str, int, str]]) -> bool:
    path = finding.get("path")
    line = finding.get("line")
    side = finding.get("side") or "RIGHT"
    return (
        bool(path)
        and isinstance(line, int)
        and side in _SIDES
        and (path, line, side) in diff_index
    )


def _indexed_start_line(
    finding: dict[str, Any],
    diff_index: set[tuple[str, int, str]],
    *,
    on_diff: bool,
) -> int | None:
    """Publish attaches ``start_line`` only when that line is in the index too."""

    if not on_diff:
        return None
    path = finding.get("path")
    line = finding.get("line")
    side = finding.get("side") or "RIGHT"
    start_line = finding.get("start_line")
    if (
        isinstance(start_line, int)
        and start_line != line
        and side in _SIDES
        and (path, start_line, side) in diff_index
    ):
        return start_line
    return None


def _off_diff_segment(finding: dict[str, Any]) -> str:
    section = _general_section([finding]).rstrip()
    header = _GENERAL_HEADER + "\n\n"
    if section.startswith(header):
        section = section[len(header) :]
    return section.rstrip()


def _summary_block(findings: list[dict[str, Any]]) -> str:
    if not findings:
        return ""
    segments = [
        append_finding_marker(_off_diff_segment(finding), str(finding.get("id") or "")).rstrip()
        for finding in findings
    ]
    return _GENERAL_HEADER + "\n\n" + "\n\n".join(segments) + "\n"


def _finding_body(finding: dict[str, Any], *, on_diff: bool) -> str:
    finding_id = str(finding.get("id") or "")
    if on_diff:
        prepared = dict(finding)
        prepared["_inline"] = True
        return append_finding_marker(render_finding_body(prepared), finding_id)
    return append_finding_marker(_off_diff_segment(finding), finding_id)


def build_snapshot(
    *,
    issue: str,
    owner: str,
    repo: str,
    number: int,
    sha: str,
    findings: list[dict[str, Any]],
    diff_index: set[tuple[str, int, str]],
) -> dict[str, Any]:
    """One PR snapshot. Every stored finding is listed; nothing is triaged out."""

    rows: list[dict[str, Any]] = []
    off_diff: list[dict[str, Any]] = []
    for finding in findings:
        inline = _on_diff(finding, diff_index)
        if not inline:
            off_diff.append(finding)
        body = _finding_body(finding, on_diff=inline)
        rows.append(
            {
                "id": str(finding.get("id") or ""),
                "title": finding.get("title") or "",
                "path": finding.get("path") or None,
                "line": finding.get("line") if isinstance(finding.get("line"), int) else None,
                "start_line": _indexed_start_line(finding, diff_index, on_diff=inline),
                "side": finding.get("side") or "RIGHT",
                "on_diff": inline,
                "body": body,
                "scan_text": scan_text(body),
            }
        )
    return {
        "issue": issue,
        "pr": f"{owner}/{repo}#{number}",
        "owner": owner,
        "repo": repo,
        "number": number,
        "sha": sha,
        "findings": rows,
        "summary_block": _summary_block(off_diff),
    }


def snapshot_for_store(
    store: Store,
    issue: str,
    owner: str,
    repo: str,
    number: int,
    sha: str,
) -> dict[str, Any] | None:
    """Load the snapshot, or None when the review directory is not on disk."""

    commit_dir = store.commit_dir(issue, owner, repo, number, sha)
    review_dir = commit_dir / "review"
    if not review_dir.is_dir():
        return None
    document = read_json(review_dir / "findings.json")
    if not isinstance(document, dict):
        return None
    raw_findings = document.get("findings")
    if not isinstance(raw_findings, list):
        return None
    findings = [item for item in raw_findings if isinstance(item, dict)]
    return build_snapshot(
        issue=issue,
        owner=owner,
        repo=repo,
        number=number,
        sha=sha,
        findings=findings,
        diff_index=load_diff_index(commit_dir),
    )


class InlineReviewHandler(BaseHTTPRequestHandler):
    """GET /snapshot for one configured pull request. No cross-origin header."""

    server: InlineReviewServer

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler name
        bridge = self.server
        if not bearer_matches(self.headers.get("Authorization"), bridge.bridge_token):
            self._send(401, {"error": "unauthorized"})
            return
        parsed = urlsplit(self.path)
        if parsed.path != "/snapshot":
            self._send(404, {"error": "not_found"})
            return
        identity = _snapshot_query(parsed.query)
        if identity is None:
            self._send(400, {"error": "bad_request"})
            return
        try:
            snapshot = bridge.load_snapshot(*identity)
        except ValueError:
            self._send(400, {"error": "bad_request"})
            return
        if snapshot is None:
            self._send(404, {"error": "not_found"})
            return
        self._send(200, snapshot)

    def _send(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class InlineReviewServer(ThreadingHTTPServer):
    """Loopback server. Construction refuses any other bind address."""

    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        token: str,
        load_snapshot: SnapshotLoader,
    ) -> None:
        if not token:
            raise WorkflowError(f"{BRIDGE_TOKEN_ENV} is empty. Refusing to listen.")
        require_loopback(str(server_address[0]))
        self.bridge_token = token
        self.load_snapshot = load_snapshot
        super().__init__(server_address, InlineReviewHandler)


def serve_inline_review(
    store: Store,
    issue: str,
    *,
    pr: str | None = None,
    sha: str | None = None,
    port: int = DEFAULT_BRIDGE_PORT,
    host: str = LOOPBACK_HOST,
) -> InlineReviewServer:
    """Bind the bridge for one PR snapshot. The caller runs ``serve_forever``."""

    token = read_bridge_token()
    require_loopback(host)
    owner, repo, number, resolved_sha = resolve_inline_review_target(store, issue, pr=pr, sha=sha)

    def load_snapshot(
        query_owner: str,
        query_repo: str,
        query_number: int,
        query_sha: str,
    ) -> dict[str, Any] | None:
        if (query_owner, query_repo, query_number, query_sha) != (owner, repo, number, resolved_sha):
            return None
        return snapshot_for_store(store, issue, owner, repo, number, resolved_sha)

    return InlineReviewServer((host, port), token, load_snapshot)


def _snapshot_query(query: str) -> tuple[str, str, int, str] | None:
    params = parse_qs(query, keep_blank_values=False)
    owner = _only(params, "owner")
    repo = _only(params, "repo")
    number_text = _only(params, "number")
    sha = _only(params, "sha")
    if not owner or not repo or not number_text or not sha:
        return None
    if not number_text.isdigit():
        return None
    return owner, repo, int(number_text), sha


def _only(params: dict[str, list[str]], key: str) -> str:
    values = params.get(key) or []
    if len(values) != 1:
        return ""
    return values[0].strip()
