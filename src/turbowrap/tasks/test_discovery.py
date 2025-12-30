"""Test discovery service using Gemini CLI.

Scans repositories to automatically discover test suites and frameworks.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..llm.gemini import GeminiCLI

logger = logging.getLogger(__name__)

# Path to test-discoverer agent prompt
AGENT_PROMPT_PATH = Path(__file__).parents[3] / "agents" / "test_discoverer.md"


@dataclass
class DiscoveredSuite:
    """A discovered test suite."""

    name: str
    path: str
    framework: str
    type: str  # unit | integration | e2e
    test_files_count: int = 0
    suggested_command: str | None = None
    confidence: str = "medium"  # high | medium | low


@dataclass
class DiscoveryResult:
    """Result of test discovery."""

    success: bool
    suites: list[DiscoveredSuite] = field(default_factory=list)
    detected_frameworks: list[str] = field(default_factory=list)
    project_type: str | None = None
    has_coverage_config: bool = False
    notes: str | None = None
    error: str | None = None
    duration_ms: int = 0


def _load_agent_prompt() -> str:
    """Load the test-discoverer agent prompt from MD file."""
    if not AGENT_PROMPT_PATH.exists():
        raise FileNotFoundError(f"Agent prompt not found: {AGENT_PROMPT_PATH}")

    content = AGENT_PROMPT_PATH.read_text()

    # Remove YAML frontmatter (between --- markers)
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            content = parts[2].strip()

    return content


def _extract_json_from_output(output: str) -> dict[str, Any] | None:
    """Extract JSON object from Gemini output.

    The output may contain markdown or other text, so we need to find
    the JSON object within it.
    """
    # Try direct JSON parse first
    try:
        return json.loads(output.strip())
    except json.JSONDecodeError:
        pass

    # Look for JSON object in output
    # Pattern: starts with { and ends with matching }
    json_match = re.search(r"\{[\s\S]*\"discovered_suites\"[\s\S]*\}", output)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Try to find any JSON object
    for match in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", output):
        try:
            data = json.loads(match.group())
            if "discovered_suites" in data:
                return data
        except json.JSONDecodeError:
            continue

    return None


async def discover_tests(
    repo_path: Path,
    repo_name: str,
    context_id: str | None = None,
    timeout: int = 60,
) -> DiscoveryResult:
    """Discover test suites in a repository using Gemini CLI.

    Args:
        repo_path: Path to the repository.
        repo_name: Name of the repository for tracking.
        context_id: Optional context ID for S3 logging.
        timeout: Timeout in seconds.

    Returns:
        DiscoveryResult with discovered suites.
    """
    logger.info(f"[TEST DISCOVERY] Starting discovery for {repo_name} at {repo_path}")

    try:
        # Load agent prompt
        prompt = _load_agent_prompt()

        # Create Gemini CLI runner
        cli = GeminiCLI(
            working_dir=repo_path,
            model="flash",  # Use Gemini Flash 3 for speed
            timeout=timeout,
            auto_accept=True,
        )

        # Run discovery
        result = await cli.run(
            prompt=prompt,
            operation_type="test_discovery",
            repo_name=repo_name,
            context_id=context_id,
            track_operation=True,
        )

        if not result.success:
            logger.error(f"[TEST DISCOVERY] Failed: {result.error}")
            return DiscoveryResult(
                success=False,
                error=result.error or "Discovery failed",
                duration_ms=result.duration_ms,
            )

        # Parse JSON from output
        json_data = _extract_json_from_output(result.output)

        if not json_data:
            logger.warning("[TEST DISCOVERY] Could not extract JSON from output")
            return DiscoveryResult(
                success=False,
                error="Failed to parse discovery output",
                duration_ms=result.duration_ms,
            )

        # Convert to DiscoveryResult
        suites = []
        for suite_data in json_data.get("discovered_suites", []):
            suites.append(
                DiscoveredSuite(
                    name=suite_data.get("name", "Unknown"),
                    path=suite_data.get("path", ""),
                    framework=suite_data.get("framework", "unknown"),
                    type=suite_data.get("type", "unit"),
                    test_files_count=suite_data.get("test_files_count", 0),
                    suggested_command=suite_data.get("suggested_command"),
                    confidence=suite_data.get("confidence", "medium"),
                )
            )

        logger.info(f"[TEST DISCOVERY] Found {len(suites)} test suites")

        return DiscoveryResult(
            success=True,
            suites=suites,
            detected_frameworks=json_data.get("detected_frameworks", []),
            project_type=json_data.get("project_type"),
            has_coverage_config=json_data.get("has_coverage_config", False),
            notes=json_data.get("notes"),
            duration_ms=result.duration_ms,
        )

    except FileNotFoundError as e:
        logger.error(f"[TEST DISCOVERY] Agent prompt not found: {e}")
        return DiscoveryResult(
            success=False,
            error=str(e),
        )
    except Exception as e:
        logger.exception(f"[TEST DISCOVERY] Error: {e}")
        return DiscoveryResult(
            success=False,
            error=str(e),
        )


async def discover_and_save_tests(
    repo_path: Path,
    repo_name: str,
    repository_id: str,
    db_session: Any,
    context_id: str | None = None,
) -> DiscoveryResult:
    """Discover tests and save them to database.

    Args:
        repo_path: Path to the repository.
        repo_name: Name of the repository.
        repository_id: Repository UUID.
        db_session: Database session.
        context_id: Optional context ID for S3 logging.

    Returns:
        DiscoveryResult with discovered suites.
    """
    from ..db.models import TestSuite

    # Run discovery
    result = await discover_tests(repo_path, repo_name, context_id)

    if not result.success:
        return result

    # Save discovered suites to database
    saved_count = 0
    for suite in result.suites:
        # Check if suite already exists
        existing = (
            db_session.query(TestSuite)
            .filter(
                TestSuite.repository_id == repository_id,
                TestSuite.path == suite.path,
                TestSuite.deleted_at.is_(None),
            )
            .first()
        )

        if existing:
            # Update existing suite
            existing.name = suite.name
            existing.framework = suite.framework
            existing.command = suite.suggested_command
            existing.is_auto_discovered = True
            logger.info(f"[TEST DISCOVERY] Updated existing suite: {suite.name}")
        else:
            # Create new suite
            new_suite = TestSuite(
                repository_id=repository_id,
                name=suite.name,
                path=suite.path,
                type="classic",  # Auto-discovered are always classic
                framework=suite.framework,
                command=suite.suggested_command,
                is_auto_discovered=True,
            )
            db_session.add(new_suite)
            saved_count += 1
            logger.info(f"[TEST DISCOVERY] Created new suite: {suite.name}")

    db_session.commit()
    logger.info(f"[TEST DISCOVERY] Saved {saved_count} new suites to database")

    return result
