"""
Centralized JSON extraction utilities for LLM responses.

Handles various response formats:
- Raw JSON
- Markdown code blocks (```json ... ```)
- Markdown code blocks without language specifier
- Conversational text with embedded JSON
- Truncated JSON repair
"""

from __future__ import annotations

import json
import logging
from typing import Any, cast

logger = logging.getLogger(__name__)


class JSONExtractionError(Exception):
    """Raised when JSON cannot be extracted from response."""

    pass


def extract_json(text: str, repair_truncated: bool = True) -> str:
    """
    Extract JSON string from LLM response text.

    Handles multiple formats:
    1. Markdown ```json ... ``` blocks
    2. Markdown ``` ... ``` blocks (without language)
    3. Raw JSON starting with {
    4. Embedded JSON in conversational text

    Args:
        text: Raw LLM response text
        repair_truncated: Attempt to repair truncated JSON

    Returns:
        Extracted JSON string (not parsed)

    Raises:
        JSONExtractionError: If no valid JSON structure found
    """
    text = text.strip()

    # Strategy 1: Markdown code block with json language
    # NOTE: Use rfind for the closing ``` because the JSON content itself
    # may contain ``` (e.g., code snippets in file_content_snippet fields)
    if "```json" in text:
        start = text.find("```json")
        if start != -1:
            start += 7  # Length of ```json
            # Find the LAST ``` in the text (the one that closes the code block)
            end = text.rfind("```")
            if end != -1 and end > start:
                return text[start:end].strip()

    # Strategy 2: Generic markdown code block
    if "```" in text:
        lines = text.split("\n")
        json_lines: list[str] = []
        in_block = False
        for line in lines:
            if line.strip().startswith("```"):
                if in_block and json_lines:
                    # End of block - check if we collected valid JSON
                    candidate = "\n".join(json_lines)
                    if candidate.strip().startswith("{"):
                        return candidate
                    json_lines = []
                in_block = not in_block
                continue
            if in_block:
                json_lines.append(line)

    # Strategy 3: Find first { and last } to extract raw JSON
    first_brace = text.find("{")
    if first_brace != -1:
        last_brace = text.rfind("}")
        if last_brace != -1 and last_brace > first_brace:
            json_str = text[first_brace : last_brace + 1]
            if repair_truncated:
                json_str = repair_truncated_json(json_str)
            return json_str

    raise JSONExtractionError(f"No JSON structure found in text: {text[:200]}...")


def repair_truncated_json(json_text: str) -> str:
    """
    Attempt to repair truncated JSON by closing open structures.

    This handles cases where LLM output was cut off mid-JSON.

    Args:
        json_text: Potentially truncated JSON string

    Returns:
        Repaired JSON string
    """
    # Count open/close braces and brackets
    open_braces = json_text.count("{")
    close_braces = json_text.count("}")
    open_brackets = json_text.count("[")
    close_brackets = json_text.count("]")

    # If balanced, nothing to repair
    if open_braces == close_braces and open_brackets == close_brackets:
        return json_text

    logger.warning(
        f"[JSON_REPAIR] Detected truncated JSON: "
        f"braces {open_braces}/{close_braces}, brackets {open_brackets}/{close_brackets}"
    )

    # Try to find a valid stopping point (after a complete structure)
    repaired = json_text.rstrip()

    # Remove trailing incomplete content (after last complete structure)
    # Find last complete structure by looking for pattern: }, or }]
    last_complete = max(
        repaired.rfind("},"),
        repaired.rfind("}]"),
    )

    if last_complete > 0:
        # Truncate to last complete structure
        repaired = repaired[: last_complete + 2]

    # Now close any remaining open structures
    # Count again after truncation
    open_braces = repaired.count("{")
    close_braces = repaired.count("}")
    open_brackets = repaired.count("[")
    close_brackets = repaired.count("]")

    # Add missing closing characters
    # Order matters: close brackets before braces (issues array before root object)
    missing_brackets = open_brackets - close_brackets
    missing_braces = open_braces - close_braces

    if missing_brackets > 0:
        repaired += "]" * missing_brackets
    if missing_braces > 0:
        repaired += "}" * missing_braces

    return repaired


def parse_json_safe(text: str, repair_truncated: bool = True) -> dict[str, Any]:
    """
    Extract and parse JSON from LLM response.

    Combines extraction and parsing with error handling.

    Args:
        text: Raw LLM response text
        repair_truncated: Attempt to repair truncated JSON

    Returns:
        Parsed JSON dict

    Raises:
        JSONExtractionError: If extraction fails
        json.JSONDecodeError: If parsing fails
    """
    json_str = extract_json(text, repair_truncated=repair_truncated)
    return cast(dict[str, Any], json.loads(json_str))


def extract_json_from_llm(output: str) -> str | None:
    """
    Extract JSON from LLM output (handles ```json blocks and raw JSON).

    This is a convenience wrapper that returns None instead of raising
    on failure, suitable for cases where JSON may or may not be present.

    Args:
        output: Raw LLM response text

    Returns:
        Extracted JSON string, or None if no valid JSON found
    """
    try:
        return extract_json(output, repair_truncated=True)
    except JSONExtractionError:
        # Try to find raw JSON array as fallback (extract_json focuses on objects)
        import re

        for pattern in [r"\[[\s\S]*\]"]:
            match = re.search(pattern, output)
            if match:
                try:
                    json.loads(match.group())
                    return match.group()
                except json.JSONDecodeError:
                    continue
        return None


def parse_llm_json(output: str, default: Any = None) -> Any:
    """
    Parse JSON from LLM output, returning default on failure.

    This is a convenience function for cases where you want graceful
    degradation rather than exception handling.

    Args:
        output: Raw LLM response text
        default: Value to return if JSON extraction/parsing fails

    Returns:
        Parsed JSON (dict or list), or default on failure
    """
    extracted = extract_json_from_llm(output)
    if extracted:
        try:
            return json.loads(extracted)
        except json.JSONDecodeError:
            pass
    return default
