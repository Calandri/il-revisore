"""TODO Manager for Fix Planning Phase.

Handles saving and loading of MasterTodo and IssueTodo files
for the fix planning and execution workflow.

Storage:
- Local: /tmp/fix_session_{session_id}/
- S3: s3://turbowrap-thinking/fix-todos/{session_id}/
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError

from turbowrap.config import get_settings
from turbowrap.utils.aws_clients import get_s3_client

from .models import IssueTodo, MasterTodo

logger = logging.getLogger(__name__)

# Constants
S3_BUCKET = "turbowrap-thinking"
S3_PREFIX = "fix-todos"
LOCAL_BASE_PATH = Path("/tmp")


class TodoManager:
    """Manager for saving and loading TODO files.

    Saves to both local filesystem and S3 for redundancy.
    Loads from local first, falls back to S3 if not found.
    """

    def __init__(self, session_id: str):
        """Initialize TodoManager.

        Args:
            session_id: Fix session ID for organizing files
        """
        self.session_id = session_id
        self.settings = get_settings()
        self._s3_client: Any = None

        # Local directory
        self.local_dir = LOCAL_BASE_PATH / f"fix_session_{session_id}"
        self.local_dir.mkdir(parents=True, exist_ok=True)

    @property
    def s3_client(self) -> Any:
        """Lazy-load S3 client."""
        if self._s3_client is None:
            self._s3_client = get_s3_client(region=self.settings.aws.region)
        return self._s3_client

    @property
    def s3_bucket(self) -> str:
        """Get S3 bucket name."""
        return self.settings.thinking.s3_bucket or S3_BUCKET

    def _s3_key(self, filename: str) -> str:
        """Generate S3 key for a file."""
        return f"{S3_PREFIX}/{self.session_id}/{filename}"

    # =========================================================================
    # Save Methods
    # =========================================================================

    async def save_master_todo(self, master_todo: MasterTodo) -> tuple[Path, str | None]:
        """Save MasterTodo to local and S3.

        Args:
            master_todo: MasterTodo object to save

        Returns:
            Tuple of (local_path, s3_url or None if S3 failed)
        """
        filename = "master_todo.json"
        data = master_todo.model_dump(mode="json")

        # Save locally
        local_path = self.local_dir / filename
        local_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info(f"[TODO] Saved master_todo to {local_path}")

        # Save to S3
        s3_url = await self._save_to_s3(filename, data)

        return local_path, s3_url

    async def save_issue_todo(self, issue_todo: IssueTodo) -> tuple[Path, str | None]:
        """Save IssueTodo to local and S3.

        Args:
            issue_todo: IssueTodo object to save

        Returns:
            Tuple of (local_path, s3_url or None if S3 failed)
        """
        filename = f"fix_todo_{issue_todo.issue_code}.json"
        data = issue_todo.model_dump(mode="json")

        # Save locally
        local_path = self.local_dir / filename
        local_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info(f"[TODO] Saved issue_todo for {issue_todo.issue_code} to {local_path}")

        # Save to S3
        s3_url = await self._save_to_s3(filename, data)

        return local_path, s3_url

    async def save_all(
        self, master_todo: MasterTodo, issue_todos: list[IssueTodo]
    ) -> dict[str, Path]:
        """Save MasterTodo and all IssueTodos.

        Args:
            master_todo: MasterTodo to save
            issue_todos: List of IssueTodos to save

        Returns:
            Dict mapping issue codes to their local paths
        """
        paths: dict[str, Path] = {}

        # Save master TODO
        master_path, _ = await self.save_master_todo(master_todo)
        paths["master"] = master_path

        # Save issue TODOs in parallel
        tasks = [self.save_issue_todo(todo) for todo in issue_todos]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for todo, result in zip(issue_todos, results, strict=True):
            if isinstance(result, Exception):
                logger.error(f"[TODO] Failed to save {todo.issue_code}: {result}")
            else:
                local_path, _ = result
                paths[todo.issue_code] = local_path

        logger.info(f"[TODO] Saved {len(paths)} TODO files for session {self.session_id}")
        return paths

    async def _save_to_s3(self, filename: str, data: dict[str, Any]) -> str | None:
        """Save JSON data to S3.

        Args:
            filename: Filename for the S3 object
            data: Dictionary to serialize as JSON

        Returns:
            S3 URL if successful, None otherwise
        """
        if not self.s3_bucket:
            return None

        s3_key = self._s3_key(filename)
        try:
            json_content = json.dumps(data, indent=2, ensure_ascii=False)
            await asyncio.to_thread(
                self.s3_client.put_object,
                Bucket=self.s3_bucket,
                Key=s3_key,
                Body=json_content.encode("utf-8"),
                ContentType="application/json",
            )
            s3_url = f"s3://{self.s3_bucket}/{s3_key}"
            logger.info(f"[TODO] Saved to S3: {s3_url}")
            return s3_url
        except ClientError as e:
            logger.warning(f"[TODO] S3 upload failed for {filename}: {e}")
            return None

    # =========================================================================
    # Load Methods
    # =========================================================================

    async def load_master_todo(self) -> MasterTodo | None:
        """Load MasterTodo from local or S3.

        Returns:
            MasterTodo if found, None otherwise
        """
        filename = "master_todo.json"
        data = await self._load_json(filename)
        if data:
            return MasterTodo.model_validate(data)
        return None

    async def load_issue_todo(self, issue_code: str) -> IssueTodo | None:
        """Load IssueTodo from local or S3.

        Args:
            issue_code: Issue code (e.g., "BE-001")

        Returns:
            IssueTodo if found, None otherwise
        """
        filename = f"fix_todo_{issue_code}.json"
        data = await self._load_json(filename)
        if data:
            return IssueTodo.model_validate(data)
        return None

    async def load_all_issue_todos(self, issue_codes: list[str]) -> dict[str, IssueTodo]:
        """Load multiple IssueTodos in parallel.

        Args:
            issue_codes: List of issue codes to load

        Returns:
            Dict mapping issue codes to IssueTodo objects
        """
        tasks = [self.load_issue_todo(code) for code in issue_codes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        todos: dict[str, IssueTodo] = {}
        for code, result in zip(issue_codes, results, strict=True):
            if isinstance(result, BaseException):
                logger.error(f"[TODO] Failed to load {code}: {result}")
            elif isinstance(result, IssueTodo):
                todos[code] = result
            elif result is None:
                logger.warning(f"[TODO] Not found: {code}")

        return todos

    async def _load_json(self, filename: str) -> dict[str, Any] | None:
        """Load JSON from local or S3.

        Args:
            filename: Filename to load

        Returns:
            Parsed JSON dict if found, None otherwise
        """
        # Try local first
        local_path = self.local_dir / filename
        if local_path.exists():
            try:
                data = json.loads(local_path.read_text())
                logger.debug(f"[TODO] Loaded from local: {local_path}")
                return data
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"[TODO] Failed to load local {filename}: {e}")

        # Fall back to S3
        return await self._load_from_s3(filename)

    async def _load_from_s3(self, filename: str) -> dict[str, Any] | None:
        """Load JSON from S3.

        Args:
            filename: Filename to load

        Returns:
            Parsed JSON dict if found, None otherwise
        """
        if not self.s3_bucket:
            return None

        s3_key = self._s3_key(filename)
        try:
            response = await asyncio.to_thread(
                self.s3_client.get_object,
                Bucket=self.s3_bucket,
                Key=s3_key,
            )
            content = response["Body"].read().decode("utf-8")
            data = json.loads(content)
            logger.info(f"[TODO] Loaded from S3: s3://{self.s3_bucket}/{s3_key}")
            return data
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.debug(f"[TODO] Not found in S3: {s3_key}")
            else:
                logger.warning(f"[TODO] S3 load failed for {filename}: {e}")
            return None

    # =========================================================================
    # Utility Methods
    # =========================================================================

    def get_local_path(self, issue_code: str | None = None) -> Path:
        """Get local path for a TODO file.

        Args:
            issue_code: Issue code, or None for master_todo

        Returns:
            Path to the local file
        """
        if issue_code:
            return self.local_dir / f"fix_todo_{issue_code}.json"
        return self.local_dir / "master_todo.json"

    async def cleanup(self) -> None:
        """Clean up local TODO files for this session."""
        import shutil

        if self.local_dir.exists():
            shutil.rmtree(self.local_dir)
            logger.info(f"[TODO] Cleaned up local directory: {self.local_dir}")

    def exists_locally(self) -> bool:
        """Check if master_todo.json exists locally."""
        return (self.local_dir / "master_todo.json").exists()
