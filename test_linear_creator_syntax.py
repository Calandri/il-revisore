#!/usr/bin/env python3
"""
Syntax and Structure Test for Linear Issue Creator

Tests file structure, Python syntax, and basic validations
without requiring runtime dependencies.
"""

import ast
import json
import re
import sys
from pathlib import Path


def print_header(title: str):
    """Print formatted test section header."""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def test_python_syntax(file_path: Path) -> bool:
    """Test Python file syntax."""
    try:
        with open(file_path, 'r') as f:
            code = f.read()
        ast.parse(code)
        print(f"✅ {file_path.name}: Valid Python syntax")
        return True
    except SyntaxError as e:
        print(f"❌ {file_path.name}: Syntax error at line {e.lineno}: {e.msg}")
        return False
    except Exception as e:
        print(f"❌ {file_path.name}: {e}")
        return False


def test_agent_structure(file_path: Path) -> bool:
    """Test Claude agent markdown structure."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()

        # Check frontmatter
        if not content.startswith('---'):
            print(f"❌ {file_path.name}: Missing frontmatter")
            return False

        # Extract frontmatter
        parts = content.split('---', 2)
        if len(parts) < 3:
            print(f"❌ {file_path.name}: Invalid frontmatter format")
            return False

        frontmatter = parts[1].strip()

        # Check required fields
        if 'name:' not in frontmatter:
            print(f"❌ {file_path.name}: Missing 'name' in frontmatter")
            return False

        if 'model:' not in frontmatter:
            print(f"❌ {file_path.name}: Missing 'model' in frontmatter")
            return False

        # Extract model
        model_match = re.search(r'model:\s*(.+)', frontmatter)
        if model_match:
            model = model_match.group(1).strip()
            if 'claude' not in model.lower():
                print(f"⚠️  {file_path.name}: Model '{model}' doesn't seem to be Claude")

        print(f"✅ {file_path.name}: Valid agent structure")
        return True

    except Exception as e:
        print(f"❌ {file_path.name}: {e}")
        return False


def test_html_template(file_path: Path) -> bool:
    """Test HTML template structure."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()

        # Check for required elements
        checks = [
            ("Create Issue button", 'openCreateModal()'),
            ("Create modal HTML", '<!-- Create Issue Modal'),
            ("Alpine.js createModal state", 'createModal: {'),
            ("openCreateModal function", 'openCreateModal() {'),
            ("closeCreateModal function", 'closeCreateModal() {'),
            ("handleScreenshotUpload function", 'handleScreenshotUpload(event)'),
            ("analyzeWithAI function", 'analyzeWithAI()'),
            ("finalizeIssueCreation function", 'finalizeIssueCreation()'),
            ("Step 1 form", 'x-show="createModal.step === 1"'),
            ("Step 2 analysis", 'x-show="createModal.step === 2"'),
            ("Step 3 creating", 'x-show="createModal.step === 3"'),
        ]

        passed = True
        for check_name, check_text in checks:
            if check_text in content:
                print(f"✅ {check_name}: Found")
            else:
                print(f"❌ {check_name}: Not found")
                passed = False

        # Count lines
        line_count = len(content.split('\n'))
        print(f"ℹ️  Total lines: {line_count}")

        return passed

    except Exception as e:
        print(f"❌ {file_path.name}: {e}")
        return False


def test_api_routes(file_path: Path) -> bool:
    """Test API routes structure."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()

        # Check for required imports
        imports = [
            'import json',
            'import shutil',
            'import subprocess',
            'import uuid',
            'from pathlib import Path',
            'from sse_starlette.sse import EventSourceResponse',
        ]

        for imp in imports:
            if imp not in content:
                print(f"❌ Missing import: {imp}")
                return False

        # Check for required endpoints
        endpoints = [
            '@router.post("/create/analyze")',
            '@router.post("/create/finalize")',
        ]

        for endpoint in endpoints:
            if endpoint not in content:
                print(f"❌ Missing endpoint: {endpoint}")
                return False

        # Check for FinalizeIssueRequest schema
        if 'class FinalizeIssueRequest' not in content:
            print("❌ Missing FinalizeIssueRequest schema")
            return False

        print(f"✅ {file_path.name}: All required components found")
        return True

    except Exception as e:
        print(f"❌ {file_path.name}: {e}")
        return False


def main():
    """Run all syntax tests."""
    print("\n" + "=" * 70)
    print("  LINEAR ISSUE CREATOR - SYNTAX & STRUCTURE TEST".center(70))
    print("=" * 70)

    results = {}
    base_path = Path(__file__).parent

    # Test STEP 1: Gemini extension
    print_header("STEP 1: Gemini Vision Extension")
    gemini_path = base_path / "src/turbowrap/llm/gemini.py"
    results['gemini'] = test_python_syntax(gemini_path)

    # Test STEP 2: Linear client
    print_header("STEP 2: Linear Client Extension")
    linear_client_path = base_path / "src/turbowrap/review/integrations/linear.py"
    results['linear_client'] = test_python_syntax(linear_client_path)

    # Test STEP 3: Claude agents
    print_header("STEP 3: Claude Agent Prompts")
    question_gen_path = base_path / "agents/linear_question_generator.md"
    finalizer_path = base_path / "agents/linear_finalizer.md"
    results['question_gen'] = test_agent_structure(question_gen_path)
    results['finalizer'] = test_agent_structure(finalizer_path)

    # Test STEP 4: API routes
    print_header("STEP 4: Backend API Endpoints")
    routes_path = base_path / "src/turbowrap/api/routes/linear.py"
    results['routes'] = test_python_syntax(routes_path)
    results['routes_structure'] = test_api_routes(routes_path)

    # Test STEP 5: Frontend
    print_header("STEP 5: Frontend Modal UI")
    template_path = base_path / "src/turbowrap/api/templates/pages/linear_issues.html"
    results['frontend'] = test_html_template(template_path)

    # Summary
    print("\n" + "=" * 70)
    print("  TEST SUMMARY".center(70))
    print("=" * 70)

    total = len(results)
    passed = sum(1 for v in results.values() if v)

    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {name:30} {status}")

    print("-" * 70)
    print(f"  Total: {passed}/{total} tests passed".center(70))
    print("=" * 70)

    if passed == total:
        print("\n✅ All syntax and structure tests passed!")
        print("ℹ️  Implementation is complete and ready for runtime testing")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
