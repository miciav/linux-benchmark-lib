

# Implementation Spec: Resilience Dashboard

This document outlines the new interface for `linux-benchmark-lib`. The goal is to transform the current CLI output into an **Interactive Dashboard** that visually supports the new "Resume" functionality.

## 1\. Design Guidelines

The interface utilizes the **Rich** library and is structured into three fixed vertical sections to ensure clarity during long-running benchmarks:

1.  **Header (Configuration):**

      * **Purpose:** Immediate visual confirmation of global parameters (Workload, Intensity, etc.).
      * **Style:** Static table with a cyan border (matching current interface), fixed at the top.

2.  **Run Journal (Execution Plan):**

      * **Purpose:** Displays the *overall* status. Answers: *"Where are we? How much is left?"*
      * **Visualization:** A **Host x Repetitions** matrix.
      * **States:**
          * `PENDING` (Dim/Grey): Waiting.
          * `RUNNING` (Yellow/Spinner): Currently executing.
          * `COMPLETED` (Green/Check): Finished (or recovered via Resume).
          * `FAILED` (Red): Execution failed.

3.  **Log Stream (Technical Detail):**

      * **Purpose:** Shows exactly what Ansible/SSH is doing at this specific moment.
      * **Visualization:** A scrolling panel at the bottom showing only the last N lines to prevent infinite scrolling from hiding the overall plan.

-----

## 2\. Complete Code (`ui_dashboard.py`)

Copy this code into a file (e.g., `ui_dashboard.py`). It contains both the Data Model classes (the Journal) and the Visualization logic.

```python
import time
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime

# Rich Library Imports
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.style import Style

# --- 1. DATA MODEL (The "Journal") ---
# These classes represent the logical state defined in RESILIENCE_PLAN.md

@dataclass
class TaskState:
    """Represents a single atomic unit of work (Host + Workload + Repetition)"""
    host: str
    workload: str
    repetition: int
    status: str = "PENDING"  # States: PENDING, RUNNING, COMPLETED, FAILED
    current_action: str = "" # Detail of the current action (e.g., "Gathering Facts")

@dataclass
class RunJournal:
    """Contains the entire execution plan"""
    run_id: str
    tasks: List[TaskState] = field(default_factory=list)

    def get_tasks_by_host(self, host: str) -> List[TaskState]:
        """Returns all tasks for a specific host, sorted by repetition"""
        return sorted([t for t in self.tasks if t.host == host], key=lambda x: x.repetition)

    def update_task(self, host: str, workload: str, rep: int, status: str, action: str = ""):
        """Helper to update the state of a specific task"""
        for t in self.tasks:
            if t.host == host and t.workload == workload and t.repetition == rep:
                t.status = status
                if action:
                    t.current_action = action
                break

# --- 2. DASHBOARD UI CLASS ---
# Handles layout and rendering

class BenchmarkDashboard:
    def __init__(self, journal: RunJournal):
        self.journal = journal
        self.log_buffer: List[str] = []
        self.max_log_lines = 10  # Number of visible log lines at the bottom
        
        # Define Main Layout (Header, Journal, Logs)
        self.layout = Layout()
        self.layout.split_column(
            Layout(name="header", size=4),      # Fixed height for header
            Layout(name="journal", size=8),     # Adaptable height for the plan
            Layout(name="logs")                 # Remaining space for logs
        )

    def _generate_header(self) -> Table:
        """Recreates the blue configuration table (matching current interface)"""
        table = Table(show_edge=True, expand=True, border_style="cyan", header_style="bold white")
        table.add_column("Workload")
        table.add_column("Plugin", style="cyan")
        table.add_column("Intensity")
        table.add_column("Configuration")
        table.add_column("Status", style="green")
        
        # EXAMPLE: These data points should come from the actual configuration object
        table.add_row(
            "fio", "fio", "medium", 
            "Time: 60s, BS: 4k, Mode: randrw", 
            "Multipass"
        )
        return table

    def _generate_journal_table(self) -> Panel:
        """Generates the dynamic progress table (Host x Repetitions)"""
        table = Table(expand=True, box=None, padding=(0, 1))
        
        # Fixed Columns
        table.add_column("Host", style="bold magenta", width=22)
        table.add_column("Workload", width=10)
        
        # Dynamic Columns for Repetitions
        # Calculate max repetitions existing in the journal
        max_reps = max((t.repetition for t in self.journal.tasks), default=3)
        for i in range(1, max_reps + 1):
            table.add_column(f"Rep {i}", justify="center", width=8)
            
        table.add_column("Current Action", style="dim italic")

        # Group tasks to display them row by row
        unique_keys = sorted(list(set((t.host, t.workload) for t in self.journal.tasks)))
        
        for host, workload in unique_keys:
            row_cells = [host, workload]
            
            # Retrieve specific tasks for this row
            tasks = [t for t in self.journal.tasks if t.host == host and t.workload == workload]
            
            active_action = ""
            
            # Create cells for each repetition
            for i in range(1, max_reps + 1):
                task = next((t for t in tasks if t.repetition == i), None)
                if not task:
                    row_cells.append("-")
                    continue

                # Icon/Color Logic
                if task.status == "COMPLETED":
                    row_cells.append("[green]✔ Done[/green]")
                elif task.status == "RUNNING":
                    row_cells.append("[yellow]⟳ Run[/yellow]")
                    active_action = task.current_action # Show action only if running
                elif task.status == "PENDING":
                    row_cells.append("[dim]Wait[/dim]")
                elif task.status == "FAILED":
                    row_cells.append("[red]✘ Fail[/red]")
            
            # Append the current action at the end of the row
            row_cells.append(active_action)
            table.add_row(*row_cells)

        return Panel(
            table, 
            title=f"[bold]Run Journal (ID: {self.journal.run_id})[/bold]", 
            border_style="bright_black"
        )

    def _generate_log_panel(self) -> Panel:
        """Generates the scrolling log panel"""
        text_content = Text()
        # Take only the last N lines from the buffer
        visible_logs = self.log_buffer[-self.max_log_lines:]
        
        for line in visible_logs:
            text_content.append(line + "\n")
            
        return Panel(
            text_content, 
            title="[bold]Log Stream[/bold]", 
            border_style="grey30",
            padding=(0, 1)
        )

    def update(self) -> Layout:
        """Method called cyclically to refresh the entire screen"""
        self.layout["header"].update(self._generate_header())
        self.layout["journal"].update(self._generate_journal_table())
        self.layout["logs"].update(self._generate_log_panel())
        return self.layout

    def add_log(self, message: str):
        """Adds a message to the log buffer with a timestamp"""
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_buffer.append(f"[{ts}] {message}")


# --- 3. EXECUTION SIMULATION (MAIN) ---
# This block simulates how the Controller will use the Dashboard

if __name__ == "__main__":
    # A. Initial Setup (Load or create Journal)
    journal = RunJournal(run_id="run_2024_resumed")
    hosts = ["lb-worker-01", "lb-worker-02"]
    
    # Populate the journal with 3 repetitions per host
    for h in hosts:
        for r in range(1, 4):
            # Simulate Repetition 1 being already done in the past (RESUME scenario)
            status = "COMPLETED" if r == 1 else "PENDING"
            journal.tasks.append(TaskState(host=h, workload="fio", repetition=r, status=status))

    dashboard = BenchmarkDashboard(journal)

    # B. Execution Loop (Live Wrapper)
    # refresh_per_second determines how often the UI updates
    with Live(dashboard.update(), refresh_per_second=4, screen=True) as live:
        
        dashboard.add_log("[bold white]Benchmark resumed. Checking journal state...[/]")
        time.sleep(1)

        # Simulate the Controller loop on PENDING tasks
        pending_tasks = [t for t in journal.tasks if t.status == "PENDING"]
        
        for task in pending_tasks:
            # 1. Start Task: Update state and Log
            journal.update_task(task.host, task.workload, task.repetition, "RUNNING", "Initializing...")
            dashboard.add_log(f"[bold cyan][Run][/] Starting Repetition {task.repetition} on {task.host}")
            time.sleep(0.5)
            
            # 2. Simulate intermediate steps (e.g., Ansible phases)
            steps = [
                "Gathering Facts",
                "Preparing benchmark configuration",
                "Running Workload (approx 2s)...",
                "Fetching archived data"
            ]
            
            for step in steps:
                # Simulate work time
                time.sleep(0.8) 
                
                # Update current action in the table and add a log
                journal.update_task(task.host, task.workload, task.repetition, "RUNNING", action=step)
                dashboard.add_log(f"[dim]  > {step}[/]")
                
                # Force a visual refresh (optional, Live does it automatically)
                live.update(dashboard.update())

            # 3. End Task
            journal.update_task(task.host, task.workload, task.repetition, "COMPLETED", action="Done")
            dashboard.add_log(f"[bold green][Success][/] Repetition {task.repetition} finished for {task.host}")
            time.sleep(0.5)

        dashboard.add_log("[bold white]All tasks completed successfully. Generating report...[/]")
        time.sleep(3)
```

## 3\. Integration Instructions

To integrate this dashboard into your `linux-benchmark-lib` project:

1.  **Save the Module:** Save the code above (excluding the `if __name__ == "__main__":` block) into `linux_benchmark_lib/ui.py`.
2.  **In `controller.py`:**
      * Import `BenchmarkDashboard` and `RunJournal`.
      * Before the main benchmark loop (`for` or `while`), instantiate the dashboard.
      * Wrap the entire execution block with `with Live(dashboard.update(), screen=True) as live:`.
3.  **Log Management:**
      * Replace `print()` or `logging.info()` calls with `dashboard.add_log()`.
      * If using standard Python logging, you can create a custom `Handler` that redirects messages to `dashboard.add_log` to automatically capture output from underlying libraries.
4.  **Journal Updates:**
      * Ensure your logical code (launching Ansible/Playbooks) updates the `journal` object (setting status to `RUNNING`/`COMPLETED`) so the UI reflects changes.