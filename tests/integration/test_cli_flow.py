"""Integration tests for the full CLI sync flow against real Syncthing.

These tests exercise cmd_run and cmd_now with:
- Real Syncthing API (via Docker)
- Stubbed Termux commands (battery, wifi, notifications)
- Syncthing process management mocked out (we don't start/stop Syncthing — Docker does)
"""

import json
import os
from argparse import Namespace
from unittest.mock import patch

import pytest

from syncoid.config import Config
from syncoid.syncthing import Syncthing
from syncoid.cli import cmd_run, cmd_now, cmd_status


pytestmark = pytest.mark.skipif(
    not os.environ.get("SYNCTHING_GUI_ADDR"),
    reason="SYNCTHING_GUI_ADDR not set — skipping integration tests",
)


@pytest.fixture
def configured_env(tmp_config, stubs_on_path):
    """Set up a fully configured Syncoid environment pointing at the Docker Syncthing."""
    gui_addr = os.environ["SYNCTHING_GUI_ADDR"]
    api_key = os.environ.get("SYNCTHING_API_KEY", "test-api-key-for-syncoid")

    config = Config()
    config.gui_addr = gui_addr
    config.api_key = api_key
    config.managed_folders = ["test-folder"]
    config.max_window_min = 1
    config.ondemand_max_wait_min = 1
    config.enable_wakelock = False
    config.notify_on_failure = True
    config.notify_on_success = True
    config.save()

    return config


def _patch_syncthing_lifecycle():
    """Mock start/stop since Syncthing is managed by Docker, not by us."""
    return patch.multiple(
        Syncthing,
        is_running=lambda self: True,
        start=lambda self: True,
        stop=lambda self: None,
    )


class TestCmdRun:
    def test_successful_sync(self, configured_env):
        with _patch_syncthing_lifecycle():
            args = Namespace(force=True)
            rc = cmd_run(args)

        assert rc == 0

        last_run = json.loads(
            (Config.state_dir() / "last_run.json").read_text()
        )
        assert last_run["status"] == "success"
        assert "test-folder" in last_run["folders"]

    def test_skips_when_no_wifi(self, configured_env):
        os.environ["STUB_WIFI_CONNECTED"] = "false"
        os.environ["STUB_NET_TYPE"] = "mobile"
        try:
            args = Namespace(force=False)
            rc = cmd_run(args)
            # Should skip (wifi_only=True by default), return 0
            assert rc == 0
            # No last_run should be written (sync was skipped)
            last_run_file = Config.state_dir() / "last_run.json"
            assert not last_run_file.exists()
        finally:
            os.environ["STUB_WIFI_CONNECTED"] = "true"
            os.environ["STUB_NET_TYPE"] = "wifi"

    def test_force_ignores_conditions(self, configured_env):
        os.environ["STUB_WIFI_CONNECTED"] = "false"
        os.environ["STUB_NET_TYPE"] = "mobile"
        try:
            with _patch_syncthing_lifecycle():
                args = Namespace(force=True)
                rc = cmd_run(args)
            assert rc == 0
        finally:
            os.environ["STUB_WIFI_CONNECTED"] = "true"
            os.environ["STUB_NET_TYPE"] = "wifi"

    def test_skips_low_battery(self, configured_env):
        os.environ["STUB_BATTERY_PCT"] = "5"
        try:
            args = Namespace(force=False)
            rc = cmd_run(args)
            assert rc == 0
        finally:
            os.environ["STUB_BATTERY_PCT"] = "80"


class TestCmdNow:
    def test_on_demand_sync(self, configured_env):
        with _patch_syncthing_lifecycle():
            args = Namespace()
            rc = cmd_now(args)

        assert rc == 0

        last_run = json.loads(
            (Config.state_dir() / "last_run.json").read_text()
        )
        assert last_run["status"] == "ondemand_success"


class TestCmdStatus:
    def test_status_output(self, configured_env, capsys):
        # Write a fake last_run so status has something to display
        state_dir = Config.state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "last_run.json").write_text(json.dumps({
            "timestamp": "2025-01-01T00:00:00",
            "status": "success",
            "folders": ["test-folder"],
        }))

        args = Namespace()
        cmd_status(args)

        output = capsys.readouterr().out
        assert "configured" in output  # API key
        assert "success" in output
        assert "test-folder" in output
