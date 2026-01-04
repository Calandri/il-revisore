#!/usr/bin/env python3
"""CLI tool for managing Widget API keys.

Usage:
    python -m turbowrap.scripts.widget_keys create --name "3Bee Website" --origin "https://3bee.com"
    python -m turbowrap.scripts.widget_keys list
    python -m turbowrap.scripts.widget_keys revoke <key_prefix>
    python -m turbowrap.scripts.widget_keys info <key_prefix>
"""

import argparse
import hashlib
import secrets
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from turbowrap.db.models import WidgetApiKey  # noqa: E402
from turbowrap.db.session import get_session_local  # noqa: E402


def generate_api_key() -> tuple[str, str, str]:
    """Generate a new API key.

    Returns:
        (raw_key, key_hash, key_prefix)
    """
    # Generate 32 random bytes, encode as hex (64 chars)
    random_part = secrets.token_hex(16)  # 32 hex chars
    raw_key = f"twk_{random_part}"
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    key_prefix = raw_key[:8]  # "twk_xxxx"

    return raw_key, key_hash, key_prefix


def cmd_create(args: argparse.Namespace) -> int:
    """Create a new API key."""
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        # Generate key
        raw_key, key_hash, key_prefix = generate_api_key()

        # Parse allowed origins
        allowed_origins = None
        if args.origin:
            allowed_origins = [o.strip() for o in args.origin.split(",")]

        # Create record
        widget_key = WidgetApiKey(
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=args.name,
            allowed_origins=allowed_origins,
            repository_id=args.repository_id,
            team_id=args.team_id,
            is_active=True,
        )

        db.add(widget_key)
        db.commit()
        db.refresh(widget_key)

        print("\n" + "=" * 60)
        print("API KEY CREATED SUCCESSFULLY")
        print("=" * 60)
        print(f"\nName: {args.name}")
        print(f"ID: {widget_key.id}")
        print(f"Prefix: {key_prefix}")
        if allowed_origins:
            print(f"Allowed Origins: {', '.join(allowed_origins)}")
        if args.repository_id:
            print(f"Repository ID: {args.repository_id}")
        if args.team_id:
            print(f"Team ID: {args.team_id}")

        print("\n" + "-" * 60)
        print("YOUR API KEY (SAVE THIS - IT WON'T BE SHOWN AGAIN):")
        print("-" * 60)
        print(f"\n  {raw_key}\n")
        print("-" * 60)
        print("\nUse this key in the X-Widget-Key header for API requests.")
        print("=" * 60 + "\n")

        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_list(args: argparse.Namespace) -> int:
    """List all API keys."""
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        query = db.query(WidgetApiKey).order_by(WidgetApiKey.created_at.desc())

        if not args.all:
            query = query.filter(WidgetApiKey.is_active.is_(True))

        keys = query.all()

        if not keys:
            print("No API keys found.")
            return 0

        print("\nWidget API Keys:")
        print("-" * 80)
        print(f"{'Prefix':<10} {'Name':<25} {'Active':<8} {'Last Used':<20} {'Origins'}")
        print("-" * 80)

        for key in keys:
            last_used = key.last_used_at.strftime("%Y-%m-%d %H:%M") if key.last_used_at else "Never"
            origins = ", ".join(key.allowed_origins[:2]) if key.allowed_origins else "Any"
            if key.allowed_origins and len(key.allowed_origins) > 2:
                origins += f" (+{len(key.allowed_origins) - 2})"

            status = "Yes" if key.is_active else "No"
            print(f"{key.key_prefix:<10} {key.name[:24]:<25} {status:<8} {last_used:<20} {origins}")

        print("-" * 80)
        print(f"Total: {len(keys)} key(s)")

        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_revoke(args: argparse.Namespace) -> int:
    """Revoke an API key."""
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        key = db.query(WidgetApiKey).filter(WidgetApiKey.key_prefix == args.key_prefix).first()

        if not key:
            print(f"ERROR: Key with prefix '{args.key_prefix}' not found.", file=sys.stderr)
            return 1

        if not key.is_active:
            print(f"Key '{args.key_prefix}' is already revoked.")
            return 0

        key.is_active = False
        db.commit()

        print(f"Key '{args.key_prefix}' ({key.name}) has been revoked.")
        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


def cmd_info(args: argparse.Namespace) -> int:
    """Show detailed info for an API key."""
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        key = db.query(WidgetApiKey).filter(WidgetApiKey.key_prefix == args.key_prefix).first()

        if not key:
            print(f"ERROR: Key with prefix '{args.key_prefix}' not found.", file=sys.stderr)
            return 1

        print(f"\nAPI Key Details: {key.key_prefix}")
        print("-" * 40)
        print(f"ID:              {key.id}")
        print(f"Name:            {key.name}")
        print(f"Active:          {'Yes' if key.is_active else 'No'}")
        print(f"Created:         {key.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
        print(
            f"Last Used:       {key.last_used_at.strftime('%Y-%m-%d %H:%M:%S') if key.last_used_at else 'Never'}"
        )
        print(
            f"Expires:         {key.expires_at.strftime('%Y-%m-%d %H:%M:%S') if key.expires_at else 'Never'}"
        )
        print(f"Repository ID:   {key.repository_id or 'Not set'}")
        print(f"Team ID:         {key.team_id or 'Not set'}")
        print(
            f"Allowed Origins: {', '.join(key.allowed_origins) if key.allowed_origins else 'Any'}"
        )
        print("-" * 40)

        return 0

    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    finally:
        db.close()


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Manage Widget API keys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Create command
    create_parser = subparsers.add_parser("create", help="Create a new API key")
    create_parser.add_argument(
        "--name", "-n", required=True, help="Key name (e.g., '3Bee Website')"
    )
    create_parser.add_argument(
        "--origin",
        "-o",
        help="Allowed origins (comma-separated, e.g., 'https://3bee.com,https://app.3bee.com')",
    )
    create_parser.add_argument("--repository-id", "-r", help="Default repository ID")
    create_parser.add_argument("--team-id", "-t", help="Default Linear team ID")

    # List command
    list_parser = subparsers.add_parser("list", help="List all API keys")
    list_parser.add_argument("--all", "-a", action="store_true", help="Include revoked keys")

    # Revoke command
    revoke_parser = subparsers.add_parser("revoke", help="Revoke an API key")
    revoke_parser.add_argument("key_prefix", help="Key prefix (e.g., 'twk_abc1')")

    # Info command
    info_parser = subparsers.add_parser("info", help="Show key details")
    info_parser.add_argument("key_prefix", help="Key prefix (e.g., 'twk_abc1')")

    args = parser.parse_args()

    if args.command == "create":
        return cmd_create(args)
    if args.command == "list":
        return cmd_list(args)
    if args.command == "revoke":
        return cmd_revoke(args)
    if args.command == "info":
        return cmd_info(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
