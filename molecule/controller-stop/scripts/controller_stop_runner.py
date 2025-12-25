"""Helpers to exercise controller stop lifecycle (no VM, delegated driver)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from lb_controller.adapters.ansible_runner import AnsibleRunnerExecutor
from lb_controller.api import BenchmarkController
from lb_runner.models.config import (
    BenchmarkConfig,
    RemoteExecutionConfig,
    RemoteHostConfig,
    WorkloadConfig,
)
from lb_runner.engine.stop_token import StopToken

SCENARIO_ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK_ROOT = SCENARIO_ROOT / "playbooks"


def _config(output_root: Path) -> BenchmarkConfig:
    cfg = BenchmarkConfig(
        output_dir=output_root,
        report_dir=output_root / "reports",
        data_export_dir=output_root / "exports",
        remote_hosts=[
            RemoteHostConfig(
                name="simulated",
                address="127.0.0.1",
                user="runner",
                become=False,
                vars={
                    "ansible_connection": "local",
                    "ansible_python_interpreter": "python3",
                },
            )
        ],
    )
    cfg.workloads = {"dummy": WorkloadConfig(plugin="stress_ng", enabled=True)}
    cfg.remote_execution = RemoteExecutionConfig(
        enabled=True,
        setup_playbook=PLAYBOOK_ROOT / "setup.yml",
        run_playbook=PLAYBOOK_ROOT / "run.yml",
        collect_playbook=PLAYBOOK_ROOT / "run.yml",
        teardown_playbook=PLAYBOOK_ROOT / "teardown.yml",
        run_collect=False,
        run_setup=True,
        run_teardown=True,
    )
    cfg.repetitions = 1
    return cfg


def run_controller(stop_at: str | None) -> dict[str, bool]:
    out = Path.cwd() / "controller_artifacts" / (stop_at or "clean")
    out.mkdir(parents=True, exist_ok=True)
    run_id = f"molecule-{stop_at or 'clean'}"
    lb_workdir = out / "lb_workdir"
    lb_workdir.mkdir(parents=True, exist_ok=True)
    cfg = _config(out)
    stop_token = StopToken(enable_signals=False)
    executor = AnsibleRunnerExecutor(stream_output=True, stop_token=stop_token)
    controller = BenchmarkController(cfg, executor=executor, stop_token=stop_token)

    class _StubPlugin:
        name = "stub"

        def get_ansible_setup_path(self):
            return None

        def get_ansible_teardown_path(self):
            return None

        def get_ansible_setup_extravars(self):
            return {}

        def get_ansible_teardown_extravars(self):
            return {}

    class _StubRegistry:
        def get(self, name: str):
            return _StubPlugin()

    controller.plugin_registry = _StubRegistry()

    if stop_at:
        def arm_stop() -> None:
            delay = 0.1 if stop_at == "setup" else 1.5 if stop_at == "run" else 4.0
            time.sleep(delay)
            stop_token.request_stop()

        threading.Thread(target=arm_stop, daemon=True).start()

    def _patched_handle(inventory, extravars, log_fn):
        patched = extravars.copy()
        patched["lb_workdir"] = str(lb_workdir)
        try:
            (lb_workdir / "STOP").touch()
        except Exception:
            pass
        return True

    controller._handle_stop_protocol = _patched_handle  # type: ignore[attr-defined]

    summary = controller.run(test_types=["dummy"], run_id=run_id)
    run_path = out / run_id
    markers = {
        "setup": (run_path / "setup_marker").exists(),
        "run_start": (run_path / "run_start").exists(),
        "run_done": (run_path / "run_done").exists(),
        "teardown": (run_path / "teardown_marker").exists(),
        "success": summary.success,
    }
    return markers


def run_all_cases() -> dict[str, dict[str, bool]]:
    return {
        "clean": run_controller(None),
        "setup_interrupt": run_controller("setup"),
        "run_interrupt": run_controller("run"),
        "teardown_interrupt": run_controller("teardown"),
    }


def main() -> None:
    cases = run_all_cases()
    for name, markers in cases.items():
        print(f"[{name}] {markers}")
        if name == "clean":
            assert markers["success"] is True
            assert markers["setup"] and markers["run_done"] and markers["teardown"]
        elif name == "setup_interrupt":
            assert markers["teardown"], "Teardown must run after setup interruption"
        elif name == "run_interrupt":
            assert markers["setup"]
            assert markers["teardown"], "Teardown must run after run interruption"
        elif name == "teardown_interrupt":
            assert markers["setup"]
            assert markers["teardown"]


if __name__ == "__main__":
    main()
