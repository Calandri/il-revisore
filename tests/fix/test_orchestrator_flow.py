"""
Test script for the new simplified FixOrchestrator flow.

Run with: uv run python tests/fix/test_orchestrator_flow.py
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from turbowrap.fix.models import (
    ExecutionStep,
    FixRequest,
    IssueEntry,
    IssueTodo,
    MasterTodo,
    MasterTodoSummary,
)
from turbowrap.fix.orchestrator import FixOrchestrator, generate_branch_name
from turbowrap.fix.todo_manager import TodoManager


def create_mock_issue(
    issue_code: str,
    file: str,
    title: str,
    description: str = "Test issue",
    line: int = 10,
) -> MagicMock:
    """Create a mock Issue object."""
    issue = MagicMock()
    issue.id = f"uuid-{issue_code}"
    issue.issue_code = issue_code
    issue.file = file
    issue.title = title
    issue.description = description
    issue.line = line
    issue.end_line = line + 5
    issue.severity = "HIGH"
    issue.category = "quality"
    issue.suggested_fix = "Fix the issue"
    issue.current_code = "# problematic code here"
    return issue


def test_generate_branch_name():
    """Test branch name generation."""
    print("\n=== Test: generate_branch_name ===")

    # Single issue
    issues = [create_mock_issue("BE-001", "src/api.py", "Missing null check")]
    branch = generate_branch_name(issues)
    print(f"Single issue: {branch}")
    assert branch.startswith("fix/")

    # Multiple issues
    issues = [
        create_mock_issue("BE-001", "src/api.py", "Missing null check"),
        create_mock_issue("BE-002", "src/db.py", "SQL injection risk"),
        create_mock_issue("BE-003", "src/auth.py", "Weak password hashing"),
    ]
    branch = generate_branch_name(issues)
    print(f"Multiple issues: {branch}")
    assert "and-2-more" in branch

    print("✅ generate_branch_name OK")


def test_create_todos():
    """Test TODO file creation."""
    print("\n=== Test: _create_todos ===")

    repo_path = Path("/tmp/test_repo")
    orchestrator = FixOrchestrator(repo_path)

    # Create mock issues - 2 on same file, 1 on different file
    issues = [
        create_mock_issue("BE-001", "src/api.py", "Issue 1"),
        create_mock_issue("BE-002", "src/api.py", "Issue 2"),  # Same file as BE-001
        create_mock_issue("FE-001", "src/app.js", "Issue 3"),  # Different file
    ]

    request = FixRequest(
        repository_id="test-repo",
        task_id="test-task",
        issue_ids=["BE-001", "BE-002", "FE-001"],
    )

    master_todo, issue_todos = orchestrator._create_todos(
        issues, "test-session", "fix/test-branch", request
    )

    print(f"Master TODO: {master_todo.session_id}")
    print(f"Execution steps: {len(master_todo.execution_steps)}")
    print(f"Issue TODOs: {len(issue_todos)}")

    # Verify structure
    assert len(master_todo.execution_steps) == 2, "Should have 2 steps (parallel + serial)"
    assert len(issue_todos) == 3, "Should have 3 issue TODOs"

    # Step 1: Parallel (BE-001 and FE-001 - different files)
    step1 = master_todo.execution_steps[0]
    print(f"Step 1: {len(step1.issues)} issues - {step1.reason}")
    assert step1.step == 1
    assert len(step1.issues) == 2  # BE-001 and FE-001

    # Step 2: Serial (BE-002 - same file as BE-001)
    step2 = master_todo.execution_steps[1]
    print(f"Step 2: {len(step2.issues)} issues - {step2.reason}")
    assert step2.step == 2
    assert len(step2.issues) == 1  # BE-002

    print("✅ _create_todos OK")


async def test_todo_manager():
    """Test TodoManager save/load."""
    print("\n=== Test: TodoManager ===")

    session_id = "test-todo-manager"
    todo_manager = TodoManager(session_id)

    # Create test data
    master_todo = MasterTodo(
        session_id=session_id,
        branch_name="fix/test",
        execution_steps=[
            ExecutionStep(
                step=1,
                reason="Test step",
                issues=[
                    IssueEntry(
                        code="TEST-001",
                        todo_file=f"/tmp/fix_session_{session_id}/fix_todo_TEST-001.json",
                        agent_type="fixer-single",
                    )
                ],
            )
        ],
        summary=MasterTodoSummary(total_issues=1, total_steps=1),
    )

    issue_todo = IssueTodo(
        issue_code="TEST-001",
        issue_id="uuid-test",
        file="src/test.py",
        line=10,
        title="Test Issue",
    )

    # Save
    paths = await todo_manager.save_all(master_todo, [issue_todo])
    print(f"Saved to: {paths}")

    # Verify files exist
    master_path = todo_manager.get_local_path()
    print(f"Master TODO path: {master_path}")
    assert master_path.exists(), "Master TODO file should exist"

    issue_path = todo_manager.get_local_path("TEST-001")
    print(f"Issue TODO path: {issue_path}")
    assert issue_path.exists(), "Issue TODO file should exist"

    # Load back
    loaded_master = await todo_manager.load_master_todo()
    assert loaded_master is not None
    print(f"Loaded master: {loaded_master.session_id}")

    loaded_issue = await todo_manager.load_issue_todo("TEST-001")
    assert loaded_issue is not None
    print(f"Loaded issue: {loaded_issue.issue_code}")

    # Cleanup
    await todo_manager.cleanup()
    print("✅ TodoManager OK")


def test_build_prompts():
    """Test prompt building."""
    print("\n=== Test: Prompt Building ===")

    repo_path = Path("/tmp/test_repo")
    orchestrator = FixOrchestrator(repo_path)

    # Test fix prompt
    fix_prompt = orchestrator._build_fix_prompt(
        master_todo_path=Path("/tmp/fix_session_test/master_todo.json"),
        branch_name="fix/test-issue",
        workspace_path=None,
    )
    print(f"Fix prompt length: {len(fix_prompt)} chars")
    assert "master_todo" in fix_prompt.lower()
    assert "fix/test-issue" in fix_prompt

    # Test refix prompt
    refix_prompt = orchestrator._build_refix_prompt(
        failed_codes=["BE-001", "BE-002"],
        gemini_feedback="## BE-001\nIncorrect fix\n## BE-002\nMissing edge case",
    )
    print(f"Refix prompt length: {len(refix_prompt)} chars")
    assert "BE-001" in refix_prompt
    assert "BE-002" in refix_prompt
    assert "Gemini" in refix_prompt

    print("✅ Prompt building OK")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing New FixOrchestrator")
    print("=" * 60)

    # Sync tests
    test_generate_branch_name()
    test_create_todos()
    test_build_prompts()

    # Async tests
    asyncio.run(test_todo_manager())

    print("\n" + "=" * 60)
    print("✅ ALL TESTS PASSED!")
    print("=" * 60)
    print("\nNote: Full integration test requires Claude CLI and Gemini API.")
    print("Run the actual fix flow from the web UI to test end-to-end.")


if __name__ == "__main__":
    main()
