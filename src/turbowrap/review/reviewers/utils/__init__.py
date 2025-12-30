"""
Utilities for reviewers.

Centralized modules for:
- JSON extraction from LLM responses
- S3 logging for review artifacts
- Response parsing for ReviewOutput and ChallengerFeedback
- Prompt builders for challengers
"""

from turbowrap.review.reviewers.utils.json_extraction import (
    JSONExtractionError,
    extract_json,
    extract_json_from_llm,
    parse_json_safe,
    parse_llm_json,
    repair_truncated_json,
)
from turbowrap.review.reviewers.utils.prompt_builders import (
    build_challenge_prompt_cli,
    build_challenge_prompt_sdk,
)
from turbowrap.review.reviewers.utils.response_parsers import (
    convert_dict_to_review_output,
    parse_challenger_feedback,
    parse_review_output,
)
from turbowrap.review.reviewers.utils.s3_logger import S3ArtifactMetadata, S3Logger

__all__ = [
    # JSON extraction
    "extract_json",
    "extract_json_from_llm",
    "repair_truncated_json",
    "parse_json_safe",
    "parse_llm_json",
    "JSONExtractionError",
    # S3 logging
    "S3Logger",
    "S3ArtifactMetadata",
    # Response parsers
    "parse_review_output",
    "parse_challenger_feedback",
    "convert_dict_to_review_output",
    # Prompt builders
    "build_challenge_prompt_sdk",
    "build_challenge_prompt_cli",
]
