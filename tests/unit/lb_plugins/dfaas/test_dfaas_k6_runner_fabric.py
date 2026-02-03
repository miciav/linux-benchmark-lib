"""Unit tests for the Fabric-based K6Runner."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, ANY

import pytest
from fabric import Connection
from invoke.exceptions import UnexpectedExit

from lb_plugins.plugins.peva_faas.services.k6_runner import K6Runner, K6ExecutionError
from lb_plugins.plugins.peva_faas.config import DfaasFunctionConfig


@pytest.fixture
def k6_runner():
    return K6Runner(
        k6_host="1.2.3.4",
        k6_user="testuser",
        k6_ssh_key="/tmp/key",
        k6_port=2222,
        k6_workspace_root="/home/test/.dfaas-k6",
        gateway_url="http://gateway:8080",
        duration="10s",
        log_stream_enabled=True,
    )


class TestK6RunnerFabric:
    
    @patch("lb_plugins.plugins.peva_faas.services.k6_runner.Connection")
    def test_get_connection(self, mock_conn_cls, k6_runner):
        """Test Fabric connection initialization."""
        conn = k6_runner._get_connection()
        
        mock_conn_cls.assert_called_once_with(
            host="1.2.3.4",
            user="testuser",
            port=2222,
            connect_kwargs={
                "key_filename": "/tmp/key",
                "banner_timeout": 30,
            }
        )
        assert conn == mock_conn_cls.return_value

    @patch("lb_plugins.plugins.peva_faas.services.k6_runner.Connection")
    @patch("tempfile.NamedTemporaryFile")
    @patch("pathlib.Path.read_text")
    @patch("os.unlink")
    def test_execute_success(self, mock_unlink, mock_read_text, mock_tempfile, mock_conn_cls, k6_runner):
        """Test successful execution flow."""
        # Mock connection and run results
        mock_conn = mock_conn_cls.return_value
        mock_run_result = MagicMock()
        mock_run_result.failed = False
        mock_run_result.exited = 0
        mock_conn.run.return_value = mock_run_result
        
        # Mock temp files (script and summary download)
        mock_file = MagicMock()
        mock_file.name = "/tmp/local_script.js"
        mock_tempfile.return_value.__enter__.return_value = mock_file
        
        # Mock summary content
        mock_read_text.return_value = json.dumps({"metrics": {"http_reqs": 100}})

        # Execute
        test_metric_ids = {"fn1": "fn_1", "fn2": "fn_2"}
        result = k6_runner.execute(
            config_id="cfg1",
            script="import k6...",
            target_name="target1",
            run_id="run1",
            metric_ids=test_metric_ids,
        )

        # 1. Verify Workspace Creation
        remote_ws = "/home/test/.dfaas-k6/target1/run1/cfg1"
        mock_conn.run.assert_any_call(
            f"mkdir -p {remote_ws}", hide=True, in_stream=False
        )

        # 2. Verify Script Upload
        mock_conn.put.assert_any_call("/tmp/local_script.js", f"{remote_ws}/script.js")

        # 3. Verify Execution
        expected_cmd = (
            f"k6 run --summary-export {remote_ws}/summary.json "
            f"{remote_ws}/script.js 2>&1 | tee {remote_ws}/k6.log"
        )
        # out_stream is a _StreamWriter wrapper, so we use ANY
        mock_conn.run.assert_any_call(
            expected_cmd,
            hide=True,
            out_stream=ANY,
            warn=True,
            in_stream=False,
        )

        # 4. Verify Summary Download
        # Note: tempfile is called twice (script, then summary download)
        # We assume the second name generated is used for get
        mock_conn.get.assert_called() # Exact path match is tricky with shared mock_file name

        # 5. Verify Cleanup
        assert mock_unlink.call_count == 2 # Script and Summary local temp files
        mock_conn.close.assert_called_once()

        # 6. Verify Result
        assert result.summary == {"metrics": {"http_reqs": 100}}
        assert result.config_id == "cfg1"
        assert result.metric_ids == test_metric_ids

    @patch("lb_plugins.plugins.peva_faas.services.k6_runner.Connection")
    @patch("tempfile.NamedTemporaryFile")
    @patch("os.unlink")
    def test_execute_failure_k6_error(self, mock_unlink, mock_tempfile, mock_conn_cls, k6_runner):
        """Test handling of k6 non-zero exit code."""
        mock_conn = mock_conn_cls.return_value
        
        # First run (mkdir) succeeds
        # Second run (k6) fails
        success_result = MagicMock(failed=False)
        failure_result = MagicMock(failed=True, exited=99, stdout="Error log", stderr="Fatal error")
        
        mock_conn.run.side_effect = [success_result, failure_result]
        
        mock_file = MagicMock()
        mock_tempfile.return_value.__enter__.return_value = mock_file

        with pytest.raises(K6ExecutionError) as excinfo:
            k6_runner.execute("cfg1", "script", "t1", "r1", {"fn": "fn_id"})

        assert "k6 failed with exit code 99" in str(excinfo.value)
        assert excinfo.value.stdout == "Error log"
        mock_conn.close.assert_called()

    @patch("lb_plugins.plugins.peva_faas.services.k6_runner.Connection")
    @patch("tempfile.NamedTemporaryFile")
    @patch("os.unlink")
    def test_execute_failure_ssh_error(self, mock_unlink, mock_tempfile, mock_conn_cls, k6_runner):
        """Test handling of SSH transport errors (UnexpectedExit)."""
        mock_conn = mock_conn_cls.return_value
        
        # Simulate SSH dropping during k6 run
        mock_conn.run.side_effect = [
            MagicMock(), # mkdir
            UnexpectedExit(MagicMock(command="k6 run", exited=255, stderr="Connection reset")) # k6
        ]
        
        mock_file = MagicMock()
        mock_tempfile.return_value.__enter__.return_value = mock_file

        with pytest.raises(K6ExecutionError) as excinfo:
            k6_runner.execute("cfg1", "script", "t1", "r1", {"fn": "fn_id"})

        assert "k6 ssh execution failed" in str(excinfo.value)
        # Verify the wrapper exception message contains the underlying cause
        # Note: UnexpectedExit str() might be verbose, but our wrapper includes it.
        # We rely on "k6 ssh execution failed" which we added explicitly.
        mock_conn.close.assert_called()

    def test_stream_handler(self, k6_runner):
        """Test log streaming callback."""
        mock_callback = MagicMock()
        k6_runner._log_callback = mock_callback
        
        chunk = "Line 1\nLine 2  "
        k6_runner._stream_handler(chunk)
        
        assert mock_callback.call_count == 2
        mock_callback.assert_any_call("k6 remote: Line 1")
        mock_callback.assert_any_call("k6 remote: Line 2")

