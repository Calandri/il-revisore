"""
Integration tests for Gemini Vision screenshot analysis.

Run with: uv run pytest tests/integrations/test_gemini_vision.py -v

These tests verify Gemini Vision API integration.
The actual API tests require a valid GOOGLE_AI_API_KEY and are marked as e2e.
"""

from unittest.mock import MagicMock, patch

import pytest

# =============================================================================
# Unit Tests (Mocked)
# =============================================================================


@pytest.mark.unit
class TestGeminiVisionClient:
    """Unit tests for GeminiProClient with mocked API."""

    def test_client_initialization(self):
        """GeminiProClient should initialize correctly."""
        with patch("turbowrap.llm.gemini.genai") as mock_genai:
            mock_genai.GenerativeModel.return_value = MagicMock()

            from turbowrap.llm.gemini import GeminiProClient

            client = GeminiProClient()
            assert client is not None

    def test_analyze_screenshots_returns_string(self):
        """analyze_screenshots should return analysis string."""
        with patch("turbowrap.llm.gemini.genai") as mock_genai:
            mock_model = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "Analysis result: Button alignment issue found"
            mock_model.generate_content.return_value = mock_response
            mock_genai.GenerativeModel.return_value = mock_model

            from turbowrap.llm.gemini import GeminiProClient

            client = GeminiProClient()

            # Mock image loading
            with patch.object(client, "_load_images", return_value=[MagicMock()]):
                result = client.analyze_screenshots(
                    ["/fake/path.png"], {"title": "Test", "description": "Test issue"}
                )

            assert isinstance(result, str)
            assert len(result) > 0


# =============================================================================
# E2E Tests (Real API - Skipped by default)
# =============================================================================


@pytest.mark.e2e
@pytest.mark.skip(reason="Requires GOOGLE_AI_API_KEY and real screenshot files")
class TestGeminiVisionE2E:
    """E2E tests that hit the real Gemini API."""

    def test_real_screenshot_analysis(self, tmp_path):
        """Test with real API (requires GOOGLE_AI_API_KEY)."""
        from turbowrap.llm.gemini import GeminiProClient

        # Create a test image (1x1 pixel PNG)
        test_image = tmp_path / "test.png"
        # Minimal PNG file bytes
        test_image.write_bytes(
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
            b"\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00"
            b"\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )

        client = GeminiProClient()
        result = client.analyze_screenshots(
            [str(test_image)], {"title": "Test", "description": "Test analysis"}
        )

        assert isinstance(result, str)
        assert len(result) > 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
