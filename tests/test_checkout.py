import subprocess
from pathlib import Path

from review_ticket.checkout import add_worktree, ensure_checkout
from review_ticket.config import Config
from review_ticket.models import ToolError
from review_ticket.runner import CommandResult, ScriptedRunner, SubprocessRunner


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


def test_ensure_checkout_runs_checkout_command_and_verifies_sha(tmp_path: Path):
    source = tmp_path / "org-clone"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "review@example.com")
    _git(source, "config", "user.name", "Reviewer")
    (source / "README.md").write_text("snapshot\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "snapshot")
    sha = _git(source, "rev-parse", "HEAD").strip()

    dest = tmp_path / "artifact-checkout"

    def run_custom_checkout(argv: list[str], cwd: str | None, data: str | None, env: dict | None) -> CommandResult:
        assert str(dest) in argv
        assert sha in argv
        assert "acme/widgets" in argv
        add_worktree(SubprocessRunner(), "git", source, dest, sha)
        return CommandResult(argv=list(argv), returncode=0, stdout="", stderr="")

    runner = ScriptedRunner()
    runner.when(lambda argv: argv and argv[0] == "review-ticket-checkout-stub", run_custom_checkout)
    runner.respond("rev-parse", stdout=sha)

    config = Config(
        reviews_dir=tmp_path / "reviews",
        cache_dir=tmp_path / "cache",
        checkout_command="review-ticket-checkout-stub {repository} {sha} {dest}",
    )
    result = ensure_checkout(
        runner,
        config,
        owner="acme",
        repo="widgets",
        sha=sha,
        dest=dest,
    )

    assert result == dest
    assert _git(dest, "rev-parse", "HEAD").strip() == sha
    assert len(runner.calls) == 2
    assert runner.calls[0][0] == "review-ticket-checkout-stub"
    assert runner.calls[1][:2] == ["git", "rev-parse"]


def test_ensure_checkout_reuses_dest_when_sha_matches(tmp_path: Path):
    source = tmp_path / "org-clone"
    source.mkdir()
    _git(source, "init", "-b", "main")
    _git(source, "config", "user.email", "review@example.com")
    _git(source, "config", "user.name", "Reviewer")
    (source / "README.md").write_text("snapshot\n", encoding="utf-8")
    _git(source, "add", "README.md")
    _git(source, "commit", "-m", "snapshot")
    sha = _git(source, "rev-parse", "HEAD").strip()
    dest = tmp_path / "artifact-checkout"
    add_worktree(SubprocessRunner(), "git", source, dest, sha)

    runner = ScriptedRunner()

    def capture_checkout(argv: list[str], cwd: str | None, data: str | None, env: dict | None) -> CommandResult:
        raise AssertionError(f"checkout_command should not run: {argv}")

    runner.when(lambda argv: argv and argv[0] == "should-not-run", capture_checkout)
    runner.respond("rev-parse", stdout=sha)

    config = Config(
        reviews_dir=tmp_path / "reviews",
        cache_dir=tmp_path / "cache",
        checkout_command="should-not-run",
    )
    ensure_checkout(runner, config, owner="acme", repo="widgets", sha=sha, dest=dest)

    assert not any(call and call[0] == "should-not-run" for call in runner.calls)
    assert runner.calls == [["git", "rev-parse", "HEAD"]]


def test_ensure_checkout_refuses_mismatched_existing_dest(tmp_path: Path):
    source = tmp_path / "org-clone"
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
    dest = tmp_path / "artifact-checkout"
    add_worktree(SubprocessRunner(), "git", source, dest, first)

    config = Config(reviews_dir=tmp_path, cache_dir=tmp_path, checkout_command="noop")
    try:
        ensure_checkout(
            SubprocessRunner(),
            config,
            owner="acme",
            repo="widgets",
            sha=second,
            dest=dest,
        )
    except ToolError as exc:
        assert "not the review snapshot" in str(exc)
    else:
        raise AssertionError("expected ToolError")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True)
