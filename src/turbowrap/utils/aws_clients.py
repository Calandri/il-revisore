"""Centralized AWS clients factory.

Provides cached boto3 client getters to eliminate duplicated client creation
code across the codebase. Uses functools.lru_cache for efficient caching.

Usage:
    from turbowrap.utils.aws_clients import get_s3_client, get_logs_client

    # Get default S3 client
    s3 = get_s3_client()

    # Get S3 client for specific region
    s3_eu = get_s3_client(region="eu-west-1")
"""

from functools import lru_cache
from typing import Any

import boto3


@lru_cache(maxsize=4)
def get_s3_client(region: str | None = None) -> Any:
    """Get cached S3 client.

    Args:
        region: AWS region (uses default if not specified)

    Returns:
        boto3 S3 client
    """
    kwargs = {"region_name": region} if region else {}
    return boto3.client("s3", **kwargs)


@lru_cache(maxsize=4)
def get_logs_client(region: str | None = None) -> Any:
    """Get cached CloudWatch Logs client.

    Args:
        region: AWS region (uses default if not specified)

    Returns:
        boto3 CloudWatch Logs client
    """
    kwargs = {"region_name": region} if region else {}
    return boto3.client("logs", **kwargs)


@lru_cache(maxsize=4)
def get_ssm_client(region: str | None = None) -> Any:
    """Get cached SSM client.

    Args:
        region: AWS region (uses default if not specified)

    Returns:
        boto3 SSM client
    """
    kwargs = {"region_name": region} if region else {}
    return boto3.client("ssm", **kwargs)


@lru_cache(maxsize=4)
def get_cognito_client(region: str | None = None) -> Any:
    """Get cached Cognito client.

    Args:
        region: AWS region (uses default if not specified)

    Returns:
        boto3 Cognito Identity Provider client
    """
    kwargs = {"region_name": region} if region else {}
    return boto3.client("cognito-idp", **kwargs)


def clear_client_cache() -> None:
    """Clear all cached clients.

    Useful for testing or when AWS credentials change.
    """
    get_s3_client.cache_clear()
    get_logs_client.cache_clear()
    get_ssm_client.cache_clear()
    get_cognito_client.cache_clear()
