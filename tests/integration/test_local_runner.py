from unittest.mock import MagicMock
import pytest
from dataclasses import asdict

from lb_runner.benchmark_config import (
    BenchmarkConfig,
    MetricCollectorConfig,
    PerfConfig,
    WorkloadConfig,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]

from lb_runner.plugins.stress_ng.plugin import StressNGConfig
from lb_runner.local_runner import LocalRunner

def test_run_stress_ng_benchmark(tmp_path, mocker):
    """
    Test a full execution of stress-ng benchmark using LocalRunner.
    Simulates the workload generator and collectors.
    """
    # --- Setup Mocks ---
    mock_cleanup = mocker.patch('lb_runner.local_runner.LocalRunner._pre_test_cleanup')
    mock_data_handler_factory = mocker.patch('lb_runner.local_runner.make_data_handler')
    mock_data_handler_instance = mock_data_handler_factory.return_value
    mock_data_handler_instance.process_test_results.return_value = None

    mock_gen_instance = MagicMock()
    mock_gen_instance.get_result.return_value = {"status": "success"}

    mock_col_instance = MagicMock()
    mock_col_instance.name = "PSUtilCollector"
    mock_col_instance.get_data.return_value = [
        {'timestamp': '2025-01-01T12:00:00', 'cpu_percent': 50.0},
        {'timestamp': '2025-01-01T12:00:01', 'cpu_percent': 55.0},
    ]

    # --- Configuration ---
    stress_cfg = StressNGConfig(cpu_workers=1, timeout=1, vm_workers=0, io_workers=0)
    config = BenchmarkConfig(
        repetitions=1,
        test_duration_seconds=1,
        warmup_seconds=0,
        cooldown_seconds=0,
        output_dir=tmp_path / "results",
        data_export_dir=tmp_path / "exports",
        report_dir=tmp_path / "reports",
        plugin_settings={"stress_ng": stress_cfg},
        workloads={
            "stress_ng": WorkloadConfig(
                plugin="stress_ng",
                enabled=True,
                options=asdict(stress_cfg),
            )
        },
        collectors=MetricCollectorConfig(
            cli_commands=None, 
            perf_config=PerfConfig(events=None), 
            enable_ebpf=False
        )
    )

    registry = MagicMock()
    registry.create_generator.return_value = mock_gen_instance
    registry.create_collectors.return_value = [mock_col_instance]

    # --- Execution ---
    runner = LocalRunner(config, registry=registry)
    runner.run_benchmark("stress_ng")

    # --- Assertions ---
    mock_cleanup.assert_called_once()

    # Verify generator usage
    registry.create_generator.assert_called()
    mock_gen_instance.start.assert_called_once()
    mock_gen_instance.stop.assert_called_once()

    # Verify collector usage
    registry.create_collectors.assert_called_once()
    mock_col_instance.start.assert_called_once()
    mock_col_instance.stop.assert_called_once()
    mock_col_instance.save_data.assert_called_once()

    # Verify DataHandler usage
    mock_data_handler_instance.process_test_results.assert_called_once()
    
    # Verify save path
    save_data_calls = mock_col_instance.save_data.call_args_list
    assert len(save_data_calls) == 1
    called_path = save_data_calls[0][0][0]
    assert called_path.name == "stress_ng_rep1_PSUtilCollector.csv"
    run_id = getattr(runner, "_current_run_id", None)
    if run_id:
        assert called_path.parent.name == run_id
