# Integrations Module

External API integrations for fetching pull request data and posting review summaries to project management and version control platforms.

## Files
- `__init__.py`: Module entry point that exports the primary integration clients.
- `github.py`: Client for GitHub API to retrieve PR diffs, file lists, and manage review comments.
- `linear.py`: Client for Linear GraphQL API to link reviews to tickets and post status comments.

## Key Exports
- `GitHubClient`: Handles GitHub authentication, PR metadata retrieval, and comment lifecycle.
- `LinearClient`: Handles Linear authentication and posting review summaries to specific issues.

## Dependencies
- `turbowrap.config`: Retrieves API keys and environment settings.
- `turbowrap.review.models.report`: Uses `FinalReport` and `Recommendation` for data formatting.
- **External**: `httpx` (Linear API), `PyGithub` (GitHub API), `requests` (Diff retrieval).