"""Headless reviewer adapter and stub command tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from tests.support import ISSUE, make_app
from tests.test_acceptance import _ready_issue, _run

REPO_ROOT = Path(__file__).resolve().parent.parent
STUB = REPO_ROOT / "scripts" / "review-ticket-reviewer-stub.py"


def _stub_command() -> str:
    py = sys.executable.replace("\\", "/")
    stub = str(STUB).replace("\\", "/")
    return (
        f'"{py}" "{stub}" --context {{context}} --output {{output}} '
        f"--checkout {{checkout}} --repository {{repository}} --sha {{sha}} --issue {{issue}}"
    )


def test_stub_adapter_writes_schema_valid_json(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(STUB),
            "--context",
            str(tmp_path),
            "--output",
            str(tmp_path / "out.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2

    (tmp_path / "prompt.md").write_text("# context\n", encoding="utf-8")
    out = tmp_path / "out.json"
    result = subprocess.run(
        [sys.executable, str(STUB), "--context", str(tmp_path), "--output", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["approval_recommendation"] == "request_changes"
    assert payload["findings"][0]["title"]


def test_run_review_with_stub_adapter_reaches_human_review(tmp_path):
    app, runner, world = make_app(tmp_path, reviewer_command=_stub_command())
    _ready_issue(world)
    _run(app, [ISSUE, "notes", "--accept"])
    code = _run(app, [ISSUE, "run-review"])
    output = app.stdout.getvalue()
    assert code == 0
    assert "outcome: REVIEW_DECISION" in output
    assert "human-review" in output or "review apply" in output
    findings_path = tmp_path / "reviews" / ISSUE / "prs" / "acme-widgets-pr-87" / "commits"
    sha_dirs = list(findings_path.iterdir())
    assert sha_dirs
    review_dir = sha_dirs[0] / "review"
    assert (review_dir / "findings.json").is_file()
    stored = json.loads((review_dir / "findings.json").read_text(encoding="utf-8"))
    assert stored["findings"][0]["title"] == "Missing validation"
