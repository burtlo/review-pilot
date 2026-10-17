import subprocess
from pathlib import Path

from review_ticket.checkout import add_worktree
from review_ticket.runner import SubprocessRunner


def test_worktree_checkout_does_not_move_the_source_branch(tmp_path: Path):
    source = tmp_path / "repo"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "review@example.com")
    _git(source, "config", "user.name", "Reviewer")
    (source / "README.md").write_text("one\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "one")
    first = _git(source, "rev-parse", "HEAD").strip()
    (source / "README.md").write_text("two\n", encoding="utf-8")
    _git(source, "commit", "-am", "two")
    second = _git(source, "rev-parse", "HEAD").strip()

    dest = tmp_path / "review-checkout"
    add_worktree(SubprocessRunner(), "git", source, dest, first)

    assert _git(dest, "rev-parse", "HEAD").strip() == first
    assert _git(source, "rev-parse", "HEAD").strip() == second
    assert _git(source, "branch", "--show-current").strip() == "main"
    assert (dest / "README.md").read_text(encoding="utf-8") == "one\n"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True)
