
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from lb_runner.models.config import BenchmarkConfig
from lb_controller.services.paths import prepare_run_dirs

@pytest.mark.unit_controller
def test_prepare_run_dirs_does_not_create_report_and_export_dirs(tmp_path: Path):
    """Ensure prepare_run_dirs only creates output_root, not report/export dirs."""
    config = MagicMock(spec=BenchmarkConfig)
    config.output_dir = tmp_path / "out"
    config.report_dir = tmp_path / "rep"
    config.data_export_dir = tmp_path / "exp"
    
    run_id = "run-test"
    output_root, report_root, data_export_root = prepare_run_dirs(config, run_id)

    assert output_root.exists()
    
    # These should NOT exist yet
    assert not report_root.exists()
    assert not data_export_root.exists()
