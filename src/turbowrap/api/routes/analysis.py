"""Code analysis routes - linting, testing, static analysis."""

import asyncio
import json
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from turbowrap_llm import GeminiCLI

from ...db.models import Issue, IssueStatus, Repository, Task
from ...review.reviewers.utils.json_extraction import parse_llm_json
from ...utils.aws_secrets import get_anthropic_api_key
from ...utils.git_utils import get_current_branch
from ...utils.lint_utils import parse_lint_json_from_llm
from ..deps import get_db, get_or_404

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analysis", tags=["analysis"])

# Agent file paths
AGENTS_DIR = Path(__file__).parent.parent.parent.parent.parent / "agents"
LINTER_ANALYZER_AGENT = AGENTS_DIR / "linter_analyzer.md"
LINT_FIXER_AGENT = AGENTS_DIR / "lint_fixer.md"

# Linting types by category
LINT_TYPES = {
    "FE": ["typescript", "eslint"],  # Frontend linting
    "BE": ["ruff", "mypy"],  # Backend linting
}


def _load_agent(agent_path: Path) -> str:
    """Load agent prompt from MD file, stripping frontmatter."""
    if not agent_path.exists():
        logger.warning(f"Agent file not found: {agent_path}")
        return ""

    content = agent_path.read_text(encoding="utf-8")

    # Strip YAML frontmatter (--- ... ---)
    if content.startswith("---"):
        end_match = re.search(r"\n---\n", content[3:])
        if end_match:
            content = content[3 + end_match.end() :]

    return content.strip()


class LintRequest(BaseModel):
    """Request to run linting analysis."""

    repository_id: str = Field(..., description="Repository ID")
    task_id: str | None = Field(default=None, description="Task ID to associate issues with")


class LintIssue(BaseModel):
    """Issue found by linter."""

    issue_code: str
    severity: str
    category: str
    rule: str | None = None
    file: str
    line: int | None = None
    title: str
    description: str
    current_code: str | None = None
    suggested_fix: str | None = None
    flagged_by: list[str] | None = None


class LintResult(BaseModel):
    """Result of linting analysis."""

    status: str
    issues_found: int
    issues_created: int
    task_id: str
    message: str


@router.post("/lint")
async def run_lint_analysis(
    request: LintRequest,
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    """
    Run linting analysis on a repository using Claude CLI.

    Uses the linter_analyzer agent to:
    1. Detect project type (Python, TypeScript, etc.)
    2. Run appropriate linting tools
    3. Parse output into structured issues
    4. Create issues in the database

    Returns SSE stream with progress updates.
    """
    # Verify repository
    repo = get_or_404(db, Repository, request.repository_id)

    repo_path = Path(str(repo.local_path))
    if not repo_path.exists():
        raise HTTPException(status_code=400, detail="Repository path not found")

    # Create or use task
    task_id: str
    if request.task_id:
        task = get_or_404(db, Task, request.task_id)
        task_id = str(task.id)
    else:
        # Create a new task for this lint run
        task_id = str(uuid.uuid4())
        task = Task(
            id=task_id,
            repository_id=request.repository_id,
            type="lint_analysis",
            status="running",
            config={"analysis_type": "lint"},
            created_at=datetime.utcnow(),
        )
        db.add(task)
        db.commit()

    async def generate() -> AsyncIterator[dict[str, str]]:
        """Generate SSE events from lint analysis."""
        issues_created = 0

        try:
            # Send start event
            yield {
                "event": "lint_start",
                "data": json.dumps(
                    {
                        "message": "Starting lint analysis...",
                        "task_id": task_id,
                        "repository": repo.name,
                    }
                ),
            }

            # Load agent prompt
            lint_prompt = _load_agent(LINTER_ANALYZER_AGENT)
            if not lint_prompt:
                yield {
                    "event": "lint_error",
                    "data": json.dumps(
                        {
                            "error": "Linter analyzer agent not found",
                        }
                    ),
                }
                return

            # Build environment with API key
            env = os.environ.copy()
            api_key = get_anthropic_api_key()
            if api_key:
                env["ANTHROPIC_API_KEY"] = api_key
            # Workaround: Bun file watcher bug on macOS /var/folders
            env["TMPDIR"] = "/tmp"

            # Find Claude CLI
            cli_path = "/Users/niccolocalandri/.claude/local/claude"
            if not Path(cli_path).exists():
                cli_path = "claude"  # Fallback to PATH

            yield {
                "event": "lint_progress",
                "data": json.dumps(
                    {
                        "message": "Running linting tools with Claude CLI...",
                        "phase": "analysis",
                    }
                ),
            }

            # Run Claude CLI with lint prompt
            process = await asyncio.create_subprocess_exec(
                cli_path,
                "--print",
                "--verbose",
                "--dangerously-skip-permissions",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(repo_path),
                env=env,
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=lint_prompt.encode()),
                timeout=300,  # 5 minutes timeout for linting
            )

            output = stdout.decode() if stdout else ""
            error = stderr.decode() if stderr else ""

            if process.returncode != 0:
                logger.error(f"Lint analysis failed: {error}")
                yield {
                    "event": "lint_error",
                    "data": json.dumps(
                        {
                            "error": f"Linting failed: {error[:500]}",
                        }
                    ),
                }
                return

            yield {
                "event": "lint_progress",
                "data": json.dumps(
                    {
                        "message": "Parsing linting results...",
                        "phase": "parsing",
                    }
                ),
            }

            # Parse JSON output from Claude
            issues = parse_lint_json_from_llm(output)

            if not issues:
                yield {
                    "event": "lint_complete",
                    "data": json.dumps(
                        {
                            "message": "No issues found!",
                            "issues_found": 0,
                            "issues_created": 0,
                            "task_id": task_id,
                        }
                    ),
                }
                # Update task status
                task_obj = db.query(Task).filter(Task.id == task_id).first()
                if task_obj:
                    task_obj.status = "completed"  # type: ignore[assignment]
                    task_obj.result = {"issues_found": 0}  # type: ignore[assignment]
                    db.commit()
                return

            yield {
                "event": "lint_progress",
                "data": json.dumps(
                    {
                        "message": f"Found {len(issues)} issues, creating in database...",
                        "phase": "creating",
                        "issues_found": len(issues),
                    }
                ),
            }

            # Create issues in database
            for issue_data in issues:
                # Check for duplicates (same file, line, issue_code)
                existing = (
                    db.query(Issue)
                    .filter(
                        Issue.repository_id == request.repository_id,
                        Issue.file == issue_data.get("file", ""),
                        Issue.line == issue_data.get("line"),
                        Issue.issue_code == issue_data.get("issue_code", ""),
                        Issue.status.in_(["open", "in_progress"]),
                    )
                    .first()
                )

                if existing:
                    logger.debug(f"Skipping duplicate issue: {issue_data.get('issue_code')}")
                    continue

                issue = Issue(
                    id=str(uuid.uuid4()),
                    task_id=task_id,
                    repository_id=request.repository_id,
                    issue_code=issue_data.get("issue_code", f"LINT-{issues_created + 1:03d}"),
                    severity=issue_data.get("severity", "MEDIUM").upper(),
                    category=issue_data.get("category", "linting"),
                    rule=issue_data.get("rule"),
                    file=issue_data.get("file", "unknown"),
                    line=issue_data.get("line"),
                    title=issue_data.get("title", "Linting issue"),
                    description=issue_data.get("description", ""),
                    current_code=issue_data.get("current_code"),
                    suggested_fix=issue_data.get("suggested_fix"),
                    flagged_by=issue_data.get("flagged_by", ["linter"]),
                    status=IssueStatus.OPEN.value,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                db.add(issue)
                issues_created += 1

            db.commit()

            # Update task status
            task_obj = db.query(Task).filter(Task.id == task_id).first()
            if task_obj:
                task_obj.status = "completed"  # type: ignore[assignment]
                task_obj.result = {  # type: ignore[assignment]
                    "issues_found": len(issues),
                    "issues_created": issues_created,
                }
                db.commit()

            yield {
                "event": "lint_complete",
                "data": json.dumps(
                    {
                        "message": f"Analysis complete! Created {issues_created} issues.",
                        "issues_found": len(issues),
                        "issues_created": issues_created,
                        "task_id": task_id,
                    }
                ),
            }

        except asyncio.TimeoutError:
            yield {
                "event": "lint_error",
                "data": json.dumps(
                    {
                        "error": "Lint analysis timed out after 5 minutes",
                    }
                ),
            }
        except Exception as e:
            logger.exception("Lint analysis failed")
            yield {
                "event": "lint_error",
                "data": json.dumps(
                    {
                        "error": str(e),
                    }
                ),
            }

    return EventSourceResponse(generate())


@router.get("/lint/{task_id}")
async def get_lint_results(
    task_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Get results of a lint analysis task."""
    task = get_or_404(db, Task, task_id)

    issues = db.query(Issue).filter(Issue.task_id == task_id).all()

    return {
        "task_id": task_id,
        "status": task.status,
        "result": task.result,
        "issues_count": len(issues),
        "issues": [
            {
                "id": i.id,
                "issue_code": i.issue_code,
                "severity": i.severity,
                "category": i.category,
                "file": i.file,
                "line": i.line,
                "title": i.title,
                "status": i.status,
            }
            for i in issues
        ],
    }


class LintFixRequest(BaseModel):
    """Request to run lint + fix flow."""

    repository_id: str = Field(..., description="Repository ID")
    category: str = Field(default="all", description="Category to lint: 'FE', 'BE', or 'all'")
    workspace_path: str | None = Field(default=None, description="Workspace path to scope changes")


class LintFixResult(BaseModel):
    """Result of a single lint-fix run."""

    lint_type: str
    issues_found: int
    issues_fixed: int
    files_modified: list[str]
    commit_sha: str | None = None
    status: str


@router.post("/lint-fix")
async def run_lint_fix(
    request: LintFixRequest,
    db: Session = Depends(get_db),
) -> EventSourceResponse:
    """
    Run lint + fix flow on a repository.

    Orchestrates linting by category (FE/BE), running one lint type at a time.
    For each type:
    1. Runs linting tool
    2. Identifies issues
    3. Fixes them directly
    4. Commits changes
    5. Creates a macro-issue marked as RESOLVED

    Returns SSE stream with progress updates.
    """
    # Verify repository
    repo = get_or_404(db, Repository, request.repository_id)

    repo_path = Path(str(repo.local_path))
    if not repo_path.exists():
        raise HTTPException(status_code=400, detail="Repository path not found")

    # Determine which lint types to run
    lint_types: list[str]
    if request.category == "all":
        lint_types = LINT_TYPES["BE"] + LINT_TYPES["FE"]
    elif request.category in LINT_TYPES:
        lint_types = LINT_TYPES[request.category]
    else:
        raise HTTPException(status_code=400, detail=f"Invalid category: {request.category}")

    # Create task
    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        repository_id=request.repository_id,
        type="lint_fix",
        status="running",
        config={"category": request.category, "lint_types": lint_types},
        created_at=datetime.utcnow(),
    )
    db.add(task)
    db.commit()

    async def generate() -> AsyncIterator[dict[str, str]]:
        """Generate SSE events from lint-fix orchestration."""
        results: list[LintFixResult] = []
        total_fixed = 0

        try:
            yield {
                "event": "lint_fix_start",
                "data": json.dumps(
                    {
                        "message": f"Starting lint-fix for {request.category}...",
                        "task_id": task_id,
                        "lint_types": lint_types,
                    }
                ),
            }

            # Load agent prompt
            agent_prompt = _load_agent(LINT_FIXER_AGENT)
            if not agent_prompt:
                yield {
                    "event": "lint_fix_error",
                    "data": json.dumps({"error": "Lint fixer agent not found"}),
                }
                return

            # Notify which lint types are starting in parallel
            yield {
                "event": "lint_fix_progress",
                "data": json.dumps(
                    {
                        "message": f"Launching {len(lint_types)} Gemini Flash processes in parallel...",
                        "lint_types": lint_types,
                        "phase": "launching",
                    }
                ),
            }

            async def run_single_lint(lint_type: str) -> tuple[str, LintFixResult]:
                """Run a single lint type with GeminiCLI Flash."""
                # Prepare prompt with variables
                prompt = agent_prompt.replace("{lint_type}", lint_type)
                if request.workspace_path:
                    prompt = prompt.replace("{workspace_path}", request.workspace_path)

                logger.info(f"[LINT-FIX] Starting Gemini Flash for {lint_type}")

                # Import here to avoid circular imports
                from turbowrap.config import get_settings
                from turbowrap.utils.s3_artifact_saver import S3ArtifactSaver

                settings = get_settings()
                artifact_saver = S3ArtifactSaver(
                    bucket=settings.thinking.s3_bucket,
                    region=settings.thinking.s3_region,
                    prefix=f"lint-fix/{lint_type}",
                )

                gemini_cli = GeminiCLI(
                    working_dir=repo_path,
                    model="flash",
                    timeout=300,  # 5 minutes per lint type
                    artifact_saver=artifact_saver,
                )

                gemini_result = await gemini_cli.run(
                    prompt=prompt,
                    save_artifacts=True,
                )

                if not gemini_result.success:
                    logger.error(f"Lint-fix failed for {lint_type}: {gemini_result.error}")
                    return lint_type, LintFixResult(
                        lint_type=lint_type,
                        issues_found=0,
                        issues_fixed=0,
                        files_modified=[],
                        status="failed",
                    )

                # Parse result from output
                result = _parse_lint_fix_output(gemini_result.output, lint_type)
                logger.info(f"[LINT-FIX] {lint_type}: fixed {result.issues_fixed} issues")
                return lint_type, result

            # Run all lint types in parallel with Gemini Flash
            parallel_results = await asyncio.gather(
                *[run_single_lint(lt) for lt in lint_types],
                return_exceptions=True,
            )

            # Process results
            for item in parallel_results:
                if isinstance(item, Exception):
                    logger.exception(f"Lint-fix parallel task failed: {item}")
                    continue

                lint_type, result = item
                results.append(result)
                total_fixed += result.issues_fixed

                # Emit progress for this lint type
                yield {
                    "event": "lint_fix_progress",
                    "data": json.dumps(
                        {
                            "message": f"{lint_type}: fixed {result.issues_fixed} issues",
                            "lint_type": lint_type,
                            "phase": "completed" if result.status != "failed" else "error",
                            "issues_fixed": result.issues_fixed,
                            "commit_sha": result.commit_sha,
                        }
                    ),
                }

                # Create macro-issue for tracking (marked as RESOLVED)
                if result.issues_fixed > 0:
                    first_file = (
                        result.files_modified[0] if result.files_modified else "(multiple files)"
                    )
                    try:
                        current_branch = get_current_branch(repo_path)
                    except Exception:
                        current_branch = str(repo.default_branch) if repo.default_branch else "main"

                    issue = Issue(
                        id=str(uuid.uuid4()),
                        task_id=task_id,
                        repository_id=request.repository_id,
                        issue_code=f"LINT-FIX-{lint_type.upper()}",
                        severity="LOW",
                        category="linting",
                        file=first_file,
                        line=1,
                        title=f"[{lint_type}] Fixed {result.issues_fixed} linting issues",
                        description=(
                            f"Automatically fixed {result.issues_fixed} {lint_type} issues."
                            f"\n\nFiles modified:\n"
                        )
                        + "\n".join(f"- {f}" for f in result.files_modified[:20]),
                        status=IssueStatus.RESOLVED.value,
                        fix_commit_sha=result.commit_sha,
                        fix_branch=current_branch,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow(),
                    )
                    db.add(issue)
                    db.commit()

            # Update task status
            task_obj = db.query(Task).filter(Task.id == task_id).first()
            if task_obj:
                task_obj.status = "completed"  # type: ignore[assignment]
                task_obj.result = {  # type: ignore[assignment]
                    "total_fixed": total_fixed,
                    "results": [r.model_dump() for r in results],
                }
                db.commit()

            yield {
                "event": "lint_fix_complete",
                "data": json.dumps(
                    {
                        "message": f"Lint-fix complete! Fixed {total_fixed} issues total.",
                        "task_id": task_id,
                        "total_fixed": total_fixed,
                        "results": [r.model_dump() for r in results],
                    }
                ),
            }

        except asyncio.TimeoutError:
            yield {
                "event": "lint_fix_error",
                "data": json.dumps({"error": "Lint-fix timed out"}),
            }
        except Exception as e:
            logger.exception("Lint-fix failed")
            yield {
                "event": "lint_fix_error",
                "data": json.dumps({"error": str(e)}),
            }

    return EventSourceResponse(generate())


def _parse_lint_fix_output(output: str, lint_type: str) -> LintFixResult:
    """Parse JSON result from lint-fixer agent output.

    Extracts the JSON summary from Gemini CLI output, handling markdown code blocks.
    """
    data = parse_llm_json(output)
    if data:
        return LintFixResult(
            lint_type=data.get("lint_type", lint_type),
            issues_found=data.get("issues_found", 0),
            issues_fixed=data.get("issues_fixed", 0),
            files_modified=data.get("files_modified", []),
            commit_sha=data.get("commit_sha"),
            status=data.get("status", "success"),
        )

    logger.warning(f"Could not parse lint-fix output for {lint_type}: {output[:200]}")
    return LintFixResult(
        lint_type=lint_type,
        issues_found=0,
        issues_fixed=0,
        files_modified=[],
        status="unknown",
    )
