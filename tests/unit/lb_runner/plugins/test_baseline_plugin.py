"""
Unit tests for the Baseline workload plugin.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError # Added ValidationError import
from lb_runner.plugin_system.interface import WorkloadIntensity
from lb_runner.plugins.baseline.plugin import (
    BaselineConfig,
    BaselineGenerator,
    BaselinePlugin,
    PLUGIN,
)

pytestmark = pytest.mark.unit

class TestBaselineConfig:
    def test_defaults(self):
        config = BaselineConfig()
        assert config.duration == 60
        assert config.max_retries == 0 # Inherited default
        assert config.timeout_buffer == 10 # Inherited default
        assert config.tags == [] # Inherited default

    def test_custom_values(self):
        config = BaselineConfig(duration=10, max_retries=5, tags=["e2e", "dev"])
        assert config.duration == 10
        assert config.max_retries == 5
        assert config.tags == ["e2e", "dev"]

    def test_validation_error(self):
        with pytest.raises(ValidationError):
            BaselineConfig(duration=0) # duration must be greater than 0
        with pytest.raises(ValidationError):
            BaselineConfig(duration=-1)
        with pytest.raises(ValidationError):
            BaselineConfig(max_retries=-1) # max_retries must be >= 0


class TestBaselinePlugin:
    def test_metadata(self):
        assert PLUGIN.name == "baseline"
        assert "Idle workload" in PLUGIN.description
        assert PLUGIN.config_cls == BaselineConfig

    def test_factory(self):
        config = BaselineConfig(duration=5)
        generator = PLUGIN.create_generator(config)
        assert isinstance(generator, BaselineGenerator)
        assert generator.config.duration == 5
        assert generator.config.max_retries == 0 # Ensure inherited fields are present

    def test_presets(self):
        low = PLUGIN.get_preset_config(WorkloadIntensity.LOW)
        assert low.duration == 30
        assert low.max_retries == 0 # Inherited default still applies for presets

        medium = PLUGIN.get_preset_config(WorkloadIntensity.MEDIUM)
        assert medium.duration == 60

        high = PLUGIN.get_preset_config(WorkloadIntensity.HIGH)
        assert high.duration == 300

        unknown = PLUGIN.get_preset_config(WorkloadIntensity.USER_DEFINED)
        assert unknown is None

    def test_requirements(self):
        assert PLUGIN.get_required_apt_packages() == []
        assert PLUGIN.get_required_local_tools() == []
        assert PLUGIN.get_dockerfile_path().name == "Dockerfile"


class TestBaselineConfigLoading:
    def test_load_config_from_file_empty(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        loaded_config = PLUGIN.load_config_from_file(config_file)
        assert isinstance(loaded_config, BaselineConfig)
        assert loaded_config.duration == 60
        assert loaded_config.max_retries == 0
        assert loaded_config.tags == []

    def test_load_config_from_file_common_only(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
common:
  max_retries: 5
  tags: ["common-tag"]
""")
        loaded_config = PLUGIN.load_config_from_file(config_file)
        assert isinstance(loaded_config, BaselineConfig)
        assert loaded_config.duration == 60  # From BaselineConfig default
        assert loaded_config.max_retries == 5  # From common
        assert loaded_config.tags == ["common-tag"]

    def test_load_config_from_file_plugin_specific_only(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
plugins:
  baseline:
    duration: 120
    timeout_buffer: 50
""")
        loaded_config = PLUGIN.load_config_from_file(config_file)
        assert isinstance(loaded_config, BaselineConfig)
        assert loaded_config.duration == 120  # From plugin specific
        assert loaded_config.max_retries == 0  # From BasePluginConfig default
        assert loaded_config.timeout_buffer == 50

    def test_load_config_from_file_with_override(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
common:
  max_retries: 5
  tags: ["common-tag"]
plugins:
  baseline:
    duration: 120
    max_retries: 10 # Plugin-specific overrides common
    tags: ["baseline-tag"] # Plugin-specific overrides common
""")
        loaded_config = PLUGIN.load_config_from_file(config_file)
        assert isinstance(loaded_config, BaselineConfig)
        assert loaded_config.duration == 120
        assert loaded_config.max_retries == 10
        assert loaded_config.tags == ["baseline-tag"]

    def test_load_config_from_file_invalid_data(self, tmp_path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text("""
plugins:
  baseline:
    duration: 0 # Invalid duration (must be gt 0)
""")
        with pytest.raises(ValidationError):
            PLUGIN.load_config_from_file(config_file)

    def test_load_config_from_file_not_found(self, tmp_path):
        non_existent_file = tmp_path / "non_existent_config.yaml"
        with pytest.raises(FileNotFoundError):
            PLUGIN.load_config_from_file(non_existent_file)


class TestBaselineGenerator:
    def test_validate_environment(self):
        config = BaselineConfig()
        generator = BaselineGenerator(config)
        assert generator._validate_environment() is True

    def test_run_success(self):
        # Run a very short test
        config = BaselineConfig(duration=0.01) # duration must be > 0
        generator = BaselineGenerator(config)
        
        generator._run_command()
        
        result = generator.get_result()
        assert result is not None
        assert result["status"] == "completed"
        assert result["workload"] == "idle"
        assert "actual_duration" in result
        assert result["target_duration"] == 0.01
        assert result["max_retries"] == 0 # Check inherited field in result
        assert result["tags"] == [] # Check inherited field in result


    def test_stop_early(self):
        """Test that the generator can be stopped before duration expires."""
        config = BaselineConfig(duration=2)  # Long enough to intercept
        generator = BaselineGenerator(config)
        
        # Start in a thread (using the public start/stop interface would be integration, 
        # but here we test the internal logic via _run_command or by simulating threading)
        
        # We'll use a thread to run _run_command so we can stop it from main thread
        t = threading.Thread(target=generator._run_command)
        t.start()
        
        # Give it a moment to start waiting
        time.sleep(0.1)
        
        # Stop it
        generator._stop_workload()
        t.join(timeout=1.0)
        
        assert not t.is_alive()
        result = generator.get_result()
        assert result["status"] == "stopped"
        # Duration should be much less than 2s
        assert result["actual_duration"] < 1.0

    @patch("time.time")
    @patch("threading.Event.wait")
    def test_run_logic_mocked(self, mock_wait, mock_time):
        """Verify logic without actual sleeping using mocks."""
        config = BaselineConfig(duration=100, max_retries=3, tags=["mocked"])
        generator = BaselineGenerator(config)
        
        # Setup mocks
        mock_wait.return_value = False  # Simulate duration completion (timeout)
        
        mock_time.side_effect = [1000.0, 1100.0] # start, end (100s duration)
        
        generator._run_command()
        
        mock_wait.assert_called_with(100) # Ensure duration is passed to wait
        result = generator.get_result()
        assert result["status"] == "completed"
        assert result["actual_duration"] == 100.0
        assert result["max_retries"] == 3 # Check inherited field in result
        assert result["tags"] == ["mocked"] # Check inherited field in result
