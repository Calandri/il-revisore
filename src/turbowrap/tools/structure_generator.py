"""
Structure generator for STRUCTURE.md files.

Generates documentation files for each directory containing code,
with file statistics, extracted elements, and repo type detection.
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from turbowrap.llm.base import BaseAgent

from turbowrap.utils.file_utils import calculate_tokens

logger = logging.getLogger(__name__)

try:
    import tomllib
except ImportError:
    import tomli as tomllib


class RepoType(str, Enum):
    """Repository type classification."""

    BACKEND = "backend"
    FRONTEND = "frontend"
    FULLSTACK = "fullstack"
    UNKNOWN = "unknown"


# File extensions by type
BE_EXTENSIONS = {".py"}
FE_EXTENSIONS = {".tsx", ".ts", ".jsx", ".js"}

# Directories to ignore
IGNORE_DIRS = {
    "node_modules",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".next",
    "coverage",
    ".pytest_cache",
    "eggs",
    "*.egg-info",
    ".tox",
    ".mypy_cache",
    ".reviews",
    ".ruff_cache",
    "htmlcov",
    ".eggs",
}

# Files to ignore
IGNORE_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock"}

# Tree generation config
MAX_TREE_DEPTH = 3
STRUCTURE_FILENAME = "STRUCTURE.md"
FE_ELEMENTS = ["Component", "Hook", "Utils", "Context", "Type"]
BE_ELEMENTS = ["Function", "Class", "Decorator", "Constant"]


@dataclass
class Dependency:
    """A project dependency."""

    name: str
    version: str
    purpose: str = ""  # Filled by Gemini


@dataclass
class RepoMetadata:
    """Metadata extracted from project files."""

    # Tech stack
    language: str = ""
    framework: str = ""
    database: str = ""

    # Entry points
    entry_points: list[str] = field(default_factory=list)

    # Dependencies
    dependencies: list[Dependency] = field(default_factory=list)

    # Environment
    env_vars: list[str] = field(default_factory=list)

    # Architecture (filled by Gemini)
    architecture_pattern: str = ""
    architecture_description: str = ""


@dataclass
class FileElement:
    """Element extracted from a file (Component, Hook, Function, etc.)."""

    type: str  # "Component", "Hook", "Utils", "Function", "Class"
    name: str  # Element identifier
    description: str  # Max 10 words


@dataclass
class FileStructure:
    """Structure of an analyzed file."""

    path: Path
    file_type: Literal["be", "fe"]
    elements: list[FileElement] = field(default_factory=list)
    tokens: int = 0
    lines: int = 0


@dataclass
class DirectoryStructure:
    """Structure of a directory for STRUCTURE.md generation."""

    path: Path
    depth: int
    files: list[FileStructure] = field(default_factory=list)
    subdirectories: list["DirectoryStructure"] = field(default_factory=list)
    purpose: str = ""  # Brief description of directory purpose (from Gemini)


def count_tokens(content: str) -> int:
    """Count tokens using tiktoken cl100k_base encoding."""
    return calculate_tokens(content)["tokens"]


def should_ignore(path: Path) -> bool:
    """Check if path should be ignored."""
    for part in path.parts:
        if part in IGNORE_DIRS or part.startswith("."):
            return True
    return path.name in IGNORE_FILES


class StructureGenerator:
    """
    Generates STRUCTURE.md documentation files.

    Uses Gemini Flash to extract semantic elements from code files
    and generates a documentation tree.
    """

    def __init__(
        self,
        repo_path: Path,
        workspace_path: str | None = None,
        max_depth: int = MAX_TREE_DEPTH,
        max_workers: int = 5,
        gemini_client: "BaseAgent | None" = None,
    ):
        """
        Initialize structure generator.

        Args:
            repo_path: Path to repository root
            workspace_path: Optional workspace subfolder for monorepo (e.g., "apps/helpdesk")
            max_depth: Maximum directory depth to process
            max_workers: Number of parallel workers for file analysis
            gemini_client: Optional Gemini client for element extraction
        """
        self.repo_path = Path(repo_path).resolve()
        self.workspace_path = workspace_path
        # For monorepo: scan only the workspace, not the entire repo
        if workspace_path:
            self.scan_root = self.repo_path / workspace_path
        else:
            self.scan_root = self.repo_path
        self.max_depth = max_depth
        self.max_workers = max_workers
        self.gemini_client = gemini_client

        # Stats
        self.be_file_count = 0
        self.fe_file_count = 0
        self.total_tokens = 0
        self.total_lines = 0

        # Metadata
        self.metadata = RepoMetadata()

    def detect_repo_type(self) -> RepoType:
        """
        Detect repository type based on file distribution.

        Uses scan_root for monorepo workspace support.

        Returns:
            RepoType enum value
        """
        be_count = 0
        fe_count = 0

        # Use scan_root to only scan the workspace (not entire monorepo)
        for file_path in self.scan_root.rglob("*"):
            if not file_path.is_file():
                continue
            # Use relative path to avoid issues with parent dirs like .turbowrap
            try:
                rel_path = file_path.relative_to(self.scan_root)
            except ValueError:
                continue
            if should_ignore(rel_path):
                continue

            suffix = file_path.suffix.lower()
            if suffix in BE_EXTENSIONS:
                be_count += 1
            elif suffix in FE_EXTENSIONS:
                fe_count += 1

        self.be_file_count = be_count
        self.fe_file_count = fe_count

        if be_count > 0 and fe_count > 0:
            return RepoType.FULLSTACK
        if be_count > 0:
            return RepoType.BACKEND
        if fe_count > 0:
            return RepoType.FRONTEND
        return RepoType.UNKNOWN

    def extract_metadata(self) -> RepoMetadata:
        """
        Extract metadata from project configuration files.

        Parses pyproject.toml, package.json, .env.example, etc.
        """
        self._parse_pyproject()
        self._parse_package_json()
        self._find_entry_points()
        self._find_env_vars()

        # Use Gemini to analyze architecture if available
        if self.gemini_client:
            self._analyze_architecture()

        return self.metadata

    def _parse_pyproject(self) -> None:
        """Parse pyproject.toml for Python projects.

        Uses scan_root for monorepo workspace support.
        """
        pyproject_path = self.scan_root / "pyproject.toml"
        if not pyproject_path.exists():
            return

        try:
            with open(pyproject_path, "rb") as f:
                data = tomllib.load(f)

            # Language
            self.metadata.language = "Python"

            # Project info
            project = data.get("project", {})
            data.get("tool", {})

            # Python version
            requires_python = project.get("requires-python", "")
            if requires_python:
                self.metadata.language = f"Python {requires_python}"

            # Dependencies
            deps = project.get("dependencies", [])
            for dep in deps[:15]:  # Limit to 15
                # Parse "package>=1.0" format
                match = re.match(r"([a-zA-Z0-9_-]+)([<>=!~]+.*)?", dep)
                if match:
                    name = match.group(1)
                    version = match.group(2) or ""
                    self.metadata.dependencies.append(
                        Dependency(name=name, version=version.strip())
                    )

            # Detect framework from dependencies
            dep_names = [d.name.lower() for d in self.metadata.dependencies]
            if "fastapi" in dep_names:
                self.metadata.framework = "FastAPI"
            elif "django" in dep_names:
                self.metadata.framework = "Django"
            elif "flask" in dep_names:
                self.metadata.framework = "Flask"

            # Detect database
            if "sqlalchemy" in dep_names:
                self.metadata.database = "SQLAlchemy"
            if "asyncpg" in dep_names or "psycopg2" in dep_names:
                self.metadata.database += " + PostgreSQL"

        except Exception:
            pass

    def _parse_package_json(self) -> None:
        """Parse package.json for JS/TS projects.

        Uses scan_root for monorepo workspace support.
        """
        package_path = self.scan_root / "package.json"
        if not package_path.exists():
            return

        try:
            with open(package_path) as f:
                data = json.load(f)

            # Language
            if not self.metadata.language:
                self.metadata.language = "TypeScript/JavaScript"

            # Dependencies
            deps = data.get("dependencies", {})
            for name, version in list(deps.items())[:15]:
                self.metadata.dependencies.append(Dependency(name=name, version=version))

            # Detect framework
            if "react" in deps:
                self.metadata.framework = "React"
            if "next" in deps:
                self.metadata.framework = "Next.js"
            if "vue" in deps:
                self.metadata.framework = "Vue"

        except Exception:
            pass

    def _find_entry_points(self) -> None:
        """Find main entry point files.

        Uses scan_root for monorepo workspace support.
        """
        entry_patterns = [
            "main.py",
            "app.py",
            "cli.py",
            "__main__.py",
            "index.ts",
            "index.tsx",
            "main.ts",
            "App.tsx",
            "server.py",
            "run.py",
            "manage.py",
        ]

        for pattern in entry_patterns:
            # Only search within scan_root (workspace for monorepo)
            for match in self.scan_root.rglob(pattern):
                if not should_ignore(match):
                    # Relative path from scan_root, not repo_path
                    rel_path = str(match.relative_to(self.scan_root))
                    if rel_path not in self.metadata.entry_points:
                        self.metadata.entry_points.append(rel_path)

        # Limit to 10
        self.metadata.entry_points = self.metadata.entry_points[:10]

    def _find_env_vars(self) -> None:
        """Find environment variables from .env.example or .env.template.

        Uses scan_root for monorepo workspace support.
        """
        env_files = [".env.example", ".env.template", ".env.sample"]

        for env_file in env_files:
            env_path = self.scan_root / env_file
            if env_path.exists():
                try:
                    content = env_path.read_text()
                    for line in content.split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            var_name = line.split("=")[0].strip()
                            if var_name and var_name not in self.metadata.env_vars:
                                self.metadata.env_vars.append(var_name)
                except Exception:
                    pass
                break  # Only read first found

        # Limit to 20
        self.metadata.env_vars = self.metadata.env_vars[:20]

    def _analyze_architecture(self) -> None:
        """Use Gemini to analyze architecture pattern.

        Uses scan_root for monorepo workspace support.
        """
        # Build context from directory structure (within scan_root only)
        dirs = []
        for item in self.scan_root.iterdir():
            if item.is_dir() and not should_ignore(item):
                dirs.append(item.name)

        # Use scan_root name for workspace, otherwise repo_path name
        project_name = self.scan_root.name if self.workspace_path else self.repo_path.name

        prompt = f"""Analyze this project structure and describe its architecture.

Project: {project_name}
Language: {self.metadata.language or "Unknown"}
Framework: {self.metadata.framework or "Unknown"}
Directories: {", ".join(sorted(dirs))}
Dependencies: {", ".join(d.name for d in self.metadata.dependencies[:10])}

Provide:
1. PATTERN: One of: Monolith, Modular Monolith, Microservices, CLI Tool, Library, API Server
2. DESCRIPTION: 2-3 sentences describing the architecture and layers (in English)

Format:
PATTERN: <pattern>
DESCRIPTION: <description>
"""

        # Type narrowing for mypy - caller checks gemini_client is not None
        assert self.gemini_client is not None

        try:
            result = self.gemini_client.generate(prompt)

            for line in result.split("\n"):
                if line.startswith("PATTERN:"):
                    self.metadata.architecture_pattern = line.split(":", 1)[1].strip()
                elif line.startswith("DESCRIPTION:"):
                    self.metadata.architecture_description = line.split(":", 1)[1].strip()
        except Exception:
            pass

    def _analyze_directory_purposes(self, directories: list[DirectoryStructure]) -> None:
        """Use Gemini to analyze the purpose of each subdirectory."""
        if not self.gemini_client:
            return

        # Collect all subdirectories that need purpose analysis
        subdirs_to_analyze: list[DirectoryStructure] = []
        for dir_struct in directories:
            for sub in dir_struct.subdirectories:
                if not sub.purpose:
                    subdirs_to_analyze.append(sub)

        if not subdirs_to_analyze:
            return

        # Build batch prompt for all directories
        dir_list = []
        for sub in subdirs_to_analyze:
            files = [f.path.name for f in sub.files[:5]]
            dir_list.append(f"- {sub.path.name}/: files={', '.join(files) or 'none'}")

        prompt = f"""Analyze these directories and provide a brief purpose for each.

Directories:
{chr(10).join(dir_list)}

For EACH directory, provide a 3-5 word purpose description in English.
Format: directory_name: purpose

Example:
api: REST API endpoints and routes
utils: Shared helper functions
models: Data models and schemas
"""

        # Type narrowing for mypy - caller checks gemini_client is not None
        assert self.gemini_client is not None

        try:
            result = self.gemini_client.generate(prompt)

            # Parse response
            purposes: dict[str, str] = {}
            for line in result.strip().split("\n"):
                if ":" in line:
                    parts = line.split(":", 1)
                    dir_name = parts[0].strip().rstrip("/")
                    purpose = parts[1].strip()
                    if dir_name and purpose:
                        purposes[dir_name] = purpose[:50]  # Limit length

            # Assign purposes to directories
            for sub in subdirs_to_analyze:
                sub.purpose = purposes.get(sub.path.name, "")

        except Exception:
            pass

    def discover_directories(self) -> list[DirectoryStructure]:
        """
        Discover directories to process respecting max depth.

        Returns:
            List of DirectoryStructure ordered by depth (root first)
        """
        directories: list[DirectoryStructure] = []

        def scan_dir(current_path: Path, depth: int) -> DirectoryStructure | None:
            # Note: We continue scanning beyond max_depth to find nested files
            # (they'll be inlined in parent STRUCTURE.md, not get their own file)

            # Relative path for display (and for should_ignore check)
            try:
                rel_path = current_path.relative_to(self.repo_path)
            except ValueError:
                rel_path = Path(".")

            # Check ignore using relative path to avoid issues with parent dirs
            if str(rel_path) != "." and should_ignore(rel_path):
                return None

            dir_struct = DirectoryStructure(
                path=rel_path if str(rel_path) != "." else Path("."), depth=depth
            )

            # Find processable files in current directory
            try:
                for item in current_path.iterdir():
                    if not item.is_file():
                        continue
                    rel_file = item.relative_to(self.repo_path)
                    if should_ignore(rel_file):
                        continue
                    suffix = item.suffix.lower()
                    if suffix in BE_EXTENSIONS:
                        dir_struct.files.append(FileStructure(path=rel_file, file_type="be"))
                    elif suffix in FE_EXTENSIONS:
                        dir_struct.files.append(FileStructure(path=rel_file, file_type="fe"))
            except PermissionError:
                pass

            # Always recurse into subdirectories to find all files
            # (even beyond max_depth, for inlining in parent STRUCTURE.md)
            try:
                for item in sorted(current_path.iterdir()):
                    if not item.is_dir():
                        continue
                    rel_item = item.relative_to(self.repo_path)
                    if should_ignore(rel_item):
                        continue
                    sub_struct = scan_dir(item, depth + 1)
                    if sub_struct and (sub_struct.files or sub_struct.subdirectories):
                        dir_struct.subdirectories.append(sub_struct)
            except PermissionError:
                pass

            return dir_struct if (dir_struct.files or dir_struct.subdirectories) else None

        # Use scan_root for monorepo workspace support
        root = scan_dir(self.scan_root, 1)
        if root:
            # Flatten for processing (BFS order)
            queue = [root]
            while queue:
                current = queue.pop(0)
                directories.append(current)
                queue.extend(current.subdirectories)

        return directories

    def _extract_file_elements(self, file_struct: FileStructure) -> FileStructure:
        """
        Extract semantic elements from a file.

        Uses Gemini Flash if available, otherwise just calculates stats.
        """
        full_path = self.repo_path / file_struct.path
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return file_struct

        # Calculate tokens and lines
        file_struct.tokens = count_tokens(content)
        file_struct.lines = content.count("\n") + 1

        # Update totals
        self.total_tokens += file_struct.tokens
        self.total_lines += file_struct.lines

        # Use Gemini for element extraction if available
        if self.gemini_client:
            file_struct.elements = self._extract_with_gemini(file_struct, content)

        return file_struct

    def _extract_with_gemini(self, file_struct: FileStructure, content: str) -> list[FileElement]:
        """Extract elements using Gemini Flash."""
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
- Description (max 5 words, in English)

Format your response as a simple list:
TYPE: Name - Description

Example:
Component: Button - Reusable button with variants
Hook: useAuth - Manages user authentication
Function: calculate_total - Calculates order total

If no elements found, respond with: EMPTY

Be concise. Only list the most important elements (max 10).
"""

        # Type narrowing for mypy - caller checks gemini_client is not None
        assert self.gemini_client is not None

        try:
            result = self.gemini_client.generate(prompt)
            return self._parse_elements_response(result, file_struct.file_type)
        except Exception:
            return []

    def _parse_elements_response(
        self, response: str, file_type: Literal["be", "fe"]
    ) -> list[FileElement]:
        """Parse Gemini response into list of FileElement."""
        elements: list[FileElement] = []
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

                    # Normalize type
                    for valid in valid_types:
                        if valid.lower() == element_type.lower():
                            element_type = valid
                            break
                    else:
                        continue  # Invalid type

                    if "-" in rest:
                        name_part, desc_part = rest.split("-", 1)
                        name = name_part.strip().strip("`").strip("*")
                        description = desc_part.strip()[:30]  # Reduced to 30 chars to save tokens

                        if name:  # Only if has valid name
                            elements.append(
                                FileElement(type=element_type, name=name, description=description)
                            )
                except ValueError:
                    continue

        return elements[:10]  # Max 10 elements per file

    def _generate_structure_md(
        self, dir_struct: DirectoryStructure, repo_type: RepoType, is_root: bool = False
    ) -> Path:
        """Generate STRUCTURE.md for a single directory."""
        # Directory name for title
        dir_name = dir_struct.path.name if str(dir_struct.path) != "." else self.repo_path.name

        lines = [
            f"# {dir_name}",
            "",
        ]

        # Add repo type metadata only for root STRUCTURE.md
        if is_root:
            generated_at = int(time.time())
            lines.extend(
                [
                    "## Metadata",
                    "",
                    f"**Repository Type**: `{repo_type.value.upper()}`",
                    f"**Backend Files**: {self.be_file_count}",
                    f"**Frontend Files**: {self.fe_file_count}",
                    f"**Total Tokens**: {self.total_tokens:,}",
                    f"**Total Lines**: {self.total_lines:,}",
                    f"**Generated At**: `{generated_at}`",
                    "",
                ]
            )

            # Tech Stack
            if self.metadata.language or self.metadata.framework:
                lines.extend(
                    [
                        "## Tech Stack",
                        "",
                        "| Category | Technology |",
                        "|----------|------------|",
                    ]
                )
                if self.metadata.language:
                    lines.append(f"| Language | {self.metadata.language} |")
                if self.metadata.framework:
                    lines.append(f"| Framework | {self.metadata.framework} |")
                if self.metadata.database:
                    lines.append(f"| Database | {self.metadata.database} |")
                lines.append("")

            # Architecture
            if self.metadata.architecture_pattern:
                lines.extend(
                    [
                        "## Architecture",
                        "",
                        f"**Pattern**: {self.metadata.architecture_pattern}",
                        "",
                    ]
                )
                if self.metadata.architecture_description:
                    lines.append(self.metadata.architecture_description)
                    lines.append("")

            # Entry Points
            if self.metadata.entry_points:
                lines.extend(
                    [
                        "## Entry Points",
                        "",
                    ]
                )
                for ep in self.metadata.entry_points:
                    lines.append(f"- `{ep}`")
                lines.append("")

            # Key Dependencies
            if self.metadata.dependencies:
                lines.extend(
                    [
                        "## Key Dependencies",
                        "",
                        "| Package | Version |",
                        "|---------|---------|",
                    ]
                )
                for dep in self.metadata.dependencies[:10]:
                    lines.append(f"| {dep.name} | {dep.version} |")
                lines.append("")

            # Environment Variables
            if self.metadata.env_vars:
                lines.extend(
                    [
                        "## Environment Variables",
                        "",
                    ]
                )
                for var in self.metadata.env_vars:
                    lines.append(f"- `{var}`")
                lines.append("")

        # Files section
        if dir_struct.files:
            # Calculate totals for directory
            total_tokens = sum(f.tokens for f in dir_struct.files)
            total_lines = sum(f.lines for f in dir_struct.files)

            lines.extend(
                [
                    "## Files",
                    "",
                    (
                        f"**Directory Stats:** {len(dir_struct.files)} files, "
                        f"{total_lines:,} lines, {total_tokens:,} tokens"
                    ),
                    "",
                    "| File | Lines | Tokens |",
                    "|------|------:|-------:|",
                ]
            )

            for file_struct in sorted(dir_struct.files, key=lambda f: f.path.name):
                lines.append(
                    f"| `{file_struct.path.name}` | "
                    f"{file_struct.lines:,} | {file_struct.tokens:,} |"
                )

            lines.append("")

            # Only show per-file sections for files WITH elements (reduces redundancy)
            files_with_elements = [f for f in dir_struct.files if f.elements]
            for file_struct in sorted(files_with_elements, key=lambda f: f.path.name):
                lines.append(f"### {file_struct.path.name}")
                lines.append("")
                for elem in file_struct.elements:
                    lines.append(f"- **{elem.type}**: `{elem.name}` - {elem.description}")
                lines.append("")

        # Subdirectories section
        if dir_struct.subdirectories:
            if dir_struct.depth < self.max_depth:
                # Link to child STRUCTURE.md files
                lines.extend(["## Subdirectories", ""])

                for sub in sorted(dir_struct.subdirectories, key=lambda s: s.path.name):
                    sub_name = sub.path.name
                    # Use purpose if available, otherwise fall back to file count
                    if sub.purpose:
                        desc = sub.purpose
                    else:
                        file_count = len(sub.files)
                        sub_count = len(sub.subdirectories)
                        desc_parts = []
                        if file_count:
                            desc_parts.append(f"{file_count} file{'s' if file_count > 1 else ''}")
                        if sub_count:
                            desc_parts.append(
                                f"{sub_count} subfolder{'s' if sub_count > 1 else ''}"
                            )
                        desc = ", ".join(desc_parts) if desc_parts else "Empty"

                    lines.append(f"- [{sub_name}/]({sub_name}/{STRUCTURE_FILENAME}) - {desc}")

                lines.append("")
            else:
                # At max depth: inline nested directory info (no separate STRUCTURE.md)
                lines.extend(["## Nested Directories", ""])
                lines.append("*Directories beyond max depth, included inline:*")
                lines.append("")

                for sub in sorted(dir_struct.subdirectories, key=lambda s: s.path.name):
                    sub_name = sub.path.name
                    file_count = len(sub.files)
                    purpose = sub.purpose or "nested module"

                    lines.append(f"### {sub_name}/ ({file_count} files)")
                    lines.append(f"*{purpose}*")
                    lines.append("")

                    # List files with elements
                    for file_struct in sorted(sub.files, key=lambda f: f.path.name):
                        file_name = file_struct.path.name
                        lines.append(f"**{file_name}** - {file_struct.lines} lines")
                        if file_struct.elements:
                            for elem in file_struct.elements[:5]:  # Limit to 5
                                lines.append(f"- `{elem.name}` ({elem.type})")
                        lines.append("")

        # Footer
        lines.extend(
            [
                "---",
                (
                    f"*Generated by TurboWrap - {time.strftime('%Y-%m-%d %H:%M')} | "
                    f"ts:{int(time.time())}*"
                ),
            ]
        )

        # Determine output path (in-place in repository)
        if str(dir_struct.path) == ".":
            output_path = self.repo_path / STRUCTURE_FILENAME
        else:
            output_path = self.repo_path / dir_struct.path / STRUCTURE_FILENAME

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines), encoding="utf-8")

        return output_path

    def _generate_structure_xml(
        self,
        directories: list[DirectoryStructure],
        repo_type: RepoType,
    ) -> Path:
        """
        Generate a single consolidated .llms/structure.xml file.

        This XML format is optimized for LLM consumption with semantic tags.
        """
        import xml.etree.ElementTree as ET
        from xml.dom import minidom

        # Create root element
        # For monorepo workspace, use workspace name (e.g., "helpdesk") not repo name
        repo_name = self.scan_root.name if self.workspace_path else self.repo_path.name
        root = ET.Element("repository")
        root.set("name", repo_name)
        root.set("type", repo_type.value)
        root.set("lang", self.metadata.language or "unknown")

        # Add metadata section
        metadata = ET.SubElement(root, "metadata")

        if self.metadata.framework:
            framework = ET.SubElement(metadata, "framework")
            framework.text = self.metadata.framework

        if self.metadata.database:
            database = ET.SubElement(metadata, "database")
            database.text = self.metadata.database

        stats = ET.SubElement(metadata, "stats")
        stats.set("files", str(self.be_file_count + self.fe_file_count))
        stats.set("lines", str(self.total_lines))
        stats.set("tokens", str(self.total_tokens))

        if self.metadata.architecture_pattern:
            arch = ET.SubElement(metadata, "architecture")
            arch.set("pattern", self.metadata.architecture_pattern)
            if self.metadata.architecture_description:
                arch.text = self.metadata.architecture_description

        # Add entry points
        if self.metadata.entry_points:
            entry_points = ET.SubElement(metadata, "entry-points")
            for ep in self.metadata.entry_points:
                entry = ET.SubElement(entry_points, "entry")
                entry.text = ep

        # Add modules (directories with files)
        for dir_struct in directories:
            if not dir_struct.files:
                continue

            module = ET.SubElement(root, "module")
            module.set("path", str(dir_struct.path) if str(dir_struct.path) != "." else "/")

            if dir_struct.purpose:
                module.set("purpose", dir_struct.purpose)

            # Add files
            for file_struct in sorted(dir_struct.files, key=lambda f: f.path.name):
                file_elem = ET.SubElement(module, "file")
                file_elem.set("name", file_struct.path.name)
                file_elem.set("lines", str(file_struct.lines))
                file_elem.set("tokens", str(file_struct.tokens))

                # Add elements (functions, classes, components - skip constants/decorators)
                for elem in file_struct.elements:
                    if elem.type.lower() in ("class",):
                        class_elem = ET.SubElement(file_elem, "class")
                        class_elem.set("name", elem.name)
                        if elem.description:
                            class_elem.set("desc", elem.description)
                    elif elem.type.lower() in ("function", "hook", "utils"):
                        func_elem = ET.SubElement(file_elem, "function")
                        func_elem.set("name", elem.name)
                        if elem.description:
                            func_elem.set("desc", elem.description)
                    elif elem.type.lower() in ("component",):
                        comp_elem = ET.SubElement(file_elem, "component")
                        comp_elem.set("name", elem.name)
                        if elem.description:
                            comp_elem.set("desc", elem.description)
                    # Skip constants and decorators - they add bulk without much value

        # Pretty print XML (xml_string is self-generated, not untrusted input)
        xml_string = ET.tostring(root, encoding="unicode")
        dom = minidom.parseString(xml_string)  # noqa: S318
        pretty_xml = dom.toprettyxml(indent="  ", encoding=None)

        # Remove extra blank lines and XML declaration (we'll add our own)
        lines = pretty_xml.split("\n")
        # Skip the XML declaration line from minidom
        clean_lines = [line for line in lines[1:] if line.strip()]

        # Add our own XML declaration with timestamp
        output_lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            (
                f"<!-- Generated by TurboWrap - {time.strftime('%Y-%m-%d %H:%M')} | "
                f"ts:{int(time.time())} -->"
            ),
            *clean_lines,
        ]

        # Create .llms directory and write file
        # For monorepo: put in workspace/.llms/, otherwise repo_root/.llms/
        llms_dir = self.scan_root / ".llms"
        llms_dir.mkdir(parents=True, exist_ok=True)

        output_path = llms_dir / "structure.xml"
        output_path.write_text("\n".join(output_lines), encoding="utf-8")

        return output_path

    def generate(self, verbose: bool = True, formats: list[str] | None = None) -> list[Path]:
        """
        Generate structure documentation files.

        Args:
            verbose: Print progress messages
            formats: List of formats to generate. Options: "markdown", "xml".
                     Defaults to ["markdown", "xml"] (both formats).

        Returns:
            List of generated file paths
        """
        if formats is None:
            formats = ["markdown", "xml"]

        logger.info("[StructureGenerator] Starting generation...")
        logger.info(f"[StructureGenerator] repo_path={self.repo_path}, scan_root={self.scan_root}")
        logger.info(f"[StructureGenerator] workspace_path={self.workspace_path}, formats={formats}")

        # 1. Detect repo type
        repo_type = self.detect_repo_type()
        logger.info(
            f"[StructureGenerator] Repo type: {repo_type.value}, "
            f"BE files: {self.be_file_count}, FE files: {self.fe_file_count}"
        )

        # 2. Extract metadata
        logger.info("[StructureGenerator] Extracting metadata...")
        self.extract_metadata()
        logger.info(
            f"[StructureGenerator] Language: {self.metadata.language}, "
            f"Framework: {self.metadata.framework}"
        )

        # 3. Discover directories
        logger.info("[StructureGenerator] Discovering directories...")
        directories = self.discover_directories()

        if not directories:
            logger.warning("[StructureGenerator] No directories with processable files found!")
            return []

        total_files = sum(len(d.files) for d in directories)
        logger.info(
            f"[StructureGenerator] Found {len(directories)} directories with {total_files} files"
        )

        # 4. Collect all files to process
        all_files: list[FileStructure] = []
        for dir_struct in directories:
            all_files.extend(dir_struct.files)

        # 5. Extract elements in parallel
        logger.info(f"[StructureGenerator] Extracting elements from {len(all_files)} files...")

        processed_files: dict[Path, FileStructure] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._extract_file_elements, file_struct): file_struct
                for file_struct in all_files
            }

            completed = 0
            for future in as_completed(futures):
                completed += 1
                original = futures[future]
                try:
                    result = future.result()
                    processed_files[result.path] = result
                    if completed % 20 == 0 or completed == len(all_files):
                        logger.info(
                            f"[StructureGenerator] Processed {completed}/{len(all_files)} files"
                        )
                except Exception as e:
                    logger.error(f"[StructureGenerator] Error processing {original.path}: {e}")
                    processed_files[original.path] = original

        # 6. Update directory structures with results
        for dir_struct in directories:
            dir_struct.files = [processed_files.get(f.path, f) for f in dir_struct.files]

        # 6b. Analyze directory purposes
        if self.gemini_client:
            logger.info("[StructureGenerator] Analyzing directory purposes...")
            self._analyze_directory_purposes(directories)

        # 7. Generate output files based on requested formats
        generated_files: list[Path] = []

        # 7a. Generate STRUCTURE.md files (markdown format)
        if "markdown" in formats:
            dirs_to_generate = [d for d in directories if d.depth <= self.max_depth]
            logger.info(
                f"[StructureGenerator] Generating {len(dirs_to_generate)} STRUCTURE.md files..."
            )

            for _i, dir_struct in enumerate(dirs_to_generate):
                try:
                    is_root = str(dir_struct.path) == "."
                    output_path = self._generate_structure_md(
                        dir_struct, repo_type, is_root=is_root
                    )
                    generated_files.append(output_path)
                except Exception as e:
                    logger.error(
                        f"[StructureGenerator] Error generating STRUCTURE.md for "
                        f"{dir_struct.path}: {e}"
                    )

        # 7b. Generate .llms/structure.xml (XML format for LLM)
        if "xml" in formats:
            logger.info("[StructureGenerator] Generating .llms/structure.xml...")

            try:
                xml_path = self._generate_structure_xml(directories, repo_type)
                generated_files.append(xml_path)
                xml_size = xml_path.stat().st_size
                logger.info(
                    f"[StructureGenerator] SUCCESS: Generated {xml_path} ({xml_size:,} bytes)"
                )
            except Exception as e:
                import traceback

                logger.error(f"[StructureGenerator] FAILED to generate XML: {e}")
                logger.error(f"[StructureGenerator] Traceback:\n{traceback.format_exc()}")
                # Re-raise so caller knows it failed!
                raise RuntimeError(f"Failed to generate structure.xml: {e}") from e

        logger.info(
            f"[StructureGenerator] Complete! Generated {len(generated_files)} files, "
            f"{self.total_lines:,} lines, {self.total_tokens:,} tokens"
        )

        return generated_files

    def check_stale_structures(self) -> list[Path]:
        """
        Find STRUCTURE.md files that are stale (directory has newer files).

        Uses the ts: timestamp embedded in STRUCTURE.md footer for comparison.
        Falls back to file mtime if no ts: found.

        Returns:
            List of directories whose STRUCTURE.md needs regeneration
        """
        import re

        stale_dirs: list[Path] = []

        # Find all STRUCTURE.md files
        for structure_file in self.repo_path.rglob(STRUCTURE_FILENAME):
            if should_ignore(structure_file.parent):
                continue

            # Try to extract ts: timestamp from content
            try:
                content = structure_file.read_text()
                match = re.search(r"\|\s*ts:(\d+)", content)
                if match:
                    generated_at = int(match.group(1))
                else:
                    # Fallback to file mtime for legacy files
                    generated_at = int(structure_file.stat().st_mtime)
            except Exception:
                continue

            # Check if any code file in the directory is newer
            parent_dir = structure_file.parent
            is_stale = False

            for code_file in parent_dir.iterdir():
                if not code_file.is_file():
                    continue

                suffix = code_file.suffix.lower()
                if suffix not in BE_EXTENSIONS and suffix not in FE_EXTENSIONS:
                    continue

                # 10 second tolerance to avoid false positives from timing issues
                file_mtime = int(code_file.stat().st_mtime)
                if file_mtime > generated_at + 10:
                    is_stale = True
                    break

            if is_stale:
                try:
                    rel_path = parent_dir.relative_to(self.repo_path)
                    stale_dirs.append(rel_path if str(rel_path) != "." else Path("."))
                except ValueError:
                    stale_dirs.append(Path("."))

        return stale_dirs

    def regenerate_stale(self, verbose: bool = True) -> list[Path]:
        """
        Check and regenerate only stale STRUCTURE.md files.

        Args:
            verbose: Print progress messages

        Returns:
            List of regenerated STRUCTURE.md file paths
        """
        if verbose:
            print("\n[StructureGenerator] Checking for stale STRUCTURE.md files...")

        stale_dirs = self.check_stale_structures()

        if not stale_dirs:
            if verbose:
                print("   All STRUCTURE.md files are up to date.")
            return []

        if verbose:
            print(f"   Found {len(stale_dirs)} stale directories:")
            for d in stale_dirs:
                print(f"      - {d}/")

        # Detect repo type for metadata
        repo_type = self.detect_repo_type()

        regenerated: list[Path] = []

        for stale_dir in stale_dirs:
            if verbose:
                print(f"\n   Regenerating {stale_dir}/STRUCTURE.md...")

            # Build DirectoryStructure for this directory
            full_path = self.repo_path / stale_dir if str(stale_dir) != "." else self.repo_path

            dir_struct = DirectoryStructure(
                path=stale_dir, depth=len(stale_dir.parts) + 1 if str(stale_dir) != "." else 1
            )

            # Find files in directory
            try:
                for item in full_path.iterdir():
                    if item.is_file() and not should_ignore(item):
                        suffix = item.suffix.lower()
                        rel_file = item.relative_to(self.repo_path)
                        if suffix in BE_EXTENSIONS:
                            dir_struct.files.append(FileStructure(path=rel_file, file_type="be"))
                        elif suffix in FE_EXTENSIONS:
                            dir_struct.files.append(FileStructure(path=rel_file, file_type="fe"))
            except PermissionError:
                continue

            # Find subdirectories
            try:
                for item in sorted(full_path.iterdir()):
                    if item.is_dir() and not should_ignore(item):
                        sub_rel = item.relative_to(self.repo_path)
                        sub_struct = DirectoryStructure(path=sub_rel, depth=dir_struct.depth + 1)
                        # Just count files for link description
                        for sub_item in item.iterdir():
                            if sub_item.is_file() and not should_ignore(sub_item):
                                suffix = sub_item.suffix.lower()
                                if suffix in BE_EXTENSIONS or suffix in FE_EXTENSIONS:
                                    sub_struct.files.append(
                                        FileStructure(
                                            path=sub_item.relative_to(self.repo_path),
                                            file_type="be" if suffix in BE_EXTENSIONS else "fe",
                                        )
                                    )
                        if sub_struct.files:
                            dir_struct.subdirectories.append(sub_struct)
            except PermissionError:
                pass

            # Extract file elements
            for file_struct in dir_struct.files:
                self._extract_file_elements(file_struct)

            # Generate STRUCTURE.md
            is_root = str(stale_dir) == "."
            if is_root:
                self.extract_metadata()

            try:
                output_path = self._generate_structure_md(dir_struct, repo_type, is_root=is_root)
                regenerated.append(output_path)
                if verbose:
                    print(f"      ✓ {output_path.relative_to(self.repo_path)}")
            except Exception as e:
                if verbose:
                    print(f"      ✗ Error: {e}")

        if verbose:
            print(f"\n   Regenerated {len(regenerated)} STRUCTURE.md files")

        return regenerated
