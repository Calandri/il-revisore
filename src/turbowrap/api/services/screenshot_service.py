"""Screenshot service for Live View.

Uses Playwright to capture screenshots of production sites
when iframe embedding is blocked.
"""

import logging
from datetime import datetime, timezone

from ...config import get_settings

logger = logging.getLogger(__name__)


class ScreenshotService:
    """Service to capture and upload screenshots using Playwright."""

    def __init__(self) -> None:
        """Initialize screenshot service."""
        self.settings = get_settings()

    async def capture_and_upload(
        self,
        url: str,
        repo_slug: str,
        viewport_width: int = 1920,
        viewport_height: int = 1080,
    ) -> str:
        """Capture a screenshot and upload to S3.

        Args:
            url: URL to screenshot
            repo_slug: Repository slug for S3 path organization
            viewport_width: Browser viewport width
            viewport_height: Browser viewport height

        Returns:
            S3 pre-signed URL to the uploaded screenshot

        Raises:
            RuntimeError: If Playwright is not installed or screenshot fails
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError as e:
            raise RuntimeError(
                "Playwright is not installed. Run: pip install playwright && playwright install chromium"
            ) from e

        screenshot_bytes: bytes | None = None

        # Capture screenshot with Playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    viewport={"width": viewport_width, "height": viewport_height},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                )
                page = await context.new_page()

                # Navigate with timeout
                await page.goto(url, wait_until="networkidle", timeout=30000)

                # Wait a bit for any lazy-loaded content
                await page.wait_for_timeout(1000)

                # Capture full page screenshot
                screenshot_bytes = await page.screenshot(
                    full_page=True,
                    type="png",
                )

            finally:
                await browser.close()

        if not screenshot_bytes:
            raise RuntimeError("Failed to capture screenshot")

        logger.info(f"Captured screenshot of {url} ({len(screenshot_bytes)} bytes)")

        # Upload to S3
        return await self._upload_to_s3(screenshot_bytes, repo_slug, url)

    async def _upload_to_s3(
        self,
        screenshot_bytes: bytes,
        repo_slug: str,
        source_url: str,
    ) -> str:
        """Upload screenshot to S3.

        Args:
            screenshot_bytes: PNG screenshot data
            repo_slug: Repository slug for path organization
            source_url: Original URL (for metadata)

        Returns:
            S3 pre-signed URL
        """
        import asyncio

        from botocore.exceptions import ClientError

        from ...utils.aws_clients import get_s3_client

        settings = self.settings
        bucket = settings.s3_bucket

        if not bucket:
            raise RuntimeError("S3_BUCKET not configured")

        # Generate S3 key
        timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d/%H%M%S")
        s3_key = f"live-view-screenshots/{repo_slug}/{timestamp}.png"

        # Upload
        client = get_s3_client(region=settings.aws_region)

        try:
            await asyncio.to_thread(
                client.put_object,
                Bucket=bucket,
                Key=s3_key,
                Body=screenshot_bytes,
                ContentType="image/png",
                Metadata={
                    "source_url": source_url[:256],  # Limit length
                    "captured_at": datetime.now(timezone.utc).isoformat(),
                },
            )

            # Generate pre-signed URL (7 days expiry)
            presigned_url = client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": s3_key},
                ExpiresIn=7 * 24 * 60 * 60,  # 7 days
            )

            logger.info(f"Uploaded screenshot to s3://{bucket}/{s3_key}")
            return presigned_url

        except ClientError as e:
            logger.error(f"S3 upload failed: {e}")
            raise RuntimeError(f"S3 upload failed: {e}") from e
