"""
Tests for git_utils functions.

Run with: uv run pytest tests/utils/test_git_utils.py -v
"""

import subprocess

import pytest

from turbowrap.utils.git_utils import GitStatus, get_repo_status


@pytest.fixture
def git_repo(tmp_path):
    """Create a temporary git repository."""
    repo = tmp_path / "test_repo"
    repo.mkdir()

    # Initialize git repo
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    # Create initial commit
    (repo / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    return repo


@pytest.fixture
def git_repo_with_remote(tmp_path):
    """Create a git repo with a bare remote for ahead/behind testing."""
    # Create bare remote with main as default branch
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(
        ["git", "symbolic-ref", "HEAD", "refs/heads/main"],
        cwd=remote,
        check=True,
        capture_output=True,
    )

    # Create local repo (not a clone, since remote is empty)
    local = tmp_path / "local"
    local.mkdir()
    subprocess.run(["git", "init"], cwd=local, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        cwd=local,
        check=True,
        capture_output=True,
    )

    # Configure user
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=local,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=local,
        check=True,
        capture_output=True,
    )

    # Create initial commit on main branch and push
    subprocess.run(["git", "checkout", "-b", "main"], cwd=local, check=True, capture_output=True)
    (local / "README.md").write_text("# Test Repo")
    subprocess.run(["git", "add", "."], cwd=local, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=local,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"], cwd=local, check=True, capture_output=True
    )

    return {"local": local, "remote": remote}


class TestGetRepoStatus:
    """Tests for get_repo_status function."""

    def test_clean_repo_status(self, git_repo):
        """Clean repository returns is_clean=True."""
        status = get_repo_status(git_repo)

        assert isinstance(status, GitStatus)
        assert status.is_clean is True
        assert status.modified == []
        assert status.untracked == []

    def test_modified_files_detected(self, git_repo):
        """Modified files are detected."""
        # Modify a tracked file
        (git_repo / "README.md").write_text("# Modified")

        status = get_repo_status(git_repo)

        assert status.is_clean is False
        assert "README.md" in status.modified

    def test_untracked_files_detected(self, git_repo):
        """Untracked files are detected."""
        # Create new untracked file
        (git_repo / "new_file.txt").write_text("new content")

        status = get_repo_status(git_repo)

        assert status.is_clean is False
        assert "new_file.txt" in status.untracked


class TestGetRepoStatusAheadBehind:
    """Tests for ahead/behind calculation in get_repo_status."""

    def test_in_sync_with_remote(self, git_repo_with_remote):
        """Repo in sync shows ahead=0, behind=0."""
        local = git_repo_with_remote["local"]

        status = get_repo_status(local)

        assert status.ahead == 0
        assert status.behind == 0

    def test_ahead_of_remote(self, git_repo_with_remote):
        """Local commits not pushed show ahead > 0."""
        local = git_repo_with_remote["local"]

        # Create local commit without pushing
        (local / "local_change.txt").write_text("local only")
        subprocess.run(["git", "add", "."], cwd=local, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Local commit"],
            cwd=local,
            check=True,
            capture_output=True,
        )

        status = get_repo_status(local)

        assert status.ahead == 1
        assert status.behind == 0

    def test_behind_remote(self, git_repo_with_remote):
        """Remote commits not pulled show behind > 0."""
        local = git_repo_with_remote["local"]
        remote = git_repo_with_remote["remote"]

        # Create another clone, make commit, push
        other = local.parent / "other"
        subprocess.run(["git", "clone", str(remote), str(other)], check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "other@test.com"],
            cwd=other,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Other User"],
            cwd=other,
            check=True,
            capture_output=True,
        )
        (other / "remote_change.txt").write_text("from other")
        subprocess.run(["git", "add", "."], cwd=other, check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Remote commit"],
            cwd=other,
            check=True,
            capture_output=True,
        )
        subprocess.run(["git", "push"], cwd=other, check=True, capture_output=True)

        # Fetch in local to update remote tracking
        subprocess.run(["git", "fetch"], cwd=local, check=True, capture_output=True)

        status = get_repo_status(local)

        assert status.ahead == 0
        assert status.behind == 1
