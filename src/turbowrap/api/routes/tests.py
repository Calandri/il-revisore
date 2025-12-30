"""Test suite management routes."""

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ...db.models import (
    Repository,
    TestCase,
    TestRun,
    TestSuite,
)
from ..deps import get_db, get_or_404

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tests", tags=["tests"])


# =============================================================================
# Pydantic Schemas
# =============================================================================


class TestSuiteCreate(BaseModel):
    """Request to create a test suite."""

    repository_id: str = Field(..., description="Repository ID")
    name: str = Field(..., min_length=1, max_length=255, description="Suite name")
    path: str = Field(..., min_length=1, max_length=512, description="Path to tests")
    description: str | None = Field(None, description="Suite description")
    type: str = Field(
        default="classic", description="Suite type: classic, ai_analysis, ai_generation"
    )
    framework: str = Field(
        ..., description="Test framework: pytest, playwright, vitest, jest, cypress"
    )
    command: str | None = Field(None, description="Custom test command")
    config: dict[str, Any] | None = Field(None, description="Framework-specific config")


class TestSuiteUpdate(BaseModel):
    """Request to update a test suite."""

    name: str | None = Field(None, min_length=1, max_length=255)
    path: str | None = Field(None, min_length=1, max_length=512)
    description: str | None = None
    type: str | None = None
    framework: str | None = None
    command: str | None = None
    config: dict[str, Any] | None = None


class TestSuiteResponse(BaseModel):
    """Test suite response schema."""

    id: str
    repository_id: str
    name: str
    path: str
    description: str | None = None
    type: str
    framework: str
    command: str | None = None
    config: dict[str, Any] | None = None
    is_auto_discovered: bool
    discovered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    # Computed from relationships
    runs_count: int = 0
    last_run_status: str | None = None
    last_run_at: datetime | None = None

    class Config:
        from_attributes = True


class TestRunResponse(BaseModel):
    """Test run response schema."""

    id: str
    suite_id: str
    repository_id: str
    task_id: str | None = None
    status: str
    branch: str | None = None
    commit_sha: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    total_tests: int
    passed: int
    failed: int
    skipped: int
    errors: int
    coverage_percent: float | None = None
    coverage_report_url: str | None = None
    report_url: str | None = None
    report_data: dict[str, Any] | None = None
    ai_analysis: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: datetime

    # Computed
    pass_rate: float = 0.0
    is_successful: bool = False

    class Config:
        from_attributes = True


class TestCaseResponse(BaseModel):
    """Test case response schema."""

    id: str
    run_id: str
    name: str
    class_name: str | None = None
    file: str | None = None
    line: int | None = None
    status: str
    duration_ms: int | None = None
    error_message: str | None = None
    stack_trace: str | None = None
    ai_suggestion: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class TestSummary(BaseModel):
    """Summary statistics for tests."""

    total_suites: int
    total_runs: int
    by_framework: dict[str, int]
    by_type: dict[str, int]
    by_status: dict[str, int]
    recent_pass_rate: float


class RunTestRequest(BaseModel):
    """Request to run a test suite."""

    branch: str | None = Field(None, description="Git branch to test")
    commit_sha: str | None = Field(None, description="Git commit to test")


class DiscoverTestsResponse(BaseModel):
    """Response from test discovery."""

    discovered_count: int
    suites: list[TestSuiteResponse]
    message: str


# =============================================================================
# Test Suite CRUD Endpoints
# =============================================================================


@router.get("/suites", response_model=list[TestSuiteResponse])
def list_test_suites(
    repository_id: str = Query(..., description="Repository ID"),
    type: str | None = Query(
        None, description="Filter by type: classic, ai_analysis, ai_generation"
    ),
    framework: str | None = Query(None, description="Filter by framework"),
    include_deleted: bool = Query(False, description="Include soft-deleted suites"),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List all test suites for a repository."""
    # Verify repository exists
    get_or_404(db, Repository, repository_id)

    query = db.query(TestSuite).filter(TestSuite.repository_id == repository_id)

    if not include_deleted:
        query = query.filter(TestSuite.deleted_at.is_(None))
    if type:
        query = query.filter(TestSuite.type == type)
    if framework:
        query = query.filter(TestSuite.framework == framework)

    suites = query.order_by(TestSuite.name).all()

    # Build response with computed fields
    result = []
    for suite in suites:
        # Get run stats
        runs_count = len(suite.runs) if suite.runs else 0
        last_run = None
        if suite.runs:
            last_run = sorted(suite.runs, key=lambda r: r.created_at, reverse=True)[0]

        result.append(
            {
                "id": suite.id,
                "repository_id": suite.repository_id,
                "name": suite.name,
                "path": suite.path,
                "description": suite.description,
                "type": suite.type,
                "framework": suite.framework,
                "command": suite.command,
                "config": suite.config,
                "is_auto_discovered": suite.is_auto_discovered,
                "discovered_at": suite.discovered_at,
                "created_at": suite.created_at,
                "updated_at": suite.updated_at,
                "runs_count": runs_count,
                "last_run_status": last_run.status if last_run else None,
                "last_run_at": last_run.created_at if last_run else None,
            }
        )

    return result


@router.get("/suites/{suite_id}", response_model=TestSuiteResponse)
def get_test_suite(
    suite_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get a specific test suite."""
    suite = get_or_404(db, TestSuite, suite_id)

    runs_count = len(suite.runs) if suite.runs else 0
    last_run = None
    if suite.runs:
        last_run = sorted(suite.runs, key=lambda r: r.created_at, reverse=True)[0]

    return {
        "id": suite.id,
        "repository_id": suite.repository_id,
        "name": suite.name,
        "path": suite.path,
        "description": suite.description,
        "type": suite.type,
        "framework": suite.framework,
        "command": suite.command,
        "config": suite.config,
        "is_auto_discovered": suite.is_auto_discovered,
        "discovered_at": suite.discovered_at,
        "created_at": suite.created_at,
        "updated_at": suite.updated_at,
        "runs_count": runs_count,
        "last_run_status": last_run.status if last_run else None,
        "last_run_at": last_run.created_at if last_run else None,
    }


@router.post("/suites", response_model=TestSuiteResponse, status_code=201)
def create_test_suite(
    data: TestSuiteCreate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Create a new test suite manually."""
    # Verify repository exists
    get_or_404(db, Repository, data.repository_id)

    # Validate framework
    valid_frameworks = ["pytest", "playwright", "vitest", "jest", "cypress", "custom"]
    if data.framework not in valid_frameworks:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid framework. Must be one of: {valid_frameworks}",
        )

    # Validate type
    valid_types = ["classic", "ai_analysis", "ai_generation"]
    if data.type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid type. Must be one of: {valid_types}",
        )

    # Check for duplicate name in same repository
    existing = (
        db.query(TestSuite)
        .filter(
            TestSuite.repository_id == data.repository_id,
            TestSuite.name == data.name,
            TestSuite.deleted_at.is_(None),
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Test suite '{data.name}' already exists in this repository",
        )

    suite = TestSuite(
        repository_id=data.repository_id,
        name=data.name,
        path=data.path,
        description=data.description,
        type=data.type,
        framework=data.framework,
        command=data.command,
        config=data.config,
        is_auto_discovered=False,
    )

    db.add(suite)
    db.commit()
    db.refresh(suite)

    logger.info(f"Created test suite: {suite.name} ({suite.framework})")

    return {
        "id": suite.id,
        "repository_id": suite.repository_id,
        "name": suite.name,
        "path": suite.path,
        "description": suite.description,
        "type": suite.type,
        "framework": suite.framework,
        "command": suite.command,
        "config": suite.config,
        "is_auto_discovered": suite.is_auto_discovered,
        "discovered_at": suite.discovered_at,
        "created_at": suite.created_at,
        "updated_at": suite.updated_at,
        "runs_count": 0,
        "last_run_status": None,
        "last_run_at": None,
    }


@router.patch("/suites/{suite_id}", response_model=TestSuiteResponse)
def update_test_suite(
    suite_id: str,
    data: TestSuiteUpdate,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Update a test suite."""
    suite = get_or_404(db, TestSuite, suite_id)

    # Update fields
    if data.name is not None:
        suite.name = data.name
    if data.path is not None:
        suite.path = data.path
    if data.description is not None:
        suite.description = data.description
    if data.type is not None:
        valid_types = ["classic", "ai_analysis", "ai_generation"]
        if data.type not in valid_types:
            raise HTTPException(status_code=400, detail=f"Invalid type: {data.type}")
        suite.type = data.type
    if data.framework is not None:
        valid_frameworks = ["pytest", "playwright", "vitest", "jest", "cypress", "custom"]
        if data.framework not in valid_frameworks:
            raise HTTPException(status_code=400, detail=f"Invalid framework: {data.framework}")
        suite.framework = data.framework
    if data.command is not None:
        suite.command = data.command
    if data.config is not None:
        suite.config = data.config

    suite.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(suite)

    runs_count = len(suite.runs) if suite.runs else 0
    last_run = None
    if suite.runs:
        last_run = sorted(suite.runs, key=lambda r: r.created_at, reverse=True)[0]

    return {
        "id": suite.id,
        "repository_id": suite.repository_id,
        "name": suite.name,
        "path": suite.path,
        "description": suite.description,
        "type": suite.type,
        "framework": suite.framework,
        "command": suite.command,
        "config": suite.config,
        "is_auto_discovered": suite.is_auto_discovered,
        "discovered_at": suite.discovered_at,
        "created_at": suite.created_at,
        "updated_at": suite.updated_at,
        "runs_count": runs_count,
        "last_run_status": last_run.status if last_run else None,
        "last_run_at": last_run.created_at if last_run else None,
    }


@router.delete("/suites/{suite_id}")
def delete_test_suite(
    suite_id: str,
    hard_delete: bool = Query(False, description="Permanently delete instead of soft delete"),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Delete a test suite (soft delete by default)."""
    suite = get_or_404(db, TestSuite, suite_id)

    if hard_delete:
        db.delete(suite)
        logger.info(f"Hard deleted test suite: {suite.name}")
    else:
        suite.soft_delete()
        logger.info(f"Soft deleted test suite: {suite.name}")

    db.commit()
    return {"message": f"Test suite '{suite.name}' deleted"}


# =============================================================================
# Test Run Endpoints
# =============================================================================


@router.get("/runs", response_model=list[TestRunResponse])
def list_test_runs(
    repository_id: str | None = Query(None, description="Filter by repository"),
    suite_id: str | None = Query(None, description="Filter by suite"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(20, le=100),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List test runs with optional filters."""
    query = db.query(TestRun)

    if repository_id:
        query = query.filter(TestRun.repository_id == repository_id)
    if suite_id:
        query = query.filter(TestRun.suite_id == suite_id)
    if status:
        query = query.filter(TestRun.status == status)

    runs = query.order_by(TestRun.created_at.desc()).offset(offset).limit(limit).all()

    result = []
    for run in runs:
        result.append(
            {
                "id": run.id,
                "suite_id": run.suite_id,
                "repository_id": run.repository_id,
                "task_id": run.task_id,
                "status": run.status,
                "branch": run.branch,
                "commit_sha": run.commit_sha,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "duration_seconds": run.duration_seconds,
                "total_tests": run.total_tests,
                "passed": run.passed,
                "failed": run.failed,
                "skipped": run.skipped,
                "errors": run.errors,
                "coverage_percent": run.coverage_percent,
                "coverage_report_url": run.coverage_report_url,
                "report_url": run.report_url,
                "report_data": run.report_data,
                "ai_analysis": run.ai_analysis,
                "error_message": run.error_message,
                "created_at": run.created_at,
                "pass_rate": run.pass_rate,
                "is_successful": run.is_successful,
            }
        )

    return result


@router.get("/runs/{run_id}", response_model=TestRunResponse)
def get_test_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get a specific test run."""
    run = get_or_404(db, TestRun, run_id)

    return {
        "id": run.id,
        "suite_id": run.suite_id,
        "repository_id": run.repository_id,
        "task_id": run.task_id,
        "status": run.status,
        "branch": run.branch,
        "commit_sha": run.commit_sha,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "duration_seconds": run.duration_seconds,
        "total_tests": run.total_tests,
        "passed": run.passed,
        "failed": run.failed,
        "skipped": run.skipped,
        "errors": run.errors,
        "coverage_percent": run.coverage_percent,
        "coverage_report_url": run.coverage_report_url,
        "report_url": run.report_url,
        "report_data": run.report_data,
        "ai_analysis": run.ai_analysis,
        "error_message": run.error_message,
        "created_at": run.created_at,
        "pass_rate": run.pass_rate,
        "is_successful": run.is_successful,
    }


@router.get("/runs/{run_id}/cases", response_model=list[TestCaseResponse])
def get_test_run_cases(
    run_id: str,
    status: str | None = Query(
        None, description="Filter by status: passed, failed, skipped, error"
    ),
    limit: int = Query(100, le=500),
    offset: int = 0,
    db: Session = Depends(get_db),
) -> list[TestCase]:
    """Get all test cases for a run."""
    get_or_404(db, TestRun, run_id)

    query = db.query(TestCase).filter(TestCase.run_id == run_id)

    if status:
        query = query.filter(TestCase.status == status)

    return query.order_by(TestCase.status, TestCase.name).offset(offset).limit(limit).all()


# =============================================================================
# Test Execution Endpoints
# =============================================================================


@router.post("/run/{suite_id}", response_model=dict[str, Any])
def run_test_suite(
    suite_id: str,
    data: RunTestRequest | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Execute a test suite.

    Creates a test run record and starts the test execution task.
    Returns the run ID and task ID for tracking progress.
    """
    suite = get_or_404(db, TestSuite, suite_id)

    # Create pending test run
    run = TestRun(
        suite_id=suite.id,
        repository_id=suite.repository_id,
        status="pending",
        branch=data.branch if data else None,
        commit_sha=data.commit_sha if data else None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # TODO: Create and queue TestTask for execution
    # For now, return the created run
    logger.info(f"Created test run {run.id} for suite {suite.name}")

    return {
        "run_id": run.id,
        "suite_id": suite.id,
        "suite_name": suite.name,
        "status": "pending",
        "message": "Test run created. Execution will be implemented with TestTask.",
    }


@router.post("/run-all/{repository_id}", response_model=dict[str, Any])
def run_all_tests(
    repository_id: str,
    branch: str | None = Query(None, description="Git branch to test"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Execute all test suites for a repository."""
    get_or_404(db, Repository, repository_id)

    suites = (
        db.query(TestSuite)
        .filter(
            TestSuite.repository_id == repository_id,
            TestSuite.deleted_at.is_(None),
        )
        .all()
    )

    if not suites:
        raise HTTPException(status_code=400, detail="No test suites found for this repository")

    runs = []
    for suite in suites:
        run = TestRun(
            suite_id=suite.id,
            repository_id=repository_id,
            status="pending",
            branch=branch,
        )
        db.add(run)
        runs.append(run)

    db.commit()

    logger.info(f"Created {len(runs)} test runs for repository {repository_id}")

    return {
        "repository_id": repository_id,
        "runs_created": len(runs),
        "run_ids": [r.id for r in runs],
        "message": f"Created {len(runs)} test runs. Execution will be implemented with TestTask.",
    }


# =============================================================================
# Test Discovery Endpoints
# =============================================================================


@router.post("/discover/{repository_id}", response_model=DiscoverTestsResponse)
def discover_tests(
    repository_id: str,
    db: Session = Depends(get_db),
) -> DiscoverTestsResponse:
    """
    Auto-discover test suites in a repository.

    Scans common test directories and config files to identify test frameworks.
    Creates test suite records for discovered tests.
    """
    get_or_404(db, Repository, repository_id)

    # TODO: Implement discovery agent
    # For now, return empty response
    logger.info(f"Test discovery requested for repository {repository_id}")

    return DiscoverTestsResponse(
        discovered_count=0,
        suites=[],
        message="Test discovery will be implemented with test-discoverer agent.",
    )


# =============================================================================
# Summary & Stats Endpoints
# =============================================================================


@router.get("/summary", response_model=TestSummary)
def get_test_summary(
    repository_id: str = Query(..., description="Repository ID"),
    db: Session = Depends(get_db),
) -> TestSummary:
    """Get summary statistics for tests in a repository."""
    suites = (
        db.query(TestSuite)
        .filter(
            TestSuite.repository_id == repository_id,
            TestSuite.deleted_at.is_(None),
        )
        .all()
    )

    # Compute stats
    by_framework: dict[str, int] = {}
    by_type: dict[str, int] = {}
    total_runs = 0

    for suite in suites:
        # Count by framework
        fw = suite.framework or "unknown"
        by_framework[fw] = by_framework.get(fw, 0) + 1

        # Count by type
        st = suite.type or "classic"
        by_type[st] = by_type.get(st, 0) + 1

        # Count runs
        if suite.runs:
            total_runs += len(suite.runs)

    # Get recent runs for pass rate calculation
    recent_runs = (
        db.query(TestRun)
        .filter(TestRun.repository_id == repository_id)
        .order_by(TestRun.created_at.desc())
        .limit(10)
        .all()
    )

    by_status: dict[str, int] = {
        "pending": 0,
        "running": 0,
        "passed": 0,
        "failed": 0,
        "error": 0,
    }
    total_tests = 0
    total_passed = 0

    for run in recent_runs:
        status = run.status or "pending"
        by_status[status] = by_status.get(status, 0) + 1
        total_tests += run.total_tests or 0
        total_passed += run.passed or 0

    recent_pass_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0.0

    return TestSummary(
        total_suites=len(suites),
        total_runs=total_runs,
        by_framework=by_framework,
        by_type=by_type,
        by_status=by_status,
        recent_pass_rate=round(recent_pass_rate, 1),
    )


# =============================================================================
# AI Analysis Endpoints
# =============================================================================


@router.post("/analyze/{run_id}", response_model=dict[str, Any])
def analyze_test_run(
    run_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Trigger AI analysis of a test run.

    Analyzes failed tests and generates suggestions for fixes.
    """
    run = get_or_404(db, TestRun, run_id)

    if run.status not in ("passed", "failed"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot analyze run with status '{run.status}'. Must be 'passed' or 'failed'.",
        )

    # TODO: Implement test-analyzer agent
    logger.info(f"AI analysis requested for test run {run_id}")

    return {
        "run_id": run_id,
        "status": "pending",
        "message": "AI analysis will be implemented with test-analyzer agent.",
    }


@router.post("/generate/{repository_id}", response_model=dict[str, Any])
def generate_tests(
    repository_id: str,
    target_path: str = Query(None, description="Path to generate tests for"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """
    Generate tests using AI.

    Creates new test cases based on source code analysis.
    """
    get_or_404(db, Repository, repository_id)

    # TODO: Implement test-generator agent
    logger.info(f"Test generation requested for repository {repository_id}")

    return {
        "repository_id": repository_id,
        "target_path": target_path,
        "status": "pending",
        "message": "Test generation will be implemented with test-generator agent.",
    }
