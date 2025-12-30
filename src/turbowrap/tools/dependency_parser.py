"""
Dependency parser for generating Mermaid diagrams from code analysis.
Uses AST for Python and regex for JS/TS.
"""

import ast
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Directories to ignore when scanning
IGNORE_DIRS = {
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "node_modules",
    ".next",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "coverage",
    ".coverage",
    "htmlcov",
    ".tox",
    "eggs",
    "*.egg-info",
}


@dataclass
class ModuleDependency:
    """A dependency between modules."""

    source: str  # importing module
    target: str  # imported module
    import_type: str = "import"  # import | from


@dataclass
class FunctionCall:
    """A function call relationship."""

    caller: str
    callee: str
    file: str


@dataclass
class DependencyGraph:
    """Complete dependency graph for a repository."""

    module_deps: list[ModuleDependency] = field(default_factory=list)
    function_calls: list[FunctionCall] = field(default_factory=list)

    def to_mermaid_dependency(self, max_nodes: int = 15) -> str:
        """Generate Mermaid dependency graph."""
        if not self.module_deps:
            return ""

        # Count module occurrences to find most important
        module_counts: dict[str, int] = defaultdict(int)
        for dep in self.module_deps:
            module_counts[dep.source] += 1
            module_counts[dep.target] += 1

        # Get top modules
        top_modules = sorted(module_counts.items(), key=lambda x: -x[1])[:max_nodes]
        top_module_names = {m[0] for m in top_modules}

        # Filter deps to only include top modules
        filtered_deps = [
            dep
            for dep in self.module_deps
            if dep.source in top_module_names and dep.target in top_module_names
        ]

        # Remove duplicates
        seen = set()
        unique_deps = []
        for dep in filtered_deps:
            key = (dep.source, dep.target)
            if key not in seen and dep.source != dep.target:
                seen.add(key)
                unique_deps.append(dep)

        if not unique_deps:
            return ""

        lines = ["graph TD"]
        for dep in unique_deps[:30]:  # Limit edges
            source = self._sanitize_node_name(dep.source)
            target = self._sanitize_node_name(dep.target)
            lines.append(f"    {source}[{dep.source}] --> {target}[{dep.target}]")

        return "\n".join(lines)

    def to_mermaid_architecture(self, layers: list[dict[str, Any]] | None = None) -> str:
        """Generate Mermaid architecture diagram with subgraphs."""
        if layers is None:
            # Auto-detect layers from module names
            layers = self._detect_layers()

        if not layers:
            return ""

        lines = ["graph TB"]

        for layer_info in layers:
            layer_name = str(layer_info.get("name", "Unknown"))
            modules: list[str] = layer_info.get("modules", [])

            if modules:
                lines.append(f'    subgraph {self._sanitize_node_name(layer_name)}["{layer_name}"]')
                for module in modules[:5]:  # Limit modules per layer
                    node_name = self._sanitize_node_name(module)
                    lines.append(f"        {node_name}[{module}]")
                lines.append("    end")

        # Add connections between layers
        for i, layer in enumerate(layers[:-1]):
            next_layer = layers[i + 1]
            if layer.get("modules") and next_layer.get("modules"):
                source = self._sanitize_node_name(layer["modules"][0])
                target = self._sanitize_node_name(next_layer["modules"][0])
                lines.append(f"    {source} --> {target}")

        return "\n".join(lines)

    def to_mermaid_flowchart(self, flow_name: str, steps: list[str]) -> str:
        """Generate Mermaid flowchart from steps."""
        if not steps:
            return ""

        lines = ["flowchart LR"]
        for i, step in enumerate(steps):
            node_name = self._sanitize_node_name(f"step{i}")
            lines.append(f"    {node_name}[{step}]")
            if i > 0:
                prev_node = self._sanitize_node_name(f"step{i - 1}")
                lines.append(f"    {prev_node} --> {node_name}")

        return "\n".join(lines)

    def _detect_layers(self) -> list[dict[str, Any]]:
        """Auto-detect layers from module names."""
        layer_patterns = {
            "API": ["api", "routes", "views", "endpoints", "controllers"],
            "Services": ["services", "use_cases", "handlers", "tasks"],
            "Models": ["models", "schemas", "entities", "domain"],
            "Data": ["db", "database", "repositories", "storage"],
            "Utils": ["utils", "helpers", "common", "shared"],
        }

        layers = []
        all_modules = set()
        for dep in self.module_deps:
            all_modules.add(dep.source)
            all_modules.add(dep.target)

        for layer_name, patterns in layer_patterns.items():
            matching = [m for m in all_modules if any(p in m.lower() for p in patterns)]
            if matching:
                layers.append({"name": layer_name, "modules": matching[:5]})

        return layers

    def _sanitize_node_name(self, name: str) -> str:
        """Sanitize node name for Mermaid (remove special chars)."""
        # Replace non-alphanumeric chars with underscore
        sanitized = re.sub(r"[^a-zA-Z0-9]", "_", name)
        # Ensure it starts with a letter
        if sanitized and not sanitized[0].isalpha():
            sanitized = "n_" + sanitized
        return sanitized or "unknown"


class PythonDependencyParser:
    """Parse Python files for dependencies."""

    def parse_file(self, file_path: Path) -> list[ModuleDependency]:
        """Extract imports from a Python file."""
        deps = []
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            module_name = file_path.stem

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        target = alias.name.split(".")[0]
                        deps.append(
                            ModuleDependency(
                                source=module_name, target=target, import_type="import"
                            )
                        )
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        target = node.module.split(".")[0]
                        deps.append(
                            ModuleDependency(source=module_name, target=target, import_type="from")
                        )
        except (SyntaxError, UnicodeDecodeError) as e:
            logger.debug(f"Could not parse {file_path}: {e}")
        return deps

    def parse_function_defs(self, file_path: Path) -> list[str]:
        """Extract function names from Python file."""
        functions = []
        try:
            source = file_path.read_text(encoding="utf-8")
            tree = ast.parse(source)

            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    if not node.name.startswith("_"):  # Skip private functions
                        functions.append(node.name)
        except (SyntaxError, UnicodeDecodeError):
            pass
        return functions


class TypeScriptDependencyParser:
    """Parse TypeScript/JavaScript files for dependencies."""

    # Match various import patterns
    IMPORT_PATTERNS = [
        # import { x } from 'module'
        re.compile(r"import\s+\{[^}]+\}\s+from\s+['\"]([^'\"]+)['\"]"),
        # import x from 'module'
        re.compile(r"import\s+\w+\s+from\s+['\"]([^'\"]+)['\"]"),
        # import * as x from 'module'
        re.compile(r"import\s+\*\s+as\s+\w+\s+from\s+['\"]([^'\"]+)['\"]"),
        # const x = require('module')
        re.compile(r"require\(['\"]([^'\"]+)['\"]\)"),
    ]

    def parse_file(self, file_path: Path) -> list[ModuleDependency]:
        """Extract imports from TS/JS file."""
        deps = []
        try:
            source = file_path.read_text(encoding="utf-8")
            module_name = file_path.stem

            for pattern in self.IMPORT_PATTERNS:
                for match in pattern.finditer(source):
                    target = match.group(1)
                    # Normalize: extract last part of path, remove extensions
                    if "/" in target:
                        target = target.split("/")[-1]
                    target = re.sub(r"\.(js|ts|tsx|jsx)$", "", target)

                    # Skip node_modules (packages starting with letters, not ./ or ../)
                    if not target.startswith(".") and not target.startswith("@"):
                        # This is a package, keep first part
                        target = target.split("/")[0]

                    deps.append(
                        ModuleDependency(source=module_name, target=target, import_type="import")
                    )
        except (UnicodeDecodeError, OSError) as e:
            logger.debug(f"Could not parse {file_path}: {e}")
        return deps

    def parse_component_names(self, file_path: Path) -> list[str]:
        """Extract React component names from file."""
        components = []
        try:
            source = file_path.read_text(encoding="utf-8")

            # Match function components
            func_pattern = re.compile(r"(?:export\s+)?function\s+([A-Z]\w+)")
            for match in func_pattern.finditer(source):
                components.append(match.group(1))

            # Match arrow function components
            arrow_pattern = re.compile(
                r"(?:export\s+)?const\s+([A-Z]\w+)\s*=\s*(?:\([^)]*\)|[^=])\s*=>"
            )
            for match in arrow_pattern.finditer(source):
                components.append(match.group(1))

        except (UnicodeDecodeError, OSError):
            pass
        return components


def _should_ignore(path: Path) -> bool:
    """Check if path should be ignored."""
    return any(part in IGNORE_DIRS or part.endswith(".egg-info") for part in path.parts)


def build_dependency_graph(
    repo_path: Path, workspace_path: str | None = None, max_files: int = 200
) -> DependencyGraph:
    """Build complete dependency graph for repository."""
    graph = DependencyGraph()

    scan_root = repo_path / workspace_path if workspace_path else repo_path

    if not scan_root.exists():
        logger.warning(f"Scan root does not exist: {scan_root}")
        return graph

    py_parser = PythonDependencyParser()
    ts_parser = TypeScriptDependencyParser()

    file_count = 0

    # Parse Python files
    for py_file in scan_root.rglob("*.py"):
        if _should_ignore(py_file) or file_count >= max_files:
            continue
        graph.module_deps.extend(py_parser.parse_file(py_file))
        file_count += 1

    # Parse TypeScript files
    for ts_file in scan_root.rglob("*.ts"):
        if _should_ignore(ts_file) or file_count >= max_files:
            continue
        # Skip .d.ts declaration files
        if ts_file.name.endswith(".d.ts"):
            continue
        graph.module_deps.extend(ts_parser.parse_file(ts_file))
        file_count += 1

    # Parse TSX files
    for tsx_file in scan_root.rglob("*.tsx"):
        if _should_ignore(tsx_file) or file_count >= max_files:
            continue
        graph.module_deps.extend(ts_parser.parse_file(tsx_file))
        file_count += 1

    logger.info(f"Parsed {file_count} files, found {len(graph.module_deps)} dependencies")
    return graph


def generate_mermaid_diagrams(graph: DependencyGraph, repo_name: str) -> list[dict[str, str]]:
    """Generate multiple Mermaid diagrams from dependency graph."""
    diagrams = []

    # 1. Dependency diagram
    dep_code = graph.to_mermaid_dependency()
    if dep_code:
        diagrams.append(
            {
                "type": "dependency",
                "title": "Dipendenze tra Moduli",
                "code": dep_code,
                "description": "Mostra le dipendenze di import tra i moduli principali",
            }
        )

    # 2. Architecture diagram
    arch_code = graph.to_mermaid_architecture()
    if arch_code:
        diagrams.append(
            {
                "type": "architecture",
                "title": "Architettura a Layer",
                "code": arch_code,
                "description": "Organizzazione dei moduli per layer architetturale",
            }
        )

    return diagrams
