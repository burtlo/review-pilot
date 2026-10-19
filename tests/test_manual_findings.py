"""P8: manual finding merge and duplicate suppression."""

from review_ticket.findings import build_review_payload
from review_ticket.interactive_triage import proposed_payload_from_human
from review_ticket.manual_review import suppress_duplicate_manual_findings
from review_ticket.textutil import parse_unified_diff
from tests.support import DIFF, make_app
from tests.test_acceptance import _commit, _seed_publishable


def test_duplicate_manual_finding_suppressed_in_preview_list(tmp_path):
    commit = _commit(tmp_path, "a" * 40)
    _seed_publishable(tmp_path, "a" * 40)
    human = {
        "rejected_review": False,
        "findings": {
            "F001": {"decision": "accept", "must_fix": True},
        },
        "added": [],
        "summary": "Automated",
    }
    machine = [
        {
            "id": "F001",
            "title": "Null risk",
            "must_fix": True,
            "path": "src/Example.cs",
            "line": 142,
            "side": "RIGHT",
            "explanation": "Handle null lookup.",
        }
    ]
    manual = [
        {
            "path": "src/Example.cs",
            "line": 142,
            "blocking": True,
            "text": "Handle null lookup.",
        },
        {
            "path": "src/Other.cs",
            "line": 10,
            "blocking": False,
            "text": "Naming only.",
        },
    ]
    kept = suppress_duplicate_manual_findings(manual, human, machine)
    assert len(kept) == 1
    assert kept[0]["path"] == "src/Other.cs"


def test_publication_eligibility_still_false_without_manual_review_file(tmp_path):
    from review_ticket.tracks import publication_eligibility

    commit = _commit(tmp_path, "a" * 40)
    _seed_publishable(tmp_path, "a" * 40)
    allowed, reason = publication_eligibility("APPROVE", commit, expected_sha="a" * 40)
    assert not allowed
    assert "manual" in reason.casefold()
