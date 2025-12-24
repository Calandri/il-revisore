# review

## Files

**Directory Stats:** 4 files, 1,448 lines, 10,126 tokens

| File | Lines | Tokens |
|------|------:|-------:|
| `__init__.py` | 15 | 91 |
| `challenger_loop.py` | 306 | 2,146 |
| `orchestrator.py` | 793 | 5,544 |
| `report_generator.py` | 334 | 2,345 |

### __init__.py
*15 lines, 91 tokens*

- **Class**: `Orchestrator` - Manages coordination of the dual-reviewer system.
- **Class**: `ChallengerLoop` - Implements the iterative feedback loop between reviewers.
- **Function**: `run_challenger_loop` - Triggers execution of the challenger review cycle.
- **Class**: `ReportGenerator` - Produces final reports for the review process.
- **Constant**: `__all__` - Defines exported symbols for the review module.

### challenger_loop.py
*306 lines, 2,146 tokens*

- **Class**: `ChallengerLoopResult` - Data structure containing final review results and iteration metadata.
- **Class**: `ChallengerLoop` - Orchestrates the iterative feedback loop between reviewer and challenger.
- **Function**: `run` - Executes the multi-iteration review process until satisfaction criteria met.
- **Constant**: `IterationCallback` - Type definition for reporting progress during the review cycle.
- **Constant**: `ContentCallback` - Type definition for handling streaming review content updates.

### orchestrator.py
*793 lines, 5,544 tokens*

- **Class**: `Orchestrator` - Main coordinator for the code review system.
- **Function**: `review` - Executes the complete code review process and reporting.
- **Function**: `emit` - Internal helper to broadcast progress status updates.
- **Function**: `run_reviewer_with_progress` - Manages individual reviewer execution and event emission.
- **Constant**: `logger` - Logger instance for the orchestrator module.

### report_generator.py
*334 lines, 2,345 tokens*

- **Class**: `ReportGenerator` - Generates formatted reports from code review results.
- **Function**: `to_markdown` - Converts a FinalReport object into a Markdown string.
- **Function**: `_generate_summary` - Generates the executive summary section of the report.
- **Function**: `_generate_challenger_section` - Creates the review quality and challenger iteration section.
- **Function**: `_generate_coverage_section` - Builds the report section detailing review coverage status.

## Nested Directories

*Directories beyond max depth, included inline:*

### integrations/ (3 files)
*Third-party service API connectors*

**__init__.py** - 12 lines
- `GitHubClient` (Class)
- `LinearClient` (Class)
- `__all__` (Constant)

**github.py** - 283 lines
- `GitHubClient` (Class)
- `__init__` (Function)
- `get_pr_files` (Function)
- `get_pr_diff` (Function)
- `post_review_comment` (Function)

**linear.py** - 292 lines
- `LinearClient` (Class)
- `API_URL` (Constant)
- `post_review_comment` (Function)
- `get_issue_id` (Function)
- `_extract_issue_id` (Function)

### models/ (5 files)
*Domain-specific data structures*

**__init__.py** - 73 lines
- `ReviewRequest` (Class)
- `ReviewOutput` (Class)
- `Issue` (Class)
- `FinalReport` (Class)
- `Challenge` (Class)

**challenger.py** - 142 lines
- `ChallengerStatus` (Class)
- `DimensionScores` (Class)
- `MissedIssue` (Class)
- `Challenge` (Class)
- `ChallengerFeedback` (Class)

**progress.py** - 120 lines
- `ProgressEventType` (Class)
- `ProgressEvent` (Class)
- `ReviewerState` (Class)
- `ReviewProgress` (Class)
- `REVIEWER_DISPLAY_NAMES` (Constant)

**report.py** - 183 lines
- `RepoType` (Class)
- `Recommendation` (Class)
- `ReviewerResult` (Class)
- `SeveritySummary` (Class)
- `ReportSummary` (Class)

**review.py** - 191 lines
- `IssueSeverity` (Class)
- `IssueCategory` (Class)
- `Issue` (Class)
- `ChecklistResult` (Class)
- `ReviewMetrics` (Class)

### reviewers/ (4 files)
*AI reviewer implementations*

**__init__.py** - 15 lines
- `BaseReviewer` (Class)
- `ReviewContext` (Class)
- `ClaudeReviewer` (Class)
- `GeminiChallenger` (Class)
- `__all__` (Constant)

**base.py** - 200 lines
- `ReviewContext` (Class)
- `get_files_summary` (Function)
- `get_structure_context` (Function)
- `get_code_context` (Function)
- `BaseReviewer` (Class)

**claude_reviewer.py** - 375 lines
- `ClaudeReviewer` (Class)
- `__init__` (Function)
- `review` (Function)
- `refine` (Function)
- `_build_system_prompt` (Function)

**gemini_challenger.py** - 427 lines
- `GeminiChallenger` (Class)
- `review` (Function)
- `refine` (Function)
- `challenge` (Function)
- `_build_challenge_prompt` (Function)

### utils/ (4 files)
*Shared helper function library*

**__init__.py** - 17 lines
- `GitUtils` (Class)
- `PRInfo` (Class)
- `CommitInfo` (Class)
- `FileUtils` (Class)
- `RepoDetector` (Class)

**file_utils.py** - 259 lines
- `FileUtils` (Class)
- `read_file` (Function)
- `read_lines` (Function)
- `get_file_hash` (Function)
- `count_lines` (Function)

**git_utils.py** - 196 lines
- `PRInfo` (Class)
- `CommitInfo` (Class)
- `GitUtils` (Class)
- `get_changed_files` (Function)
- `get_diff` (Function)

**repo_detector.py** - 254 lines
- `DEFAULT_BACKEND_INDICATORS` (Constant)
- `DEFAULT_FRONTEND_INDICATORS` (Constant)
- `RepoDetector` (Class)
- `detect` (Function)
- `detect_from_directory` (Function)

---
*Generated by TurboWrap - 2025-12-24 15:47*