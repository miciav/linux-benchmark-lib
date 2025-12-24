
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from lb_runner.benchmark_config import BenchmarkConfig
from lb_runner.output_helpers import ensure_run_dirs

@pytest.mark.unit_runner
def test_ensure_run_dirs_does_not_create_report_and_export_dirs(tmp_path: Path):
    """Ensure ensure_run_dirs only creates output_root, not report/export dirs."""
    config = MagicMock(spec=BenchmarkConfig)
    config.output_dir = tmp_path / "out"
    config.report_dir = tmp_path / "rep"
    config.data_export_dir = tmp_path / "exp"
    
    # Mock ensure_output_dirs to do nothing
    config.ensure_output_dirs = MagicMock()

    run_id = "run-test"
    output_root, data_export_root, report_root = ensure_run_dirs(config, run_id)

    assert output_root.exists()
    assert output_root.name == run_id
    
    # These should NOT exist yet
    assert not report_root.exists()
    assert not data_export_root.exists()
