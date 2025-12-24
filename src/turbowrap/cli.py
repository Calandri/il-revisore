"""TurboWrap CLI with Typer."""

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import get_settings
from .db.session import init_db, get_session_local

app = typer.Typer(
    name="turbowrap",
    help="TurboWrap - AI-Powered Repository Orchestrator",
    add_completion=False,
)
console = Console()

# Sub-commands
repo_app = typer.Typer(help="Repository management")
app.add_typer(repo_app, name="repo")


# ============================================================================
# Repository Commands
# ============================================================================

@repo_app.command("clone")
def repo_clone(
    url: str = typer.Argument(..., help="GitHub repository URL"),
    branch: str = typer.Option("main", "--branch", "-b", help="Branch to clone"),
):
    """Clone a GitHub repository."""
    from .core.repo_manager import RepoManager

    init_db()
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        manager = RepoManager(db)
        console.print(f"[bold blue]Cloning[/] {url}...")

        repo = manager.clone(url, branch)

        console.print(f"[bold green]✓[/] Cloned to: {repo.local_path}")
        console.print(f"  ID: {repo.id}")
        console.print(f"  Type: {repo.repo_type}")
    except Exception as e:
        console.print(f"[bold red]✗[/] Error: {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@repo_app.command("list")
def repo_list(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
):
    """List all repositories."""
    from .core.repo_manager import RepoManager

    init_db()
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        manager = RepoManager(db)
        repos = manager.list(status=status)

        if not repos:
            console.print("[yellow]No repositories found.[/]")
            return

        table = Table(title="Repositories")
        table.add_column("ID", style="dim")
        table.add_column("Name")
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Last Synced")

        for repo in repos:
            synced = repo.last_synced_at.strftime("%Y-%m-%d %H:%M") if repo.last_synced_at else "-"
            table.add_row(
                repo.id[:8],
                repo.name,
                repo.repo_type or "-",
                repo.status,
                synced,
            )

        console.print(table)
    finally:
        db.close()


@repo_app.command("sync")
def repo_sync(
    repo_id: str = typer.Argument(..., help="Repository ID (or prefix)"),
):
    """Sync (pull) a repository."""
    from .core.repo_manager import RepoManager

    init_db()
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        manager = RepoManager(db)

        # Find repo by prefix
        repos = manager.list()
        matched = [r for r in repos if r.id.startswith(repo_id)]

        if not matched:
            console.print(f"[bold red]✗[/] Repository not found: {repo_id}")
            raise typer.Exit(1)

        if len(matched) > 1:
            console.print(f"[bold red]✗[/] Ambiguous ID, matches: {[r.id[:8] for r in matched]}")
            raise typer.Exit(1)

        repo = matched[0]
        console.print(f"[bold blue]Syncing[/] {repo.name}...")

        manager.sync(repo.id)
        console.print(f"[bold green]✓[/] Synced successfully")
    except Exception as e:
        console.print(f"[bold red]✗[/] Error: {e}")
        raise typer.Exit(1)
    finally:
        db.close()


@repo_app.command("remove")
def repo_remove(
    repo_id: str = typer.Argument(..., help="Repository ID (or prefix)"),
    keep_local: bool = typer.Option(False, "--keep-local", help="Keep local files"),
):
    """Remove a repository."""
    from .core.repo_manager import RepoManager

    init_db()
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        manager = RepoManager(db)

        # Find repo by prefix
        repos = manager.list()
        matched = [r for r in repos if r.id.startswith(repo_id)]

        if not matched:
            console.print(f"[bold red]✗[/] Repository not found: {repo_id}")
            raise typer.Exit(1)

        repo = matched[0]

        if not typer.confirm(f"Remove {repo.name}?"):
            raise typer.Abort()

        manager.delete(repo.id, delete_local=not keep_local)
        console.print(f"[bold green]✓[/] Removed {repo.name}")
    finally:
        db.close()


# ============================================================================
# Task Commands
# ============================================================================

@app.command("review")
def run_review(
    repo_id: str = typer.Argument(..., help="Repository ID (or prefix)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output directory"),
    max_workers: int = typer.Option(3, "--max-workers", "-w", help="Max parallel workers"),
):
    """Run code review on a repository."""
    from .core.repo_manager import RepoManager
    from .tasks import ReviewTask, TaskContext

    init_db()
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        manager = RepoManager(db)

        # Find repo
        repos = manager.list()
        matched = [r for r in repos if r.id.startswith(repo_id)]

        if not matched:
            console.print(f"[bold red]✗[/] Repository not found: {repo_id}")
            raise typer.Exit(1)

        repo = matched[0]
        repo_path = Path(repo.local_path)

        console.print("=" * 60)
        console.print("[bold blue]TurboWrap[/] - Code Review")
        console.print("=" * 60)
        console.print(f"  Repository: {repo.name}")
        console.print(f"  Path: {repo_path}")
        console.print("=" * 60)

        # Run review task
        task = ReviewTask()
        context = TaskContext(
            db=db,
            repo_path=repo_path,
            config={
                "repository_id": repo.id,
                "max_workers": max_workers,
            },
        )

        console.print("\n[bold]Running review...[/]")
        result = task.execute(context)

        if result.status == "completed":
            console.print(f"\n[bold green]✓[/] Review completed in {result.duration_seconds:.2f}s")

            # Generate report
            output_dir = output or (repo_path / ".reviews")
            report_path = task.generate_report(result, output_dir)
            console.print(f"  Report: {report_path}")
        else:
            console.print(f"\n[bold red]✗[/] Review failed: {result.error}")
            raise typer.Exit(1)

    finally:
        db.close()


@app.command("develop")
def run_develop(
    repo_id: str = typer.Argument(..., help="Repository ID (or prefix)"),
    instruction: str = typer.Option(..., "--instruction", "-i", help="Development instruction"),
    files: Optional[list[str]] = typer.Option(None, "--file", "-f", help="Target files"),
):
    """Run AI-assisted development on a repository."""
    from .core.repo_manager import RepoManager
    from .tasks import DevelopTask, TaskContext

    init_db()
    SessionLocal = get_session_local()
    db = SessionLocal()

    try:
        manager = RepoManager(db)

        # Find repo
        repos = manager.list()
        matched = [r for r in repos if r.id.startswith(repo_id)]

        if not matched:
            console.print(f"[bold red]✗[/] Repository not found: {repo_id}")
            raise typer.Exit(1)

        repo = matched[0]
        repo_path = Path(repo.local_path)

        console.print("=" * 60)
        console.print("[bold blue]TurboWrap[/] - Development")
        console.print("=" * 60)
        console.print(f"  Repository: {repo.name}")
        console.print(f"  Instruction: {instruction}")
        console.print("=" * 60)

        # Run develop task
        task = DevelopTask()
        context = TaskContext(
            db=db,
            repo_path=repo_path,
            config={
                "repository_id": repo.id,
                "instruction": instruction,
                "files": files or [],
            },
        )

        console.print("\n[bold]Running development...[/]")
        result = task.execute(context)

        if result.status == "completed":
            console.print(f"\n[bold green]✓[/] Development completed in {result.duration_seconds:.2f}s")

            # Print result
            if result.data.get("development"):
                console.print("\n[bold]Development Result:[/]")
                console.print(result.data["development"][:2000])
        else:
            console.print(f"\n[bold red]✗[/] Development failed: {result.error}")
            raise typer.Exit(1)

    finally:
        db.close()


# ============================================================================
# Server Command
# ============================================================================

@app.command("serve")
def serve(
    host: str = typer.Option("0.0.0.0", "--host", "-h", help="Server host"),
    port: int = typer.Option(8000, "--port", "-p", help="Server port"),
    reload: bool = typer.Option(False, "--reload", help="Enable auto-reload"),
):
    """Start the API server."""
    import uvicorn

    init_db()

    console.print("=" * 60)
    console.print("[bold blue]TurboWrap[/] - API Server")
    console.print("=" * 60)
    console.print(f"  URL: http://{host}:{port}")
    console.print(f"  Docs: http://{host}:{port}/docs")
    console.print("=" * 60)

    uvicorn.run(
        "turbowrap.api.main:app",
        host=host,
        port=port,
        reload=reload,
    )


# ============================================================================
# Status Command
# ============================================================================

@app.command("status")
def status():
    """Show TurboWrap status."""
    settings = get_settings()

    console.print("=" * 60)
    console.print("[bold blue]TurboWrap[/] - Status")
    console.print("=" * 60)

    # Check agents
    gemini_ok = "✓" if settings.agents.effective_google_key else "✗"
    claude_ok = "✓" if settings.agents.anthropic_api_key else "✗"

    console.print(f"\n[bold]Agents:[/]")
    console.print(f"  [{gemini_ok}] Gemini Flash ({settings.agents.gemini_model})")
    console.print(f"  [{claude_ok}] Claude Opus ({settings.agents.claude_model})")

    # Show paths
    console.print(f"\n[bold]Paths:[/]")
    console.print(f"  Repos: {settings.repos_dir}")
    console.print(f"  Agents: {settings.agents_dir}")

    # Show DB
    console.print(f"\n[bold]Database:[/]")
    console.print(f"  {settings.database.url}")


@app.command("check")
def check():
    """Check API keys and connectivity."""
    settings = get_settings()

    console.print("[bold]Checking API keys...[/]\n")

    # Check Gemini
    if settings.agents.effective_google_key:
        try:
            from .llm import GeminiClient
            client = GeminiClient()
            result = client.generate("Say 'ok' if you can hear me.")
            console.print(f"[bold green]✓[/] Gemini: Connected ({settings.agents.gemini_model})")
        except Exception as e:
            console.print(f"[bold red]✗[/] Gemini: {e}")
    else:
        console.print("[bold yellow]![/] Gemini: GOOGLE_API_KEY not set")

    # Check Claude
    if settings.agents.anthropic_api_key:
        try:
            from .llm import ClaudeClient
            client = ClaudeClient()
            result = client.generate("Say 'ok' if you can hear me.")
            console.print(f"[bold green]✓[/] Claude: Connected ({settings.agents.claude_model})")
        except Exception as e:
            console.print(f"[bold red]✗[/] Claude: {e}")
    else:
        console.print("[bold yellow]![/] Claude: ANTHROPIC_API_KEY not set")


# ============================================================================
# Main
# ============================================================================

def main():
    """CLI entry point."""
    app()


if __name__ == "__main__":
    main()
