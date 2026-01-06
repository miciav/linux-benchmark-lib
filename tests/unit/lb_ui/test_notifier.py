
import pytest
from unittest.mock import patch, MagicMock
import logging

# We import the module under test inside tests to facilitate patching imports if needed,
# but standard patching of the imported symbol usually works better.
from lb_ui.services import notifier

class TestNotifier:
    def test_send_notification_success_linux(self):
        """Test standard successful notification via plyer (Linux)."""
        with patch("lb_ui.services.notifier.notification") as mock_notification, \
             patch("platform.system", return_value="Linux"), \
             patch("lb_ui.services.notifier._resolve_icon_path", return_value="/tmp/icon.png"):
            
            notifier.send_notification(
                title="Test Title",
                message="Test Message",
                success=True
            )
            
            mock_notification.notify.assert_called_once()
            args, kwargs = mock_notification.notify.call_args
            assert kwargs["title"] == "Test Title"
            assert kwargs["message"] == "Test Message"
            assert kwargs["app_name"] == "Linux Benchmark Lib"
            assert kwargs["app_icon"] == "/tmp/icon.png"

    def test_send_notification_macos(self):
        """Test notification via osascript on macOS."""
        with patch("platform.system", return_value="Darwin"), \
             patch("subprocess.run") as mock_run:
            notifier.send_notification("Title", "Message")
            
            mock_run.assert_called_once()
            args, _ = mock_run.call_args
            cmd = args[0]
            assert cmd[0] == "osascript"
            assert 'display notification "Message" with title "Title"' in cmd[2]

    def test_send_notification_plyer_missing(self):
        """Test behavior when plyer is not installed (notification module is None) on Linux."""
        with patch("lb_ui.services.notifier.notification", None), \
             patch("platform.system", return_value="Linux"):
            # This should just log a debug message and return, not crash
            notifier.send_notification("Title", "Message")

    def test_send_notification_exception_handling(self, caplog):
        """Test that exceptions from plyer are caught and logged (Linux)."""
        with patch("lb_ui.services.notifier.notification") as mock_notification, \
             patch("platform.system", return_value="Linux"):
            # Simulate an error from the underlying library
            mock_notification.notify.side_effect = Exception("DBus connection failed")
            
            with caplog.at_level(logging.WARNING):
                notifier.send_notification("Title", "Message")
            
            assert "Failed to send system notification" in caplog.text
            assert "DBus connection failed" in caplog.text

    def test_send_notification_custom_timeout(self):
        """Test that timeout parameter is passed correctly (Linux)."""
        with patch("lb_ui.services.notifier.notification") as mock_notification, \
             patch("platform.system", return_value="Linux"):
            notifier.send_notification("T", "M", timeout=30)
            mock_notification.notify.assert_called_once()
            assert mock_notification.notify.call_args[1]["timeout"] == 30
