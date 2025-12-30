"""
Mockup service - handles generation and modification of UI mockups via LLM.

Manages:
- Mockup generation using Claude/Gemini/Grok
- S3 storage for HTML/CSS/JS files
- Version management for modifications
"""

import asyncio
import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from ...config import get_settings
from ...db.models import Mockup, MockupProject
from ...llm.claude_cli import ClaudeCLI
from ...utils.s3_artifact_saver import S3ArtifactSaver

logger = logging.getLogger(__name__)


# Design system prompts
DESIGN_SYSTEM_PROMPTS = {
    "tailwind": (
        "Use Tailwind CSS utility classes for all styling.\n"
        'Include the Tailwind CDN: <script src="https://cdn.tailwindcss.com"></script>\n'
        "Follow Tailwind best practices with responsive classes (sm:, md:, lg:)."
    ),
    "bootstrap": (
        "Use Bootstrap 5 for styling.\n"
        "Include Bootstrap CSS and JS from CDN.\n"
        "Use Bootstrap grid system and components."
    ),
    "material": (
        "Use Material Design principles with custom CSS.\n"
        "Include Material Icons from Google Fonts.\n"
        "Use Material Design color palette and elevation shadows."
    ),
    "custom": (
        "Use custom CSS with modern best practices.\n"
        "Include CSS custom properties (CSS variables) for theming.\n"
        "Use flexbox and grid for layouts."
    ),
}

# TurboWrap color palette
TURBOWRAP_PALETTE = """
TurboWrap Brand Colors:
- Primary: #6366f1 (Indigo)
- Primary Light: #818cf8
- Primary Dark: #4f46e5
- Success: #10b981 (Emerald)
- Warning: #f59e0b (Amber)
- Error: #ef4444 (Red)
- Text Dark: #1f2937
- Text Light: #6b7280
- Background: #f9fafb
- Card Background: #ffffff
"""

MOCKUP_SYSTEM_PROMPT = """You are an expert UI/UX designer and frontend developer.
Your task is to create beautiful, modern UI mockups as complete standalone HTML files.

REQUIREMENTS:
1. Generate a SINGLE complete HTML file with all CSS and JavaScript inline
2. The HTML must be fully standalone and work when opened directly in a browser
3. Use modern design patterns: clean typography, proper spacing, consistent colors
4. Make it responsive (works on mobile, tablet, desktop)
5. Include subtle animations and hover states for better UX
6. Use placeholder images from https://placehold.co/ when needed
7. Include realistic placeholder text/data

{design_system_prompt}

{turbowrap_palette}

OUTPUT FORMAT:
Return ONLY the HTML code wrapped in ```html and ``` markers.
Do not include any explanation before or after the code.

Example output:
```html
<!DOCTYPE html>
<html lang="en">
<head>...</head>
<body>...</body>
</html>
```
"""

MODIFY_SYSTEM_PROMPT = """You are an expert UI/UX designer and frontend developer.
Your task is to modify an existing UI mockup based on the user's request.

CURRENT MOCKUP HTML:
```html
{current_html}
```

{element_context}

MODIFICATION REQUEST:
{modification_prompt}

REQUIREMENTS:
1. Return the COMPLETE modified HTML file
2. Preserve the overall structure and style unless specifically asked to change it
3. Only modify what was requested
4. Keep all existing functionality intact
5. Maintain responsive design

OUTPUT FORMAT:
Return ONLY the complete modified HTML code wrapped in ```html and ``` markers.
Do not include any explanation before or after the code.
"""


@dataclass
class MockupGenerationResult:
    """Result from mockup generation."""

    success: bool
    html: str | None = None
    css: str | None = None
    js: str | None = None
    s3_html_url: str | None = None
    s3_css_url: str | None = None
    s3_js_url: str | None = None
    s3_prompt_url: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    llm_model: str = ""
    error: str | None = None


class MockupService:
    """
    Service for generating and modifying UI mockups.

    Handles:
    - Generating mockups via LLM (Claude, Gemini, Grok)
    - Saving mockup files to S3
    - Creating modified versions of mockups
    """

    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self._s3_saver = S3ArtifactSaver(
            bucket=self.settings.thinking.s3_bucket,
            region=self.settings.thinking.s3_region,
            prefix="mockups",
        )

    async def generate_mockup(
        self,
        mockup: Mockup,
        prompt: str,
        design_system: str = "tailwind",
    ) -> MockupGenerationResult:
        """Generate a mockup using the configured LLM.

        Args:
            mockup: The Mockup model instance
            prompt: User's description of what to create
            design_system: CSS framework/system to use

        Returns:
            MockupGenerationResult with generated code and S3 URLs
        """
        llm_type = mockup.llm_type or "claude"

        # Build system prompt
        design_prompt = DESIGN_SYSTEM_PROMPTS.get(design_system, DESIGN_SYSTEM_PROMPTS["tailwind"])
        system_prompt = MOCKUP_SYSTEM_PROMPT.format(
            design_system_prompt=design_prompt,
            turbowrap_palette=TURBOWRAP_PALETTE,
        )

        full_prompt = f"{system_prompt}\n\nCREATE THIS UI:\n{prompt}"

        try:
            if llm_type == "claude":
                result = await self._generate_with_claude(mockup.id, full_prompt, prompt)
            elif llm_type == "gemini":
                result = await self._generate_with_gemini(mockup.id, full_prompt, prompt)
            elif llm_type == "grok":
                result = await self._generate_with_grok(mockup.id, full_prompt, prompt)
            else:
                return MockupGenerationResult(
                    success=False,
                    error=f"Unsupported LLM type: {llm_type}",
                )

            if not result.success or not result.html:
                return result

            # Save to S3
            s3_result = await self._save_to_s3(mockup.id, result.html)

            return MockupGenerationResult(
                success=True,
                html=result.html,
                s3_html_url=s3_result.get("html"),
                s3_prompt_url=result.s3_prompt_url,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                llm_model=result.llm_model,
            )

        except Exception as e:
            logger.exception(f"Error generating mockup: {e}")
            return MockupGenerationResult(
                success=False,
                error=str(e),
            )

    async def modify_mockup(
        self,
        mockup: Mockup,
        modification_prompt: str,
        element_selector: str | None = None,
        current_html: str | None = None,
    ) -> MockupGenerationResult:
        """Modify an existing mockup based on user request.

        Args:
            mockup: The Mockup model instance
            modification_prompt: User's modification request
            element_selector: CSS selector of clicked element (optional)
            current_html: Current HTML content (fetched from S3 if not provided)

        Returns:
            MockupGenerationResult with modified code and S3 URLs
        """
        if not current_html:
            current_html = await self._fetch_from_s3(mockup.s3_html_url)
            if not current_html:
                return MockupGenerationResult(
                    success=False,
                    error="Could not fetch current mockup HTML from S3",
                )

        # Build element context if selector provided
        element_context = ""
        if element_selector:
            element_context = f"""
SELECTED ELEMENT:
CSS Selector: {element_selector}
The user clicked on this specific element to modify. Focus your changes on this element
while ensuring the rest of the page remains functional.
"""

        full_prompt = MODIFY_SYSTEM_PROMPT.format(
            current_html=current_html,
            element_context=element_context,
            modification_prompt=modification_prompt,
        )

        llm_type = mockup.llm_type or "claude"

        try:
            if llm_type == "claude":
                result = await self._generate_with_claude(
                    mockup.id, full_prompt, modification_prompt
                )
            elif llm_type == "gemini":
                result = await self._generate_with_gemini(
                    mockup.id, full_prompt, modification_prompt
                )
            elif llm_type == "grok":
                result = await self._generate_with_grok(mockup.id, full_prompt, modification_prompt)
            else:
                return MockupGenerationResult(
                    success=False,
                    error=f"Unsupported LLM type: {llm_type}",
                )

            if not result.success or not result.html:
                return result

            # Save modified version to S3
            s3_result = await self._save_to_s3(mockup.id, result.html)

            return MockupGenerationResult(
                success=True,
                html=result.html,
                s3_html_url=s3_result.get("html"),
                s3_prompt_url=result.s3_prompt_url,
                tokens_in=result.tokens_in,
                tokens_out=result.tokens_out,
                llm_model=result.llm_model,
            )

        except Exception as e:
            logger.exception(f"Error modifying mockup: {e}")
            return MockupGenerationResult(
                success=False,
                error=str(e),
            )

    async def _generate_with_claude(
        self,
        mockup_id: str,
        full_prompt: str,
        user_prompt: str,
    ) -> MockupGenerationResult:
        """Generate mockup using Claude CLI."""
        cli = ClaudeCLI(
            model="sonnet",  # Use Sonnet for faster generation
            s3_prefix="mockups/claude",
            timeout=120,
            skip_permissions=True,
        )

        result = await cli.run(
            prompt=full_prompt,
            operation_type="mockup",
            repo_name=f"mockup_{mockup_id[:8]}",
            context_id=f"mockup_{mockup_id}",
            save_prompt=True,
            save_output=True,
            track_operation=True,
        )

        if not result.success:
            return MockupGenerationResult(
                success=False,
                error=result.error or "Claude CLI failed",
                s3_prompt_url=result.s3_prompt_url,
            )

        # Extract HTML from output
        html = self._extract_html(result.output)
        if not html:
            return MockupGenerationResult(
                success=False,
                error="Could not extract HTML from Claude response",
                s3_prompt_url=result.s3_prompt_url,
            )

        # Calculate token usage
        tokens_in = sum(u.input_tokens for u in result.model_usage)
        tokens_out = sum(u.output_tokens for u in result.model_usage)

        return MockupGenerationResult(
            success=True,
            html=html,
            s3_prompt_url=result.s3_prompt_url,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            llm_model=result.model,
        )

    async def _generate_with_gemini(
        self,
        mockup_id: str,
        full_prompt: str,
        user_prompt: str,
    ) -> MockupGenerationResult:
        """Generate mockup using Gemini CLI."""
        try:
            from ...llm.gemini import GeminiCLI

            cli = GeminiCLI()
            result = await cli.run(
                full_prompt,
                operation_type="mockup",
                repo_name=f"mockup_{mockup_id[:8]}",
            )

            if not result.success:
                return MockupGenerationResult(
                    success=False,
                    error=result.error or "Gemini CLI failed",
                )

            html = self._extract_html(result.output)
            if not html:
                return MockupGenerationResult(
                    success=False,
                    error="Could not extract HTML from Gemini response",
                )

            return MockupGenerationResult(
                success=True,
                html=html,
                tokens_in=result.input_tokens,
                tokens_out=result.output_tokens,
                llm_model=result.model or "gemini",
            )

        except ImportError:
            return MockupGenerationResult(
                success=False,
                error="Gemini CLI not available",
            )

    async def _generate_with_grok(
        self,
        mockup_id: str,
        full_prompt: str,
        user_prompt: str,
    ) -> MockupGenerationResult:
        """Generate mockup using Grok CLI."""
        try:
            from ...llm.grok import GrokCLI

            cli = GrokCLI()
            result = await cli.run(
                full_prompt,
                operation_type="mockup",
                repo_name=f"mockup_{mockup_id[:8]}",
            )

            if not result.success:
                return MockupGenerationResult(
                    success=False,
                    error=result.error or "Grok CLI failed",
                )

            html = self._extract_html(result.output)
            if not html:
                return MockupGenerationResult(
                    success=False,
                    error="Could not extract HTML from Grok response",
                )

            return MockupGenerationResult(
                success=True,
                html=html,
                tokens_in=result.input_tokens,
                tokens_out=result.output_tokens,
                llm_model=result.model or "grok",
            )

        except ImportError:
            return MockupGenerationResult(
                success=False,
                error="Grok CLI not available",
            )

    def _extract_html(self, output: str) -> str | None:
        """Extract HTML from LLM output.

        Looks for ```html ... ``` blocks first, then tries to find
        a complete HTML document.
        """
        if not output:
            return None

        # Try to find ```html ... ``` block
        html_match = re.search(r"```html\s*([\s\S]*?)```", output, re.IGNORECASE)
        if html_match:
            html = html_match.group(1).strip()
            if html:
                return html

        # Try to find <!DOCTYPE or <html directly
        doc_match = re.search(
            r"(<!DOCTYPE html[\s\S]*</html>)",
            output,
            re.IGNORECASE,
        )
        if doc_match:
            return doc_match.group(1).strip()

        # Try just <html>...</html>
        html_tag_match = re.search(
            r"(<html[\s\S]*</html>)",
            output,
            re.IGNORECASE,
        )
        if html_tag_match:
            return html_tag_match.group(1).strip()

        return None

    async def _save_to_s3(
        self,
        mockup_id: str,
        html: str,
        css: str | None = None,
        js: str | None = None,
    ) -> dict[str, str | None]:
        """Save mockup files to S3.

        Returns dict with S3 URLs for each file type.
        """
        result: dict[str, str | None] = {"html": None, "css": None, "js": None}

        # Save HTML
        if html:
            url = await self._save_file_to_s3(mockup_id, html, "html", "text/html")
            result["html"] = url

        # Save CSS if separate
        if css:
            url = await self._save_file_to_s3(mockup_id, css, "css", "text/css")
            result["css"] = url

        # Save JS if separate
        if js:
            url = await self._save_file_to_s3(mockup_id, js, "js", "application/javascript")
            result["js"] = url

        return result

    async def _save_file_to_s3(
        self,
        mockup_id: str,
        content: str,
        file_type: str,
        content_type: str,
    ) -> str | None:
        """Save a single file to S3."""
        if not self.settings.thinking.s3_bucket:
            logger.warning("S3 bucket not configured, skipping upload")
            return None

        from datetime import datetime, timezone

        from botocore.exceptions import ClientError

        from ...utils.aws_clients import get_s3_client

        try:
            client = get_s3_client(region=self.settings.thinking.s3_region)

            timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d")
            s3_key = f"mockups/{timestamp}/{mockup_id}/mockup.{file_type}"

            await asyncio.to_thread(
                client.put_object,
                Bucket=self.settings.thinking.s3_bucket,
                Key=s3_key,
                Body=content.encode("utf-8"),
                ContentType=content_type,
            )

            # Build URL
            bucket_region = self.settings.thinking.s3_region
            s3_url = (
                f"https://{self.settings.thinking.s3_bucket}"
                f".s3.{bucket_region}.amazonaws.com/{s3_key}"
            )

            logger.info(f"[S3] Saved mockup {file_type} to {s3_key}")
            return s3_url

        except ClientError as e:
            logger.warning(f"[S3] Upload failed: {e}")
            return None

    async def _fetch_from_s3(self, s3_url: str | None) -> str | None:
        """Fetch content from S3 URL."""
        if not s3_url:
            return None

        from botocore.exceptions import ClientError

        from ...utils.aws_clients import get_s3_client

        try:
            # Parse S3 URL to get bucket and key
            # URL format: https://bucket.s3.region.amazonaws.com/key
            import re

            match = re.match(
                r"https://([^.]+)\.s3\.([^.]+)\.amazonaws\.com/(.+)",
                s3_url,
            )
            if not match:
                logger.warning(f"Invalid S3 URL format: {s3_url}")
                return None

            bucket, region, key = match.groups()
            client = get_s3_client(region=region)

            response = await asyncio.to_thread(
                client.get_object,
                Bucket=bucket,
                Key=key,
            )

            return response["Body"].read().decode("utf-8")

        except ClientError as e:
            logger.warning(f"[S3] Fetch failed: {e}")
            return None

    def get_project(self, project_id: str) -> MockupProject | None:
        """Get a mockup project by ID."""
        return (
            self.db.query(MockupProject)
            .filter(
                MockupProject.id == project_id,
                MockupProject.deleted_at.is_(None),
            )
            .first()
        )

    def get_mockup(self, mockup_id: str) -> Mockup | None:
        """Get a mockup by ID."""
        return (
            self.db.query(Mockup)
            .filter(
                Mockup.id == mockup_id,
                Mockup.deleted_at.is_(None),
            )
            .first()
        )


def get_mockup_service(db: Session) -> MockupService:
    """Factory function to create MockupService with dependencies."""
    return MockupService(db=db)
