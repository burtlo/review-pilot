"""Shared outcome and result types.

Outcomes are report labels for the reviewer. They are not a workflow engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Outcome(str, Enum):
    WAITING = "WAITING"
    ACTION_REQUIRED = "ACTION_REQUIRED"
    REVIEW_DECISION = "REVIEW_DECISION"
    READY = "READY"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"


class ToolError(RuntimeError):
    """A CLI or API the workflow shells out to failed."""

    def __init__(
        self,
        message: str,
        *,
        unavailable: bool = False,
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.unavailable = unavailable
        self.returncode = returncode


class WorkflowError(RuntimeError):
    """The requested command cannot run against the current artifacts."""


class AuthorizationDenied(RuntimeError):
    """An external mutation was not explicitly authorized."""


@dataclass
class StepResult:
    step: str
    outcome: Outcome
    summary: str
    recommendation: str | None = None
    next_command: str | None = None
    report_path: str | None = None
    jira_mutated: bool = False
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step": self.step,
            "outcome": self.outcome.value,
            "summary": self.summary,
            "recommendation": self.recommendation,
            "next_command": self.next_command,
            "report_path": self.report_path,
            "jira_mutated": self.jira_mutated,
            "details": self.details,
        }
