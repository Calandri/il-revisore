"""Shared parsing utilities for CLI output processing."""

import re


def parse_token_string(token_str: str) -> int:
    """Parse token string like '3.4k' or '175.0k' or '317' to int.

    Examples:
        >>> parse_token_string('3.4k')
        3400
        >>> parse_token_string('175.0k')
        175000
        >>> parse_token_string('317')
        317
        >>> parse_token_string('1,435')
        1435
    """
    if not token_str:
        return 0
    token_str = token_str.strip().lower()
    if token_str.endswith("k"):
        return int(float(token_str[:-1]) * 1000)
    return int(float(token_str.replace(",", "")))


def parse_token_count(token_str: str) -> int:
    """Parse token count string like '1,435' or '10449' to int.

    Examples:
        >>> parse_token_count('1,435')
        1435
        >>> parse_token_count('10449')
        10449
    """
    if not token_str:
        return 0
    return int(token_str.replace(",", "").strip())


def parse_time_string(time_str: str) -> float:
    """Parse time string like '2m 54s' or '6.2s' to seconds.

    Examples:
        >>> parse_time_string('2m 54s')
        174.0
        >>> parse_time_string('6.2s')
        6.2
        >>> parse_time_string('1m')
        60.0
    """
    if not time_str:
        return 0.0

    total_seconds = 0.0
    # Match minutes
    m_match = re.search(r"(\d+)m", time_str)
    if m_match:
        total_seconds += int(m_match.group(1)) * 60
    # Match seconds (including decimals)
    s_match = re.search(r"([\d.]+)s", time_str)
    if s_match:
        total_seconds += float(s_match.group(1))
    return total_seconds
