import time
import sys
import os
from rich.live import Live

# Ensure the local package is importable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from linux_benchmark_lib.journal import RunJournal, TaskState
from linux_benchmark_lib.ui.dashboard import BenchmarkDashboard

def run_demo():
    # 1. Setup Journal
    journal = RunJournal(run_id="demo_run_2025")
    hosts = ["lb-worker-01", "lb-worker-02", "lb-worker-03"]
    
    # Pre-populate tasks
    for h in hosts:
        for r in range(1, 4):
            journal.add_task(TaskState(host=h, workload="fio", repetition=r))

    dashboard = BenchmarkDashboard(journal)

    # 2. Run Simulation
    with Live(dashboard.update(), refresh_per_second=4, screen=True) as live:
        dashboard.add_log("[bold white]Benchmark initialized. Starting simulation...[/]")
        time.sleep(1.5)

        # Iterate through tasks to simulate progress
        tasks = journal.tasks
        
        for task in tasks:
            # Update to RUNNING
            journal.update_task(task.host, task.workload, task.repetition, "RUNNING", "Initializing...")
            dashboard.add_log(f"[bold cyan][Run][/] Starting Repetition {task.repetition} on {task.host}")
            time.sleep(0.5)
            
            # Simulate steps
            steps = ["Gathering Facts", "Running Workload", "Finalizing"]
            for step in steps:
                journal.update_task(task.host, task.workload, task.repetition, "RUNNING", action=step)
                dashboard.add_log(f"[dim]  > {step}[/]")
                live.update(dashboard.update())
                time.sleep(0.4) # Fast simulation

            # Update to COMPLETED (or fail one for demo purposes)
            if task.host == "lb-worker-02" and task.repetition == 2:
                 journal.update_task(task.host, task.workload, task.repetition, "FAILED", action="SSH Error")
                 dashboard.add_log(f"[bold red][Fail][/] Repetition {task.repetition} failed on {task.host}!")
            else:
                journal.update_task(task.host, task.workload, task.repetition, "COMPLETED", action="Done")
                dashboard.add_log(f"[bold green][Success][/] Repetition {task.repetition} finished")
            
            time.sleep(0.2)

        dashboard.add_log("[bold white]All tasks processed. Press Ctrl+C to exit.[/]")
        while True:
            time.sleep(1)

if __name__ == "__main__":
    try:
        run_demo()
    except KeyboardInterrupt:
        print("\nDemo exited.")
