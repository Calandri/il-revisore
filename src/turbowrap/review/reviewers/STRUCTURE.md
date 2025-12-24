# Reviewers Module

This module implements the dual-reviewer logic for TurboWrap, using Claude for initial code reviews and Gemini for challenging and refining findings.

## Files
- **base.py**: Defines the `BaseReviewer` abstract class and the `ReviewContext` container for review metadata.
- **claude_reviewer.py**: Implementation of the primary reviewer role using Anthropic's Claude models.
- **gemini_challenger.py**: Implementation of the challenger role using Gemini CLI to evaluate and critique reviews.
- **__init__.py**: Module entry point exporting the core reviewer and challenger classes.

## Key Classes
- `BaseReviewer`: Abstract interface for all reviewer and challenger implementations.
- `ReviewContext`: Data structure containing file contents, git diffs, and repository architecture docs.
- `ClaudeReviewer`: Handles initial code analysis and review refinement iterations.
- `GeminiChallenger`: Evaluates reviewer outputs against quality thresholds to identify missed issues.

## Dependencies
- **Internal**: `turbowrap.review.models` (data schemas), `turbowrap.config` (API settings).
- **External**: `anthropic` (Anthropic API client), Gemini CLI (via subprocess).