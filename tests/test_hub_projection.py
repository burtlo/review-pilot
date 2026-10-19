"""P5: hub projection over track_projection."""

from __future__ import annotations

from review_ticket.hub_projection import github_outcome_from_receipt, project_review_hub
from review_ticket.status_projection import PublicationReceipt

from tests.support import ISSUE
from tests.test_status_projection import _seed_three_pr_session, _store


def test_github_outcome_uses_receipt_only():
    assert github_outcome_from_receipt(None) == "Not published"
    assert (
        github_outcome_from_receipt(
            PublicationReceipt(status="success", event="COMMENT", published_at=None, recorded_at=None)
        )
        == "COMMENT"
    )
    assert (
        github_outcome_from_receipt(
            PublicationReceipt(status="pending", event="APPROVE", published_at=None, recorded_at=None)
        )
        == "Not published"
    )


def test_project_review_hub_uses_three_tracks_per_pr(tmp_path):
    _seed_three_pr_session(tmp_path)
    projection = project_review_hub(_store(tmp_path), ISSUE)
    assert len(projection.pr_blocks) == 3
    for block in projection.pr_blocks:
        assert len(block.tracks) == 3
        kinds = {row.kind for row in block.tracks}
        assert kinds == {"automated", "manual", "functional"}
    assert projection.ticket_dock_enabled is False
