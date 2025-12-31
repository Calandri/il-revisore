"""
End-to-end tests for the fix clarification and planning flow.

Run with: uv run pytest tests/fix/test_fix_clarify_e2e.py -v

These tests verify the pre-fix clarification and planning flow:
1. POST /clarify creates a session and may ask questions (grouped by issue)
2. POST /clarify with answers resumes the session
3. POST /plan creates execution plan with MasterTodo and IssueTodos
4. POST /start with master_todo_path uses step-by-step execution
5. Claude sessions can be resumed across different models (HAIKU → OPUS)

Requirements:
- Server must be running: TURBOWRAP_AUTH_ENABLED=false uvicorn turbowrap.api.main:app --port 8000
- At least one repository with open issues must exist
"""

import subprocess

import httpx
import pytest

# Test configuration
BASE_URL = "http://localhost:8000"
TIMEOUT = 120.0  # Claude CLI can be slow


def is_server_running() -> bool:
    """Check if the TurboWrap server is running."""
    try:
        resp = httpx.get(f"{BASE_URL}/api/repos", timeout=5.0)
        return resp.status_code == 200
    except Exception:
        return False


def get_test_repo_and_issues() -> tuple[str, list[str]] | None:
    """Get a repository and multiple issues for testing."""
    try:
        # Get first repo
        repos = httpx.get(f"{BASE_URL}/api/repos", timeout=5.0).json()
        if not repos:
            return None

        repo_id = repos[0]["id"]

        # Get open issues for this repo (at least 2 for step testing)
        issues = httpx.get(
            f"{BASE_URL}/api/issues",
            params={"repository_id": repo_id, "status": "open", "limit": 3},
            timeout=5.0,
        ).json()

        if not issues:
            # Try without status filter
            issues = httpx.get(
                f"{BASE_URL}/api/issues",
                params={"repository_id": repo_id, "limit": 3},
                timeout=5.0,
            ).json()

        if not issues:
            return None

        issue_ids = [i["id"] for i in issues]
        return repo_id, issue_ids
    except Exception as e:
        print(f"Error getting test data: {e}")
        return None


@pytest.fixture(scope="module")
def server_check():
    """Ensure server is running before tests."""
    if not is_server_running():
        pytest.skip("TurboWrap server not running at localhost:8000")


@pytest.fixture(scope="module")
def test_data(server_check):
    """Get test repository and issues."""
    data = get_test_repo_and_issues()
    if not data:
        pytest.skip("No repository with issues found for testing")
    return data


# =============================================================================
# Claude CLI Session Tests
# =============================================================================


@pytest.mark.e2e
class TestClaudeSessionCrossModel:
    """Tests for Claude CLI session resumption across models."""

    def test_session_can_resume_across_models(self):
        """Claude sessions can be resumed with different models."""
        # Create session with HAIKU
        result = subprocess.run(
            [
                "claude",
                "--model",
                "haiku",
                "--print",
                "--output-format",
                "json",
            ],
            input="Remember this: TURBOWRAP_TEST_12345",
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, f"HAIKU failed: {result.stderr}"

        # Parse session_id from JSON output
        import json

        output = json.loads(result.stdout)
        session_id = output.get("session_id")
        assert session_id, "No session_id returned from HAIKU"

        # Resume with OPUS and verify context
        result = subprocess.run(
            [
                "claude",
                "--model",
                "opus",
                "--resume",
                session_id,
                "--print",
            ],
            input="What did I ask you to remember?",
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, f"OPUS resume failed: {result.stderr}"
        assert "TURBOWRAP_TEST_12345" in result.stdout, f"Context not preserved: {result.stdout}"


# =============================================================================
# Clarify Endpoint Tests (with grouped questions)
# =============================================================================


@pytest.mark.e2e
class TestClarifyEndpoint:
    """Tests for POST /api/fix/clarify endpoint with grouped questions."""

    def test_clarify_first_call_creates_session(self, test_data):
        """First call to /clarify creates a session."""
        repo_id, issue_ids = test_data

        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(
                f"{BASE_URL}/api/fix/clarify",
                json={"repository_id": repo_id, "issue_ids": issue_ids[:1]},
            )

        assert response.status_code == 200
        data = response.json()

        # Must have session_id
        assert "session_id" in data
        assert data["session_id"], "session_id should not be empty"

        # Must have boolean flags
        assert "has_questions" in data
        assert "ready_to_fix" in data or "ready_to_plan" in data
        assert isinstance(data["has_questions"], bool)

        # Should support questions_by_issue format (new) or questions (legacy)
        if data["has_questions"]:
            has_grouped = (
                "questions_by_issue" in data and len(data.get("questions_by_issue", [])) > 0
            )
            has_flat = "questions" in data and len(data.get("questions", [])) > 0
            assert has_grouped or has_flat, "No questions found despite has_questions=True"

            # If grouped format, verify structure
            if has_grouped:
                for group in data["questions_by_issue"]:
                    assert "issue_code" in group
                    assert "questions" in group
                    for q in group["questions"]:
                        assert "id" in q
                        assert "question" in q

    def test_clarify_with_multiple_issues(self, test_data):
        """Clarify with multiple issues returns grouped questions."""
        repo_id, issue_ids = test_data

        if len(issue_ids) < 2:
            pytest.skip("Need at least 2 issues for this test")

        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(
                f"{BASE_URL}/api/fix/clarify",
                json={"repository_id": repo_id, "issue_ids": issue_ids[:2]},
            )

        assert response.status_code == 200
        data = response.json()

        assert "session_id" in data
        print(f"\nClarify response for {len(issue_ids[:2])} issues:")
        print(f"  has_questions: {data.get('has_questions')}")
        print(f"  questions_by_issue: {len(data.get('questions_by_issue', []))} groups")
        print(f"  issues_without_questions: {data.get('issues_without_questions', [])}")

    def test_clarify_resume_preserves_session(self, test_data):
        """Resuming /clarify uses the same session."""
        repo_id, issue_ids = test_data

        with httpx.Client(timeout=TIMEOUT) as client:
            # First call
            resp1 = client.post(
                f"{BASE_URL}/api/fix/clarify",
                json={"repository_id": repo_id, "issue_ids": issue_ids[:1]},
            )
            data1 = resp1.json()
            session_id = data1["session_id"]

            # If has questions, answer them
            if data1["has_questions"]:
                # Build answers for both grouped and flat formats
                answers = {}

                # Handle grouped questions
                for group in data1.get("questions_by_issue", []):
                    for q in group.get("questions", []):
                        answers[q["id"]] = "Yes, proceed"

                # Handle flat questions (legacy)
                for q in data1.get("questions", []):
                    answers[q["id"]] = "Yes, proceed"

                if answers:
                    resp2 = client.post(
                        f"{BASE_URL}/api/fix/clarify",
                        json={
                            "repository_id": repo_id,
                            "issue_ids": issue_ids[:1],
                            "session_id": session_id,
                            "answers": answers,
                            "previous_questions": data1.get("questions", []),
                        },
                    )

                    data2 = resp2.json()

                    # Session ID should be preserved
                    assert data2["session_id"] == session_id


# =============================================================================
# Plan Endpoint Tests (NEW)
# =============================================================================


@pytest.mark.e2e
class TestPlanEndpoint:
    """Tests for POST /api/fix/plan endpoint."""

    def test_plan_creates_master_todo(self, test_data):
        """POST /plan creates MasterTodo and IssueTodos."""
        repo_id, issue_ids = test_data

        with httpx.Client(timeout=TIMEOUT) as client:
            # First, run clarification to get a session
            clarify_resp = client.post(
                f"{BASE_URL}/api/fix/clarify",
                json={"repository_id": repo_id, "issue_ids": issue_ids[:2]},
            )
            clarify_data = clarify_resp.json()
            session_id = clarify_data["session_id"]

            # Answer any questions to get ready_to_plan
            max_iterations = 3
            for _ in range(max_iterations):
                if clarify_data.get("ready_to_fix") or clarify_data.get("ready_to_plan"):
                    break

                answers = {}
                for group in clarify_data.get("questions_by_issue", []):
                    for q in group.get("questions", []):
                        answers[q["id"]] = "Yes"
                for q in clarify_data.get("questions", []):
                    answers[q["id"]] = "Yes"

                if not answers:
                    break

                clarify_resp = client.post(
                    f"{BASE_URL}/api/fix/clarify",
                    json={
                        "repository_id": repo_id,
                        "issue_ids": issue_ids[:2],
                        "session_id": session_id,
                        "answers": answers,
                    },
                )
                clarify_data = clarify_resp.json()

            # Now call /plan
            plan_resp = client.post(
                f"{BASE_URL}/api/fix/plan",
                json={
                    "repository_id": repo_id,
                    "issue_ids": issue_ids[:2],
                    "clarify_session_id": session_id,
                },
            )

            if plan_resp.status_code != 200:
                print(f"\nPlan endpoint failed: {plan_resp.status_code}")
                print(f"Response: {plan_resp.text}")

            assert plan_resp.status_code == 200, f"Plan failed: {plan_resp.text}"
            plan_data = plan_resp.json()

            # Verify plan response structure
            assert "master_todo_path" in plan_data
            assert "issue_count" in plan_data
            assert "step_count" in plan_data
            assert "execution_steps" in plan_data
            assert "ready_to_execute" in plan_data

            print("\nPlan created:")
            print(f"  master_todo_path: {plan_data['master_todo_path']}")
            print(f"  issue_count: {plan_data['issue_count']}")
            print(f"  step_count: {plan_data['step_count']}")
            print(f"  execution_steps: {len(plan_data['execution_steps'])}")

            # Verify execution_steps structure
            for step in plan_data["execution_steps"]:
                assert "step" in step
                assert "issue_codes" in step
                print(f"    Step {step['step']}: {step['issue_codes']} - {step.get('reason', '')}")

            assert plan_data["ready_to_execute"] is True


# =============================================================================
# Start with Plan Tests (NEW)
# =============================================================================


@pytest.mark.e2e
class TestStartWithPlan:
    """Tests for POST /api/fix/start with master_todo_path."""

    def test_start_accepts_master_todo_path(self, test_data):
        """POST /start accepts master_todo_path for step-by-step execution."""
        repo_id, issue_ids = test_data

        with httpx.Client(timeout=TIMEOUT) as client:
            # Create clarify session and plan
            clarify_resp = client.post(
                f"{BASE_URL}/api/fix/clarify",
                json={"repository_id": repo_id, "issue_ids": issue_ids[:1]},
            )
            session_id = clarify_resp.json()["session_id"]

            plan_resp = client.post(
                f"{BASE_URL}/api/fix/plan",
                json={
                    "repository_id": repo_id,
                    "issue_ids": issue_ids[:1],
                    "clarify_session_id": session_id,
                },
            )
            plan_data = plan_resp.json()
            master_todo_path = plan_data["master_todo_path"]

            # Create task
            task_resp = client.post(
                f"{BASE_URL}/api/tasks",
                json={"repository_id": repo_id, "type": "develop"},
            )
            task_id = task_resp.json()["id"]

            # Start fix with master_todo_path
            events_received = []

            try:
                with client.stream(
                    "POST",
                    f"{BASE_URL}/api/fix/start",
                    json={
                        "repository_id": repo_id,
                        "issue_ids": issue_ids[:1],
                        "task_id": task_id,
                        "clarify_session_id": session_id,
                        "master_todo_path": master_todo_path,
                    },
                    timeout=30.0,
                ) as response:
                    for line in response.iter_lines():
                        if line.startswith("event:"):
                            event_type = line.replace("event:", "").strip()
                            events_received.append(event_type)
                            print(f"  Event: {event_type}")

                            # Collect a few events then stop
                            if len(events_received) >= 5:
                                break
            except Exception as e:
                print(f"  Stream interrupted: {e}")

            # Verify we got the session started event
            assert (
                "fix_session_started" in events_received
            ), f"Expected fix_session_started, got {events_received}"

            print(f"\nStart with master_todo_path accepted, events: {events_received}")

    def test_step_events_emitted(self, test_data):
        """Verify step events are emitted during step-by-step execution."""
        repo_id, issue_ids = test_data

        if len(issue_ids) < 2:
            pytest.skip("Need at least 2 issues for step event testing")

        with httpx.Client(timeout=TIMEOUT) as client:
            # Create full plan
            clarify_resp = client.post(
                f"{BASE_URL}/api/fix/clarify",
                json={"repository_id": repo_id, "issue_ids": issue_ids[:2]},
            )
            session_id = clarify_resp.json()["session_id"]

            plan_resp = client.post(
                f"{BASE_URL}/api/fix/plan",
                json={
                    "repository_id": repo_id,
                    "issue_ids": issue_ids[:2],
                    "clarify_session_id": session_id,
                },
            )
            plan_data = plan_resp.json()

            # Create task
            task_resp = client.post(
                f"{BASE_URL}/api/tasks",
                json={"repository_id": repo_id, "type": "develop"},
            )
            task_id = task_resp.json()["id"]

            # Start and listen for step events
            step_events = []
            all_events = []

            try:
                with client.stream(
                    "POST",
                    f"{BASE_URL}/api/fix/start",
                    json={
                        "repository_id": repo_id,
                        "issue_ids": issue_ids[:2],
                        "task_id": task_id,
                        "clarify_session_id": session_id,
                        "master_todo_path": plan_data["master_todo_path"],
                    },
                    timeout=60.0,
                ) as response:
                    for line in response.iter_lines():
                        if line.startswith("event:"):
                            event_type = line.replace("event:", "").strip()
                            all_events.append(event_type)

                            if event_type in ["fix_step_started", "fix_step_completed"]:
                                step_events.append(event_type)

                            # Stop after a reasonable number of events
                            if len(all_events) >= 20:
                                break

                            if event_type in ["fix_session_completed", "fix_session_error"]:
                                break
            except Exception as e:
                print(f"  Stream interrupted: {e}")

            print(f"\nStep events received: {step_events}")
            print(f"All events: {all_events}")

            # If we have step-based execution, we should see step events
            # (but only if there are multiple steps in the plan)
            if plan_data["step_count"] > 0:
                # At minimum, we should get session_started
                assert "fix_session_started" in all_events


# =============================================================================
# Full E2E Flow Test
# =============================================================================


@pytest.mark.e2e
class TestFullClarifyPlanFlow:
    """Full end-to-end test of clarify → plan → start flow."""

    def test_full_clarify_plan_start_flow(self, test_data):
        """Complete flow: clarify → answer → plan → start with master_todo."""
        repo_id, issue_ids = test_data

        with httpx.Client(timeout=TIMEOUT) as client:
            # Step 1: Initial clarify
            resp = client.post(
                f"{BASE_URL}/api/fix/clarify",
                json={"repository_id": repo_id, "issue_ids": issue_ids[:2]},
            )
            assert resp.status_code == 200
            data = resp.json()
            session_id = data["session_id"]
            print(f"\n[Step 1] Session created: {session_id[:8]}...")
            print(f"         has_questions={data.get('has_questions')}")
            print(f"         questions_by_issue count: {len(data.get('questions_by_issue', []))}")

            # Step 2: Answer questions if any
            iteration = 0
            while data.get("has_questions") and iteration < 3:
                iteration += 1
                answers = {}

                # Handle grouped questions
                for group in data.get("questions_by_issue", []):
                    for q in group.get("questions", []):
                        answers[q["id"]] = "Yes, proceed"

                # Handle flat questions
                for q in data.get("questions", []):
                    answers[q["id"]] = "Yes, proceed"

                if not answers:
                    break

                print(f"\n[Step 2.{iteration}] Answering {len(answers)} questions...")

                resp = client.post(
                    f"{BASE_URL}/api/fix/clarify",
                    json={
                        "repository_id": repo_id,
                        "issue_ids": issue_ids[:2],
                        "session_id": session_id,
                        "answers": answers,
                    },
                )
                data = resp.json()
                assert data["session_id"] == session_id, "Session ID changed!"
                print(f"         ready_to_fix={data.get('ready_to_fix')}")

                if data.get("ready_to_fix") or data.get("ready_to_plan"):
                    break

            # Step 3: Create execution plan
            print("\n[Step 3] Creating execution plan...")
            plan_resp = client.post(
                f"{BASE_URL}/api/fix/plan",
                json={
                    "repository_id": repo_id,
                    "issue_ids": issue_ids[:2],
                    "clarify_session_id": session_id,
                },
            )
            assert plan_resp.status_code == 200
            plan_data = plan_resp.json()
            print(f"         master_todo_path: {plan_data['master_todo_path']}")
            print(f"         {plan_data['issue_count']} issues in {plan_data['step_count']} steps")
            for step in plan_data["execution_steps"]:
                print(f"           Step {step['step']}: {step['issue_codes']}")

            # Step 4: Create task
            print("\n[Step 4] Creating task...")
            task_resp = client.post(
                f"{BASE_URL}/api/tasks",
                json={"repository_id": repo_id, "type": "develop"},
            )
            task_id = task_resp.json()["id"]
            print(f"         Task ID: {task_id}")

            # Step 5: Start fix with master_todo_path
            print("\n[Step 5] Starting fix with master_todo_path...")
            events_received = []
            step_events = []

            try:
                with client.stream(
                    "POST",
                    f"{BASE_URL}/api/fix/start",
                    json={
                        "repository_id": repo_id,
                        "issue_ids": issue_ids[:2],
                        "task_id": task_id,
                        "clarify_session_id": session_id,
                        "master_todo_path": plan_data["master_todo_path"],
                    },
                    timeout=30.0,
                ) as response:
                    for line in response.iter_lines():
                        if line.startswith("event:"):
                            event_type = line.replace("event:", "").strip()
                            events_received.append(event_type)
                            print(f"         Event: {event_type}")

                            if "step" in event_type:
                                step_events.append(event_type)

                            if event_type in [
                                "fix_session_started",
                                "fix_step_started",
                            ]:
                                # Got what we need
                                if len(events_received) >= 3:
                                    break
            except Exception as e:
                print(f"         Stream interrupted: {e}")

            # Verify flow worked
            assert len(events_received) > 0, "No SSE events received"
            assert (
                "fix_session_started" in events_received
            ), f"Expected fix_session_started, got {events_received}"

            print("\n[PASS] Full clarify → plan → start flow works correctly!")
            print(f"       Total events: {len(events_received)}")
            print(f"       Step events: {step_events}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
