"""P3: filtered analyzer return draft vs all-findings listing."""

from __future__ import annotations

from review_ticket.storage import write_json
from review_ticket.util import sha256_text
from review_ticket.workflow import decide_analyzers
from tests.support import ISSUE, SHA1, SHA2, jira_document, make_app
from tests.test_status_projection import REF_A, REF_B, REF_C, _commit_dir, _pr_slug, _seed_checks


def _seed_three_pr_analyzer_blocker(tmp_path):
    root = tmp_path / "reviews" / ISSUE
    sha_c = "c" * 40
    write_json(
        root / "session.json",
        {
            "issue": ISSUE,
            "active_pr": REF_A,
            "active_sha": SHA1,
            "active_prs": [REF_A, REF_B, REF_C],
            "pr_shas": {REF_A: SHA1, REF_B: SHA2, REF_C: sha_c},
            "pr_scope": "all",
            "decisions": {
                "testing_notes": {
                    "choice": "accept",
                    "at": "2026-10-17T00:00:00Z",
                    "notes_hash": sha256_text("Ran the cart tests and recorded the result."),
                }
            },
        },
    )
    for ref, sha in ((REF_A, SHA1), (REF_B, SHA2), (REF_C, sha_c)):
        commit = _commit_dir(tmp_path, ref, sha)
        commit.mkdir(parents=True, exist_ok=True)
        _seed_checks(commit)
        findings = []
        if ref == REF_C:
            findings = [
                {
                    "source": "bugbot",
                    "id": "bugbot:1",
                    "path": "src/Foo.cs",
                    "line": 134,
                    "url": "https://github.com/acme/tools/pull/3#discussion_r1",
                    "body": "Bugbot: potential null reference",
                    "attention": "unaddressed",
                }
            ]
        write_json(commit / "bugbot-findings.json", {"sha": sha, "findings": findings})
        write_json(commit / "codeql-findings.json", {"sha": sha, "findings": []})


def test_analyzer_return_draft_cites_only_blocking_pr(tmp_path):
    _seed_three_pr_analyzer_blocker(tmp_path)
    app, _runner, world = make_app(tmp_path)
    world.issue = jira_document("Ran the cart tests and recorded the result.")
    decide_analyzers(app, ISSUE, "return", "", revise=False)
    draft = (tmp_path / "reviews" / ISSUE / "return-comment.md").read_text(encoding="utf-8")
    assert REF_C in draft
    assert "potential null reference" in draft
    assert REF_A not in draft
    assert REF_B not in draft
    assert "build" not in draft.lower() or "checks" not in draft.lower()
