import pytest
from unittest.mock import patch, MagicMock, ANY
import os
import platform
from lb_ui.services import notifier

class TestNotifier:
    def test_send_notification_composite_logic(self):
        """Test that send_notification dispatches to engines."""
        # We patch the engines themselves to see if they are called
        with patch("lb_ui.services.notifier.DesktopEngine.send") as mock_desktop_send:
            notifier.send_notification(
                title="Test",
                message="Msg",
                run_id="run-123",
                duration_s=10.5
            )
            
            mock_desktop_send.assert_called_once()
            args = mock_desktop_send.call_args[0]
            # Verify enrichment
            assert "run-123" in args[0]
            assert "Duration: 10.5s" in args[1]

    def test_webhook_engine_called_when_env_present(self):
        """Test that WebhookEngine is used when env var is set."""
        with patch.dict(os.environ, {"LB_WEBHOOK_URL": "http://hooks.slack.com/services/XXX"}), \
             patch("lb_ui.services.notifier.WebhookEngine.send") as mock_webhook_send, \
             patch("lb_ui.services.notifier.DesktopEngine.send"):
            
            notifier.send_notification("Title", "Message")
            mock_webhook_send.assert_called_once()

    @patch("urllib.request.urlopen")
    def test_webhook_payload(self, mock_urlopen):
        """Test that WebhookEngine sends correct JSON payload."""
        from lb_ui.services.notifier import WebhookEngine
        engine = WebhookEngine("http://test.url")
        
        engine.send("My Title", "My Message", True, None)
        
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert req.get_full_url() == "http://test.url"
        # Check payload
        import json
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["title"] == "My Title"
        assert "My Message" in payload["text"]

    def test_headless_detection_linux(self):
        """Test that DesktopEngine skips on Linux when headless."""
        from lb_ui.services.notifier import DesktopEngine
        engine = DesktopEngine("App")
        
        with patch("platform.system", return_value="Linux"), \
             patch.dict(os.environ, {}, clear=True): # Ensure NO DISPLAY
            
            # Use a mock for internal notification calls
            with patch("lb_ui.services.notifier.notification") as mock_plyer:
                engine.send("T", "M", True, None)
                mock_plyer.notify.assert_not_called()

    def test_desktop_engine_macos_uses_correct_backends(self):
        """Test macOS path in DesktopEngine."""
        from lb_ui.services.notifier import DesktopEngine
        engine = DesktopEngine("App")
        
        with patch("platform.system", return_value="Darwin"), \
             patch("lb_ui.services.notifier.DesktopNotifier") as mock_dn_cls, \
             patch("asyncio.run") as mock_async_run:
            
            engine.send("T", "M", True, "/path/icon.png")
            
            mock_dn_cls.assert_called_once_with(app_name="App", app_icon="/path/icon.png")
            mock_async_run.assert_called_once()