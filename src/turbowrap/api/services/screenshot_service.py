"""Screenshot service for Live View.

Uses Playwright to capture screenshots of production sites
when iframe embedding is blocked.
"""

import logging
from datetime import datetime, timezone

from ...config import get_settings
from ...utils.s3_artifact_saver import S3ArtifactSaver

logger = logging.getLogger(__name__)


class ScreenshotService:
    """Service to capture and upload screenshots using Playwright."""

    def __init__(self) -> None:
        """Initialize screenshot service."""
        self.settings = get_settings()
        self._saver: S3ArtifactSaver | None = None

    @property
    def saver(self) -> S3ArtifactSaver:
        """Lazy-load S3 artifact saver."""
        if self._saver is None:
            self._saver = S3ArtifactSaver(
                bucket=self.settings.s3_bucket,
                region=self.settings.aws_region,
                prefix="live-view-screenshots",
            )
        return self._saver

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

        # Upload to S3 using centralized S3ArtifactSaver
        presigned_url = await self.saver.save_binary(
            content=screenshot_bytes,
            artifact_type="screenshot",
            context_id=repo_slug,
            content_type="image/png",
            file_extension="png",
            metadata={
                "source_url": url[:256],
                "captured_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        if not presigned_url:
            raise RuntimeError("S3_BUCKET not configured or upload failed")

        return presigned_url
