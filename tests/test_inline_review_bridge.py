"""Loopback snapshot bridge for the inline reviewer."""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode

import pytest

from review_ticket.cli import build_parser
from review_ticket.findings import _general_section, render_finding_body
from review_ticket.inline_review import (
    BRIDGE_TOKEN_ENV,
    DEFAULT_BRIDGE_PORT,
    InlineReviewServer,
    append_finding_marker,
    resolve_inline_review_target,
    scan_text,
    serve_inline_review,
    snapshot_for_store,
)
from review_ticket.models import WorkflowError
from review_ticket.storage import Store, write_json
from review_ticket.textutil import parse_unified_diff
from tests.support import DIFF, ISSUE, SHA1, SHA2

TOKEN = "bridge-test-token"
REF = "acme/widgets#87"
OWNER = "acme"
REPO = "widgets"
NUMBER = 87
REVIEWER_SUMMARY = "Quantity is not validated on every path."

ON_DIFF = {
    "id": "F001",
    "priority": "high",
    "must_fix": True,
    "path": "src/Example.cs",
    "line": 142,
    "start_line": 140,
    "side": "RIGHT",
    "title": "Missing validation",
    "explanation": "This path permits an invalid state.",
    "suggested_change": "if (item.Quantity < 0) throw new InvalidOperationException();",
    "decision": "accept",
}
OFF_DIFF = {
    "id": "F002",
    "priority": "medium",
    "must_fix": False,
    "path": "src/Example.cs",
    "line": 10,
    "start_line": 140,
    "side": "RIGHT",
    "title": "Unrelated helper",
    "explanation": "This behavior lives outside the diff.",
    "decision": "accept",
}
GENERAL = {
    "id": "F003",
    "priority": "low",
    "must_fix": False,
    "title": "Release note",
    "explanation": "Mention the validation in the changelog.",
    "decision": "accept",
}
REJECTED = {
    "id": "F004",
    "priority": "low",
    "must_fix": False,
    "path": "src/Example.cs",
    "line": 143,
    "start_line": 10,
    "side": "RIGHT",
    "title": "Rejected on purpose",
    "explanation": "Publish drops this finding.",
    "decision": "reject",
}
FINDINGS = [ON_DIFF, OFF_DIFF, GENERAL, REJECTED]


def _write_session(store: Store, *, sha: str = SHA1, active_sha: str | None = None) -> None:
    write_json(
        store.issue_dir(ISSUE) / "session.json",
        {
            "issue": ISSUE,
            "active_pr": REF,
            "active_sha": SHA2 if active_sha is None else active_sha,
            "active_prs": [REF, "acme/gadgets#12"],
            "pr_shas": {REF: sha, "acme/gadgets#12": SHA2},
        },
    )


def _write_review(store: Store, *, sha: str = SHA1, diff_lines: bool = True) -> None:
    commit = store.commit_dir(ISSUE, OWNER, REPO, NUMBER, sha)
    review = commit / "review"
    review.mkdir(parents=True)
    write_json(
        review / "findings.json",
        {"summary": REVIEWER_SUMMARY, "findings": FINDINGS},
    )
    write_json(
        review / "human-review.json",
        {
            "findings": {
                "F001": {"decision": "reject"},
                "F004": {"decision": "reject"},
            }
        },
    )
    if diff_lines:
        index = sorted(list(item) for item in parse_unified_diff(DIFF))
        write_json(review / "diff-lines.json", index)
    else:
        (commit / "diff.patch").write_text(DIFF, encoding="utf-8")


def _wait_until_listening(server: InlineReviewServer) -> None:
    host, port = server.server_address[:2]
    deadline = time.time() + 5
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.02)
    raise AssertionError("bridge did not accept connections")


def _start(server: InlineReviewServer) -> threading.Thread:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _wait_until_listening(server)
    return thread


def _stop(server: InlineReviewServer, thread: threading.Thread) -> None:
    server.shutdown()
    thread.join(timeout=5)
    server.server_close()


def _fetch(
    server: InlineReviewServer,
    *,
    token: str | None,
    params: dict[str, str] | None = None,
) -> tuple[int, list[str], bytes]:
    host, port = server.server_address[:2]
    query = {
        "owner": OWNER,
        "repo": REPO,
        "number": str(NUMBER),
        "sha": SHA1,
    }
    if params is not None:
        query.update(params)
    url = f"http://{host}:{port}/snapshot?{urlencode(query)}"
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            status, header_map, body = response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        status, header_map, body = exc.code, exc.headers, exc.read()
    names = [key.lower() for key in header_map.keys()]
    return status, names, body


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    store = Store(tmp_path / "reviews")
    _write_session(store)
    _write_review(store)
    server = serve_inline_review(store, ISSUE, port=0)
    thread = _start(server)
    try:
        yield server
    finally:
        _stop(server, thread)


def _snapshot(server: InlineReviewServer) -> dict:
    status, names, body = _fetch(server, token=TOKEN)
    assert status == 200
    assert "access-control-allow-origin" not in names
    return json.loads(body.decode("utf-8"))


def test_scan_text_drops_emphasis_comments_and_keeps_suggestion_lines():
    body = append_finding_marker(
        "**Missing validation** (Must-fix, high)\n\nLine.\n\n```suggestion\nif (item.Quantity < 0)\n```\n",
        "F001",
    )
    assert "```suggestion" in body
    fence = body.index("```suggestion")
    close = body.index("```", fence + len("```suggestion"))
    marker = body.index("review-pilot finding F001")
    assert fence < close < marker
    scan = scan_text(body)
    assert scan == (
        "Missing validation (Must-fix, high) Line. if (item.Quantity < 0) "
        "review-pilot finding F001"
    )
    assert "<!--" not in scan
    assert "```" not in scan
    assert "**" not in scan


def test_snapshot_returns_every_finding_including_rejected(bridge):
    payload = _snapshot(bridge)
    assert payload["issue"] == ISSUE
    assert payload["pr"] == REF
    assert payload["owner"] == OWNER
    assert payload["repo"] == REPO
    assert payload["number"] == NUMBER
    assert payload["sha"] == SHA1
    assert [row["id"] for row in payload["findings"]] == ["F001", "F002", "F003", "F004"]
    rejected = payload["findings"][3]
    assert rejected["title"] == "Rejected on purpose"
    assert rejected["on_diff"] is True
    assert rejected["start_line"] is None
    encoded = json.dumps(payload)
    assert REVIEWER_SUMMARY not in encoded
    assert "Peer review notes." not in encoded


def test_on_diff_body_has_suggestion_fence_and_marker_outside_it(bridge):
    row = _snapshot(bridge)["findings"][0]
    assert row["on_diff"] is True
    assert row["start_line"] == 140
    assert row["line"] == 142
    assert row["side"] == "RIGHT"
    body = row["body"]
    prepared = dict(ON_DIFF)
    prepared["_inline"] = True
    rendered = render_finding_body(prepared).rstrip()
    assert rendered in body
    assert "```suggestion" in body
    fence = body.index("```suggestion")
    close = body.index("```", fence + len("```suggestion"))
    marker = body.index("review-pilot finding F001")
    comment = body.index("<!-- review-pilot:finding:F001 -->")
    assert fence < close < marker < comment
    assert "if (item.Quantity < 0) throw new InvalidOperationException();" in body[fence:close]
    scan = row["scan_text"]
    assert "review-pilot finding F001" in scan
    assert "<!--" not in scan
    assert "```" not in scan
    assert "**" not in scan
    assert "Missing validation" in scan
    assert "if (item.Quantity < 0) throw new InvalidOperationException();" in scan


def test_off_diff_finding_is_in_summary_and_absent_from_inline_bodies(bridge):
    payload = _snapshot(bridge)
    summary = payload["summary_block"]
    plain = _general_section([OFF_DIFF, GENERAL])
    for line in plain.splitlines():
        if line.strip():
            assert line in summary
    assert "review-pilot finding F002" in summary
    assert "review-pilot finding F003" in summary
    assert "<!-- review-pilot:finding:F002 -->" in summary
    assert "<!-- review-pilot:finding:F003 -->" in summary
    assert "```suggestion" not in summary
    assert "Missing validation" not in summary
    assert "Rejected on purpose" not in summary
    assert "review-pilot finding F001" not in summary
    for row in payload["findings"]:
        if row["on_diff"]:
            assert "Unrelated helper" not in row["body"]
            assert "Release note" not in row["body"]
            assert "This behavior lives outside the diff." not in row["body"]
        else:
            assert row["body"].rstrip() in summary
            assert "```suggestion" not in row["body"]
            assert f"review-pilot finding {row['id']}" in row["body"]
    off_diff = payload["findings"][1]
    assert off_diff["on_diff"] is False
    assert off_diff["start_line"] is None
    assert off_diff["line"] == 10


def test_wrong_token_is_rejected(bridge):
    status, names, body = _fetch(bridge, token="not-the-token")
    assert status == 401
    assert b"Missing validation" not in body
    assert b"Rejected on purpose" not in body
    assert b"```suggestion" not in body
    assert b"summary_block" not in body
    assert "access-control-allow-origin" not in names
    assert json.loads(body.decode("utf-8")) == {"error": "unauthorized"}


def test_client_without_token_cannot_read_the_body(bridge):
    opened = _snapshot(bridge)
    assert opened["findings"][0]["title"] == "Missing validation"
    status, names, body = _fetch(bridge, token=None)
    assert status == 401
    assert b"Missing validation" not in body
    assert b"Unrelated helper" not in body
    assert b"Rejected on purpose" not in body
    assert b"summary_block" not in body
    assert b"review-pilot finding" not in body
    assert "access-control-allow-origin" not in names


def test_missing_review_directory_is_404(tmp_path, monkeypatch):
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    store = Store(tmp_path / "reviews")
    _write_session(store)
    server = serve_inline_review(store, ISSUE, port=0)
    thread = _start(server)
    try:
        status, names, body = _fetch(server, token=TOKEN)
    finally:
        _stop(server, thread)
    assert status == 404
    assert json.loads(body.decode("utf-8")) == {"error": "not_found"}
    assert b"Missing validation" not in body
    assert "access-control-allow-origin" not in names


@pytest.mark.parametrize("host", ["0.0.0.0", "localhost", "::1"])
def test_non_loopback_bind_is_rejected(tmp_path, monkeypatch, host):
    monkeypatch.setenv(BRIDGE_TOKEN_ENV, TOKEN)
    store = Store(tmp_path / "reviews")
    with pytest.raises(WorkflowError, match="127.0.0.1"):
        serve_inline_review(store, ISSUE, host=host, port=0)
    with pytest.raises(WorkflowError, match="127.0.0.1"):
        InlineReviewServer((host, 0), TOKEN, lambda *_args: None)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_empty_token_refuses_to_listen(tmp_path, monkeypatch, value):
    if value is None:
        monkeypatch.delenv(BRIDGE_TOKEN_ENV, raising=False)
    else:
        monkeypatch.setenv(BRIDGE_TOKEN_ENV, value)
    store = Store(tmp_path / "reviews")
    with pytest.raises(WorkflowError, match="REVIEW_PILOT_BRIDGE_TOKEN"):
        serve_inline_review(store, ISSUE, port=8765)


def test_sha_defaults_to_pr_shas_for_the_selected_pull_request(tmp_path):
    store = Store(tmp_path / "reviews")
    _write_session(store, sha=SHA1, active_sha=SHA2)
    assert resolve_inline_review_target(store, ISSUE, pr=None, sha=None) == (OWNER, REPO, NUMBER, SHA1)
    assert resolve_inline_review_target(store, ISSUE, pr="acme/gadgets#12", sha=None) == (
        "acme",
        "gadgets",
        12,
        SHA2,
    )
    assert resolve_inline_review_target(store, ISSUE, pr=None, sha="d" * 40)[3] == "d" * 40


def test_diff_patch_fallback_and_diff_lines_preference(tmp_path):
    store = Store(tmp_path / "reviews")
    _write_review(store, diff_lines=False)
    from_patch = snapshot_for_store(store, ISSUE, OWNER, REPO, NUMBER, SHA1)
    assert from_patch is not None
    assert from_patch["findings"][0]["on_diff"] is True
    assert "```suggestion" in from_patch["findings"][0]["body"]

    commit = store.commit_dir(ISSUE, OWNER, REPO, NUMBER, SHA1)
    write_json(commit / "review" / "diff-lines.json", [["src/Example.cs", 10, "RIGHT"]])
    from_lines = snapshot_for_store(store, ISSUE, OWNER, REPO, NUMBER, SHA1)
    assert from_lines is not None
    by_id = {row["id"]: row for row in from_lines["findings"]}
    assert by_id["F001"]["on_diff"] is False
    assert by_id["F002"]["on_diff"] is True
    assert by_id["F002"]["start_line"] is None
    assert "```suggestion" not in by_id["F001"]["body"]
    assert "Missing validation" in from_lines["summary_block"]


def test_cli_serve_inline_review_has_no_token_or_bind_flag():
    args = build_parser().parse_args([ISSUE, "serve-inline-review"])
    assert args.command == "serve-inline-review"
    assert args.pr is None
    assert args.sha is None
    assert args.port == DEFAULT_BRIDGE_PORT == 8765
    assert "token" not in args
    with pytest.raises(SystemExit):
        build_parser().parse_args([ISSUE, "serve-inline-review", "--token", TOKEN])
    with pytest.raises(SystemExit):
        build_parser().parse_args([ISSUE, "serve-inline-review", "--bind", "0.0.0.0"])
