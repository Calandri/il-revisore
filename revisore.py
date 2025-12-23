#!/usr/bin/env python3
"""
Il Revisore - Orchestrates Gemini agents to analyze and review code repositories.

Usage:
    python revisore.py /path/to/repo [--output ./output]

Example:
    python revisore.py ~/code/my-project
    python revisore.py ~/code/my-project --output ./reviews --max-workers 5
"""

import argparse
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Literal

from google import genai

# ============================================================================
# Configuration
# ============================================================================

AGENTS_DIR = Path(__file__).parent / "agents"

# File extensions by type
BE_EXTENSIONS = {".py"}
FE_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js"}

# Directories to ignore
IGNORE_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", "coverage", ".pytest_cache",
    "eggs", "*.egg-info", ".tox", ".mypy_cache", ".reviews"
}

# Files to ignore
IGNORE_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}

# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class FileInfo:
    path: Path
    type: Literal["be", "fe"]
    content: str = ""

@dataclass
class ReviewIssue:
    file: str
    line: str
    severity: Literal["critical", "warning", "info"]
    category: str
    description: str
    suggestion: str

@dataclass
class ReviewResult:
    files: list[str]
    issues: list[ReviewIssue] = field(default_factory=list)
    summary: str = ""

# ============================================================================
# Gemini Client
# ============================================================================

class GeminiClient:
    def __init__(self, model: str = "gemini-2.0-flash"):
        api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable")

        self.client = genai.Client(api_key=api_key)
        self.model = model

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate content using Gemini."""
        contents = []
        if system_prompt:
            contents.append({"role": "user", "parts": [{"text": system_prompt}]})
            contents.append({"role": "model", "parts": [{"text": "Understood. I will follow these instructions."}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        response = self.client.models.generate_content(
            model=self.model,
            contents=contents,
        )
        return response.text

# ============================================================================
# File Discovery
# ============================================================================

def should_ignore(path: Path) -> bool:
    """Check if path should be ignored."""
    for part in path.parts:
        if part in IGNORE_DIRS or part.startswith("."):
            return True
    return path.name in IGNORE_FILES

def discover_files(repo_path: Path) -> tuple[list[FileInfo], list[FileInfo]]:
    """Discover BE and FE files in repository."""
    be_files: list[FileInfo] = []
    fe_files: list[FileInfo] = []

    for file_path in repo_path.rglob("*"):
        if not file_path.is_file() or should_ignore(file_path):
            continue

        suffix = file_path.suffix.lower()
        rel_path = file_path.relative_to(repo_path)

        if suffix in BE_EXTENSIONS:
            be_files.append(FileInfo(path=rel_path, type="be"))
        elif suffix in FE_EXTENSIONS:
            fe_files.append(FileInfo(path=rel_path, type="fe"))

    return be_files, fe_files

def load_file_content(repo_path: Path, file_info: FileInfo) -> FileInfo:
    """Load file content."""
    full_path = repo_path / file_info.path
    try:
        file_info.content = full_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        file_info.content = f"# Error reading file: {e}"
    return file_info

# ============================================================================
# Agent: Flash Analyzer (Repository Description)
# ============================================================================

def run_flash_analyzer(client: GeminiClient, repo_path: Path, output_dir: Path) -> Path:
    """Run Flash analyzer to create/update repository description."""
    print("\n🔍 Running Flash Analyzer - Analyzing repository structure...")

    system_prompt = (AGENTS_DIR / "flash_analyzer.md").read_text()

    # Gather repository structure
    structure_lines = ["# Repository Structure\n"]
    for item in sorted(repo_path.rglob("*")):
        if should_ignore(item):
            continue
        rel = item.relative_to(repo_path)
        if item.is_dir():
            structure_lines.append(f"📁 {rel}/")
        else:
            structure_lines.append(f"   📄 {rel}")

    structure = "\n".join(structure_lines[:500])  # Limit to avoid token overflow

    # Read key files for context
    key_files_content = []
    key_files = ["README.md", "pyproject.toml", "package.json", "requirements.txt"]
    for kf in key_files:
        kf_path = repo_path / kf
        if kf_path.exists():
            content = kf_path.read_text(encoding="utf-8", errors="ignore")[:2000]
            key_files_content.append(f"## {kf}\n```\n{content}\n```")

    prompt = f"""Analyze this repository and create a comprehensive description.

{structure}

## Key Files Content
{chr(10).join(key_files_content)}

Create a markdown document with:
1. **Overview**: What this project does
2. **Tech Stack**: Technologies used (BE/FE)
3. **Project Structure**: Key directories and their purpose
4. **Key Components**: Main modules/components
5. **Dependencies**: Important external dependencies
6. **Architecture Notes**: How the system is organized

Be concise but thorough.
"""

    result = client.generate(prompt, system_prompt)

    # Save result
    output_file = output_dir / "REPO_DESCRIPTION.md"
    output_file.write_text(f"# Repository Analysis\n\n*Generated by Il Revisore - Flash Analyzer*\n\n{result}")
    print(f"   ✅ Saved: {output_file}")

    return output_file

# ============================================================================
# Agent: Code Reviewer (BE/FE)
# ============================================================================

def run_reviewer_agent(
    client: GeminiClient,
    repo_path: Path,
    files: list[FileInfo],
    agent_type: Literal["be", "fe"],
    batch_id: int
) -> ReviewResult:
    """Run reviewer agent on a batch of files."""
    agent_file = "reviewer_be.md" if agent_type == "be" else "reviewer_fe.md"
    system_prompt = (AGENTS_DIR / agent_file).read_text()

    # Load file contents
    files_with_content = [load_file_content(repo_path, f) for f in files]

    # Build prompt
    files_section = []
    for f in files_with_content:
        files_section.append(f"## File: {f.path}\n```\n{f.content[:8000]}\n```\n")

    lang = "Python/Backend" if agent_type == "be" else "React/TypeScript/Frontend"

    prompt = f"""Review the following {lang} files for issues and improvements.

{chr(10).join(files_section)}

For each issue found, provide:
1. **File**: Which file
2. **Line**: Approximate line number or section
3. **Severity**: critical / warning / info
4. **Category**: (e.g., security, performance, maintainability, bug, style)
5. **Description**: Clear description of the issue
6. **Suggestion**: How to fix it

Format your response as a structured list. Be specific and actionable.
Focus on real issues, not style nitpicks unless they affect readability significantly.
"""

    result = client.generate(prompt, system_prompt)

    return ReviewResult(
        files=[str(f.path) for f in files],
        summary=result
    )

def run_all_reviewers(
    client: GeminiClient,
    repo_path: Path,
    be_files: list[FileInfo],
    fe_files: list[FileInfo],
    max_workers: int = 3
) -> list[ReviewResult]:
    """Run reviewer agents in parallel, 1 agent per 3 files."""
    results: list[ReviewResult] = []

    # Create batches of 3 files
    def create_batches(files: list[FileInfo], batch_size: int = 3):
        for i in range(0, len(files), batch_size):
            yield files[i:i + batch_size]

    be_batches = list(create_batches(be_files))
    fe_batches = list(create_batches(fe_files))

    total_batches = len(be_batches) + len(fe_batches)
    print(f"\n🔎 Running Reviewers - {len(be_batches)} BE batches, {len(fe_batches)} FE batches")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}

        # Submit BE review tasks
        for i, batch in enumerate(be_batches):
            future = executor.submit(run_reviewer_agent, client, repo_path, batch, "be", i)
            futures[future] = f"BE batch {i+1}/{len(be_batches)}"

        # Submit FE review tasks
        for i, batch in enumerate(fe_batches):
            future = executor.submit(run_reviewer_agent, client, repo_path, batch, "fe", i)
            futures[future] = f"FE batch {i+1}/{len(fe_batches)}"

        # Collect results
        completed = 0
        for future in as_completed(futures):
            completed += 1
            batch_name = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(f"   ✅ [{completed}/{total_batches}] {batch_name} - {len(result.files)} files")
            except Exception as e:
                print(f"   ❌ [{completed}/{total_batches}] {batch_name} - Error: {e}")

    return results

# ============================================================================
# Generate TODO List
# ============================================================================

def generate_todo_list(results: list[ReviewResult], output_dir: Path) -> Path:
    """Generate comprehensive TODO list from review results."""
    print("\n📝 Generating TODO List...")

    lines = [
        "# 📋 Code Review TODO List",
        "",
        f"*Generated by Il Revisore: {time.strftime('%Y-%m-%d %H:%M:%S')}*",
        "",
        "---",
        "",
        "## 📊 Summary",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total batches reviewed | {len(results)} |",
        f"| Total files analyzed | {sum(len(r.files) for r in results)} |",
        "",
        "---",
        "",
    ]

    # Group by BE/FE
    be_results = [r for r in results if any(".py" in f for f in r.files)]
    fe_results = [r for r in results if any(f.endswith(('.tsx', '.ts', '.jsx', '.js')) for f in r.files)]

    # Backend section
    if be_results:
        lines.extend([
            "## 🐍 Backend (Python) Issues",
            "",
        ])
        for i, result in enumerate(be_results, 1):
            files_str = ", ".join([f"`{f}`" for f in result.files])
            lines.append(f"### Batch {i}")
            lines.append(f"**Files:** {files_str}")
            lines.append("")
            lines.append(result.summary)
            lines.append("")
            lines.append("---")
            lines.append("")

    # Frontend section
    if fe_results:
        lines.extend([
            "## ⚛️ Frontend (React/TypeScript) Issues",
            "",
        ])
        for i, result in enumerate(fe_results, 1):
            files_str = ", ".join([f"`{f}`" for f in result.files])
            lines.append(f"### Batch {i}")
            lines.append(f"**Files:** {files_str}")
            lines.append("")
            lines.append(result.summary)
            lines.append("")
            lines.append("---")
            lines.append("")

    # Action items template
    lines.extend([
        "## ✅ Action Items Checklist",
        "",
        "### 🔴 Critical (Fix Immediately)",
        "- [ ] Review and fix all issues marked as **critical** above",
        "",
        "### 🟠 High Priority (This Sprint)",
        "- [ ] Review and fix all issues marked as **warning** above",
        "",
        "### 🟢 Low Priority (Backlog)",
        "- [ ] Review issues marked as **info** for future improvements",
        "",
        "---",
        "",
        "*Generated with ❤️ by Il Revisore*",
    ])

    output_file = output_dir / "REVIEW_TODO.md"
    output_file.write_text("\n".join(lines))
    print(f"   ✅ Saved: {output_file}")

    return output_file

# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="🔍 Il Revisore - Analyze repository with Gemini agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python revisore.py ~/code/my-project
    python revisore.py ~/code/my-project --output ./reviews
    python revisore.py ~/code/my-project --max-workers 5
    python revisore.py ~/code/my-project --skip-flash  # Skip repo analysis
        """
    )
    parser.add_argument("repo_path", type=Path, help="Path to repository to analyze")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output directory (default: <repo>/.reviews)")
    parser.add_argument("--max-workers", "-w", type=int, default=3, help="Max parallel review agents (default: 3)")
    parser.add_argument("--skip-flash", action="store_true", help="Skip Flash analyzer (repo description)")
    parser.add_argument("--skip-review", action="store_true", help="Skip code review")

    args = parser.parse_args()

    repo_path = args.repo_path.resolve()
    if not repo_path.exists():
        print(f"❌ Repository path not found: {repo_path}")
        sys.exit(1)

    output_dir = args.output or (repo_path / ".reviews")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("🔍 IL REVISORE - Code Repository Analyzer")
    print("=" * 60)
    print(f"   📁 Repository: {repo_path}")
    print(f"   📂 Output: {output_dir}")
    print("=" * 60)

    # Initialize Gemini client
    try:
        client = GeminiClient()
        print("   ✅ Gemini client initialized")
    except ValueError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Discover files
    be_files, fe_files = discover_files(repo_path)
    print(f"\n📂 Discovered Files:")
    print(f"   🐍 Python (BE): {len(be_files)} files")
    print(f"   ⚛️  React/TS (FE): {len(fe_files)} files")

    # Run Flash Analyzer
    if not args.skip_flash:
        run_flash_analyzer(client, repo_path, output_dir)

    # Run Reviewers
    if not args.skip_review and (be_files or fe_files):
        results = run_all_reviewers(client, repo_path, be_files, fe_files, args.max_workers)
        generate_todo_list(results, output_dir)

    print("\n" + "=" * 60)
    print(f"✨ Done! Check {output_dir} for results:")
    print(f"   📄 REPO_DESCRIPTION.md - Repository overview")
    print(f"   📋 REVIEW_TODO.md - Issues and action items")
    print("=" * 60)

if __name__ == "__main__":
    main()
