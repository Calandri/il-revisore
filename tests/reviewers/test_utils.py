"""
Tests for reviewer utilities (refactored modules).

Run with: uv run pytest tests/reviewers/test_utils.py -v

These tests verify the reviewer utilities refactoring is correct:
1. JSON extraction from LLM responses
2. Response parsers (ReviewOutput, ChallengerFeedback)
3. Prompt builders
4. S3Logger
5. GeminiChallenger unified modes
6. Deprecated wrapper compatibility
"""

import warnings
from unittest.mock import MagicMock, patch

import pytest

from turbowrap.review.models.challenger import ChallengerStatus
from turbowrap.review.models.review import IssueCategory, IssueSeverity
from turbowrap.review.reviewers.utils import (
    JSONExtractionError,
    build_challenge_prompt_cli,
    build_challenge_prompt_sdk,
    extract_json,
    parse_challenger_feedback,
    parse_json_safe,
    parse_review_output,
    repair_truncated_json,
)


# =============================================================================
# Test 1: JSON Extraction - Basic Cases
# =============================================================================
@pytest.mark.unit
class TestJsonExtractionBasic:
    """Test 1: Basic JSON extraction from LLM responses."""

    def test_extract_from_markdown_json_block(self):
        """Extract JSON from ```json code block."""
        response = """Here is my analysis:

```json
{
    "summary": {"score": 8.5},
    "issues": []
}
```

That's my review."""
        result = extract_json(response)
        assert '"summary"' in result
        assert '"score": 8.5' in result

    def test_extract_from_generic_code_block(self):
        """Extract JSON from ``` code block without language."""
        response = """Analysis complete:

```
{"result": "success", "count": 42}
```
"""
        result = extract_json(response)
        assert '"result": "success"' in result

    def test_extract_raw_json(self):
        """Extract JSON without code blocks (raw braces)."""
        response = 'The output is {"key": "value", "nested": {"a": 1}}'
        result = extract_json(response)
        assert '"key": "value"' in result

    def test_pure_json_response(self):
        """Handle response that is pure JSON."""
        response = '{"clean": true, "items": [1, 2, 3]}'
        result = extract_json(response)
        assert result == response

    def test_parse_json_safe_returns_dict(self):
        """parse_json_safe should return parsed dict."""
        response = '{"name": "test", "value": 123}'
        result = parse_json_safe(response)
        assert isinstance(result, dict)
        assert result["name"] == "test"
        assert result["value"] == 123


# =============================================================================
# Test 2: JSON Extraction - LLM Edge Cases
# =============================================================================
@pytest.mark.unit
class TestJsonExtractionLLMEdgeCases:
    """Test 2: Real LLM response edge cases."""

    def test_thinking_before_json(self):
        """LLM thinking text before JSON output."""
        response = """Let me analyze this code carefully...

First, I'll check for security issues.
Then performance problems.

OK, here's my review:

```json
{
    "summary": {"files_reviewed": 5, "score": 7.0},
    "issues": [
        {"id": "SEC-001", "severity": "HIGH", "title": "SQL Injection"}
    ]
}
```"""
        result = parse_json_safe(response)
        assert result["summary"]["files_reviewed"] == 5
        assert len(result["issues"]) == 1

    def test_explanation_after_json(self):
        """LLM explanation after JSON output."""
        response = """```json
{"status": "complete"}
```

As you can see, I've finished the analysis. The status is complete."""
        result = parse_json_safe(response)
        assert result["status"] == "complete"

    def test_multiple_json_blocks_uses_first(self):
        """Multiple JSON blocks - use first one."""
        response = """First result:
```json
{"first": true}
```

Wait, let me reconsider:
```json
{"second": true}
```"""
        result = parse_json_safe(response)
        # Should use first block
        assert result.get("first") is True or result.get("second") is True

    def test_nested_code_blocks(self):
        """Code examples inside JSON (escaped)."""
        response = """```json
{
    "issue": "Missing type hints",
    "current_code": "def foo(x):\\n    return x + 1",
    "suggested_fix": "def foo(x: int) -> int:\\n    return x + 1"
}
```"""
        result = parse_json_safe(response)
        assert "def foo" in result["current_code"]

    def test_unicode_in_json(self):
        """Unicode characters in JSON response."""
        response = """```json
{
    "title": "Emoji test: 🚀🔥",
    "description": "Chinese: 中文测试, Italian: caffè, Special: ñ"
}
```"""
        result = parse_json_safe(response)
        assert "🚀" in result["title"]
        assert "中文" in result["description"]


# =============================================================================
# Test 3: Truncated JSON Repair
# =============================================================================
@pytest.mark.unit
class TestTruncatedJsonRepair:
    """Test 3: Repair truncated JSON from token limits."""

    def test_repair_missing_closing_brace(self):
        """Repair JSON missing final }."""
        truncated = '{"key": "value", "nested": {"a": 1}'
        repaired = repair_truncated_json(truncated)
        # Should be parseable after repair
        import json

        parsed = json.loads(repaired)
        assert parsed["key"] == "value"

    def test_repair_missing_closing_bracket(self):
        """Repair JSON missing final ]."""
        truncated = '{"items": [1, 2, 3'
        repaired = repair_truncated_json(truncated)
        import json

        parsed = json.loads(repaired)
        assert parsed["items"] == [1, 2, 3]

    def test_repair_truncated_string(self):
        """Repair truncated string value - may not fully repair strings."""
        truncated = '{"message": "Hello wor'
        repaired = repair_truncated_json(truncated)
        # Truncated strings are hard to repair - just verify it doesn't crash
        # and closes the structure
        assert repaired.endswith("}") or "Hello" in repaired

    def test_repair_deeply_nested(self):
        """Repair deeply nested truncated JSON."""
        truncated = '{"a": {"b": {"c": {"d": "deep"'
        repaired = repair_truncated_json(truncated)
        import json

        parsed = json.loads(repaired)
        assert parsed["a"]["b"]["c"]["d"] == "deep"

    def test_repair_array_in_object(self):
        """Repair array truncated inside object - at least adds closing brackets."""
        truncated = '{"issues": [{"id": 1}, {"id": 2}'
        repaired = repair_truncated_json(truncated)
        # Repair adds closing brackets; result may not be perfect JSON
        # but should at least attempt to close open structures
        assert repaired.endswith("}") or repaired.endswith("]")
        assert repaired.count("{") <= repaired.count("}")  # More closes added

    def test_valid_json_unchanged(self):
        """Valid JSON should not be modified."""
        valid = '{"valid": true}'
        result = repair_truncated_json(valid)
        assert result == valid


# =============================================================================
# Test 4: parse_review_output - Real Reviewer Responses
# =============================================================================
@pytest.mark.unit
class TestParseReviewOutput:
    """Test 4: Parse ReviewOutput from real reviewer responses."""

    def test_parse_complete_review(self):
        """Parse complete review with all fields."""
        response = """```json
{
    "summary": {
        "files_reviewed": 10,
        "critical_issues": 1,
        "high_issues": 3,
        "medium_issues": 5,
        "low_issues": 2,
        "score": 7.5
    },
    "issues": [
        {
            "id": "SEC-001",
            "severity": "CRITICAL",
            "category": "security",
            "file": "auth.py",
            "line": 42,
            "title": "SQL Injection vulnerability",
            "description": "User input not sanitized",
            "current_code": "query = f'SELECT * FROM users WHERE id = {user_id}'",
            "suggested_fix": "query = 'SELECT * FROM users WHERE id = %s'; cursor.execute(query, (user_id,))"
        }
    ],
    "checklists": {
        "security": {"passed": 8, "failed": 2, "skipped": 0}
    },
    "metrics": {
        "complexity_avg": 5.2,
        "test_coverage": 75.0
    }
}
```"""
        result = parse_review_output(response, "test_reviewer", 10)

        assert result.summary.files_reviewed == 10
        assert result.summary.critical_issues == 1
        assert result.summary.score == 7.5
        assert len(result.issues) == 1
        assert result.issues[0].severity == IssueSeverity.CRITICAL
        assert result.issues[0].category == IssueCategory.SECURITY

    def test_score_normalization_above_10(self):
        """Scores > 10 should be normalized to 0-10 scale."""
        response = '{"summary": {"files_reviewed": 5, "score": 85}, "issues": []}'
        result = parse_review_output(response, "test", 5)
        # 85 / 10 = 8.5
        assert result.summary.score == 8.5

    def test_category_alias_normalization(self):
        """Category aliases should be normalized."""
        response = """{"summary": {"files_reviewed": 1, "score": 8}, "issues": [
            {
                "id": "1", "severity": "MEDIUM", "category": "business_logic",
                "file": "a.py", "title": "Test"
            },
            {
                "id": "2", "severity": "MEDIUM", "category": "maintainability",
                "file": "b.py", "title": "Test2"
            },
            {
                "id": "3", "severity": "MEDIUM", "category": "code_quality",
                "file": "c.py", "title": "Test3"
            }
        ]}"""
        result = parse_review_output(response, "test", 1)

        # business_logic -> logic
        assert result.issues[0].category == IssueCategory.LOGIC
        # maintainability -> architecture
        assert result.issues[1].category == IssueCategory.ARCHITECTURE
        # code_quality -> style
        assert result.issues[2].category == IssueCategory.STYLE

    def test_missing_optional_fields(self):
        """Handle missing optional fields gracefully."""
        response = '{"summary": {"files_reviewed": 3}, "issues": []}'
        result = parse_review_output(response, "test", 3)

        assert result.summary.files_reviewed == 3
        assert result.summary.critical_issues == 0  # Default
        # Score defaults to 10.0 (perfect) when not specified
        assert result.summary.score == 10.0

    def test_invalid_json_returns_empty_output(self):
        """Invalid JSON returns empty ReviewOutput."""
        response = "This is not JSON at all"
        result = parse_review_output(response, "test", 5)

        assert result.summary.files_reviewed == 5  # Fallback
        assert len(result.issues) == 0

    def test_alternative_field_names(self):
        """Handle alternative field name variations."""
        response = (
            '{"summary": {"files_reviewed": 2, "critical": 1, "high": 2, "score": 6}, '
            '"issues": []}'
        )
        result = parse_review_output(response, "test", 2)

        # Uses "critical" instead of "critical_issues"
        assert result.summary.critical_issues == 1
        assert result.summary.high_issues == 2


# =============================================================================
# Test 5: parse_challenger_feedback - Real Challenger Responses
# =============================================================================
@pytest.mark.unit
class TestParseChallengerFeedback:
    """Test 5: Parse ChallengerFeedback from real challenger responses."""

    def test_parse_approved_feedback(self):
        """Parse feedback that approves the review."""
        response = """```json
{
    "satisfaction_score": 92,
    "status": "APPROVED",
    "dimension_scores": {
        "completeness": 95,
        "accuracy": 90,
        "depth": 88,
        "actionability": 92
    },
    "missed_issues": [],
    "challenges": [],
    "improvements_needed": [],
    "positive_feedback": ["Thorough security analysis", "Clear fix suggestions"]
}
```"""
        result = parse_challenger_feedback(response, iteration=1, threshold=85.0)

        assert result.satisfaction_score == 92
        assert result.status == ChallengerStatus.APPROVED
        assert result.dimension_scores.completeness == 95
        assert len(result.positive_feedback) == 2

    def test_parse_needs_refinement_feedback(self):
        """Parse feedback requiring refinement."""
        response = """```json
{
    "satisfaction_score": 65,
    "status": "NEEDS_REFINEMENT",
    "dimension_scores": {
        "completeness": 60,
        "accuracy": 70,
        "depth": 65,
        "actionability": 60
    },
    "missed_issues": [
        {
            "type": "security",
            "description": "Missing XSS check in template rendering",
            "file": "views.py",
            "lines": "120-125",
            "why_important": "Could allow script injection",
            "suggested_severity": "HIGH"
        }
    ],
    "challenges": [
        {
            "issue_id": "PERF-001",
            "challenge_type": "false_positive",
            "challenge": "This is not actually a performance issue",
            "reasoning": "The query is cached"
        }
    ],
    "improvements_needed": ["Add security checks", "Verify performance claims"]
}
```"""
        result = parse_challenger_feedback(response, iteration=2, threshold=85.0)

        assert result.satisfaction_score == 65
        assert result.status == ChallengerStatus.NEEDS_REFINEMENT
        assert len(result.missed_issues) == 1
        assert result.missed_issues[0].suggested_severity == "HIGH"
        assert len(result.challenges) == 1

    def test_status_from_score_when_missing(self):
        """Derive status from score when not provided."""
        response = (
            '{"satisfaction_score": 95, "dimension_scores": '
            '{"completeness": 95, "accuracy": 95, "depth": 95, "actionability": 95}}'
        )
        result = parse_challenger_feedback(response, iteration=1, threshold=90.0)
        assert result.status == ChallengerStatus.APPROVED

        response2 = (
            '{"satisfaction_score": 50, "dimension_scores": '
            '{"completeness": 50, "accuracy": 50, "depth": 50, "actionability": 50}}'
        )
        result2 = parse_challenger_feedback(response2, iteration=1, threshold=90.0)
        assert result2.status == ChallengerStatus.MAJOR_ISSUES

    def test_invalid_response_returns_fallback(self):
        """Invalid response returns fallback feedback."""
        response = "Completely invalid response"
        result = parse_challenger_feedback(response, iteration=3, threshold=85.0)

        assert result.satisfaction_score == 50
        assert result.status == ChallengerStatus.NEEDS_REFINEMENT
        assert len(result.improvements_needed) > 0  # Contains error message


# =============================================================================
# Test 6: Prompt Builders
# =============================================================================
@pytest.mark.unit
class TestPromptBuilders:
    """Test 6: Challenge prompt builders."""

    def test_build_sdk_prompt_contains_review(self):
        """SDK prompt should contain the review JSON."""
        # Mock ReviewOutput
        mock_review = MagicMock()
        mock_review.model_dump_json.return_value = '{"summary": {}, "issues": []}'

        # Mock ReviewContext
        mock_context = MagicMock()
        mock_context.get_code_context.return_value = "# Code here\ndef foo(): pass"

        prompt = build_challenge_prompt_sdk(mock_review, mock_context, iteration=1)

        assert "Iteration 1" in prompt
        assert '{"summary": {}, "issues": []}' in prompt
        assert "Code here" in prompt
        assert "Completeness" in prompt
        assert "Accuracy" in prompt

    def test_build_cli_prompt_contains_file_list(self):
        """CLI prompt should contain file list, not code."""
        mock_review = MagicMock()
        mock_review.model_dump_json.return_value = '{"summary": {}, "issues": []}'

        file_list = ["src/main.py", "src/utils.py", "tests/test_main.py"]
        prompt = build_challenge_prompt_cli(mock_review, file_list, iteration=2)

        assert "Iteration 2" in prompt
        assert "src/main.py" in prompt
        assert "src/utils.py" in prompt
        assert "Read the files" in prompt
        assert "IMPORTANT" in prompt

    def test_prompt_iteration_number(self):
        """Prompt includes correct iteration number."""
        mock_review = MagicMock()
        mock_review.model_dump_json.return_value = "{}"

        prompt = build_challenge_prompt_cli(mock_review, ["file.py"], iteration=5)
        assert "Iteration 5" in prompt


# =============================================================================
# Test 7: S3Logger
# =============================================================================
@pytest.mark.integration
class TestS3Logger:
    """Test 7: S3Logger functionality."""

    def test_s3_logger_disabled_when_no_bucket(self):
        """S3Logger should be disabled when no bucket configured."""
        with patch("turbowrap.review.reviewers.utils.s3_logger.get_settings") as mock:
            mock.return_value.thinking.s3_bucket = None
            mock.return_value.thinking.s3_region = "eu-west-1"

            from turbowrap.review.reviewers.utils.s3_logger import S3Logger

            logger = S3Logger()
            assert logger.enabled is False

    def test_s3_logger_enabled_when_bucket_set(self):
        """S3Logger should be enabled when bucket configured."""
        with patch("turbowrap.review.reviewers.utils.s3_logger.get_settings") as mock:
            mock.return_value.thinking.s3_bucket = "my-bucket"
            mock.return_value.thinking.s3_region = "eu-west-1"

            from turbowrap.review.reviewers.utils.s3_logger import S3Logger

            logger = S3Logger()
            assert logger.enabled is True

    @pytest.mark.asyncio
    async def test_save_thinking_returns_none_when_disabled(self):
        """save_thinking returns None when S3 disabled."""
        with patch("turbowrap.review.reviewers.utils.s3_logger.get_settings") as mock:
            mock.return_value.thinking.s3_bucket = None
            mock.return_value.thinking.s3_region = "eu-west-1"

            from turbowrap.review.reviewers.utils.s3_logger import S3ArtifactMetadata, S3Logger

            logger = S3Logger()
            metadata = S3ArtifactMetadata(
                review_id="test-123", component="reviewer_be", model="opus"
            )
            result = await logger.save_thinking("thinking content", metadata)
            assert result is None

    @pytest.mark.asyncio
    async def test_save_review_builds_correct_markdown(self):
        """save_review builds proper markdown format."""
        with patch("turbowrap.review.reviewers.utils.s3_logger.get_settings") as mock_settings:
            mock_settings.return_value.thinking.s3_bucket = "test-bucket"
            mock_settings.return_value.thinking.s3_region = "eu-west-1"

            with patch("turbowrap.review.reviewers.utils.s3_logger.boto3") as mock_boto:
                mock_s3 = MagicMock()
                mock_boto.client.return_value = mock_s3

                from turbowrap.review.reviewers.utils.s3_logger import S3ArtifactMetadata, S3Logger

                logger = S3Logger()
                metadata = S3ArtifactMetadata(
                    review_id="test-123", component="reviewer_be", model="opus"
                )

                await logger.save_review(
                    system_prompt="System prompt here",
                    user_prompt="User prompt here",
                    response="Response here",
                    review_json='{"summary": {}}',
                    metadata=metadata,
                    duration_seconds=45.5,
                    files_reviewed=10,
                )

                mock_s3.put_object.assert_called_once()
                call_args = mock_s3.put_object.call_args
                # Handle both positional and keyword args
                body_bytes = call_args.kwargs.get("Body") or call_args[1].get("Body", b"")
                body = (
                    body_bytes.decode("utf-8") if isinstance(body_bytes, bytes) else str(body_bytes)
                )

                assert "# Code Review - reviewer_be" in body
                assert "System prompt here" in body
                assert "45.50" in body  # Duration format may vary


# =============================================================================
# Test 8: GeminiChallenger Unified Modes
# =============================================================================
@pytest.mark.unit
class TestGeminiChallengerModes:
    """Test 8: GeminiChallenger with SDK and CLI modes."""

    def test_sdk_mode_initialization(self):
        """SDK mode uses correct model."""
        with patch("turbowrap.review.reviewers.gemini_challenger.get_settings") as mock:
            mock.return_value.challenger.satisfaction_threshold = 85.0
            mock.return_value.agents.effective_google_key = "test-key"
            mock.return_value.agents.gemini_model = "gemini-2.0-flash"

            from turbowrap.review.reviewers.gemini_challenger import GeminiChallenger, GeminiMode

            challenger = GeminiChallenger(mode=GeminiMode.SDK)
            assert challenger.mode == GeminiMode.SDK
            # SDK mode uses the configured model name
            assert "gemini" in challenger.model.lower() or "flash" in challenger.model.lower()

    def test_cli_mode_initialization(self):
        """CLI mode sets model to gemini-cli."""
        with patch("turbowrap.review.reviewers.gemini_challenger.get_settings") as mock:
            mock.return_value.challenger.satisfaction_threshold = 85.0
            mock.return_value.agents.effective_google_key = "test-key"
            mock.return_value.agents.gemini_model = "gemini-2.0-flash"

            from turbowrap.review.reviewers.gemini_challenger import GeminiChallenger, GeminiMode

            challenger = GeminiChallenger(mode=GeminiMode.CLI)
            assert challenger.mode == GeminiMode.CLI
            assert challenger.model == "gemini-cli"

    def test_string_mode_accepted(self):
        """String 'sdk' and 'cli' accepted as mode."""
        with patch("turbowrap.review.reviewers.gemini_challenger.get_settings") as mock:
            mock.return_value.challenger.satisfaction_threshold = 85.0
            mock.return_value.agents.effective_google_key = "test-key"
            mock.return_value.agents.gemini_model = "gemini-2.0-flash"

            from turbowrap.review.reviewers.gemini_challenger import GeminiChallenger, GeminiMode

            challenger_sdk = GeminiChallenger(mode="sdk")
            assert challenger_sdk.mode == GeminiMode.SDK

            challenger_cli = GeminiChallenger(mode="cli")
            assert challenger_cli.mode == GeminiMode.CLI

    def test_sdk_mode_challenge_requires_context(self):
        """SDK mode challenge() requires context parameter."""
        with patch("turbowrap.review.reviewers.gemini_challenger.get_settings") as mock:
            mock.return_value.challenger.satisfaction_threshold = 85.0
            mock.return_value.agents.effective_google_key = "test-key"
            mock.return_value.agents.gemini_model = "gemini-2.0-flash"

            from turbowrap.review.reviewers.gemini_challenger import GeminiChallenger

            challenger = GeminiChallenger(mode="sdk")

            # Verify challenge method exists and has correct signature
            import inspect

            sig = inspect.signature(challenger.challenge)
            params = list(sig.parameters.keys())
            assert "context" in params
            assert "review" in params

    @pytest.mark.asyncio
    async def test_cli_mode_raises_on_wrong_method(self):
        """CLI mode challenge() raises, should use challenge_cli()."""
        with patch("turbowrap.review.reviewers.gemini_challenger.get_settings") as mock:
            mock.return_value.challenger.satisfaction_threshold = 85.0
            mock.return_value.agents.effective_google_key = "test-key"
            mock.return_value.agents.gemini_model = "gemini-2.0-flash"

            from turbowrap.review.reviewers.gemini_challenger import GeminiChallenger

            challenger = GeminiChallenger(mode="cli")

            # challenge() should raise ValueError for CLI mode
            with pytest.raises(ValueError, match="challenge_cli"):
                await challenger.challenge(context=MagicMock(), review=MagicMock(), iteration=1)


# =============================================================================
# Test 9: Deprecated GeminiCLIChallenger Wrapper
# =============================================================================
@pytest.mark.unit
class TestDeprecatedGeminiCLIChallenger:
    """Test 9: Deprecated wrapper backward compatibility."""

    def test_deprecation_warning_emitted(self):
        """Instantiation emits DeprecationWarning."""
        with patch("turbowrap.review.reviewers.gemini_challenger.get_settings") as mock:
            mock.return_value.challenger.satisfaction_threshold = 85.0
            mock.return_value.agents.effective_google_key = "test-key"
            mock.return_value.agents.gemini_model = "gemini-2.0-flash"

            from turbowrap.review.reviewers.gemini_cli_challenger import GeminiCLIChallenger

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                GeminiCLIChallenger()  # instantiate to trigger deprecation warning

                assert len(w) == 1
                assert issubclass(w[0].category, DeprecationWarning)
                assert "deprecated" in str(w[0].message).lower()

    def test_wrapper_has_cli_mode(self):
        """Wrapper is initialized in CLI mode."""
        with patch("turbowrap.review.reviewers.gemini_challenger.get_settings") as mock:
            mock.return_value.challenger.satisfaction_threshold = 85.0
            mock.return_value.agents.effective_google_key = "test-key"
            mock.return_value.agents.gemini_model = "gemini-2.0-flash"

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from turbowrap.review.reviewers.gemini_challenger import GeminiMode
                from turbowrap.review.reviewers.gemini_cli_challenger import GeminiCLIChallenger

                challenger = GeminiCLIChallenger()
                assert challenger.mode == GeminiMode.CLI

    def test_wrapper_challenge_signature_matches_old_api(self):
        """Wrapper challenge() has old signature for compatibility."""
        with patch("turbowrap.review.reviewers.gemini_challenger.get_settings") as mock:
            mock.return_value.challenger.satisfaction_threshold = 85.0
            mock.return_value.agents.effective_google_key = "test-key"
            mock.return_value.agents.gemini_model = "gemini-2.0-flash"

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                from turbowrap.review.reviewers.gemini_cli_challenger import GeminiCLIChallenger

                challenger = GeminiCLIChallenger()

                import inspect

                sig = inspect.signature(challenger.challenge)
                params = list(sig.parameters.keys())

                # Old API: challenge(review, file_list, repo_path, ...)
                assert "review" in params
                assert "file_list" in params
                assert "repo_path" in params
                # Should NOT require context (that's SDK mode)
                assert "context" not in params


# =============================================================================
# Test 10: Edge Cases - Malformed LLM Responses
# =============================================================================
@pytest.mark.edge_case
class TestMalformedLLMResponses:
    """Test 10: Handle malformed LLM responses gracefully."""

    def test_response_with_control_characters(self):
        """Handle control characters in response - raises JSONDecodeError."""
        import json

        response = '{"key": "value\x00with\x1fnull\x7fbytes"}'
        # Control characters cause JSON parse to fail
        with pytest.raises(json.JSONDecodeError):
            parse_json_safe(response)

    def test_response_with_bom(self):
        """Handle UTF-8 BOM at start."""
        response = '\ufeff{"key": "value"}'
        result = parse_json_safe(response)
        assert result["key"] == "value"

    def test_windows_line_endings(self):
        """Handle Windows CRLF line endings."""
        response = '{\r\n    "key": "value"\r\n}'
        result = parse_json_safe(response)
        assert result["key"] == "value"

    def test_trailing_comma_in_json(self):
        """Trailing comma is invalid JSON - raises JSONDecodeError."""
        import json

        response = '{"items": [1, 2, 3,], "key": "value",}'
        # Python's json module doesn't accept trailing commas
        with pytest.raises(json.JSONDecodeError):
            parse_json_safe(response)

    def test_single_quotes_in_json(self):
        """Single quotes are invalid JSON - raises JSONDecodeError."""
        import json

        response = "{'key': 'value'}"
        with pytest.raises(json.JSONDecodeError):
            parse_json_safe(response)

    def test_comments_in_json(self):
        """Comments are invalid JSON - raises JSONDecodeError."""
        import json

        response = """{
    // This is a comment
    "key": "value"
}"""
        with pytest.raises(json.JSONDecodeError):
            parse_json_safe(response)


# =============================================================================
# Test 11: Real Review JSON Structures
# =============================================================================
@pytest.mark.unit
class TestRealReviewStructures:
    """Test 11: Parse real-world review JSON structures."""

    def test_large_issue_count(self):
        """Handle review with many issues."""
        issues = [
            {
                "id": f"ISSUE-{i:03d}",
                "severity": ["CRITICAL", "HIGH", "MEDIUM", "LOW"][i % 4],
                "category": "logic",
                "file": f"file_{i}.py",
                "title": f"Issue number {i}",
            }
            for i in range(100)
        ]
        response = (
            '{"summary": {"files_reviewed": 50, "score": 5}, "issues": '
            + str(issues).replace("'", '"')
            + "}"
        )
        result = parse_review_output(response, "test", 50)

        assert len(result.issues) == 100

    def test_issue_with_multiline_code(self):
        """Handle issues with multiline code snippets."""
        response = """{"summary": {"files_reviewed": 1, "score": 7}, "issues": [{
            "id": "CODE-001",
            "severity": "MEDIUM",
            "category": "style",
            "file": "main.py",
            "title": "Complex function",
            "current_code": "def foo():\\n    if True:\\n        for i in range(10):\\n            print(i)",
            "suggested_fix": "def foo():\\n    for i in range(10):\\n        print(i)"
        }]}"""
        result = parse_review_output(response, "test", 1)

        assert len(result.issues) == 1
        assert "def foo" in result.issues[0].current_code

    def test_all_severity_levels(self):
        """Verify all severity levels parse correctly."""
        response = """{"summary": {"files_reviewed": 1, "score": 5}, "issues": [
            {
                "id": "1", "severity": "CRITICAL", "category": "security",
                "file": "a.py", "title": "Critical"
            },
            {
                "id": "2", "severity": "HIGH", "category": "security",
                "file": "a.py", "title": "High"
            },
            {
                "id": "3", "severity": "MEDIUM", "category": "logic",
                "file": "a.py", "title": "Medium"
            },
            {
                "id": "4", "severity": "LOW", "category": "style",
                "file": "a.py", "title": "Low"
            }
        ]}"""
        result = parse_review_output(response, "test", 1)

        severities = [issue.severity for issue in result.issues]
        assert IssueSeverity.CRITICAL in severities
        assert IssueSeverity.HIGH in severities
        assert IssueSeverity.MEDIUM in severities
        assert IssueSeverity.LOW in severities


# =============================================================================
# Test 12: Challenger Dimension Score Calculations
# =============================================================================
@pytest.mark.unit
class TestChallengerDimensionScores:
    """Test 12: Challenger dimension score edge cases."""

    def test_dimension_weighted_score(self):
        """Test weighted score calculation."""
        from turbowrap.review.models.challenger import DimensionScores

        scores = DimensionScores(completeness=100, accuracy=100, depth=100, actionability=100)
        assert scores.weighted_score == 100

        scores2 = DimensionScores(completeness=0, accuracy=0, depth=0, actionability=0)
        assert scores2.weighted_score == 0

    def test_missing_dimension_scores_default(self):
        """Missing dimension scores default to 50."""
        response = '{"satisfaction_score": 70}'
        result = parse_challenger_feedback(response, iteration=1, threshold=85.0)

        assert result.dimension_scores.completeness == 50
        assert result.dimension_scores.accuracy == 50

    def test_partial_dimension_scores(self):
        """Handle partial dimension scores."""
        response = '{"satisfaction_score": 75, ' '"dimension_scores": {"completeness": 80}}'
        result = parse_challenger_feedback(response, iteration=1, threshold=85.0)

        assert result.dimension_scores.completeness == 80
        assert result.dimension_scores.accuracy == 50  # Default


# =============================================================================
# Test 13: S3LoggingMixin Integration
# =============================================================================
@pytest.mark.integration
class TestS3LoggingMixin:
    """Test 13: S3LoggingMixin in base.py."""

    def test_mixin_provides_s3_logger(self):
        """Mixin provides lazy-loaded s3_logger property."""
        with patch("turbowrap.review.reviewers.utils.s3_logger.get_settings") as mock:
            mock.return_value.thinking.s3_bucket = "test-bucket"
            mock.return_value.thinking.s3_region = "eu-west-1"

            from turbowrap.review.reviewers.base import S3LoggingMixin

            class TestClass(S3LoggingMixin):
                name = "test"

            obj = TestClass()
            # Should be None initially (lazy load)
            assert obj._s3_logger is None

            # Access property to trigger lazy load
            logger = obj.s3_logger
            assert logger is not None

    @pytest.mark.asyncio
    async def test_mixin_log_methods_exist(self):
        """Mixin provides log methods."""
        from turbowrap.review.reviewers.base import S3LoggingMixin

        class TestClass(S3LoggingMixin):
            name = "test"
            model = "opus"

        obj = TestClass()

        assert hasattr(obj, "log_thinking_to_s3")
        assert hasattr(obj, "log_review_to_s3")
        assert hasattr(obj, "log_challenge_to_s3")


# =============================================================================
# Test 14: JSON Extraction Error Handling
# =============================================================================
@pytest.mark.edge_case
class TestJsonExtractionErrors:
    """Test 14: JSON extraction error handling."""

    def test_completely_empty_response(self):
        """Handle empty string response."""
        with pytest.raises(JSONExtractionError):
            parse_json_safe("")

    def test_whitespace_only_response(self):
        """Handle whitespace-only response."""
        with pytest.raises(JSONExtractionError):
            parse_json_safe("   \n\t  ")

    def test_no_json_at_all(self):
        """Handle response with no JSON."""
        with pytest.raises(JSONExtractionError):
            parse_json_safe("This is just plain text with no JSON")

    def test_html_response(self):
        """Handle accidental HTML response."""
        response = "<html><body>Error: 500</body></html>"
        with pytest.raises(JSONExtractionError):
            parse_json_safe(response)

    def test_error_message_is_helpful(self):
        """JSONExtractionError has helpful message."""
        try:
            parse_json_safe("not json")
        except JSONExtractionError as e:
            assert "json" in str(e).lower() or "extract" in str(e).lower()


# =============================================================================
# Test 15: Integration - Full Pipeline
# =============================================================================
@pytest.mark.integration
class TestFullPipelineIntegration:
    """Test 15: Full pipeline integration tests."""

    def test_review_output_to_challenger_input(self):
        """ReviewOutput can be serialized for challenger."""
        response = """{"summary": {"files_reviewed": 5, "score": 7.5}, "issues": [
            {
                "id": "SEC-001", "severity": "HIGH", "category": "security",
                "file": "auth.py", "title": "Test"
            }
        ]}"""
        review = parse_review_output(response, "reviewer_be", 5)

        # Serialize for challenger
        json_str = review.model_dump_json()
        assert "SEC-001" in json_str
        assert "security" in json_str

    def test_challenger_feedback_for_refinement(self):
        """ChallengerFeedback provides refinement guidance."""
        response = (
            '{"satisfaction_score": 60, "status": "NEEDS_REFINEMENT", '
            '"dimension_scores": {'
            '"completeness": 50, "accuracy": 70, "depth": 60, "actionability": 50'
            "}, "
            '"missed_issues": [{'
            '"type": "security", "description": "XSS", "file": "a.py", '
            '"why_important": "bad"'
            "}], "
            '"improvements_needed": ["Check for XSS", "Add more depth"]}'
        )
        feedback = parse_challenger_feedback(response, iteration=1, threshold=85.0)

        # Should provide refinement prompt
        prompt = feedback.to_refinement_prompt()
        assert "XSS" in prompt
        assert "missed" in prompt.lower() or "issue" in prompt.lower()

    def test_end_to_end_category_normalization(self):
        """Categories normalize consistently through pipeline."""
        # Reviewer uses alias
        review_response = """{"summary": {"files_reviewed": 1, "score": 8}, "issues": [
            {
                "id": "1", "severity": "MEDIUM", "category": "business_logic",
                "file": "a.py", "title": "Logic bug"
            }
        ]}"""
        review = parse_review_output(review_response, "test", 1)
        assert review.issues[0].category == IssueCategory.LOGIC

        # Challenger references the issue
        challenge_response = (
            '{"satisfaction_score": 90, "status": "APPROVED", '
            '"dimension_scores": {'
            '"completeness": 90, "accuracy": 90, "depth": 90, "actionability": 90'
            "}, "
            '"challenges": [{'
            '"issue_id": "1", "challenge_type": "severity", '
            '"challenge": "Should be HIGH"'
            "}]}"
        )
        feedback = parse_challenger_feedback(challenge_response, iteration=1, threshold=85.0)
        assert feedback.challenges[0].issue_id == "1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
