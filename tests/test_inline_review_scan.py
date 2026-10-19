"""Golden scan text for inline placement. Publish stays unmarked."""

from __future__ import annotations

import json
from pathlib import Path

from review_ticket.findings import build_review_payload
from review_ticket.inline_review import build_snapshot
from review_ticket.textutil import parse_unified_diff
from tests.support import DIFF

FIXTURES = Path(__file__).parent / "fixtures" / "inline_review"
SHA = "a" * 40

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
    "side": "RIGHT",
    "title": "Unrelated helper",
    "explanation": "This behavior lives outside the diff.",
    "decision": "accept",
}


def _golden(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8").strip()


def test_scan_text_matches_golden_and_marker_is_outside_the_fence():
    index = parse_unified_diff(DIFF)
    snapshot = build_snapshot(
        issue="RP-1",
        owner="acme",
        repo="widgets",
        number=87,
        sha=SHA,
        findings=[ON_DIFF, OFF_DIFF],
        diff_index=index,
    )
    inline = snapshot["findings"][0]
    body = inline["body"]
    fence = body.index("```suggestion")
    close = body.index("```", fence + len("```suggestion"))
    marker = body.index("review-pilot finding F001")
    comment = body.index("<!-- review-pilot:finding:F001 -->")
    assert fence < close < marker < comment
    assert "review-pilot finding F001" not in body[:close]
    assert inline["scan_text"] == _golden("scan_text_f001.golden.txt")
    assert "```" not in inline["scan_text"]
    assert "<!--" not in inline["scan_text"]
    assert "**" not in inline["scan_text"]

    off = snapshot["findings"][1]
    assert off["on_diff"] is False
    assert off["scan_text"] == _golden("scan_text_f002.golden.txt")
    assert "review-pilot finding F002" in snapshot["summary_block"]
    assert "```suggestion" not in off["body"]


def test_publish_payload_has_no_finding_marker():
    payload = build_review_payload(
        sha=SHA,
        event="REQUEST_CHANGES",
        summary="Please validate quantity.",
        findings=[ON_DIFF, OFF_DIFF],
        diff_index=parse_unified_diff(DIFF),
    )
    encoded = json.dumps(payload)
    assert "review-pilot finding" not in encoded
    assert "review-pilot:finding" not in encoded
    assert "```suggestion" in payload["comments"][0]["body"]
