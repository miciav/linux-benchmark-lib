from pathlib import Path

import pytest

from lb_plugins.api import FIOPlugin

pytestmark = [pytest.mark.unit_runner, pytest.mark.unit_plugins]



def test_fio_plugin_export_parsed_metrics(tmp_path: Path):
    plugin = FIOPlugin()
    results = [
        {
            "repetition": 1,
            "generator_result": {
                "returncode": 0,
                "parsed": {
                    "read_iops": 1000,
                    "read_bw_mb": 250,
                    "read_lat_ms": 1.2,
                    "write_iops": 800,
                    "write_bw_mb": 200,
                    "write_lat_ms": 1.5,
                },
            },
        }
    ]

    exported = plugin.export_results_to_csv(
        results=results,
        output_dir=tmp_path,
        run_id="run-1",
        test_name="fio",
    )

    assert exported, "Expected at least one CSV file"
    csv_path = exported[0]
    assert csv_path.exists()
    content = csv_path.read_text()
    assert "read_iops" in content
    assert "write_bw_mb" in content
    assert "1000" in content
