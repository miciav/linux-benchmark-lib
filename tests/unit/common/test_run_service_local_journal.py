"""Local run journal behavior tests."""

import time
from pathlib import Path

import pytest

from lb_runner.benchmark_config import BenchmarkConfig, WorkloadConfig
from lb_runner.events import RunEvent

pytestmark = pytest.mark.unit

from lb_controller.journal import RunJournal
from lb_controller.services import run_service as run_service_module
from lb_controller.services.run_service import RunContext, RunService


def test_repetition_start_times_follow_execution_order(tmp_path: Path, monkeypatch):
    """Start timestamps should reflect when each repetition actually begins."""
    cfg = BenchmarkConfig(
        output_dir=tmp_path / "benchmark_results",
        report_dir=tmp_path / "reports",
        data_export_dir=tmp_path / "data_exports",
        repetitions=3,
    )
    cfg.workloads = {"dummy": WorkloadConfig(plugin="dummy")}
    cfg.remote_execution.run_setup = False
    cfg.remote_execution.run_teardown = False

    class DummyRegistry:
        def get(self, name: str):
            return object()

    service = RunService(lambda: DummyRegistry())

    class FakeLocalRunner:
        def __init__(
            self,
            config,
            registry,
            ui_adapter=None,
            progress_callback=None,
            host_name=None,
            stop_token=None,
        ):
            self.config = config
            self.progress_callback = progress_callback
            self.host_name = host_name or "localhost"

        def run_benchmark(
            self,
            test_type,
            repetition_override=None,
            total_repetitions=None,
            run_id=None,
            pending_reps=None,
        ):
            for rep in range(1, self.config.repetitions + 1):
                if self.progress_callback:
                    self.progress_callback(
                        RunEvent(
                            run_id=run_id or "test",
                            host=self.host_name,
                            workload=test_type,
                            repetition=rep,
                            total_repetitions=self.config.repetitions,
                            status="running",
                            timestamp=time.time(),
                        )
                    )
                time.sleep(0.01)
                if self.progress_callback:
                    self.progress_callback(
                        RunEvent(
                            run_id=run_id or "test",
                            host=self.host_name,
                            workload=test_type,
                            repetition=rep,
                            total_repetitions=self.config.repetitions,
                            status="done",
                            timestamp=time.time(),
                        )
                    )
            return True

    monkeypatch.setattr(run_service_module, "LocalRunner", FakeLocalRunner)

    context = RunContext(
        config=cfg,
        target_tests=["dummy"],
        registry=DummyRegistry(),
        use_remote=False,
        use_container=False,
        use_multipass=False,
        multipass_count=1,
        config_path=None,
        docker_image="linux-benchmark-lib:dev",
        docker_engine="docker",
        docker_build=False,
        docker_no_cache=False,
        docker_workdir=None,
        debug=False,
        resume_from=None,
        resume_latest=False,
    )

    result = service.execute(context, run_id="start-times")
    assert result.journal_path and result.journal_path.exists()

    journal = RunJournal.load(result.journal_path)
    starts = [
        journal.get_task("localhost", "dummy", rep).started_at
        for rep in range(1, cfg.repetitions + 1)
    ]

    assert all(starts)
    assert starts == sorted(starts)
    assert len(set(starts)) == len(starts)
