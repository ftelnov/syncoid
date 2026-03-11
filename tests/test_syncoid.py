"""Tests for Syncoid."""

import os
import tempfile
from unittest.mock import patch, MagicMock
from pathlib import Path

from syncoid.config import Config
from syncoid.syncthing import Syncthing
from syncoid.power_net import BatteryStatus, NetworkInfo, check_sync_conditions


def _with_tmp_config(func):
    """Run a test function with SYNCOID_CONFIG_DIR pointing to a temp directory."""
    def wrapper(*args, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            old_env = os.environ.get("SYNCOID_CONFIG_DIR")
            os.environ["SYNCOID_CONFIG_DIR"] = tmp
            try:
                return func(tmp, *args, **kwargs)
            finally:
                if old_env is not None:
                    os.environ["SYNCOID_CONFIG_DIR"] = old_env
                else:
                    os.environ.pop("SYNCOID_CONFIG_DIR", None)
    return wrapper


def test_config_defaults():
    config = Config()
    assert config.period_hours == 0.5
    assert config.wifi_only is True
    assert config.charging_only is False
    assert config.min_battery_pct == 20
    assert config.enable_wakelock is False
    assert config.notify_on_failure is True
    print("✓ Config defaults")


@_with_tmp_config
def test_config_save_load(tmp):
    config = Config()
    config.api_key = "test-key"
    config.period_hours = 2.0
    config.wifi_only = False
    config.save()

    loaded = Config.load()
    assert loaded.api_key == "test-key"
    assert loaded.period_hours == 2.0
    assert loaded.wifi_only is False
    print("✓ Config save/load")


def test_wifi_only_condition():
    with patch('syncoid.power_net.get_battery_status') as mock_battery, \
         patch('syncoid.power_net.get_network_info') as mock_network:

        mock_battery.return_value = BatteryStatus(80, False, "UNPLUGGED")

        mock_network.return_value = NetworkInfo(False, True, "mobile")
        ok, reason = check_sync_conditions(wifi_only=True)
        assert ok is False
        assert "not on WiFi" in reason

        mock_network.return_value = NetworkInfo(True, True, "wifi")
        ok, reason = check_sync_conditions(wifi_only=True)
        assert ok is True

    print("✓ WiFi-only condition")


def test_low_battery_blocks():
    with patch('syncoid.power_net.get_battery_status') as mock_battery, \
         patch('syncoid.power_net.get_network_info') as mock_network:

        mock_battery.return_value = BatteryStatus(10, False, "UNPLUGGED")
        mock_network.return_value = NetworkInfo(True, True, "wifi")

        ok, reason = check_sync_conditions(wifi_only=False, min_battery=20)
        assert ok is False
        assert "battery low" in reason

    print("✓ Low battery blocks sync")


def test_charging_bypasses_battery_check():
    with patch('syncoid.power_net.get_battery_status') as mock_battery, \
         patch('syncoid.power_net.get_network_info') as mock_network:

        mock_battery.return_value = BatteryStatus(5, True, "PLUGGED_AC")
        mock_network.return_value = NetworkInfo(True, True, "wifi")

        ok, reason = check_sync_conditions(wifi_only=False, min_battery=20)
        assert ok is True

    print("✓ Charging bypasses low battery")


@_with_tmp_config
def test_syncthing_is_running_no_pid(tmp):
    config = Config()
    config.api_key = "test"

    st = Syncthing(config)
    assert st.is_running() is False

    print("✓ Syncthing is_running (no PID)")


@_with_tmp_config
def test_needs_sync(tmp):
    config = Config()
    config.api_key = "test"

    st = Syncthing(config)

    with patch.object(st, 'folder_status') as mock_status:
        mock_status.return_value = {"state": "idle", "needBytes": 0}
        assert st.needs_sync("default") is False

        mock_status.return_value = {"state": "syncing", "needBytes": 1000}
        assert st.needs_sync("default") is True

        mock_status.return_value = {"state": "idle", "needBytes": 500}
        assert st.needs_sync("default") is True

    print("✓ Syncthing needs_sync")


@_with_tmp_config
def test_wait_ready_checks_process(tmp):
    config = Config()
    config.api_key = "test"

    st = Syncthing(config)
    # No PID file → is_running returns False → wait_ready should fail fast
    assert st.wait_ready(timeout=2) is False

    print("✓ wait_ready fails when process not running")


@_with_tmp_config
def test_stop_always_cleans_pid(tmp):
    config = Config()
    config.api_key = "test"

    st = Syncthing(config)
    # Write a stale PID file with a PID that doesn't exist
    st.pid_file.parent.mkdir(parents=True, exist_ok=True)
    st.pid_file.write_text("999999999")

    st.stop()
    assert not st.pid_file.exists()

    print("✓ stop cleans up stale PID file")


if __name__ == "__main__":
    test_config_defaults()
    test_config_save_load()
    test_wifi_only_condition()
    test_low_battery_blocks()
    test_charging_bypasses_battery_check()
    test_syncthing_is_running_no_pid()
    test_needs_sync()
    test_wait_ready_checks_process()
    test_stop_always_cleans_pid()
    print("\nAll tests passed!")
