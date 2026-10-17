"""Explicit authorization gate for Jira and GitHub mutations."""

from __future__ import annotations

from collections.abc import Callable

from review_ticket.models import AuthorizationDenied


def authorize(
    *,
    preview: str,
    yes: bool,
    interactive: bool,
    prompt: Callable[[str], str] | None = None,
    write: Callable[[str], None] | None = None,
) -> None:
    if write:
        write(preview.rstrip() + "\n")
    if yes:
        return
    if not interactive:
        raise AuthorizationDenied(
            "This command changes Jira or GitHub. Re-run with --yes after reviewing the preview."
        )
    reader = prompt or input
    answer = reader("Authorize this action? [y/N] ")
    if answer.strip().lower() not in {"y", "yes"}:
        raise AuthorizationDenied("Authorization declined. Nothing was changed.")
