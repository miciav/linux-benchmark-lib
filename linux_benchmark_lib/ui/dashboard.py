from typing import List, Dict, Any
from datetime import datetime
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from rich.text import Text
from rich.style import Style
from linux_benchmark_lib.journal import RunJournal, TaskState
# Assumo che BenchmarkConfig sia importabile, userò un type hint generico per evitare dipendenze circolari se necessario
# ma idealmente: from linux_benchmark_lib.benchmark_config import BenchmarkConfig 

class BenchmarkDashboard:
    def __init__(self, journal: RunJournal, config: Any): # config: BenchmarkConfig
        self.journal = journal
        self.config = config
        self.log_buffer: List[str] = []
        self.max_log_lines = 10
        
        # Define Main Layout
        self.layout = Layout()
        self.layout.split_column(
            Layout(name="header", size=6), # Aumentato size per ospitare l'header più ricco
            Layout(name="journal", size=10),
            Layout(name="logs")
        )

    def _generate_header(self) -> Table:
        """Recreates the configuration table matching the CLI 'Run Plan'."""
        # Style copied from current implementation description
        table = Table(title="Run Plan", show_edge=True, expand=True, border_style="cyan", header_style="bold white")
        table.add_column("Workload")
        table.add_column("Plugin", style="cyan")
        table.add_column("Intensity")
        table.add_column("Configuration")
        table.add_column("Status", style="green")
        
        # Generate rows from config
        # Logic adapted from cli.py _print_run_plan
        if hasattr(self.config, 'workloads'):
            for name, wl in self.config.workloads.items():
                if not wl.enabled:
                    continue
                
                # Determine status based on journal
                tasks = [t for t in self.journal.tasks if t.workload == name]
                if not tasks:
                     status = "Pending"
                elif all(t.status == "COMPLETED" for t in tasks):
                     status = "Completed"
                elif any(t.status == "FAILED" for t in tasks):
                     status = "Failed"
                elif any(t.status == "RUNNING" for t in tasks):
                     status = "Running"
                else:
                     status = "In Progress"

                # Format details string
                details = f"Int: {wl.intensity}" # Simplification
                if hasattr(wl, 'options') and wl.options:
                     details = str(wl.options)

                table.add_row(
                    name,
                    wl.plugin,
                    wl.intensity,
                    details,
                    status
                )
        
        return table

    def _generate_journal_table(self) -> Panel:
        """Generates the dynamic progress table (Host x Repetitions)."""
        table = Table(expand=True, box=None, padding=(0, 1))
        
        # Fixed Columns
        table.add_column("Host", style="bold magenta", width=22)
        table.add_column("Workload", width=15)
        
        # Dynamic Columns for Repetitions
        if not self.journal.tasks:
            max_reps = 3
        else:
            max_reps = max((t.repetition for t in self.journal.tasks), default=3)

        for i in range(1, max_reps + 1):
            table.add_column(f"Rep {i}", justify="center", width=8)
            
        table.add_column("Current Action", style="dim italic")

        # Group tasks to display them row by row, preserving insertion order
        seen_keys = set()
        unique_keys = []
        for t in self.journal.tasks:
            key = (t.host, t.workload)
            if key not in seen_keys:
                seen_keys.add(key)
                unique_keys.append(key)
        
        for host, workload in unique_keys:
            row_cells = [host, workload]
            tasks = [t for t in self.journal.tasks if t.host == host and t.workload == workload]
            active_action = ""
            
            for i in range(1, max_reps + 1):
                task = next((t for t in tasks if t.repetition == i), None)
                if not task:
                    row_cells.append("-")
                    continue

                if task.status == "COMPLETED":
                    row_cells.append("[green]✔ Done[/green]")
                elif task.status == "RUNNING":
                    row_cells.append("[yellow]⟳ Run[/yellow]")
                    active_action = task.current_action
                elif task.status == "PENDING":
                    row_cells.append("[dim]Wait[/dim]")
                elif task.status == "FAILED":
                    row_cells.append("[red]✘ Fail[/red]")
                elif task.status == "SKIPPED":
                    row_cells.append("[blue]⏭ Skip[/blue]")
                else:
                    row_cells.append(task.status)
            
            row_cells.append(active_action)
            table.add_row(*row_cells)

        return Panel(
            table, 
            title=f"[bold]Run Journal (ID: {self.journal.run_id})[/bold]", 
            border_style="bright_black"
        )

    def _generate_log_panel(self) -> Panel:
        """Generates the scrolling log panel."""
        text_content = Text()
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
        self.layout["header"].update(self._generate_header())
        self.layout["journal"].update(self._generate_journal_table())
        self.layout["logs"].update(self._generate_log_panel())
        return self.layout

    def add_log(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_buffer.append(f"[{ts}] {message}")
