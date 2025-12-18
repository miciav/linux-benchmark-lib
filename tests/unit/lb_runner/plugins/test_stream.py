"""Unit tests for the STREAM workload plugin logic."""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from lb_runner.plugins.stream.plugin import (
    DEFAULT_NTIMES,
    DEFAULT_STREAM_ARRAY_SIZE,
    StreamConfig,
    StreamGenerator,
    StreamPlugin,
)

pytestmark = pytest.mark.runner

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


def test_plugin_metadata():
    plugin = StreamPlugin()
    assert plugin.name == "stream"
    assert "STREAM" in plugin.description
    assert plugin.config_cls is StreamConfig


def test_needs_recompile(stream_config):
    gen = StreamGenerator(stream_config)
    assert not gen._needs_recompile()

    stream_config.recompile = True
    assert gen._needs_recompile()

    stream_config.recompile = False
    stream_config.stream_array_size = DEFAULT_STREAM_ARRAY_SIZE + 100
    assert gen._needs_recompile()

    stream_config.stream_array_size = DEFAULT_STREAM_ARRAY_SIZE
    stream_config.ntimes = DEFAULT_NTIMES + 5
    assert gen._needs_recompile()


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


@patch("lb_runner.plugins.stream.plugin.shutil.which")
def test_validate_environment_missing_gcc_for_recompile(mock_which, stream_config):
    stream_config.recompile = True
    mock_which.return_value = None  # gcc missing
    
    gen = StreamGenerator(stream_config)
    assert gen._validate_environment() is False


@patch("lb_runner.plugins.stream.plugin.shutil.which")
def test_validate_environment_missing_numactl(mock_which, stream_config):
    stream_config.use_numactl = True
    mock_which.side_effect = lambda cmd: "/usr/bin/gcc" if cmd == "gcc" else None # numactl missing
    
    gen = StreamGenerator(stream_config)
    assert gen._validate_environment() is False


@patch("lb_runner.plugins.stream.plugin.subprocess.run")
@patch("lb_runner.plugins.stream.plugin.shutil.copy2")
def test_compile_binary_success(mock_copy, mock_run, stream_generator, tmp_path):
    # Mock workspace dirs
    stream_generator.workspace_src_dir = tmp_path / "src"
    stream_generator.workspace_bin_dir = tmp_path / "bin"
    stream_generator.workspace_src_dir.mkdir(parents=True)
    stream_generator.workspace_bin_dir.mkdir(parents=True)
    
    # Create a dummy output file to simulate successful compilation
    (stream_generator.workspace_bin_dir / "stream").touch()

    # Mock upstream file existence check
    with patch.object(StreamGenerator, "_upstream_stream_c", return_value=Path("/upstream/stream.c")):
        mock_run.return_value = MagicMock(returncode=0)
        
        out_path = stream_generator._compile_binary()
        
        assert out_path == stream_generator.workspace_bin_dir / "stream"
        assert mock_run.called
        args = mock_run.call_args[0][0]
        assert "gcc" in args
        assert f"-DSTREAM_ARRAY_SIZE={DEFAULT_STREAM_ARRAY_SIZE}" in args


@patch("lb_runner.plugins.stream.plugin.subprocess.run")
def test_compile_binary_failure(mock_run, stream_generator, tmp_path):
    stream_generator.workspace_src_dir = tmp_path / "src"
    stream_generator.workspace_bin_dir = tmp_path / "bin"
    
    with patch.object(StreamGenerator, "_upstream_stream_c", return_value=Path("/upstream/stream.c")):
        with patch("lb_runner.plugins.stream.plugin.shutil.copy2"):
            # Simulate gcc failure
            mock_run.return_value = MagicMock(returncode=1, stderr="Compilation error")
            
            with pytest.raises(RuntimeError) as exc:
                stream_generator._compile_binary()
            
            assert "Failed to compile STREAM" in str(exc.value)


@patch("lb_runner.plugins.stream.plugin.os.access")
def test_ensure_binary_uses_system_if_available(mock_access, stream_generator):
    # recompile is False by default
    
    # Mock system path exists and is executable, but workspace path does NOT exist
    def side_effect(self):
        if self == stream_generator.system_stream_path:
            return True
        return False

    with patch.object(Path, "exists", side_effect=side_effect, autospec=True):
        mock_access.return_value = True
        
        assert stream_generator._ensure_binary() is True
        assert stream_generator.stream_path == stream_generator.system_stream_path


@patch("lb_runner.plugins.stream.plugin.os.access")
def test_ensure_binary_fails_if_nothing_available(mock_access, stream_generator):
    # Mock nothing exists
    with patch.object(Path, "exists", return_value=False):
        assert stream_generator._ensure_binary() is False
        assert "stream binary missing" in stream_generator._result["error"]
