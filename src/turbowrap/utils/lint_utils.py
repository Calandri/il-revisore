"""Linting utilities for TurboWrap.

Centralized functions for running linters and parsing their output.
"""

import json
import logging
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)


@dataclass
class LintIssue:
    """A single lint issue."""

    file: str
    line: int
    column: int
    code: str
    message: str
    severity: Literal["error", "warning"] = "error"


@dataclass
class LintResult:
    """Result of running a linter."""

    file: str
    passed: bool
    issues: list[LintIssue] = field(default_factory=list)
    skipped: bool = False
    error: str | None = None


def run_ruff(
    path: Path,
    *,
    fix: bool = False,
    output_format: str = "json",
) -> LintResult:
    """Run ruff linter on a file or directory.

    Args:
        path: Path to file or directory to lint.
        fix: Whether to auto-fix issues.
        output_format: Output format (json, text).

    Returns:
        LintResult with parsed issues.
    """
    result = LintResult(file=str(path), passed=True)

    try:
        cmd = ["ruff", "check", str(path)]
        if fix:
            cmd.append("--fix")
        if output_format == "json":
            cmd.extend(["--output-format", "json"])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if proc.returncode != 0 and proc.stdout:
            issues = parse_ruff_output(proc.stdout)
            result.issues = issues
            result.passed = len(issues) == 0

    except FileNotFoundError:
        result.skipped = True
        result.error = "ruff not installed"
    except Exception as e:
        logger.warning(f"Ruff check failed: {e}")
        result.error = str(e)

    return result


def parse_ruff_output(output: str) -> list[LintIssue]:
    """Parse ruff JSON output into LintIssue objects.

    Args:
        output: Raw JSON output from ruff.

    Returns:
        List of LintIssue objects.
    """
    if not output:
        return []

    try:
        data = json.loads(output)
        if not isinstance(data, list):
            return []

        issues = []
        for item in data:
            issues.append(
                LintIssue(
                    file=item.get("filename", ""),
                    line=item.get("location", {}).get("row", 0),
                    column=item.get("location", {}).get("column", 0),
                    code=item.get("code", ""),
                    message=item.get("message", ""),
                    severity="error",
                )
            )
        return issues
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse ruff output: {e}")
        return []


def run_eslint(
    path: Path,
    *,
    fix: bool = False,
    output_format: str = "json",
) -> LintResult:
    """Run ESLint on a file or directory.

    Args:
        path: Path to file or directory to lint.
        fix: Whether to auto-fix issues.
        output_format: Output format (json, stylish).

    Returns:
        LintResult with parsed issues.
    """
    result = LintResult(file=str(path), passed=True)

    try:
        cmd = ["npx", "eslint", str(path)]
        if fix:
            cmd.append("--fix")
        if output_format == "json":
            cmd.extend(["--format", "json"])

        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if proc.stdout:
            issues = parse_eslint_output(proc.stdout)
            result.issues = issues
            result.passed = len(issues) == 0

    except FileNotFoundError:
        result.skipped = True
        result.error = "eslint not installed"
    except Exception as e:
        logger.warning(f"ESLint check failed: {e}")
        result.error = str(e)

    return result


def parse_eslint_output(output: str) -> list[LintIssue]:
    """Parse ESLint JSON output into LintIssue objects.

    Args:
        output: Raw JSON output from ESLint.

    Returns:
        List of LintIssue objects.
    """
    if not output:
        return []

    try:
        data = json.loads(output)
        if not isinstance(data, list):
            return []

        issues = []
        for file_result in data:
            file_path = file_result.get("filePath", "")
            for msg in file_result.get("messages", []):
                issues.append(
                    LintIssue(
                        file=file_path,
                        line=msg.get("line", 0),
                        column=msg.get("column", 0),
                        code=msg.get("ruleId", ""),
                        message=msg.get("message", ""),
                        severity="error" if msg.get("severity", 2) == 2 else "warning",
                    )
                )
        return issues
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse eslint output: {e}")
        return []


def parse_lint_json_from_llm(output: str) -> list[dict[str, Any]]:
    """Parse JSON issues from LLM lint output.

    Handles markdown code blocks and finds JSON arrays in the output.

    Args:
        output: Raw output from LLM containing JSON.

    Returns:
        List of issue dictionaries.
    """
    if not output:
        return []

    json_text = output.strip()

    # Handle markdown code blocks
    if "```" in json_text:
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", json_text)
        if json_match:
            json_text = json_match.group(1).strip()

    # Try to find JSON array directly
    if not json_text.startswith("["):
        array_match = re.search(r"\[\s*\{[\s\S]*\}\s*\]", json_text)
        if array_match:
            json_text = array_match.group()

    try:
        issues = json.loads(json_text)
        if isinstance(issues, list):
            return issues
        return []
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse lint output as JSON: {e}")
        logger.debug(f"Raw output: {output[:1000]}")
        return []


def detect_project_linters(repo_path: Path) -> list[str]:
    """Detect which linters are applicable for a project.

    Args:
        repo_path: Path to repository root.

    Returns:
        List of applicable linter names.
    """
    linters = []

    # Check for Python files
    if list(repo_path.rglob("*.py")):
        linters.append("ruff")

    # Check for TypeScript/JavaScript files
    ts_js_files = (
        list(repo_path.rglob("*.ts"))
        + list(repo_path.rglob("*.tsx"))
        + list(repo_path.rglob("*.js"))
        + list(repo_path.rglob("*.jsx"))
    )
    if ts_js_files:
        # Check if eslint config exists
        eslint_configs = [
            ".eslintrc",
            ".eslintrc.js",
            ".eslintrc.json",
            ".eslintrc.yaml",
            ".eslintrc.yml",
            "eslint.config.js",
            "eslint.config.mjs",
        ]
        for config in eslint_configs:
            if (repo_path / config).exists():
                linters.append("eslint")
                break
        else:
            # Check package.json for eslint
            package_json = repo_path / "package.json"
            if package_json.exists():
                try:
                    data = json.loads(package_json.read_text())
                    deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                    if "eslint" in deps:
                        linters.append("eslint")
                except Exception:
                    pass

    return linters


def format_issues_for_display(issues: list[LintIssue]) -> list[str]:
    """Format lint issues for human-readable display.

    Args:
        issues: List of LintIssue objects.

    Returns:
        List of formatted strings.
    """
    return [f"{i.code}: {i.message} (line {i.line})" for i in issues]
