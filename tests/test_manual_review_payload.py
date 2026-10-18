"""P8: manual finding dedup for publication preview."""

from __future__ import annotations

from review_ticket.findings import (
    apply_human_decisions,
    manual_findings_for_publication,
    manual_finding_duplicates_automated,
)


def _selected_automated():
    document = {
        "findings": [
            {
                "id": "F001",
                "title": "Quantity check",
                "must_fix": True,
                "path": "src/Example.cs",
                "line": 142,
                "side": "RIGHT",
                "explanation": "Reject negative quantities.",
            }
        ]
    }
    human = {
        "rejected_review": False,
        "findings": {"F001": {"decision": "accept", "must_fix": True}},
        "added": [],
    }
    return apply_human_decisions(document["findings"], human)


def test_manual_finding_duplicate_suppressed_in_preview_list():
    selected = _selected_automated()
    manual = {
        "path": "src/Example.cs",
        "line": 142,
        "blocking": True,
        "text": "Reject  negative   quantities.",
    }
    assert manual_finding_duplicates_automated(manual, selected) is True
    preview = manual_findings_for_publication([manual], selected_automated=selected)
    assert preview == []


def test_distinct_manual_finding_stays_in_preview_list():
    selected = _selected_automated()
    manual = {
        "path": "src/Example.cs",
        "line": 142,
        "blocking": True,
        "text": "Different reviewer wording.",
    }
    assert manual_finding_duplicates_automated(manual, selected) is False
    preview = manual_findings_for_publication([manual], selected_automated=selected)
    assert len(preview) == 1
