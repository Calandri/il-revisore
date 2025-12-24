#!/usr/bin/env python3
"""
TurboWrap - Orchestrates AI agents to analyze and review code repositories.

Agents:
    - Flash Analyzer (Gemini Flash): Fast repo structure analysis
    - Code Reviewer (Claude Opus): Deep code review

Usage:
    python turbowrap.py /path/to/repo [--output ./output]

Example:
    python turbowrap.py ~/code/my-project
    python turbowrap.py ~/code/my-project --output ./reviews --max-workers 5
"""

import argparse
import os
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Literal

import tiktoken

# Token encoder (cached)
_encoder = tiktoken.get_encoding("cl100k_base")

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

# Tree generation config
MAX_TREE_DEPTH = 3
STRUCTURE_FILENAME = "STRUCTURE.md"
FE_ELEMENTS = ["Component", "Hook", "Utils", "Context", "Type"]
BE_ELEMENTS = ["Function", "Class", "Decorator", "Constant"]

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

@dataclass
class FileElement:
    """Elemento estratto da un file (Component, Hook, Function, etc.)."""
    type: str           # "Component", "Hook", "Utils", "Function", "Class"
    name: str           # Nome elemento
    description: str    # Max 10 parole

@dataclass
class FileStructure:
    """Struttura di un file analizzato per tree generation."""
    path: Path
    file_type: Literal["be", "fe"]
    elements: list[FileElement] = field(default_factory=list)
    tokens: int = 0
    lines: int = 0

@dataclass
class DirectoryStructure:
    """Struttura di una cartella per STRUCTURE.md generation."""
    path: Path
    depth: int
    files: list[FileStructure] = field(default_factory=list)
    subdirectories: list["DirectoryStructure"] = field(default_factory=list)

# ============================================================================
# Gemini Client (for Flash Analyzer)
# ============================================================================

class GeminiClient:
    """Client for Google Gemini API (Flash model for fast analysis)."""

    def __init__(self, model: str = "gemini-3-flash-preview"):
        from google import genai

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


class GeminiProClient(GeminiClient):
    """Client for Google Gemini 3 Pro API (for comprehensive analysis)."""

    def __init__(self, model: str = "gemini-3-pro-preview"):
        super().__init__(model=model)

# ============================================================================
# Claude Client (for Opus Reviewer)
# ============================================================================

class ClaudeClient:
    """Client for Anthropic Claude API (Opus model for deep review)."""

    def __init__(self, model: str = "claude-opus-4-5-20251101"):
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("Set ANTHROPIC_API_KEY environment variable")

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def generate(self, prompt: str, system_prompt: str = "") -> str:
        """Generate content using Claude Opus."""
        message = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=system_prompt if system_prompt else "You are a senior code reviewer.",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return message.content[0].text

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


def count_tokens(content: str) -> int:
    """Count tokens using tiktoken cl100k_base encoding."""
    return len(_encoder.encode(content))

# ============================================================================
# Agent: Flash Analyzer (Repository Description) - Gemini Flash
# ============================================================================

def run_repo_analyzer(
    client: GeminiProClient,
    repo_path: Path,
    output_dir: Path,
    structure_files: list[Path]
) -> Path:
    """
    Run Repo Analyzer (Level 2) - uses Gemini Pro to synthesize STRUCTURE.md files.

    This is the second level of analysis that reads all generated STRUCTURE.md
    files and creates a comprehensive repository description.
    """
    print("\n🧠 [Gemini Pro] Synthesizing repository analysis...")

    system_prompt = (AGENTS_DIR / "flash_analyzer.md").read_text()

    # Read all STRUCTURE.md files
    structure_contents = []
    total_tokens = 0
    total_files = 0

    for struct_file in sorted(structure_files):
        try:
            content = struct_file.read_text(encoding="utf-8", errors="ignore")
            rel_path = struct_file.relative_to(repo_path)
            structure_contents.append(f"## {rel_path}\n\n{content}")

            # Extract stats from content
            if "tokens" in content:
                # Parse token counts from the file
                import re
                token_matches = re.findall(r'(\d{1,3}(?:,\d{3})*)\s*tokens', content)
                for match in token_matches:
                    total_tokens += int(match.replace(',', ''))
                file_matches = re.findall(r'(\d+)\s*files?', content)
                for match in file_matches:
                    total_files += int(match)
        except Exception as e:
            print(f"   ⚠️  Could not read {struct_file}: {e}")

    # Read key configuration files for additional context
    key_files_content = []
    key_files = [
        "README.md",
        "pyproject.toml",
        "package.json",
        "Dockerfile",
    ]

    for kf in key_files:
        kf_path = repo_path / kf
        if kf_path.exists():
            try:
                content = kf_path.read_text(encoding="utf-8", errors="ignore")[:2000]
                key_files_content.append(f"## {kf}\n```\n{content}\n```")
            except Exception:
                pass

    prompt = f"""You are analyzing a codebase that has already been pre-analyzed.
Below are the STRUCTURE.md files generated for each directory, containing:
- File statistics (lines, tokens)
- Extracted code elements (Functions, Classes, Components, Hooks, etc.)
- Directory organization

Your task is to synthesize this information into a comprehensive repository description.

## Pre-analyzed Structure Files

{chr(10).join(structure_contents)}

## Key Configuration Files

{chr(10).join(key_files_content)}

---

Based on ALL the information above, create a comprehensive technical analysis following this format:

# Repository Analysis: [Project Name]

## Overview
Brief 2-3 sentence description of what this project does.

## Tech Stack

| Category | Technology |
|----------|------------|
| Language | ... |
| Backend | ... |
| Frontend | ... |
| Database | ... |
| Validation | ... |
| AI/LLM | ... |

## Architecture
- **Pattern**: (Monolith, Microservices, Modular Monolith, etc.)
- **Entry Points**: (CLI, REST API, GraphQL, Web App, etc.)
- **Key Design Patterns**: (Repository, DI, CQRS, etc.)

## Project Structure
```
[tree diagram of key directories]
```

## Module Analysis
For each major module/directory, provide:
- Purpose
- Key components
- Token complexity

## DevOps
- CI/CD setup
- Containerization
- Code quality tools

## Key Dependencies
List the most important dependencies with their purpose.

## Complexity Analysis
| Module | Files | Tokens | Complexity |
|--------|-------|--------|------------|
| ... | ... | ... | Low/Medium/High |

## Notes
Important observations about architecture, patterns, or potential improvements.

Be specific and use the exact data from the STRUCTURE.md files.
"""

    result = client.generate(prompt, system_prompt)

    # Save result with metadata
    output_content = f"""# Repository Analysis

*Generated by TurboWrap - Gemini Pro (Level 2 Synthesis)*
*Date: {time.strftime('%Y-%m-%d %H:%M:%S')}*
*Based on {len(structure_files)} STRUCTURE.md files*

---

{result}
"""

    output_file = output_dir / "REPO_DESCRIPTION.md"
    output_file.write_text(output_content)
    print(f"   ✅ Saved: {output_file}")
    print(f"   📊 Synthesized from {len(structure_files)} structure files")

    return output_file


def run_flash_analyzer(client: GeminiClient, repo_path: Path, output_dir: Path) -> Path:
    """
    Run Flash analyzer (Legacy - Level 1 only).
    Use run_repo_analyzer for Level 2 synthesis after tree generation.
    """
    print("\n🔍 [Gemini Flash] Analyzing repository structure...")

    system_prompt = (AGENTS_DIR / "flash_analyzer.md").read_text()

    # Gather repository structure with token counts
    structure_lines = ["# Repository Structure\n"]
    total_tokens = 0
    total_files = 0

    for item in sorted(repo_path.rglob("*")):
        if should_ignore(item):
            continue
        rel = item.relative_to(repo_path)
        if item.is_dir():
            structure_lines.append(f"📁 {rel}/")
        else:
            # Count tokens for code files
            suffix = item.suffix.lower()
            if suffix in BE_EXTENSIONS | FE_EXTENSIONS:
                try:
                    content = item.read_text(encoding="utf-8", errors="ignore")
                    tokens = count_tokens(content)
                    total_tokens += tokens
                    total_files += 1
                    structure_lines.append(f"   📄 {rel} ({tokens:,} tokens)")
                except Exception:
                    structure_lines.append(f"   📄 {rel}")
            else:
                structure_lines.append(f"   📄 {rel}")

    structure = "\n".join(structure_lines[:500])  # Limit to avoid token overflow

    # Read key configuration files for context
    key_files_content = []

    # Project definition files
    project_files = [
        "README.md",
        "pyproject.toml",
        "package.json",
        "requirements.txt",
        "setup.py",
        "Cargo.toml",
        "go.mod",
    ]

    # Config files
    config_files = [
        "tsconfig.json",
        "vite.config.ts",
        "next.config.js",
        "next.config.ts",
        "tailwind.config.js",
        "tailwind.config.ts",
        ".eslintrc.json",
        ".eslintrc.js",
        "ruff.toml",
        "pyproject.toml",
    ]

    # DevOps files
    devops_files = [
        "Dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        ".github/workflows/ci.yml",
        ".github/workflows/main.yml",
        ".github/workflows/test.yml",
        ".gitlab-ci.yml",
    ]

    all_key_files = project_files + config_files + devops_files

    for kf in all_key_files:
        kf_path = repo_path / kf
        if kf_path.exists():
            try:
                content = kf_path.read_text(encoding="utf-8", errors="ignore")[:2000]
                key_files_content.append(f"## {kf}\n```\n{content}\n```")
            except Exception:
                pass

    # Sample a few source files for architecture hints
    sample_files = []
    for pattern in ["**/main.py", "**/app.py", "**/cli.py", "**/index.ts", "**/App.tsx"]:
        for f in list(repo_path.glob(pattern))[:2]:
            if not should_ignore(f):
                try:
                    content = f.read_text(encoding="utf-8", errors="ignore")[:3000]
                    rel = f.relative_to(repo_path)
                    sample_files.append(f"## {rel}\n```\n{content}\n```")
                except Exception:
                    pass

    prompt = f"""Analyze this repository and create a comprehensive technical description.

## Repository Statistics
- **Total code files**: {total_files}
- **Total tokens**: {total_tokens:,}

{structure}

## Key Configuration Files
{chr(10).join(key_files_content[:10])}

## Sample Source Files
{chr(10).join(sample_files[:5])}

Following the output format in your instructions, create a detailed analysis covering:

1. **Overview**: What this project does (2-3 sentences)

2. **Tech Stack Table**: Language, Backend Framework, Frontend Framework, Database/ORM, Validation, AI/ML libraries

3. **Architecture**:
   - Pattern (Monolith, Microservices, Modular Monolith, etc.)
   - Entry Points (CLI, REST API, GraphQL, Web App, etc.)
   - Key Design Patterns (Repository, DI, CQRS, etc.)

4. **Project Structure**: Key directories and their purpose (as tree diagram)

5. **DevOps**:
   - CI/CD setup
   - Containerization
   - Code quality tools (linter, formatter, type checker)

6. **Key Dependencies**: Most important production dependencies with brief purpose

7. **Notes**: Any important observations about code quality, patterns, or potential issues

Be specific about versions where visible. Use the exact format from your instructions.
"""

    result = client.generate(prompt, system_prompt)

    # Save result with metadata
    output_content = f"""# Repository Analysis

*Generated by TurboWrap - Gemini Flash*
*Date: {time.strftime('%Y-%m-%d %H:%M:%S')}*

## Quick Stats
| Metric | Value |
|--------|-------|
| Code Files | {total_files} |
| Total Tokens | {total_tokens:,} |

---

{result}
"""

    output_file = output_dir / "REPO_DESCRIPTION.md"
    output_file.write_text(output_content)
    print(f"   ✅ Saved: {output_file}")
    print(f"   📊 Analyzed {total_files} files ({total_tokens:,} tokens)")

    return output_file

# ============================================================================
# Agent: Code Reviewer (BE/FE) - Claude Opus
# ============================================================================

def run_reviewer_agent(
    client: ClaudeClient,
    repo_path: Path,
    files: list[FileInfo],
    agent_type: Literal["be", "fe"],
    batch_id: int
) -> ReviewResult:
    """Run reviewer agent on a batch of files using Claude Opus."""
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
    client: ClaudeClient,
    repo_path: Path,
    be_files: list[FileInfo],
    fe_files: list[FileInfo],
    max_workers: int = 3,
    max_tokens_per_batch: int = 50000
) -> list[ReviewResult]:
    """Run reviewer agents in parallel, 1 triplet of agents per ~50k tokens."""
    results: list[ReviewResult] = []

    def create_token_batches(files: list[FileInfo], max_tokens: int = 50000):
        """Create batches based on token count (~50k tokens per batch)."""
        # First, load content and count tokens for each file
        files_with_tokens = []
        for f in files:
            full_path = repo_path / f.path
            try:
                content = full_path.read_text(encoding="utf-8", errors="ignore")
                tokens = count_tokens(content)
                f.content = content
                files_with_tokens.append((f, tokens))
            except Exception:
                files_with_tokens.append((f, 0))

        # Create batches based on token count
        batches = []
        current_batch = []
        current_tokens = 0

        for file_info, tokens in files_with_tokens:
            # If single file exceeds max, put it in its own batch
            if tokens > max_tokens:
                if current_batch:
                    batches.append((current_batch, current_tokens))
                batches.append(([file_info], tokens))
                current_batch = []
                current_tokens = 0
            elif current_tokens + tokens > max_tokens:
                # Start new batch
                if current_batch:
                    batches.append((current_batch, current_tokens))
                current_batch = [file_info]
                current_tokens = tokens
            else:
                current_batch.append(file_info)
                current_tokens += tokens

        # Don't forget the last batch
        if current_batch:
            batches.append((current_batch, current_tokens))

        return batches

    be_batches = create_token_batches(be_files, max_tokens_per_batch)
    fe_batches = create_token_batches(fe_files, max_tokens_per_batch)

    # Calculate total tokens
    total_be_tokens = sum(tokens for _, tokens in be_batches)
    total_fe_tokens = sum(tokens for _, tokens in fe_batches)

    total_batches = len(be_batches) + len(fe_batches)
    print(f"\n🧠 [Claude Opus] Reviewing code (~50k tokens per batch)")
    print(f"   📊 BE: {len(be_batches)} batches ({total_be_tokens:,} tokens)")
    print(f"   📊 FE: {len(fe_batches)} batches ({total_fe_tokens:,} tokens)")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {}

        # Submit BE review tasks
        for i, (batch_files, batch_tokens) in enumerate(be_batches):
            future = executor.submit(run_reviewer_agent, client, repo_path, batch_files, "be", i)
            futures[future] = (f"BE batch {i+1}/{len(be_batches)}", len(batch_files), batch_tokens)

        # Submit FE review tasks
        for i, (batch_files, batch_tokens) in enumerate(fe_batches):
            future = executor.submit(run_reviewer_agent, client, repo_path, batch_files, "fe", i)
            futures[future] = (f"FE batch {i+1}/{len(fe_batches)}", len(batch_files), batch_tokens)

        # Collect results
        completed = 0
        for future in as_completed(futures):
            completed += 1
            batch_name, file_count, token_count = futures[future]
            try:
                result = future.result()
                results.append(result)
                print(f"   ✅ [{completed}/{total_batches}] {batch_name} - {file_count} files, {token_count:,} tokens")
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
        f"*Generated by TurboWrap: {time.strftime('%Y-%m-%d %H:%M:%S')}*",
        "",
        "**Agents Used:**",
        "- 🔍 Gemini Flash - Repository Analysis",
        "- 🧠 Claude Opus - Code Review",
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
        "*Generated with ❤️ by TurboWrap*",
    ])

    output_file = output_dir / "REVIEW_TODO.md"
    output_file.write_text("\n".join(lines))
    print(f"   ✅ Saved: {output_file}")

    return output_file

# ============================================================================
# Tree Generator (STRUCTURE.md) - Gemini Flash
# ============================================================================

def discover_directories(
    repo_path: Path,
    max_depth: int = MAX_TREE_DEPTH
) -> list[DirectoryStructure]:
    """
    Scopre le cartelle da processare rispettando la profondità massima.
    Ritorna lista flat di DirectoryStructure ordinata per profondità (root prima).
    """
    directories: list[DirectoryStructure] = []

    def scan_dir(current_path: Path, depth: int) -> DirectoryStructure | None:
        if depth > max_depth:
            return None
        if should_ignore(current_path):
            return None

        # Path relativo per display
        try:
            rel_path = current_path.relative_to(repo_path)
        except ValueError:
            rel_path = Path(".")

        dir_struct = DirectoryStructure(
            path=rel_path if str(rel_path) != "." else Path("."),
            depth=depth
        )

        # Trova file processabili nella cartella corrente
        try:
            for item in current_path.iterdir():
                if item.is_file() and not should_ignore(item):
                    suffix = item.suffix.lower()
                    rel_file = item.relative_to(repo_path)
                    if suffix in BE_EXTENSIONS:
                        dir_struct.files.append(
                            FileStructure(path=rel_file, file_type="be")
                        )
                    elif suffix in FE_EXTENSIONS:
                        dir_struct.files.append(
                            FileStructure(path=rel_file, file_type="fe")
                        )
        except PermissionError:
            pass

        # Ricorsione sottocartelle (solo se non al limite)
        if depth < max_depth:
            try:
                for item in sorted(current_path.iterdir()):
                    if item.is_dir() and not should_ignore(item):
                        sub_struct = scan_dir(item, depth + 1)
                        if sub_struct and (sub_struct.files or sub_struct.subdirectories):
                            dir_struct.subdirectories.append(sub_struct)
            except PermissionError:
                pass

        return dir_struct if (dir_struct.files or dir_struct.subdirectories) else None

    root = scan_dir(repo_path, 1)
    if root:
        # Flatten per processamento (BFS order)
        queue = [root]
        while queue:
            current = queue.pop(0)
            directories.append(current)
            queue.extend(current.subdirectories)

    return directories


def parse_elements_response(
    response: str,
    file_type: Literal["be", "fe"]
) -> list[FileElement]:
    """Parsa la risposta di Gemini in lista di FileElement."""
    elements = []
    valid_types = FE_ELEMENTS if file_type == "fe" else BE_ELEMENTS

    if "EMPTY" in response.upper():
        return elements

    for line in response.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Pattern: "Type: Name - Description"
        if ":" in line and "-" in line:
            try:
                type_part, rest = line.split(":", 1)
                element_type = type_part.strip()

                # Normalizza tipo
                for valid in valid_types:
                    if valid.lower() == element_type.lower():
                        element_type = valid
                        break
                else:
                    continue  # Tipo non valido

                if "-" in rest:
                    name_part, desc_part = rest.split("-", 1)
                    name = name_part.strip().strip("`").strip("*")
                    description = desc_part.strip()[:80]

                    if name:  # Solo se ha un nome valido
                        elements.append(FileElement(
                            type=element_type,
                            name=name,
                            description=description
                        ))
            except ValueError:
                continue

    return elements[:10]  # Max 10 elementi per file


def extract_file_elements(
    client: GeminiClient,
    repo_path: Path,
    file_struct: FileStructure
) -> FileStructure:
    """Usa Gemini Flash per estrarre elementi semantici da un file."""
    full_path = repo_path / file_struct.path
    try:
        content = full_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return file_struct

    # Calculate tokens and lines
    file_struct.tokens = count_tokens(content)
    file_struct.lines = content.count("\n") + 1

    # Scegli elementi in base al tipo
    if file_struct.file_type == "fe":
        elements_to_find = ", ".join(FE_ELEMENTS)
        context = "React/TypeScript frontend"
    else:
        elements_to_find = ", ".join(BE_ELEMENTS)
        context = "Python backend"

    prompt = f"""Analyze this {context} file and extract key elements.

File: {file_struct.path.name}
```
{content[:6000]}
```

Extract ONLY these types: {elements_to_find}

For EACH element found, provide:
- Type (exactly one of: {elements_to_find})
- Name (the identifier/function/class name)
- Description (max 10 words, in Italian)

Format your response as a simple list:
TYPE: Name - Description

Example:
Component: Button - Bottone riutilizzabile con varianti
Hook: useAuth - Gestisce autenticazione utente
Function: calculate_total - Calcola totale ordine

If no elements found, respond with: EMPTY

Be concise. Only list the most important elements (max 10).
"""

    try:
        result = client.generate(prompt)
        file_struct.elements = parse_elements_response(result, file_struct.file_type)
    except Exception as e:
        print(f"      ⚠️  Could not analyze {file_struct.path}: {e}")

    return file_struct


def generate_structure_md(
    dir_struct: DirectoryStructure,
    repo_path: Path
) -> Path:
    """Genera STRUCTURE.md per una singola cartella."""
    # Nome cartella per titolo
    dir_name = dir_struct.path.name if str(dir_struct.path) != "." else repo_path.name

    lines = [
        f"# {dir_name}",
        "",
    ]

    # Sezione Files
    if dir_struct.files:
        # Calculate totals for directory
        total_tokens = sum(f.tokens for f in dir_struct.files)
        total_lines = sum(f.lines for f in dir_struct.files)

        lines.extend([
            "## Files",
            "",
            f"**Directory Stats:** {len(dir_struct.files)} files, {total_lines:,} lines, {total_tokens:,} tokens",
            "",
            "| File | Lines | Tokens |",
            "|------|------:|-------:|",
        ])

        for file_struct in sorted(dir_struct.files, key=lambda f: f.path.name):
            lines.append(f"| `{file_struct.path.name}` | {file_struct.lines:,} | {file_struct.tokens:,} |")

        lines.append("")

        for file_struct in sorted(dir_struct.files, key=lambda f: f.path.name):
            lines.append(f"### {file_struct.path.name}")
            lines.append(f"*{file_struct.lines:,} lines, {file_struct.tokens:,} tokens*")
            lines.append("")

            if file_struct.elements:
                for elem in file_struct.elements:
                    lines.append(
                        f"- **{elem.type}**: `{elem.name}` - {elem.description}"
                    )
            else:
                lines.append("- *No exported elements detected*")

            lines.append("")

    # Sezione Subdirectories (solo se depth < MAX)
    if dir_struct.subdirectories and dir_struct.depth < MAX_TREE_DEPTH:
        lines.extend(["## Subdirectories", ""])

        for sub in sorted(dir_struct.subdirectories, key=lambda s: s.path.name):
            sub_name = sub.path.name
            # Calcola descrizione breve
            file_count = len(sub.files)
            sub_count = len(sub.subdirectories)
            desc_parts = []
            if file_count:
                desc_parts.append(f"{file_count} file{'s' if file_count > 1 else ''}")
            if sub_count:
                desc_parts.append(f"{sub_count} subfolder{'s' if sub_count > 1 else ''}")
            desc = ", ".join(desc_parts) if desc_parts else "Empty"

            lines.append(f"- [{sub_name}/]({sub_name}/{STRUCTURE_FILENAME}) - {desc}")

        lines.append("")

    # Footer
    lines.extend([
        "---",
        f"*Generated by TurboWrap - {time.strftime('%Y-%m-%d %H:%M')}*",
    ])

    # Determina path output (in-place nel repository)
    if str(dir_struct.path) == ".":
        output_path = repo_path / STRUCTURE_FILENAME
    else:
        output_path = repo_path / dir_struct.path / STRUCTURE_FILENAME

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")

    return output_path


def run_tree_generator(
    client: GeminiClient,
    repo_path: Path,
    max_depth: int = MAX_TREE_DEPTH,
    max_workers: int = 5
) -> list[Path]:
    """
    Orchestratore principale per la generazione dell'albero STRUCTURE.md.
    Ritorna lista dei file STRUCTURE.md generati.
    """
    print("\n🌳 [Gemini Flash] Generating documentation tree...")

    # 1. Scoperta cartelle
    print("   📁 Discovering directories...")
    directories = discover_directories(repo_path, max_depth)

    if not directories:
        print("   ⚠️  No directories with processable files found.")
        return []

    total_files = sum(len(d.files) for d in directories)
    print(f"   Found {len(directories)} directories with {total_files} files")

    # 2. Raccolta tutti i file da processare
    all_files: list[FileStructure] = []
    for dir_struct in directories:
        all_files.extend(dir_struct.files)

    # 3. Estrazione elementi in parallelo
    print(f"\n   🔍 Extracting elements from {len(all_files)} files...")

    processed_files: dict[Path, FileStructure] = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                extract_file_elements, client, repo_path, file_struct
            ): file_struct
            for file_struct in all_files
        }

        completed = 0
        for future in as_completed(futures):
            completed += 1
            original = futures[future]
            try:
                result = future.result()
                processed_files[result.path] = result
                if completed % 10 == 0 or completed == len(all_files):
                    print(f"      Processed {completed}/{len(all_files)} files")
            except Exception as e:
                print(f"      ❌ Error processing {original.path}: {e}")
                processed_files[original.path] = original

    # 4. Aggiorna strutture directory con risultati
    for dir_struct in directories:
        dir_struct.files = [
            processed_files.get(f.path, f) for f in dir_struct.files
        ]

    # 5. Genera STRUCTURE.md per ogni cartella
    print(f"\n   📝 Generating {len(directories)} STRUCTURE.md files...")

    generated_files: list[Path] = []

    for dir_struct in directories:
        try:
            output_path = generate_structure_md(dir_struct, repo_path)
            generated_files.append(output_path)
            rel_path = output_path.relative_to(repo_path)
            print(f"      ✅ {rel_path}")
        except Exception as e:
            print(f"      ❌ Error generating for {dir_struct.path}: {e}")

    return generated_files

# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="🚀 TurboWrap - Analyze repository with AI agents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Agents:
    - Gemini Flash: Fast repository structure analysis
    - Claude Opus: Deep code review (1 agent per 3 files)

Environment Variables:
    GOOGLE_API_KEY or GEMINI_API_KEY: For Gemini Flash
    ANTHROPIC_API_KEY: For Claude Opus

Examples:
    python turbowrap.py ~/code/my-project
    python turbowrap.py ~/code/my-project --output ./reviews
    python turbowrap.py ~/code/my-project --max-workers 5
    python turbowrap.py ~/code/my-project --skip-flash  # Skip repo analysis
    python turbowrap.py ~/code/my-project --tree  # Generate STRUCTURE.md tree
    python turbowrap.py ~/code/my-project --tree --tree-depth 2  # Limit to 2 levels
        """
    )
    parser.add_argument("repo_path", type=Path, help="Path to repository to analyze")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output directory (default: <repo>/.reviews)")
    parser.add_argument("--max-workers", "-w", type=int, default=3, help="Max parallel review agents (default: 3)")
    parser.add_argument("--skip-flash", action="store_true", help="Skip Flash analyzer (repo description)")
    parser.add_argument("--skip-review", action="store_true", help="Skip code review")
    parser.add_argument("--tree", action="store_true", help="Generate STRUCTURE.md documentation tree (max 3 levels)")
    parser.add_argument("--tree-depth", type=int, default=3, help="Max depth for tree generation (default: 3)")

    args = parser.parse_args()

    repo_path = args.repo_path.resolve()
    if not repo_path.exists():
        print(f"❌ Repository path not found: {repo_path}")
        sys.exit(1)

    output_dir = args.output or (repo_path / ".reviews")
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("🚀 TURBOWRAP - Code Repository Analyzer")
    print("=" * 60)
    print(f"   📁 Repository: {repo_path}")
    print(f"   📂 Output: {output_dir}")
    print("=" * 60)
    print("\n🤖 Agents (2-Level Architecture):")
    print("   Level 1: Gemini Flash → File Analysis (STRUCTURE.md)")
    print("   Level 2: Gemini Pro  → Repo Synthesis (REPO_DESCRIPTION.md)")
    print("   Review:  Claude Opus → Code Review")
    print("=" * 60)

    # Initialize clients
    gemini_client = None
    gemini_pro_client = None
    claude_client = None

    if not args.skip_flash or args.tree:
        try:
            gemini_client = GeminiClient()
            print("   ✅ Gemini Flash client initialized")
        except ValueError as e:
            print(f"   ⚠️  Gemini Flash: {e}")
        except ImportError:
            print("   ⚠️  Gemini: pip install google-genai")

        try:
            gemini_pro_client = GeminiProClient()
            print("   ✅ Gemini Pro client initialized")
        except ValueError as e:
            print(f"   ⚠️  Gemini Pro: {e}")
        except ImportError:
            pass  # Same import as Flash

    if not args.skip_review:
        try:
            claude_client = ClaudeClient()
            print("   ✅ Claude client initialized")
        except ValueError as e:
            print(f"   ⚠️  Claude: {e}")
        except ImportError:
            print("   ⚠️  Claude: pip install anthropic")

    # Discover files
    be_files, fe_files = discover_files(repo_path)
    print(f"\n📂 Discovered Files:")
    print(f"   🐍 Python (BE): {len(be_files)} files")
    print(f"   ⚛️  React/TS (FE): {len(fe_files)} files")

    # =========================================================================
    # LEVEL 1: Tree Generator (Gemini Flash) - generates STRUCTURE.md files
    # =========================================================================
    tree_generated = []
    if args.tree:
        if not gemini_client:
            print("\n⚠️  Skipping Level 1: Gemini Flash client not available")
        else:
            tree_generated = run_tree_generator(
                gemini_client,
                repo_path,
                args.tree_depth,
                args.max_workers
            )

    # =========================================================================
    # LEVEL 2: Repo Analyzer (Gemini Pro) - synthesizes STRUCTURE.md files
    # =========================================================================
    if not args.skip_flash:
        if tree_generated and gemini_pro_client:
            # Use Level 2 synthesis with Gemini Pro
            run_repo_analyzer(gemini_pro_client, repo_path, output_dir, tree_generated)
        elif gemini_client:
            # Fallback to legacy single-level analysis
            print("\n⚠️  No STRUCTURE.md files - using legacy single-level analysis")
            run_flash_analyzer(gemini_client, repo_path, output_dir)

    # =========================================================================
    # REVIEW: Code Reviewers (Claude Opus)
    # =========================================================================
    if not args.skip_review and claude_client and (be_files or fe_files):
        results = run_all_reviewers(claude_client, repo_path, be_files, fe_files, args.max_workers)
        generate_todo_list(results, output_dir)

    print("\n" + "=" * 60)
    print(f"✨ Done! Check {output_dir} for results:")
    if tree_generated:
        print(f"   🌳 Level 1: {len(tree_generated)} STRUCTURE.md files (Gemini Flash)")
        print(f"   📄 Level 2: REPO_DESCRIPTION.md (Gemini Pro synthesis)")
    else:
        print(f"   📄 REPO_DESCRIPTION.md - Repository overview")
    print(f"   📋 REVIEW_TODO.md - Issues and action items (Claude Opus)")
    print("=" * 60)

if __name__ == "__main__":
    main()
