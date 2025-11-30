import time
import sys
import os
from rich.live import Live

# Ensure the local package is importable
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from linux_benchmark_lib.journal import RunJournal, TaskState
from linux_benchmark_lib.ui.dashboard import BenchmarkDashboard

def run_demo():
    # 1. Setup Journal with MULTIPLE WORKLOADS
    journal = RunJournal(run_id="multi_workload_demo")
    hosts = ["lb-worker-01", "lb-worker-02"]
    
    # Workload 1: Network Check (Short, 2 reps)
    for h in hosts:
        for r in range(1, 3):
            journal.add_task(TaskState(host=h, workload="net_check", repetition=r))

    # Workload 2: Disk Stress (Longer, 3 reps)
    for h in hosts:
        for r in range(1, 4):
            journal.add_task(TaskState(host=h, workload="disk_stress", repetition=r))

    dashboard = BenchmarkDashboard(journal)

    # 2. Run Simulation
    with Live(dashboard.update(), refresh_per_second=4, screen=True) as live:
        dashboard.add_log("[bold white]Benchmark initialized. Plan contains multiple workloads.[/]")
        time.sleep(2)

        # Iterate through tasks to simulate progress
        # Since tasks are appended in order, this loop respects the execution plan
        tasks = journal.tasks
        
        for i, task in enumerate(tasks):
            # Visual separation when switching workloads
            if i > 0 and tasks[i-1].workload != task.workload:
                dashboard.add_log(f"[bold yellow]>>> Switching to next workload: {task.workload} <<<[/]")
                time.sleep(1.5)

            # Update to RUNNING
            journal.update_task(task.host, task.workload, task.repetition, "RUNNING", "Initializing...")
            dashboard.add_log(f"[bold cyan][Run][/] {task.workload} Rep {task.repetition} on {task.host}")
            time.sleep(0.5) # Simulation speed
            
            # Simulate steps customized by workload
            if task.workload == "net_check":
                steps = ["Ping Test", "Bandwidth Check"]
            else:
                steps = ["Generating Files", "Random R/W", "Cleanup"]

            for step in steps:
                journal.update_task(task.host, task.workload, task.repetition, "RUNNING", action=step)
                dashboard.add_log(f"[dim]  > {step}[/]")
                live.update(dashboard.update())
                time.sleep(0.3) # Simulation speed

            # Completion
            journal.update_task(task.host, task.workload, task.repetition, "COMPLETED", action="Done")
            dashboard.add_log(f"[bold green][Success][/] Finished {task.workload} on {task.host}")
            time.sleep(0.2)

        dashboard.add_log("[bold white]All workloads completed. Press Ctrl+C to exit.[/]")
        while True:
            time.sleep(1)

if __name__ == "__main__":
    try:
        run_demo()
    except KeyboardInterrupt:
        print("\nDemo exited.")
