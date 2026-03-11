"""Integration tests against a real Syncthing instance.

Run with: docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
Or locally if Syncthing is running (set SYNCTHING_GUI_ADDR and SYNCTHING_API_KEY).
"""

import os
import pytest

from syncoid.config import Config
from syncoid.syncthing import Syncthing


pytestmark = pytest.mark.skipif(
    not os.environ.get("SYNCTHING_GUI_ADDR"),
    reason="SYNCTHING_GUI_ADDR not set — skipping integration tests",
)


@pytest.fixture
def syncthing(tmp_config):
    gui_addr = os.environ["SYNCTHING_GUI_ADDR"]
    api_key = os.environ.get("SYNCTHING_API_KEY", "test-api-key-for-syncoid")

    config = Config()
    config.gui_addr = gui_addr
    config.api_key = api_key
    return Syncthing(config)


class TestSyncthingConnection:
    def test_ping(self, syncthing):
        result = syncthing._request("system/ping")
        assert result is not None
        assert result.get("ping") == "pong"

    def test_system_status(self, syncthing):
        status = syncthing.system_status()
        assert "myID" in status
        assert "startTime" in status

    def test_list_folders(self, syncthing):
        folders = syncthing.list_folders()
        assert isinstance(folders, list)
        assert "test-folder" in folders

    def test_folder_status(self, syncthing):
        status = syncthing.folder_status("test-folder")
        assert "state" in status
        # A freshly started folder with no peers should be idle
        assert status["state"] in ("idle", "scanning", "scan-waiting")

    def test_scan(self, syncthing):
        assert syncthing.scan("test-folder") is True

    def test_scan_nonexistent_folder(self, syncthing):
        assert syncthing.scan("does-not-exist") is False

    def test_needs_sync_idle(self, syncthing):
        # With no peers, folder should eventually be idle with nothing to sync
        syncthing.wait_synced("test-folder", timeout=15)
        assert syncthing.needs_sync("test-folder") is False

    def test_wait_synced(self, syncthing):
        # Should complete quickly since there are no peers to sync with
        assert syncthing.wait_synced("test-folder", timeout=30) is True


class TestSyncthingNotRunning:
    """Test behavior when Syncthing API is unreachable."""

    def test_request_raises_on_bad_addr(self, tmp_config):
        config = Config()
        config.gui_addr = "127.0.0.1:1"  # nothing listening
        config.api_key = "fake"
        st = Syncthing(config)

        with pytest.raises(Exception):
            st._request("system/ping")

    def test_folder_status_returns_empty_on_bad_addr(self, tmp_config):
        config = Config()
        config.gui_addr = "127.0.0.1:1"
        config.api_key = "fake"
        st = Syncthing(config)

        assert st.folder_status("any") == {}

    def test_list_folders_returns_empty_on_bad_addr(self, tmp_config):
        config = Config()
        config.gui_addr = "127.0.0.1:1"
        config.api_key = "fake"
        st = Syncthing(config)

        assert st.list_folders() == []
