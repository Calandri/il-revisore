"""Test file scanner service.

Scans test files to extract test functions/methods without running them.
Uses AST for Python, regex for JavaScript/TypeScript.
"""

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ScannedTest:
    """A single test function/method found in a file."""

    name: str
    line: int
    end_line: int | None = None
    class_name: str | None = None  # For class-based tests
    decorators: list[str] = field(default_factory=list)
    docstring: str | None = None
    is_async: bool = False
    # Last run status (if available)
    status: str | None = None  # passed | failed | skipped | None


@dataclass
class ScannedTestFile:
    """A test file with its discovered tests."""

    path: str  # Relative path from repo root
    filename: str
    framework: str  # pytest | jest | vitest | playwright | cypress
    tests: list[ScannedTest] = field(default_factory=list)
    error: str | None = None

    @property
    def test_count(self) -> int:
        return len(self.tests)


@dataclass
class ScanResult:
    """Result of scanning a test suite."""

    success: bool
    files: list[ScannedTestFile] = field(default_factory=list)
    total_tests: int = 0
    error: str | None = None

    @property
    def total_files(self) -> int:
        return len(self.files)


class PythonTestScanner:
    """Scans Python test files using AST."""

    def scan_file(self, file_path: Path, relative_path: str) -> ScannedTestFile:
        """Scan a Python test file for test functions."""
        result = ScannedTestFile(
            path=relative_path,
            filename=file_path.name,
            framework="pytest",
        )

        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except SyntaxError as e:
            result.error = f"Syntax error: {e}"
            return result
        except Exception as e:
            result.error = str(e)
            return result

        for node in ast.walk(tree):
            # Top-level test functions
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                if node.name.startswith("test_"):
                    result.tests.append(self._extract_test(node))

            # Test classes
            elif isinstance(node, ast.ClassDef):
                if node.name.startswith("Test"):
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                            if item.name.startswith("test_"):
                                test = self._extract_test(item)
                                test.class_name = node.name
                                result.tests.append(test)

        return result

    def _extract_test(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ScannedTest:
        """Extract test info from AST node."""
        decorators = []
        for dec in node.decorator_list:
            if isinstance(dec, ast.Name):
                decorators.append(dec.id)
            elif isinstance(dec, ast.Attribute):
                decorators.append(dec.attr)
            elif isinstance(dec, ast.Call):
                if isinstance(dec.func, ast.Name):
                    decorators.append(dec.func.id)
                elif isinstance(dec.func, ast.Attribute):
                    decorators.append(dec.func.attr)

        docstring = ast.get_docstring(node)

        return ScannedTest(
            name=node.name,
            line=node.lineno,
            end_line=node.end_lineno,
            decorators=decorators,
            docstring=docstring,
            is_async=isinstance(node, ast.AsyncFunctionDef),
        )


class JavaScriptTestScanner:
    """Scans JavaScript/TypeScript test files using regex."""

    # Patterns for different test frameworks
    PATTERNS = [
        # Jest/Vitest: test('name', ...) or it('name', ...)
        r"(?:test|it)\s*\(\s*['\"](.+?)['\"]",
        # Jest/Vitest: describe('name', ...) - for grouping
        r"describe\s*\(\s*['\"](.+?)['\"]",
        # Playwright: test('name', ...)
        r"test\s*\(\s*['\"](.+?)['\"]",
        # Cypress: it('name', ...) or specify('name', ...)
        r"(?:it|specify)\s*\(\s*['\"](.+?)['\"]",
    ]

    def __init__(self, framework: str = "jest"):
        self.framework = framework

    def scan_file(self, file_path: Path, relative_path: str) -> ScannedTestFile:
        """Scan a JS/TS test file for test functions."""
        result = ScannedTestFile(
            path=relative_path,
            filename=file_path.name,
            framework=self.framework,
        )

        try:
            source = file_path.read_text(encoding="utf-8")
            lines = source.split("\n")
        except Exception as e:
            result.error = str(e)
            return result

        # Find test/it calls
        test_pattern = re.compile(r"^\s*(?:test|it)\s*\(\s*['\"`](.+?)['\"`]", re.MULTILINE)

        for i, line in enumerate(lines, 1):
            match = test_pattern.match(line)
            if match:
                result.tests.append(
                    ScannedTest(
                        name=match.group(1),
                        line=i,
                        is_async="async" in line,
                    )
                )

        return result


def get_scanner_for_framework(framework: str):
    """Get the appropriate scanner for a test framework."""
    if framework in ("pytest", "python"):
        return PythonTestScanner()
    elif framework in ("jest", "vitest", "playwright", "cypress"):
        return JavaScriptTestScanner(framework)
    else:
        return PythonTestScanner()  # Default to Python


def scan_test_suite(
    repo_path: Path,
    suite_path: str,
    framework: str,
) -> ScanResult:
    """Scan all test files in a suite directory.

    Args:
        repo_path: Root path of the repository.
        suite_path: Relative path to the test suite directory.
        framework: Test framework (pytest, jest, vitest, etc.)

    Returns:
        ScanResult with all discovered tests.
    """
    full_path = repo_path / suite_path

    if not full_path.exists():
        return ScanResult(success=False, error=f"Path not found: {suite_path}")

    scanner = get_scanner_for_framework(framework)
    result = ScanResult(success=True)

    # Determine file patterns based on framework
    if framework in ("pytest", "python"):
        patterns = ["test_*.py", "*_test.py"]
    else:
        patterns = ["*.test.ts", "*.test.js", "*.spec.ts", "*.spec.js"]

    # Find all test files
    test_files: list[Path] = []
    for pattern in patterns:
        test_files.extend(full_path.rglob(pattern))

    # Scan each file
    for file_path in sorted(test_files):
        relative_path = str(file_path.relative_to(repo_path))
        scanned_file = scanner.scan_file(file_path, relative_path)
        result.files.append(scanned_file)
        result.total_tests += scanned_file.test_count

    logger.info(f"[TEST SCANNER] Scanned {len(result.files)} files, found {result.total_tests} tests")

    return result


def get_test_source_code(
    repo_path: Path,
    file_path: str,
    start_line: int,
    end_line: int | None = None,
    context_lines: int = 5,
) -> str | None:
    """Get source code for a specific test function.

    Args:
        repo_path: Root path of the repository.
        file_path: Relative path to the test file.
        start_line: Starting line number (1-indexed).
        end_line: Ending line number (optional).
        context_lines: Extra lines before/after for context.

    Returns:
        Source code string or None if not found.
    """
    full_path = repo_path / file_path

    if not full_path.exists():
        return None

    try:
        lines = full_path.read_text(encoding="utf-8").split("\n")

        # Calculate range
        start = max(0, start_line - 1 - context_lines)
        if end_line:
            end = min(len(lines), end_line + context_lines)
        else:
            # Estimate end by looking for next function or class
            end = min(len(lines), start_line + 50)  # Max 50 lines

        return "\n".join(lines[start:end])
    except Exception as e:
        logger.error(f"Failed to read test source: {e}")
        return None
