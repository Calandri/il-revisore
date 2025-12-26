"""TurboWrap CLI with Typer."""

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .config import get_settings
from .db.session import get_session_local, init_db

app = typer.Typer(
    name="turbowrap",
    help="TurboWrap - AI-Powered Repository Orchestrator",
    add_completion=False,
)
console = Console()

# Sub-commands
repo_app = typer.Typer(help="Repository management")
app.add_typer(repo_app, name="repo")


def _check_api_keys(require_claude: bool = False, require_gemini: bool = False) -> bool:
    """Check if required API keys are configured.

    Args:
        require_claude: Require ANTHROPIC_API_KEY.
        require_gemini: Require GOOGLE_API_KEY.

    Returns:
        True if all required keys present, False otherwise.
        Also prints helpful error messages.
    """
    settings = get_settings()
    missing = []

    if require_claude and not settings.agents.anthropic_api_key:
        missing.append(("ANTHROPIC_API_KEY", "Claude Opus (code review)"))

    if require_gemini and not settings.agents.effective_google_key:
        missing.append(("GOOGLE_API_KEY", "Gemini Flash (challenger)"))

    if missing:
        console.print("\n[bold red]✗ Missing API keys:[/]")
        for key, purpose in missing:
            console.print(f"  • {key} - Required for {purpose}")
        console.print("\n[dim]Set these environment variables and try again.[/]")
        console.print("[dim]Example: export ANTHROPIC_API_KEY=sk-ant-...[/]")
        return False

    return True


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
    status: str | None = typer.Option(None, "--status", "-s", help="Filter by status"),
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
        console.print("[bold green]✓[/] Synced successfully")
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
    output: Path | None = typer.Option(None, "--output", "-o", help="Output directory"),
    max_workers: int = typer.Option(3, "--max-workers", "-w", help="Max parallel workers"),
):
    """Run code review on a repository."""
    from .core.repo_manager import RepoManager
    from .tasks import ReviewTask, TaskContext

    # Check API keys before starting
    if not _check_api_keys(require_claude=True, require_gemini=True):
        raise typer.Exit(1)

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
    files: list[str] | None = typer.Option(None, "--file", "-f", help="Target files"),
):
    """Run AI-assisted development on a repository."""
    from .core.repo_manager import RepoManager
    from .tasks import DevelopTask, TaskContext

    # Check API keys before starting (develop uses Claude)
    if not _check_api_keys(require_claude=True):
        raise typer.Exit(1)

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

    console.print("\n[bold]Agents:[/]")
    console.print(f"  [{gemini_ok}] Gemini Flash ({settings.agents.gemini_model})")
    console.print(f"  [{claude_ok}] Claude Opus ({settings.agents.claude_model})")

    # Show paths
    console.print("\n[bold]Paths:[/]")
    console.print(f"  Repos: {settings.repos_dir}")
    console.print(f"  Agents: {settings.agents_dir}")

    # Show DB
    console.print("\n[bold]Database:[/]")
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
            client.generate("Say 'ok' if you can hear me.")
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
            client.generate("Say 'ok' if you can hear me.")
            console.print(f"[bold green]✓[/] Claude: Connected ({settings.agents.claude_model})")
        except Exception as e:
            console.print(f"[bold red]✗[/] Claude: {e}")
    else:
        console.print("[bold yellow]![/] Claude: ANTHROPIC_API_KEY not set")


# ============================================================================
# Auto-Update Commands
# ============================================================================

autoupdate_app = typer.Typer(help="Auto-update functionality discovery")
app.add_typer(autoupdate_app, name="autoupdate")


@autoupdate_app.command("run")
def autoupdate_run(
    repo_path: Path = typer.Argument(Path.cwd(), help="Repository path"),
    step: int | None = typer.Option(None, "--step", "-s", help="Run single step (1-4)"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Resume from checkpoint"),
    run_id: str | None = typer.Option(None, "--run-id", help="Existing run ID for resume"),
):
    """Run auto-update workflow to discover new features."""
    import asyncio

    from .tools.auto_update import AutoUpdateOrchestrator

    # Check API keys
    if not _check_api_keys(require_claude=True, require_gemini=True):
        raise typer.Exit(1)

    console.print("=" * 60)
    console.print("[bold blue]TurboWrap[/] - Auto-Update Workflow")
    console.print("=" * 60)
    console.print(f"  Repository: {repo_path}")
    if run_id:
        console.print(f"  Run ID: {run_id}")
    console.print("=" * 60)

    orchestrator = AutoUpdateOrchestrator(
        repo_path=repo_path,
        run_id=run_id,
    )

    async def progress(step_name: str, number: int, message: str):
        console.print(f"[dim]Step {number}:[/] {message}")

    try:
        if resume:
            result = asyncio.run(orchestrator.resume())
        elif step:
            result = asyncio.run(orchestrator.run_step(step))
        else:
            result = asyncio.run(orchestrator.run_all(progress_callback=progress))

        # Summary
        console.print("\n[bold green]Auto-Update Complete![/]")
        console.print(f"  Run ID: {result.run_id}")

        if result.step1 and result.step1.functionalities:
            console.print(f"  Functionalities found: {len(result.step1.functionalities)}")

        if result.step3 and result.step3.proposed_features:
            console.print(f"  Features proposed: {len(result.step3.proposed_features)}")

        if result.step4 and result.step4.created_issues:
            console.print(f"  Issues created: {len(result.step4.created_issues)}")
            for issue in result.step4.created_issues:
                console.print(f"    - {issue.linear_identifier}: {issue.title}")

    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        raise typer.Exit(1)


@autoupdate_app.command("status")
def autoupdate_status(
    run_id: str = typer.Argument(..., help="Run ID to check"),
):
    """Check status of auto-update run."""
    import asyncio

    from .tools.auto_update.storage import S3CheckpointManager

    manager = S3CheckpointManager()
    status = asyncio.run(manager.get_run_status(run_id))

    if not status:
        console.print(f"[bold red]✗[/] Run not found: {run_id}")
        raise typer.Exit(1)

    console.print(f"\n[bold]Run:[/] {status['run_id']}")
    console.print(f"[bold]Current Step:[/] {status['current_step']}")
    console.print(f"[bold]Completed:[/] {'Yes' if status['completed'] else 'No'}")

    console.print("\n[bold]Steps:[/]")
    for step_name, step_info in status.get("steps", {}).items():
        status_icon = "✓" if step_info["status"] == "completed" else "○"
        console.print(f"  [{status_icon}] {step_name}: {step_info['status']}")
        if step_info.get("error"):
            console.print(f"      Error: {step_info['error']}")


@autoupdate_app.command("list")
def autoupdate_list(
    limit: int = typer.Option(10, "--limit", "-l", help="Number of runs to show"),
):
    """List recent auto-update runs."""
    import asyncio

    from .tools.auto_update.storage import S3CheckpointManager

    manager = S3CheckpointManager()
    runs = asyncio.run(manager.list_runs(limit=limit))

    if not runs:
        console.print("[yellow]No runs found.[/]")
        return

    table = Table(title="Recent Auto-Update Runs")
    table.add_column("Run ID", style="dim")
    table.add_column("Started At")
    table.add_column("Steps Completed")

    for run in runs:
        steps = ", ".join(run.get("steps_completed", []))
        table.add_row(
            run["run_id"],
            run["started_at"][:19],
            steps or "-",
        )

    console.print(table)


# ============================================================================
# Main
# ============================================================================

def main():
    """CLI entry point."""
    app()


if __name__ == "__main__":
    main()
