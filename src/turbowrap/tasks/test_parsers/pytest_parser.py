"""Pytest output parser using pytest-json-report."""

import json
import logging
import re
from typing import Any

from .base import BaseTestParser, ParsedTestResults, TestCaseResult

logger = logging.getLogger(__name__)


class PytestParser(BaseTestParser):
    """Parser for pytest JSON report output.

    Requires pytest-json-report plugin:
        pip install pytest-json-report

    Usage:
        pytest tests/ --json-report --json-report-file=- -q
    """

    @property
    def framework(self) -> str:
        return "pytest"

    def get_default_command(self, path: str) -> list[str]:
        """Get pytest command with JSON reporter."""
        return [
            "pytest",
            path,
            "--json-report",
            "--json-report-file=-",  # Output to stdout
            "-q",  # Quiet mode
            "--tb=short",  # Short traceback
        ]

    def get_env_vars(self) -> dict[str, str]:
        """Set PYTHONDONTWRITEBYTECODE to avoid .pyc files."""
        return {"PYTHONDONTWRITEBYTECODE": "1"}

    def parse(self, output: str, exit_code: int = 0) -> ParsedTestResults:
        """Parse pytest JSON report output.

        Args:
            output: Raw output containing JSON report.
            exit_code: Process exit code.

        Returns:
            ParsedTestResults with test details.
        """
        # Try to extract JSON from output (it may be mixed with other output)
        json_data = self._extract_json(output)

        if json_data:
            return self._parse_json_report(json_data, output)

        # Fallback: parse plain text output
        return self._parse_plain_output(output, exit_code)

    def _extract_json(self, output: str) -> dict[str, Any] | None:
        """Extract JSON report from output."""
        # Look for JSON object in output
        # pytest-json-report outputs JSON as a single line
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    # Verify it's a pytest-json-report
                    if "tests" in data or "summary" in data:
                        return data
                except json.JSONDecodeError:
                    continue

        # Try parsing entire output as JSON
        try:
            data = json.loads(output)
            if "tests" in data or "summary" in data:
                return data
        except json.JSONDecodeError:
            pass

        return None

    def _parse_json_report(self, data: dict[str, Any], raw_output: str) -> ParsedTestResults:
        """Parse pytest-json-report format."""
        test_cases = []
        tests = data.get("tests", [])

        for test in tests:
            nodeid = test.get("nodeid", "")
            outcome = test.get("outcome", "unknown")

            # Map pytest outcomes to our status
            status_map = {
                "passed": "passed",
                "failed": "failed",
                "skipped": "skipped",
                "xfailed": "skipped",  # Expected failure
                "xpassed": "passed",  # Unexpected pass
                "error": "error",
            }
            status = status_map.get(outcome, "error")

            # Parse nodeid: tests/test_foo.py::TestClass::test_method
            file_path, class_name, test_name = self._parse_nodeid(nodeid)

            # Get duration (in seconds, convert to ms)
            duration = test.get("call", {}).get("duration", 0) or test.get("duration", 0)
            duration_ms = int(duration * 1000) if duration else None

            # Get error info
            error_message = None
            stack_trace = None
            if outcome in ("failed", "error"):
                call_info = test.get("call", {})
                if call_info:
                    longrepr = call_info.get("longrepr", "")
                    if longrepr:
                        # First line is usually the error message
                        lines = str(longrepr).split("\n")
                        error_message = lines[-1] if lines else None
                        stack_trace = longrepr

            # Get line number from location
            location = test.get("location", [])
            line = location[1] if len(location) > 1 else None

            test_cases.append(
                TestCaseResult(
                    name=test_name,
                    status=status,
                    file=file_path,
                    class_name=class_name,
                    line=line,
                    duration_ms=duration_ms,
                    error_message=error_message,
                    stack_trace=stack_trace,
                    metadata={
                        "nodeid": nodeid,
                        "markers": test.get("markers", []),
                        "keywords": test.get("keywords", []),
                    },
                )
            )

        # Get summary
        summary = data.get("summary", {})
        duration = data.get("duration", 0)

        return ParsedTestResults(
            test_cases=test_cases,
            total=summary.get("total", len(test_cases)),
            passed=summary.get("passed", 0),
            failed=summary.get("failed", 0),
            skipped=summary.get("skipped", 0) + summary.get("xfailed", 0),
            errors=summary.get("error", 0),
            duration_seconds=duration,
            raw_output=raw_output,
        )

    def _parse_nodeid(self, nodeid: str) -> tuple[str | None, str | None, str]:
        """Parse pytest nodeid into components.

        Args:
            nodeid: e.g., "tests/test_foo.py::TestClass::test_method"

        Returns:
            Tuple of (file_path, class_name, test_name)
        """
        parts = nodeid.split("::")
        file_path = parts[0] if parts else None

        if len(parts) == 3:
            # tests/foo.py::TestClass::test_method
            return file_path, parts[1], parts[2]
        if len(parts) == 2:
            # tests/foo.py::test_function
            return file_path, None, parts[1]
        return file_path, None, nodeid

    def _parse_plain_output(self, output: str, exit_code: int) -> ParsedTestResults:
        """Fallback parser for plain pytest output."""
        test_cases = []

        # Parse test results from output lines
        # Pattern: tests/test_foo.py::test_method PASSED/FAILED
        pattern = r"(\S+\.py::\S+)\s+(PASSED|FAILED|SKIPPED|ERROR)"

        for match in re.finditer(pattern, output, re.IGNORECASE):
            nodeid = match.group(1)
            status = match.group(2).lower()
            file_path, class_name, test_name = self._parse_nodeid(nodeid)

            test_cases.append(
                TestCaseResult(
                    name=test_name,
                    status=status,
                    file=file_path,
                    class_name=class_name,
                )
            )

        # Parse summary line: "5 passed, 2 failed, 1 skipped in 2.34s"
        summary_match = re.search(
            r"(\d+)\s+passed.*?(\d+)\s+failed.*?(\d+)\s+skipped.*?in\s+([\d.]+)s",
            output,
            re.IGNORECASE,
        )

        passed = failed = skipped = 0
        duration = None

        if summary_match:
            passed = int(summary_match.group(1))
            failed = int(summary_match.group(2))
            skipped = int(summary_match.group(3))
            duration = float(summary_match.group(4))
        else:
            # Simpler patterns
            passed_match = re.search(r"(\d+)\s+passed", output)
            failed_match = re.search(r"(\d+)\s+failed", output)
            skipped_match = re.search(r"(\d+)\s+skipped", output)
            duration_match = re.search(r"in\s+([\d.]+)s", output)

            if passed_match:
                passed = int(passed_match.group(1))
            if failed_match:
                failed = int(failed_match.group(1))
            if skipped_match:
                skipped = int(skipped_match.group(1))
            if duration_match:
                duration = float(duration_match.group(1))

        return ParsedTestResults(
            test_cases=test_cases,
            total=passed + failed + skipped,
            passed=passed,
            failed=failed,
            skipped=skipped,
            errors=0,
            duration_seconds=duration,
            raw_output=output,
        )
