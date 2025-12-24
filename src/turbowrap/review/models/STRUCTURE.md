# Review Models Structure

Pydantic data models for structured code review requests, challenger feedback loops, and final report generation.

## File Descriptions
- **\_\_init\_\_.py**: Exports the public API for all review-related schemas and enums.
- **review.py**: Defines core review entities like `Issue`, `IssueSeverity`, `IssueCategory`, and `ReviewMetrics`.
- **progress.py**: Models for real-time tracking of review states and Server-Sent Events (SSE) streaming.
- **challenger.py**: Models for the iterative challenger process, including quality scoring and issue validation.
- **report.py**: Defines the structure of the final output, including summaries, recommendations, and iteration history.

## Key Classes
- **Review Core**: `Issue`, `IssueSeverity`, `IssueCategory`, `ReviewMetrics`, `ReviewSummary`.
- **Challenger System**: `ChallengerFeedback`, `DimensionScores`, `MissedIssue`, `Challenge`, `ConvergenceStatus`.
- **Reporting**: `FinalReport`, `ReportSummary`, `Recommendation`, `IterationHistory`, `SeveritySummary`.
- **Streaming**: `ProgressEvent`, `ReviewerState`, `ProgressEventType`.

## Dependencies
- **Pydantic**: Used for all model definitions, validation, and JSON schema generation.
- **Internal**: `report.py` depends on `review.py` for `Issue`, `ReviewMetrics`, and `ChecklistResult`.
- **Standard Library**: `datetime` for timestamps, `enum` for constants, and `typing` for type hinting.