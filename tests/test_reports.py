from review_ticket.findings import build_review_payload
from review_ticket.reports import publish_preview_counts_for_findings, review_preview


def test_review_preview_inline_count_matches_build_review_payload():
    sha = "abc123def456"
    diff_index = {("src/Example.cs", 142, "RIGHT")}
    findings = [
        {
            "id": "F001",
            "priority": "high",
            "must_fix": True,
            "path": "src/Example.cs",
            "line": 142,
            "side": "RIGHT",
            "title": "On diff",
            "explanation": "inline",
        },
        {
            "id": "F002",
            "priority": "low",
            "must_fix": False,
            "path": "src/Other.cs",
            "line": 9,
            "side": "RIGHT",
            "title": "Off diff",
            "explanation": "summary",
        },
    ]
    document = {"summary": "Needs work.", "findings": findings}
    payload = build_review_payload(
        sha=sha,
        event="REQUEST_CHANGES",
        summary=document["summary"],
        findings=findings,
        diff_index=diff_index,
    )
    inline, summary_only = publish_preview_counts_for_findings(findings, diff_index)
    assert inline == len(payload["comments"]) == 1
    assert summary_only == 1

    markdown = review_preview(
        sha=sha,
        document=document,
        findings=findings,
        diff_index=diff_index,
        payload=payload,
    )
    assert "F001 On diff" in markdown
    assert "F002 Off diff" in markdown
    assert "**1** inline comment(s)" in markdown
    assert "**1** finding(s) in the review summary only" in markdown
    assert "pending" in markdown
