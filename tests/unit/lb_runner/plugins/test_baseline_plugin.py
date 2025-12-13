"""
Unit tests for the Baseline workload plugin.
"""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest
from lb_runner.plugin_system.interface import WorkloadIntensity
from lb_runner.plugins.baseline.plugin import (
    BaselineConfig,
    BaselineGenerator,
    BaselinePlugin,
    PLUGIN,
)


class TestBaselineConfig:
    def test_defaults(self):
        config = BaselineConfig()
        assert config.duration == 60

    def test_custom_values(self):
        config = BaselineConfig(duration=10)
        assert config.duration == 10


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

    def test_presets(self):
        low = PLUGIN.get_preset_config(WorkloadIntensity.LOW)
        assert low.duration == 30

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


class TestBaselineGenerator:
    def test_validate_environment(self):
        config = BaselineConfig()
        generator = BaselineGenerator(config)
        assert generator._validate_environment() is True

    def test_run_success(self):
        # Run a very short test
        config = BaselineConfig(duration=0) # 0 or very small float
        # Using a small float to ensure logic runs but finishes instantly
        config.duration = 0.01 
        generator = BaselineGenerator(config)
        
        generator._run_command()
        
        result = generator.get_result()
        assert result is not None
        assert result["status"] == "completed"
        assert result["workload"] == "idle"
        assert "actual_duration" in result
        assert result["target_duration"] == 0.01

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
        config = BaselineConfig(duration=100)
        generator = BaselineGenerator(config)
        
        # Setup mocks
        mock_wait.return_value = False  # creating normal timeout expiration (wait returns False if timeout reached? No, wait returns True if flag set, False if timeout)
        # threading.Event.wait returns True if the flag was set, False if timeout occurred.
        # So if we want to simulate "completed duration" (timeout), it returns False.
        
        mock_time.side_effect = [1000.0, 1100.0] # start, end
        
        generator._run_command()
        
        mock_wait.assert_called_with(100)
        result = generator.get_result()
        assert result["status"] == "completed"
        assert result["actual_duration"] == 100.0
