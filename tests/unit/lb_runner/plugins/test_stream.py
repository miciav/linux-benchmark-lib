"""Unit tests for the STREAM workload plugin logic."""

import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lb_plugins.api import (
    DEFAULT_NTIMES,
    DEFAULT_STREAM_ARRAY_SIZE,
    StreamConfig,
    StreamGenerator,
    StreamPlugin,
    WorkloadIntensity,
)

pytestmark = pytest.mark.unit_runner

@pytest.fixture
def stream_config():
    return StreamConfig()


@pytest.fixture
def stream_generator(stream_config):
    return StreamGenerator(stream_config)


def test_config_defaults(stream_config):
    assert stream_config.stream_array_size == DEFAULT_STREAM_ARRAY_SIZE
    assert stream_config.ntimes == DEFAULT_NTIMES
    assert stream_config.threads == 0
    assert stream_config.recompile is False
    assert stream_config.use_numactl is False
    assert stream_config.compilers == ["gcc"]
    assert stream_config.allow_missing_compilers is False


def test_plugin_metadata():
    plugin = StreamPlugin()
    assert plugin.name == "stream"
    assert "STREAM" in plugin.description
    assert plugin.config_cls is StreamConfig


def test_presets_use_multiple_compilers():
    plugin = StreamPlugin()
    for level in (
        WorkloadIntensity.LOW,
        WorkloadIntensity.MEDIUM,
        WorkloadIntensity.HIGH,
    ):
        config = plugin.get_preset_config(level)
        assert config is not None
        assert config.compilers == ["gcc", "icc"]
        assert config.allow_missing_compilers is True


def test_needs_recompile(stream_config):
    gen = StreamGenerator(stream_config)
    assert gen._needs_recompile()

    stream_config.recompile = True
    assert gen._needs_recompile()

    stream_config.recompile = False
    stream_config.stream_array_size = DEFAULT_STREAM_ARRAY_SIZE + 100
    assert gen._needs_recompile()

    stream_config.stream_array_size = DEFAULT_STREAM_ARRAY_SIZE
    stream_config.ntimes = 10
    assert not gen._needs_recompile()


def test_build_command_defaults(stream_generator):
    # Mock the stream path to exist
    stream_generator.stream_path = Path("/mock/stream")
    cmd = stream_generator._build_command()
    assert cmd == ["/mock/stream"]


def test_build_command_with_numactl(stream_config):
    stream_config.use_numactl = True
    stream_config.numactl_args = ["--physcpubind=0", "--localalloc"]
    gen = StreamGenerator(stream_config)
    gen.stream_path = Path("/mock/stream")
    
    cmd = gen._build_command()
    assert cmd == ["numactl", "--physcpubind=0", "--localalloc", "/mock/stream"]


def test_launcher_env(stream_config):
    gen = StreamGenerator(stream_config)
    env = gen._launcher_env()
    assert "OMP_NUM_THREADS" not in env  # Default threads=0

    stream_config.threads = 4
    gen = StreamGenerator(stream_config)
    env = gen._launcher_env()
    assert env["OMP_NUM_THREADS"] == "4"


@patch("shutil.which")
def test_validate_environment_missing_gcc_for_recompile(mock_which, stream_config):
    stream_config.recompile = True
    mock_which.return_value = None  # gcc missing
    
    gen = StreamGenerator(stream_config)
    assert gen._validate_environment() is False


@patch("shutil.which")
def test_validate_environment_missing_numactl(mock_which, stream_config):
    stream_config.use_numactl = True
    mock_which.side_effect = lambda cmd: "/usr/bin/gcc" if cmd == "gcc" else None # numactl missing
    
    gen = StreamGenerator(stream_config)
    assert gen._validate_environment() is False


@patch("subprocess.run")
@patch("shutil.copy2")
def test_compile_binary_success(_mock_copy, mock_run, stream_generator, tmp_path):
    # Mock workspace dirs
    stream_generator.workspace_src_dir = tmp_path / "src"
    stream_generator.workspace_bin_dir = tmp_path / "bin"
    stream_generator.workspace_src_dir.mkdir(parents=True)
    stream_generator.workspace_bin_dir.mkdir(parents=True)
    
    # Create a dummy output file to simulate successful compilation
    output_path = stream_generator.workspace_bin_dir / "stream"
    output_path.touch()

    # Mock upstream file existence check
    with patch.object(StreamGenerator, "_upstream_stream_c", return_value=Path("/upstream/stream.c")):
        mock_run.return_value = MagicMock(returncode=0)
        
        out_path = stream_generator._compile_binary_for_compiler("gcc", output_path)
        
        assert out_path == output_path
        assert mock_run.called
        args = mock_run.call_args[0][0]
        assert "gcc" in args
        assert f"-DSTREAM_ARRAY_SIZE={DEFAULT_STREAM_ARRAY_SIZE}" in args


@patch("subprocess.run")
def test_compile_binary_failure(mock_run, stream_generator, tmp_path):
    stream_generator.workspace_src_dir = tmp_path / "src"
    stream_generator.workspace_bin_dir = tmp_path / "bin"
    
    with patch.object(StreamGenerator, "_upstream_stream_c", return_value=Path("/upstream/stream.c")):
        with patch("shutil.copy2"):
            # Simulate gcc failure
            mock_run.return_value = MagicMock(returncode=1, stderr="Compilation error")
            
            with pytest.raises(RuntimeError) as exc:
                stream_generator._compile_binary_for_compiler(
                    "gcc", stream_generator.workspace_bin_dir / "stream"
                )
            
            assert "Failed to compile STREAM" in str(exc.value)


@patch("os.access")
def test_ensure_binary_uses_system_if_available(mock_access, stream_generator):
    # recompile is False by default
    stream_generator.config.ntimes = 10

    # Mock system path exists and is executable, but workspace path does NOT exist
    def side_effect(self):
        if self == stream_generator.system_stream_path:
            return True
        return False

    with patch.object(Path, "exists", side_effect=side_effect, autospec=True):
        mock_access.return_value = True
        
        assert (
            stream_generator._ensure_binary_for_compiler("gcc", None, multi=False)
            == stream_generator.system_stream_path
        )
        assert stream_generator.stream_path == stream_generator.system_stream_path


@patch("os.access")
def test_ensure_binary_fails_if_nothing_available(mock_access, stream_generator):
    stream_generator.config.ntimes = 10
    # Mock nothing exists
    with patch.object(Path, "exists", return_value=False):
        assert (
            stream_generator._ensure_binary_for_compiler("gcc", None, multi=False) is None
        )
        assert "stream binary missing" in stream_generator._result["error"]


def test_stream_export_includes_timing_columns(tmp_path: Path) -> None:
    plugin = StreamPlugin()
    results = [
        {
            "repetition": 1,
            "duration_seconds": 2.0,
            "success": True,
            "generator_result": {
                "returncode": 0,
                "stream_array_size": DEFAULT_STREAM_ARRAY_SIZE,
                "ntimes": DEFAULT_NTIMES,
                "threads": 4,
                "validated": True,
                "copy_best_rate_mb_s": 100.0,
                "copy_avg_time_s": 0.01,
                "copy_min_time_s": 0.009,
                "copy_max_time_s": 0.02,
                "scale_best_rate_mb_s": 90.0,
                "scale_avg_time_s": 0.02,
                "scale_min_time_s": 0.018,
                "scale_max_time_s": 0.03,
                "add_best_rate_mb_s": 80.0,
                "add_avg_time_s": 0.03,
                "add_min_time_s": 0.028,
                "add_max_time_s": 0.04,
                "triad_best_rate_mb_s": 70.0,
                "triad_avg_time_s": 0.04,
                "triad_min_time_s": 0.038,
                "triad_max_time_s": 0.05,
                "max_retries": 0,
                "tags": [],
            },
        }
    ]
    paths = plugin.export_results_to_csv(
        results=results, output_dir=tmp_path, run_id="run-1", test_name="stream"
    )
    assert paths
    csv_path = paths[0]
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)

    assert row["copy_avg_time_s"] == "0.01"
    assert row["copy_avg_time_ms"] == "10.0"
    assert row["copy_min_time_s"] == "0.009"
    assert row["copy_max_time_s"] == "0.02"
    assert row["triad_best_rate_mb_s"] == "70.0"


def test_stream_export_handles_multiple_compilers(tmp_path: Path) -> None:
    plugin = StreamPlugin()
    results = [
        {
            "repetition": 1,
            "duration_seconds": 2.0,
            "success": True,
            "generator_result": {
                "compiler_results": [
                    {
                        "compiler": "gcc",
                        "compiler_bin": "/usr/bin/gcc",
                        "returncode": 0,
                        "stream_array_size": DEFAULT_STREAM_ARRAY_SIZE,
                        "ntimes": DEFAULT_NTIMES,
                        "threads": 4,
                        "validated": True,
                        "copy_best_rate_mb_s": 100.0,
                    },
                    {
                        "compiler": "icc",
                        "compiler_bin": "/opt/intel/bin/icc",
                        "returncode": 0,
                        "stream_array_size": DEFAULT_STREAM_ARRAY_SIZE,
                        "ntimes": DEFAULT_NTIMES,
                        "threads": 4,
                        "validated": True,
                        "copy_best_rate_mb_s": 90.0,
                    },
                ]
            },
        }
    ]
    paths = plugin.export_results_to_csv(
        results=results, output_dir=tmp_path, run_id="run-1", test_name="stream"
    )
    assert paths
    csv_path = paths[0]
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)

    assert len(rows) == 2
    assert rows[0]["compiler"] == "gcc"
    assert rows[1]["compiler"] == "icc"


def test_prepare_uses_validated_compiler_plan(tmp_path: Path) -> None:
    config = StreamConfig(compilers=["gcc", "icc"], allow_missing_compilers=True)
    gen = StreamGenerator(config)

    validated = {"called": False}

    def _validate() -> bool:
        validated["called"] = True
        gen._compiler_plan = ["gcc"]
        return True

    with patch.object(gen, "_validate_environment", side_effect=_validate):
        with patch.object(gen, "_resolve_compiler_binary", return_value="/usr/bin/gcc"):
            with patch.object(
                gen,
                "_ensure_binary_for_compiler",
                return_value=tmp_path / "stream",
            ) as ensure_binary:
                gen.prepare()

    assert validated["called"] is True
    assert ensure_binary.call_count == 1
    assert ensure_binary.call_args[0][0] == "gcc"


def test_extracts_stream_table_block() -> None:
    gen = StreamGenerator(StreamConfig())
    sample = """
-------------------------------------------------------------
STREAM version $Revision: 5.10 $
-------------------------------------------------------------
Function    Best Rate MB/s  Avg time     Min time     Max time
Copy:          122606.9     0.003000     0.002610     0.003261
Scale:         122416.8     0.003024     0.002614     0.003695
Add:           115552.2     0.004840     0.004154     0.005549
Triad:         116112.0     0.004869     0.004134     0.005164
-------------------------------------------------------------
Solution Validates: avg error less than 1.000000e-13 on all three arrays
-------------------------------------------------------------
"""
    table = gen._extract_result_table(sample)  # type: ignore[attr-defined]
    assert table is not None
    assert table.startswith("-------------------------------------------------------------")
    assert "Function    Best Rate MB/s" in table
    assert "Triad:" in table
