# TurboWrap Tools

Utility module for analyzing repository architectures and generating automated `STRUCTURE.md` documentation.

### Files
- `__init__.py`: Package entry point that exports the main `StructureGenerator` class.
- `structure_generator.py`: Core logic for repository analysis, token counting, and metadata extraction.
- `__main__.py`: CLI interface for running the structure generator via `python -m turbowrap.tools`.

### Key Elements
- `StructureGenerator`: Main class for traversing directories and generating documentation files.
- `RepoMetadata`: Data class containing tech stack, entry points, and dependency information.
- `RepoType`: Enum classifying projects as backend, frontend, fullstack, or unknown.
- `count_tokens`: Function to calculate token counts using `tiktoken` (cl100k_base).
- `run_structure_generator`: Function managing CLI execution and Gemini AI integration.

### Dependencies
- **External**: `tiktoken`, `tomli` (for Python < 3.11), `google-genai` (optional for AI extraction).
- **Standard**: `pathlib`, `dataclasses`, `concurrent.futures`, `json`, `re`.