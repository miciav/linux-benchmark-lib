from pathlib import Path

from lb_controller.api import RunCatalogService


def test_get_run_understands_local_layout_without_journal(tmp_path: Path) -> None:
    output_dir = tmp_path / "benchmark_results"
    run_dir = output_dir / "run-1"
    (run_dir / "stress_ng" / "rep1").mkdir(parents=True)

    info = RunCatalogService(output_dir).get_run("run-1")

    assert info is not None
    assert info.hosts == ["localhost"]
    assert info.workloads == ["stress_ng"]


def test_get_run_understands_remote_layout_without_journal(tmp_path: Path) -> None:
    output_dir = tmp_path / "benchmark_results"
    run_dir = output_dir / "run-2"
    (run_dir / "host-a" / "stress_ng" / "rep1").mkdir(parents=True)
    (run_dir / "host-b" / "fio" / "rep1").mkdir(parents=True)

    info = RunCatalogService(output_dir).get_run("run-2")

    assert info is not None
    assert info.hosts == ["host-a", "host-b"]
    assert info.workloads == ["fio", "stress_ng"]
