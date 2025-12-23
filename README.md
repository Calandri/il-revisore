# 🔍 Il Revisore

Code repository analyzer powered by Gemini AI agents.

## Features

- **Flash Analyzer**: Analyzes repository structure and creates documentation
- **BE Reviewer**: Reviews Python/Backend code (1 agent per 3 files)
- **FE Reviewer**: Reviews React/TypeScript code (1 agent per 3 files)
- **TODO Generator**: Creates actionable review checklist

## Installation

```bash
pip install google-genai
```

## Setup

Set your Gemini API key:

```bash
export GOOGLE_API_KEY="your-api-key"
# or
export GEMINI_API_KEY="your-api-key"
```

Get your API key from [Google AI Studio](https://aistudio.google.com/app/apikey).

## Usage

```bash
# Analyze a repository
python revisore.py /path/to/repo

# Custom output directory
python revisore.py /path/to/repo --output ./my-reviews

# More parallel workers
python revisore.py /path/to/repo --max-workers 5

# Skip repo analysis (only review code)
python revisore.py /path/to/repo --skip-flash

# Skip code review (only analyze structure)
python revisore.py /path/to/repo --skip-review
```

## Output

Results are saved to `<repo>/.reviews/`:

- `REPO_DESCRIPTION.md` - Repository overview and structure
- `REVIEW_TODO.md` - Issues and action items checklist

## Agent Instructions

Customize agent behavior by editing the markdown files in `agents/`:

- `flash_analyzer.md` - Repository analysis instructions
- `reviewer_be.md` - Python/Backend review criteria
- `reviewer_fe.md` - React/Frontend review criteria

## License

MIT
