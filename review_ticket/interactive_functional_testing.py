"""Local state for the functional testing track (spec §12)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from review_ticket.interactive_triage import TRACK_DISPOSITIONS, confirm_blocker, set_track_disposition
from review_ticket.models import WorkflowError


@dataclass
class FunctionalTestingState:
    steps: str = ""
    observed: str = ""
    expected: str = ""
    plan_reference: str = ""
    notes: str = ""
    scenarios: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    result: str | None = None
    disposition: str | None = None
    blocker_confirmed: bool = False
    completed: bool = False


def environment_blocks_request_changes(result: str | None, failure_kind: str | None) -> bool:
    if result == "blocked":
        return True
    if result == "fail" and failure_kind == "environment":
        return True
    return False


def load_functional_testing_state(existing: dict[str, Any] | None) -> FunctionalTestingState:
    document = existing if isinstance(existing, dict) else {}
    disposition = document.get("disposition")
    if disposition not in TRACK_DISPOSITIONS:
        disposition = None
    result = document.get("result")
    if result not in {"pass", "fail", "blocked"}:
        result = None
    blocker_confirmed = bool(document.get("p9_handoff")) and disposition == "REQUEST_CHANGES"
    scenarios = [str(item).strip() for item in (document.get("scenarios") or []) if str(item).strip()]
    evidence = [str(item).strip() for item in (document.get("evidence") or []) if str(item).strip()]
    return FunctionalTestingState(
        steps=str(document.get("steps") or ""),
        observed=str(document.get("observed") or ""),
        expected=str(document.get("expected") or ""),
        plan_reference=str(document.get("plan_reference") or ""),
        notes=str(document.get("notes") or ""),
        scenarios=scenarios,
        evidence=evidence,
        result=result,
        disposition=disposition,
        blocker_confirmed=blocker_confirmed,
        completed=bool(document.get("completed")) if document else False,
    )


def functional_document_from_state(
    state: FunctionalTestingState,
    *,
    sha: str,
    completed: bool,
    failure_kind: str | None = None,
) -> dict[str, Any]:
    if completed and state.result not in {"pass", "fail", "blocked"}:
        raise WorkflowError("Choose Pass, Fail, or Blocked before saving the functional testing review.")
    if completed and state.disposition not in TRACK_DISPOSITIONS:
        raise WorkflowError("Choose Approve, Comment, or Request Changes before saving the functional testing review.")
    if completed and state.disposition == "REQUEST_CHANGES" and not state.blocker_confirmed:
        raise WorkflowError("Confirm the blocking problem before saving with Request Changes.")
    if state.disposition == "REQUEST_CHANGES" and environment_blocks_request_changes(state.result, failure_kind):
        raise WorkflowError("Environment blocks cannot use Request Changes disposition.")
    resolved_kind = failure_kind
    if state.result == "fail" and not resolved_kind:
        resolved_kind = "implementation"
    if state.result == "blocked":
        resolved_kind = "environment"
    if state.result == "pass":
        resolved_kind = None
    document: dict[str, Any] = {
        "sha": sha,
        "completed": completed,
        "steps": state.steps.strip(),
        "observed": state.observed.strip(),
        "expected": state.expected.strip(),
        "plan_reference": state.plan_reference.strip(),
        "notes": state.notes.strip(),
        "scenarios": list(state.scenarios),
        "evidence": list(state.evidence),
        "result": state.result,
        "failure_kind": resolved_kind,
        "disposition": state.disposition,
    }
    if state.disposition == "REQUEST_CHANGES" and state.blocker_confirmed:
        document["p9_handoff"] = True
    return document


def set_functional_disposition(state: FunctionalTestingState, disposition: str | None) -> None:
    set_track_disposition(state, disposition)


def confirm_functional_blocker(state: FunctionalTestingState) -> None:
    confirm_blocker(state)


def set_functional_result(state: FunctionalTestingState, result: str | None, *, failure_kind: str | None = None) -> None:
    if result is not None and result not in {"pass", "fail", "blocked"}:
        raise WorkflowError("Operational result must be pass, fail, or blocked.")
    state.result = result
    if environment_blocks_request_changes(result, failure_kind):
        if state.disposition == "REQUEST_CHANGES":
            state.disposition = None
        state.blocker_confirmed = False
