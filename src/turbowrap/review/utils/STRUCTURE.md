# TurboWrap Review Utilities

Utility toolkit for file system operations, Git repository interaction, and project type detection.

## Files
- **`repo_detector.py`**: Classifies repositories as Backend, Frontend, or Fullstack based on file patterns.
- **`file_utils.py`**: High-level helpers for reading files, calculating hashes, and identifying file types.
- **`git_utils.py`**: Wrapper for Git CLI to extract diffs, changed files, and commit/PR metadata.
- **`__init__.py`**: Exposes the public API for the utility sub-package.

## Key Exports
- **`RepoDetector`**: Analyzes directory structures to determine the tech stack.
- **`GitUtils`**: Handles subprocess calls to Git for repository analysis.
- **`FileUtils`**: Provides static methods for consistent file reading and metadata extraction.
- **`PRInfo` / `CommitInfo`**: Data structures for storing repository state information.
- **`detect_repo_type`**: Convenience function for quick repository classification.

## Dependencies
- **`turbowrap.review.models.report`**: Imports `RepoType` for classification results.
- **System**: Requires `git` executable available in the system PATH for `GitUtils`.
- **Standard Library**: `pathlib`, `subprocess`, `hashlib`, `fnmatch`.
