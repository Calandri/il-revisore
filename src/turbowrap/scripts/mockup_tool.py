#!/usr/bin/env python3
"""CLI tool for mockup operations.

Called by LLM to init/save mockups without using HTTP API.

Usage:
    python scripts/mockup_tool.py init --project-id UUID --name "Name" --description "Desc" --type page
    python scripts/mockup_tool.py save --mockup-id UUID --html-file path/to/file.html
    python scripts/mockup_tool.py fail --mockup-id UUID --error "Error message"
"""

import argparse
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from turbowrap.db.models import Mockup, MockupProject, MockupStatus  # noqa: E402
from turbowrap.db.session import get_session_local  # noqa: E402


def _notify_change(event_type: str, mockup_id: str, project_id: str | None = None) -> None:
    """Notify the frontend of a mockup change via SSE."""
    import urllib.parse
    import urllib.request

    try:
        params = urllib.parse.urlencode(
            {
                "event_type": event_type,
                "mockup_id": mockup_id,
                "project_id": project_id or "",
            }
        )
        url = f"http://127.0.0.1:8000/api/mockups/notify?{params}"
        req = urllib.request.Request(url, method="POST")  # noqa: S310
        urllib.request.urlopen(req, timeout=2).close()  # noqa: S310
    except Exception as e:
        # Don't fail if notification fails
        print(f"[INFO] Could not notify frontend: {e}")


def init_mockup(
    project_id: str,
    name: str,
    description: str | None = None,
    component_type: str = "page",
    llm_type: str = "claude",
) -> dict:
    """Initialize a mockup with 'generating' status."""
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        # Verify project exists
        project = (
            db.query(MockupProject)
            .filter(MockupProject.id == project_id, MockupProject.deleted_at.is_(None))
            .first()
        )
        if not project:
            return {"success": False, "error": f"Project not found: {project_id}"}

        # Create mockup
        mockup = Mockup(
            project_id=project_id,
            name=name,
            description=description,
            component_type=component_type,
            llm_type=llm_type,
            status=MockupStatus.GENERATING.value,
        )
        db.add(mockup)
        db.commit()
        db.refresh(mockup)

        # Notify frontend
        _notify_change("init", mockup.id, project_id)

        return {
            "success": True,
            "mockup_id": mockup.id,
            "status": "generating",
            "message": f"Mockup '{name}' initialized. Use 'save' command when HTML is ready.",
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def save_mockup(
    mockup_id: str,
    html_file: str,
    llm_model: str | None = None,
) -> dict:
    """Save HTML content to mockup and upload to S3."""
    from datetime import datetime, timezone

    from turbowrap.config import get_settings

    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        # Read HTML file
        html_path = Path(html_file)
        if not html_path.exists():
            return {"success": False, "error": f"HTML file not found: {html_file}"}

        html_content = html_path.read_text(encoding="utf-8")

        # Get mockup
        mockup = (
            db.query(Mockup).filter(Mockup.id == mockup_id, Mockup.deleted_at.is_(None)).first()
        )
        if not mockup:
            return {"success": False, "error": f"Mockup not found: {mockup_id}"}

        # Upload to S3
        settings = get_settings()
        s3_url = None

        if settings.thinking.s3_bucket:
            try:
                import boto3

                client = boto3.client("s3", region_name=settings.thinking.s3_region)
                timestamp = datetime.now(timezone.utc).strftime("%Y/%m/%d")
                s3_key = f"mockups/{timestamp}/{mockup_id}/mockup.html"

                client.put_object(
                    Bucket=settings.thinking.s3_bucket,
                    Key=s3_key,
                    Body=html_content.encode("utf-8"),
                    ContentType="text/html",
                )

                s3_url = (
                    f"https://{settings.thinking.s3_bucket}"
                    f".s3.{settings.thinking.s3_region}.amazonaws.com/{s3_key}"
                )
            except Exception as e:
                # S3 upload failed, but we can still save locally
                print(f"[WARNING] S3 upload failed: {e}")

        # Update mockup
        mockup.s3_html_url = s3_url
        mockup.status = MockupStatus.COMPLETED.value
        if llm_model:
            mockup.llm_model = llm_model

        project_id = mockup.project_id
        db.commit()

        # Notify frontend
        _notify_change("save", mockup_id, project_id)

        return {
            "success": True,
            "mockup_id": mockup_id,
            "status": "completed",
            "s3_url": s3_url,
            "message": "Mockup saved! View at /mockups page.",
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def fail_mockup(mockup_id: str, error: str) -> dict:
    """Mark mockup as failed."""
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        mockup = (
            db.query(Mockup).filter(Mockup.id == mockup_id, Mockup.deleted_at.is_(None)).first()
        )
        if not mockup:
            return {"success": False, "error": f"Mockup not found: {mockup_id}"}

        mockup.status = MockupStatus.FAILED.value
        mockup.error_message = error
        db.commit()

        return {
            "success": True,
            "mockup_id": mockup_id,
            "status": "failed",
            "message": "Mockup marked as failed.",
        }

    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Mockup CLI tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Init command
    init_parser = subparsers.add_parser("init", help="Initialize a new mockup")
    init_parser.add_argument("--project-id", required=True, help="Project UUID")
    init_parser.add_argument("--name", required=True, help="Mockup name")
    init_parser.add_argument("--description", help="Mockup description")
    init_parser.add_argument(
        "--type",
        default="page",
        choices=["page", "component", "modal", "form", "table"],
        help="Component type",
    )
    init_parser.add_argument("--llm", default="claude", help="LLM type")

    # Save command
    save_parser = subparsers.add_parser("save", help="Save mockup HTML")
    save_parser.add_argument("--mockup-id", required=True, help="Mockup UUID")
    save_parser.add_argument("--html-file", required=True, help="Path to HTML file")
    save_parser.add_argument("--llm-model", help="LLM model used")

    # Fail command
    fail_parser = subparsers.add_parser("fail", help="Mark mockup as failed")
    fail_parser.add_argument("--mockup-id", required=True, help="Mockup UUID")
    fail_parser.add_argument("--error", required=True, help="Error message")

    args = parser.parse_args()

    if args.command == "init":
        result = init_mockup(
            project_id=args.project_id,
            name=args.name,
            description=args.description,
            component_type=args.type,
            llm_type=args.llm,
        )
    elif args.command == "save":
        result = save_mockup(
            mockup_id=args.mockup_id,
            html_file=args.html_file,
            llm_model=args.llm_model,
        )
    elif args.command == "fail":
        result = fail_mockup(
            mockup_id=args.mockup_id,
            error=args.error,
        )

    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("success") else 1)


if __name__ == "__main__":
    main()
