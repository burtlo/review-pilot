"""Subprocess execution, with a scripted runner for tests."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable, Protocol


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str


class Runner(Protocol):
    def run(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        input: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult: ...


class SubprocessRunner:
    def run(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        input: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            input=input,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
        return CommandResult(
            argv=list(argv),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )


Handler = Callable[..., CommandResult]


class ScriptedRunner:
    """First matching predicate wins. Unmatched commands raise."""

    def __init__(self) -> None:
        self.routes: list[tuple[Callable[[list[str]], bool], Handler]] = []
        self.calls: list[list[str]] = []

    def when(self, predicate: Callable[[list[str]], bool], handler: Handler) -> ScriptedRunner:
        self.routes.append((predicate, handler))
        return self

    def respond(
        self,
        *parts: str,
        stdout: str = "",
        stderr: str = "",
        code: int = 0,
    ) -> ScriptedRunner:
        def predicate(argv: list[str]) -> bool:
            haystack = argv
            return all(part in haystack for part in parts)

        def handler(argv: list[str], cwd: str | None, data: str | None, env: dict[str, str] | None) -> CommandResult:
            return CommandResult(argv=list(argv), returncode=code, stdout=stdout, stderr=stderr)

        return self.when(predicate, handler)

    def run(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        input: str | None = None,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        self.calls.append(list(argv))
        for predicate, handler in self.routes:
            if predicate(argv):
                return handler(argv, cwd, input, env)
        joined = " ".join(argv)
        raise AssertionError(f"No scripted response for: {joined}")

    def saw(self, *parts: str) -> bool:
        return any(all(part in call for part in parts) for call in self.calls)
