# /create-issue - Create Issue from Error

Create a new issue in TurboWrap from an error or bug report.

## When to Use

Use this command when:
- You've analyzed an error and found a bug in the codebase
- The user reports a problem that needs to be tracked
- You've identified a code improvement needed

## Required Information

Before creating the issue, gather:
1. **Title**: Short, descriptive title (max 100 chars)
2. **Description**: What's happening and why it's a problem
3. **Error Details**: The actual error message/stack trace
4. **File Location**: Which files are affected
5. **Suggested Fix**: Your analysis of how to fix it
6. **Severity**: critical | high | medium | low

## API Call

Make a POST request to create the issue:

```bash
curl -X POST "http://localhost:8000/api/issues/from-error" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Brief description of the bug",
    "description": "Detailed explanation of the issue",
    "error_message": "The actual error message",
    "error_stack": "Stack trace if available",
    "file_path": "path/to/affected/file.py",
    "line_number": 42,
    "suggested_fix": "Description of how to fix this",
    "severity": "medium",
    "source": "ai_analysis"
  }'
```

## Response Format

After creating the issue, inform the user:

```markdown
## Issue Creata

**ID**: ISSUE-XXX
**Titolo**: {title}
**Severità**: {severity}

### Prossimi Passi
1. L'issue è stata aggiunta alla coda di lavoro
2. Puoi vederla nella pagina [Issues](/issues)
3. Usa `/fix ISSUE-XXX` per avviare il fix automatico

---
*Issue creata automaticamente da TurboWrapAI*
```

## Example Flow

User reports error → You analyze → You find bug → Create issue:

1. Analyze the error context provided
2. Search the codebase to understand the root cause
3. Identify the specific file(s) and line(s) involved
4. Formulate a clear title and description
5. Call the API to create the issue
6. Report back to the user with the issue details

**IMPORTANT: Always verify your analysis before creating an issue. Don't create issues for user errors or configuration problems.**
**IMPORTANT: Respond in Italian (the user's default language).**
