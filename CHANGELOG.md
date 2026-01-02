# Changelog

All notable changes to TurboWrap are documented in this file.

## [0.10.0] - 2026-01-02

### Added
- **Issue Widget System**: Embeddable JavaScript widget for reporting bugs and features from any website
  - Element picker ("Seleziona Componente") for selecting UI elements
  - Gemini Vision analysis for screenshot context extraction
  - Claude-powered clarifying questions generation
  - Dual AI analysis pipeline for comprehensive issue descriptions
- **Widget Issue Routing**: Correct database routing based on issue type
  - Bug reports → `Issue` table (appears in `/issues`)
  - Feature suggestions → `Feature` table (appears in `/features`)
  - Questions → `Feature` table
- **Multi-repo Feature Support**: Features can now span multiple repositories
- **Context File Documentation**:
  - Updated CLAUDE.md with complete Issue Widget system documentation
  - Updated GEMINI.md with dual role (Challenger + Vision Analyzer)

### Fixed
- **Widget Issue Routing Bug**: Widget issues now correctly save to Issue or Feature tables instead of LinearIssue
  - Repository linking now works correctly for both Issue (single FK) and Feature (many-to-many)
  - Widget issues now visible in correct pages (/issues for bugs, /features for suggestions)
- **Linear Issue Sync Clarity**: LinearIssue table reserved for syncing FROM Linear via `/linear/sync`

### Changed
- Issue Widget installation now via npm: `@turbowrap/issue-widget@latest`
- Widget API flow streamlined with 3-step process (analyze → answer → finalize)

### Documentation
- Added Issue Widget System section to CLAUDE.md
- Added Dual Role documentation to GEMINI.md
- Updated Architecture diagram with widget and Linear integration packages

## [0.9.0] - 2025-12-15

### Initial Pre-release
- Multi-agent code review system (Claude Opus + Gemini Flash)
- Code fix orchestration with Gemini challenger validation
- Web UI dashboard with real-time streaming
- AWS infrastructure as code (EC2, ALB, ECR, Route53)
- GitHub repository integration
- Linear issue tracking integration
