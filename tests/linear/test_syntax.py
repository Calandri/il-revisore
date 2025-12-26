"""
Syntax and Structure Tests for Linear Issue Creator.

Run with: uv run pytest tests/linear/test_syntax.py -v

Tests file structure, Python syntax, and basic validations
without requiring runtime dependencies.
"""

import ast
from pathlib import Path

import pytest

# Project root for locating source files
PROJECT_ROOT = Path(__file__).parent.parent.parent


# =============================================================================
# Helper Functions (not test functions)
# =============================================================================


def _check_python_syntax(file_path: Path) -> tuple[bool, str]:
    """Check Python file syntax. Returns (success, message)."""
    try:
        with open(file_path) as f:
            code = f.read()
        ast.parse(code)
        return True, f"{file_path.name}: Valid Python syntax"
    except SyntaxError as e:
        return False, f"{file_path.name}: Syntax error at line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"{file_path.name}: {e}"


def _check_agent_structure(file_path: Path) -> tuple[bool, str]:
    """Check Claude agent markdown structure. Returns (success, message)."""
    try:
        with open(file_path) as f:
            content = f.read()

        # Check frontmatter
        if not content.startswith("---"):
            return False, f"{file_path.name}: Missing frontmatter"

        # Extract frontmatter
        parts = content.split("---", 2)
        if len(parts) < 3:
            return False, f"{file_path.name}: Invalid frontmatter format"

        frontmatter = parts[1].strip()

        # Check required fields
        if "name:" not in frontmatter:
            return False, f"{file_path.name}: Missing 'name' in frontmatter"

        if "model:" not in frontmatter:
            return False, f"{file_path.name}: Missing 'model' in frontmatter"

        return True, f"{file_path.name}: Valid agent structure"

    except Exception as e:
        return False, f"{file_path.name}: {e}"


def _check_html_template_element(
    content: str, check_name: str, check_text: str
) -> tuple[bool, str]:
    """Check if HTML template contains required element."""
    if check_text in content:
        return True, f"{check_name}: Found"
    return False, f"{check_name}: Not found"


def _check_api_routes_structure(file_path: Path) -> tuple[bool, list[str]]:
    """Check API routes structure. Returns (success, list of messages)."""
    try:
        with open(file_path) as f:
            content = f.read()

        messages = []
        all_passed = True

        # Check for required imports
        imports = [
            "import json",
            "import shutil",
            "import subprocess",
            "import uuid",
            "from pathlib import Path",
            "from sse_starlette.sse import EventSourceResponse",
        ]

        for imp in imports:
            if imp not in content:
                messages.append(f"Missing import: {imp}")
                all_passed = False

        # Check for required endpoints
        endpoints = [
            '@router.post("/create/analyze")',
            '@router.post("/create/finalize")',
        ]

        for endpoint in endpoints:
            if endpoint not in content:
                messages.append(f"Missing endpoint: {endpoint}")
                all_passed = False

        # Check for FinalizeIssueRequest schema
        if "class FinalizeIssueRequest" not in content:
            messages.append("Missing FinalizeIssueRequest schema")
            all_passed = False

        if all_passed:
            messages.append(f"{file_path.name}: All required components found")

        return all_passed, messages

    except Exception as e:
        return False, [f"{file_path.name}: {e}"]


# =============================================================================
# Pytest Test Classes
# =============================================================================


@pytest.mark.unit
class TestGeminiExtensionSyntax:
    """Test Gemini Vision extension Python syntax."""

    def test_gemini_py_valid_syntax(self):
        """Gemini extension should have valid Python syntax."""
        gemini_path = PROJECT_ROOT / "src/turbowrap/llm/gemini.py"

        if not gemini_path.exists():
            pytest.skip(f"File not found: {gemini_path}")

        success, message = _check_python_syntax(gemini_path)
        assert success, message


@pytest.mark.unit
class TestLinearClientSyntax:
    """Test Linear client extension Python syntax."""

    def test_linear_client_valid_syntax(self):
        """Linear client should have valid Python syntax."""
        linear_path = PROJECT_ROOT / "src/turbowrap/review/integrations/linear.py"

        if not linear_path.exists():
            pytest.skip(f"File not found: {linear_path}")

        success, message = _check_python_syntax(linear_path)
        assert success, message


@pytest.mark.unit
class TestClaudeAgentStructure:
    """Test Claude agent markdown structure."""

    def test_question_generator_agent_structure(self):
        """Question generator agent should have valid structure."""
        agent_path = PROJECT_ROOT / "agents/linear_question_generator.md"

        if not agent_path.exists():
            pytest.skip(f"Agent file not found: {agent_path}")

        success, message = _check_agent_structure(agent_path)
        assert success, message

    def test_finalizer_agent_structure(self):
        """Finalizer agent should have valid structure."""
        agent_path = PROJECT_ROOT / "agents/linear_finalizer.md"

        if not agent_path.exists():
            pytest.skip(f"Agent file not found: {agent_path}")

        success, message = _check_agent_structure(agent_path)
        assert success, message

    def test_issue_analyzer_agent_structure(self):
        """Issue analyzer agent should have valid structure."""
        agent_path = PROJECT_ROOT / "agents/linear_issue_analyzer.md"

        if not agent_path.exists():
            pytest.skip(f"Agent file not found: {agent_path}")

        success, message = _check_agent_structure(agent_path)
        assert success, message


@pytest.mark.unit
class TestLinearAPIRoutesSyntax:
    """Test Linear API routes Python syntax."""

    def test_linear_routes_valid_syntax(self):
        """Linear routes should have valid Python syntax."""
        routes_path = PROJECT_ROOT / "src/turbowrap/api/routes/linear.py"

        if not routes_path.exists():
            pytest.skip(f"File not found: {routes_path}")

        success, message = _check_python_syntax(routes_path)
        assert success, message


@pytest.mark.unit
class TestLinearAPIRoutesStructure:
    """Test Linear API routes have required structure."""

    def test_linear_routes_has_required_imports(self):
        """Linear routes should have required imports."""
        routes_path = PROJECT_ROOT / "src/turbowrap/api/routes/linear.py"

        if not routes_path.exists():
            pytest.skip(f"File not found: {routes_path}")

        success, messages = _check_api_routes_structure(routes_path)
        assert success, "\n".join(messages)


@pytest.mark.unit
class TestFrontendTemplateStructure:
    """Test frontend template has required UI elements."""

    @pytest.fixture
    def template_content(self):
        """Load template content if file exists."""
        template_path = PROJECT_ROOT / "src/turbowrap/api/templates/pages/linear_issues.html"

        if not template_path.exists():
            pytest.skip(f"Template not found: {template_path}")

        with open(template_path) as f:
            return f.read()

    def test_has_create_issue_button(self, template_content):
        """Template should have Create Issue button."""
        success, msg = _check_html_template_element(
            template_content, "Create Issue button", "openCreateModal()"
        )
        assert success, msg

    def test_has_create_modal_html(self, template_content):
        """Template should have Create modal HTML."""
        success, msg = _check_html_template_element(
            template_content, "Create modal HTML", "<!-- Create Issue Modal"
        )
        assert success, msg

    def test_has_alpine_createmodal_state(self, template_content):
        """Template should have Alpine.js createModal state."""
        success, msg = _check_html_template_element(
            template_content, "Alpine.js createModal state", "createModal: {"
        )
        assert success, msg

    def test_has_open_create_modal_function(self, template_content):
        """Template should have openCreateModal function."""
        success, msg = _check_html_template_element(
            template_content, "openCreateModal function", "openCreateModal() {"
        )
        assert success, msg

    def test_has_close_create_modal_function(self, template_content):
        """Template should have closeCreateModal function."""
        success, msg = _check_html_template_element(
            template_content, "closeCreateModal function", "closeCreateModal() {"
        )
        assert success, msg

    def test_has_screenshot_upload_handler(self, template_content):
        """Template should have handleScreenshotUpload function."""
        success, msg = _check_html_template_element(
            template_content, "handleScreenshotUpload function", "handleScreenshotUpload(event)"
        )
        assert success, msg

    def test_has_analyze_with_ai_function(self, template_content):
        """Template should have analyzeWithAI function."""
        success, msg = _check_html_template_element(
            template_content, "analyzeWithAI function", "analyzeWithAI()"
        )
        assert success, msg

    def test_has_finalize_issue_creation_function(self, template_content):
        """Template should have finalizeIssueCreation function."""
        success, msg = _check_html_template_element(
            template_content, "finalizeIssueCreation function", "finalizeIssueCreation()"
        )
        assert success, msg

    def test_has_step_1_form(self, template_content):
        """Template should have Step 1 form."""
        success, msg = _check_html_template_element(
            template_content, "Step 1 form", 'x-show="createModal.step === 1"'
        )
        assert success, msg

    def test_has_step_2_analysis(self, template_content):
        """Template should have Step 2 analysis."""
        success, msg = _check_html_template_element(
            template_content, "Step 2 analysis", 'x-show="createModal.step === 2"'
        )
        assert success, msg

    def test_has_step_3_creating(self, template_content):
        """Template should have Step 3 creating."""
        success, msg = _check_html_template_element(
            template_content, "Step 3 creating", 'x-show="createModal.step === 3"'
        )
        assert success, msg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
