from unittest.mock import patch, MagicMock
import os
from lb_ui.notifications.manager import NotificationManager
from lb_ui.notifications.providers.desktop import DesktopProvider
from lb_ui.notifications.providers.webhook import WebhookProvider
from lb_ui.notifications.base import NotificationContext

class TestNotificationManager:
    def test_manager_initializes_default_providers(self):
        manager = NotificationManager()
        # Should have at least DesktopProvider
        assert any(isinstance(p, DesktopProvider) for p in manager._providers)

    def test_manager_adds_webhook_if_env_set(self):
        with patch.dict(os.environ, {"LB_WEBHOOK_URL": "http://test"}):
            manager = NotificationManager()
            assert any(isinstance(p, WebhookProvider) for p in manager._providers)

    @patch("threading.Thread")
    @patch("lb_ui.notifications.providers.desktop.DesktopProvider.send")
    def test_manager_dispatches_context(self, mock_send, mock_thread):
        manager = NotificationManager()
        # Mock providers list to only contain the mocked desktop provider
        mock_provider = MagicMock()
        manager._providers = [mock_provider]
        
        # Test logic directly via _dispatch to avoid threading issues
        context = NotificationContext("Title", "Msg", True, "App", None, "123", 10.0)
        manager._dispatch(context)
        
        mock_provider.send.assert_called_once_with(context)
        assert context.title == "Title"
        assert "Msg" in context.message

class TestWebhookProvider:
    @patch("urllib.request.urlopen")
    def test_payload_structure(self, mock_urlopen):
        provider = WebhookProvider("http://url")
        context = NotificationContext("Title", "Msg", True, "App", None, "run-1", 5.5)
        
        provider.send(context)
        
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        import json
        data = json.loads(req.data)
        
        assert data["title"] == "Title"
        assert data["status"] == "success"
        assert data["duration"] == 5.5
        assert "✅" in data["text"]

class TestDesktopProvider:
    @patch("platform.system", return_value="Linux")
    @patch.dict(os.environ, {}, clear=True) # Headless
    def test_headless_linux_skips(self, mock_system):
        provider = DesktopProvider("App")
        with patch("lb_ui.notifications.providers.desktop.notification") as mock_plyer:
            provider.send(NotificationContext("T", "M", True, "App"))
            if mock_plyer:
                mock_plyer.notify.assert_not_called()

    @patch("platform.system", return_value="Darwin")
    @patch("lb_ui.notifications.providers.desktop.DesktopNotifier")
    @patch("asyncio.run")
    def test_macos_desktop_notifier(self, mock_async, mock_dn_cls, mock_system):
        provider = DesktopProvider("App")
        ctx = NotificationContext("T", "M", True, "App", "icon.png")
        
        provider.send(ctx)
        
        mock_dn_cls.assert_called()
        mock_async.assert_called()
