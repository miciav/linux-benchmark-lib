import pytest
from rich.console import Console
from rich.table import Table
from collections import defaultdict

def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """
    Custom hook to print statistics by marker at the end of the test session.
    """
    _ = (exitstatus, config)  # unused in our reporting helper
    # Initialize statistics
    marker_stats = defaultdict(lambda: {"passed": 0, "failed": 0, "skipped": 0, "total": 0})
    
    # Defined markers in pyproject.toml
    known_markers = {
        "unit_runner", "unit_controller", "unit_ui", "unit_provisioner", 
        "unit_analytics", "unit_plugins", "unit_baseline",
        "inter_generic", "inter_docker", "inter_multipass", 
        "inter_multipass_single", "inter_e2e", "inter_plugins", "inter_baseline",
        "slow", "slowest"
    }

    # Iterate over relevant outcomes in terminalreporter.stats
    # stats is a dict like {'passed': [Report, ...], 'failed': [...]}
    marker_stats = defaultdict(lambda: {"passed": 0, "failed": 0, "skipped": 0, "total": 0, "duration": 0.0})

    for outcome in ["passed", "failed", "skipped"]:
        reports = terminalreporter.stats.get(outcome, [])
        for report in reports:
            # Only count the actual test call, or setup skips
            if report.when == "call" or (report.when == "setup" and report.outcome == "skipped"):
                duration = getattr(report, "duration", 0.0)
                # Check for markers
                for marker in known_markers:
                    # report.keywords is a dict-like object where keys are markers/keywords
                    if marker in report.keywords:
                        stats = marker_stats[marker]
                        stats[outcome] += 1
                        stats["total"] += 1
                        stats["duration"] += duration

    # Create a Rich table
    console = Console()
    
    # Only print if we found something
    if not marker_stats:
        # Optional: uncomment to debug if needed, but for now just silence or simple msg
        # console.print("\n[dim]No statistics for known markers found.[/dim]")
        return

    table = Table(title="Test Statistics by Marker", show_header=True, header_style="bold magenta")
    table.add_column("Marker", style="cyan")
    table.add_column("Total", justify="right")
    table.add_column("Passed", justify="right", style="green")
    table.add_column("Failed", justify="right", style="red")
    table.add_column("Skipped", justify="right", style="yellow")
    table.add_column("Duration (s)", justify="right", style="blue")
    table.add_column("Avg (s)", justify="right", style="blue")

    # Add rows
    sorted_markers = sorted(marker_stats.keys())
    for marker in sorted_markers:
        stats = marker_stats[marker]
        if stats["total"] > 0:
            avg_duration = stats["duration"] / stats["total"]
            table.add_row(
                marker,
                str(stats["total"]),
                str(stats["passed"]),
                str(stats["failed"]),
                str(stats["skipped"]),
                f"{stats['duration']:.2f}",
                f"{avg_duration:.2f}"
            )

    console.print("\n")
    console.print(table)
