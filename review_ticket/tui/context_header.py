"""Persistent review context header for stacked TUI screens (spec §3.2)."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from review_ticket.util import short_sha


@dataclass(frozen=True, slots=True)
class ContextHeaderView:
    """Snapshot of session context shown above scrollable evidence."""

    issue_key: str
    title: str
    stage: str
    outcome: str | None = None
    active_pr: str | None = None
    full_sha: str | None = None
    sha_stale: bool = False
    recommendation: str | None = None


def format_context_header(view: ContextHeaderView) -> str:
    """Render a compact, single-block header with full SHA available in text."""

    parts: list[str] = [f"{view.issue_key} — {view.title}"]
    meta: list[str] = [f"Stage: {view.stage}"]
    if view.outcome:
        meta.append(f"Outcome: {view.outcome}")
    if view.active_pr:
        meta.append(f"PR {view.active_pr}")
    if view.full_sha:
        compact = short_sha(view.full_sha)
        meta.append(f"SHA {compact} ({view.full_sha})")
        if view.sha_stale:
            meta.append("SHA stale")
    if view.recommendation:
        meta.append(f"Recommend: {view.recommendation}")
    parts.append(" · ".join(meta))
    return "\n".join(parts)


class ContextHeader(Widget):
    """Read-only context strip; bind with :meth:`set_view`."""

    DEFAULT_CSS = """
    ContextHeader {
        width: 1fr;
        height: auto;
        padding: 0 1;
        background: $surface;
        border-bottom: tall $primary-darken-2;
    }
    ContextHeader Static {
        width: 1fr;
        height: auto;
    }
    """

    def __init__(self, view: ContextHeaderView | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._view = view

    def compose(self) -> ComposeResult:
        text = format_context_header(self._view) if self._view else ""
        yield Static(text, id="context-header-text")

    def set_view(self, view: ContextHeaderView) -> None:
        self._view = view
        self.query_one("#context-header-text", Static).update(format_context_header(view))
