"""Local state for the manual code review track (spec §10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from review_ticket.findings import apply_human_decisions, manual_findings_for_publication
from review_ticket.models import WorkflowError
from review_ticket.interactive_triage import TRACK_DISPOSITIONS, confirm_blocker, set_track_disposition


@dataclass
class ManualFindingState:
    finding_id: str
    path: str | None
    line: int | None
    blocking: bool
    text: str

    def as_record(self) -> dict[str, Any]:
        record: dict[str, Any] = {
            "path": self.path or None,
            "line": self.line if isinstance(self.line, int) else None,
            "blocking": bool(self.blocking),
            "text": self.text.strip(),
        }
        if self.finding_id:
            record["id"] = self.finding_id
        return record


@dataclass
class ManualReviewState:
    notes: str = ""
    disposition: str | None = None
    blocker_confirmed: bool = False
    completed: bool = False
    findings: list[ManualFindingState] = field(default_factory=list)
    _next_id: int = 1

    def add_finding(
        self,
        *,
        path: str | None,
        line: int | None,
        text: str,
        blocking: bool = False,
    ) -> ManualFindingState:
        body = text.strip()
        if not body:
            raise WorkflowError("Manual finding text cannot be empty.")
        token = f"M{self._next_id:03d}"
        self._next_id += 1
        item = ManualFindingState(
            finding_id=token,
            path=path.strip() if path and path.strip() else None,
            line=line,
            blocking=blocking,
            text=body,
        )
        self.findings.append(item)
        return item

    def remove_finding(self, finding_id: str) -> None:
        for index, item in enumerate(self.findings):
            if item.finding_id == finding_id:
                self.findings.pop(index)
                return
        raise WorkflowError(f"Unknown manual finding {finding_id!r}.")


def load_manual_review_state(
    existing: dict[str, Any] | None,
    *,
    completed_default: bool = False,
) -> ManualReviewState:
    document = existing if isinstance(existing, dict) else {}
    findings: list[ManualFindingState] = []
    max_id = 0
    for index, raw in enumerate(document.get("findings") or [], start=1):
        if not isinstance(raw, dict):
            continue
        token = str(raw.get("id") or f"M{index:03d}")
        if token.startswith("M") and token[1:].isdigit():
            max_id = max(max_id, int(token[1:]))
        line = raw.get("line")
        findings.append(
            ManualFindingState(
                finding_id=token,
                path=str(raw.get("path") or "").strip() or None,
                line=line if isinstance(line, int) else None,
                blocking=bool(raw.get("blocking")),
                text=str(raw.get("text") or "").strip(),
            )
        )
    disposition = document.get("disposition")
    if disposition not in TRACK_DISPOSITIONS:
        disposition = None
    blocker_confirmed = bool(document.get("p9_handoff")) and disposition == "REQUEST_CHANGES"
    return ManualReviewState(
        notes=str(document.get("notes") or ""),
        disposition=disposition,
        blocker_confirmed=blocker_confirmed,
        completed=bool(document.get("completed")) if document else completed_default,
        findings=findings,
        _next_id=max(max_id, len(findings)) + 1,
    )


def manual_document_from_state(state: ManualReviewState, *, sha: str, completed: bool) -> dict[str, Any]:
    if completed and state.disposition not in TRACK_DISPOSITIONS:
        raise WorkflowError("Choose Approve, Comment, or Request Changes before completing manual review.")
    if completed and state.disposition == "REQUEST_CHANGES" and not state.blocker_confirmed:
        raise WorkflowError("Confirm the blocking problem before completing with Request Changes.")
    document: dict[str, Any] = {
        "sha": sha,
        "completed": completed,
        "notes": state.notes.strip(),
        "findings": [item.as_record() for item in state.findings],
        "disposition": state.disposition,
    }
    if state.disposition == "REQUEST_CHANGES" and state.blocker_confirmed:
        document["p9_handoff"] = True
    return document


def publication_preview_manual_findings(
    state: ManualReviewState,
    *,
    document: dict[str, Any],
    human: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    manual_rows = [item.as_record() for item in state.findings]
    if not human or human.get("rejected_review"):
        return manual_rows
    selected = apply_human_decisions(document.get("findings") or [], human)
    return manual_findings_for_publication(manual_rows, selected_automated=selected)


def set_manual_disposition(state: ManualReviewState, disposition: str | None) -> None:
    set_track_disposition(state, disposition)


def confirm_manual_blocker(state: ManualReviewState) -> None:
    confirm_blocker(state)
