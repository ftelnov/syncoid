"""Power and network module tests — conditions logic, stub integration."""

from unittest.mock import patch

import pytest

from syncoid.power_net import (
    BatteryStatus,
    NetworkInfo,
    check_sync_conditions,
    get_battery_status,
    get_network_info,
    send_notification,
    acquire_wakelock,
    release_wakelock,
)


class TestCheckSyncConditions:
    """Test the condition-checking logic with mocked battery/network."""

    def _mock(self, battery, network):
        return (
            patch("syncoid.power_net.get_battery_status", return_value=battery),
            patch("syncoid.power_net.get_network_info", return_value=network),
        )

    def test_all_conditions_met(self):
        with self._mock(
            BatteryStatus(80, False, "UNPLUGGED"),
            NetworkInfo(True, True, "wifi"),
        )[0], self._mock(
            BatteryStatus(80, False, "UNPLUGGED"),
            NetworkInfo(True, True, "wifi"),
        )[1]:
            ok, reason = check_sync_conditions(wifi_only=True, min_battery=20)
            assert ok is True

    def test_wifi_only_blocks_on_mobile(self):
        with patch("syncoid.power_net.get_battery_status",
                   return_value=BatteryStatus(80, False, "UNPLUGGED")), \
             patch("syncoid.power_net.get_network_info",
                   return_value=NetworkInfo(False, True, "mobile")):
            ok, reason = check_sync_conditions(wifi_only=True)
            assert ok is False
            assert "WiFi" in reason

    def test_wifi_only_false_allows_mobile(self):
        with patch("syncoid.power_net.get_battery_status",
                   return_value=BatteryStatus(80, False, "UNPLUGGED")), \
             patch("syncoid.power_net.get_network_info",
                   return_value=NetworkInfo(False, True, "mobile")):
            ok, _ = check_sync_conditions(wifi_only=False)
            assert ok is True

    def test_charging_only_blocks_when_unplugged(self):
        with patch("syncoid.power_net.get_battery_status",
                   return_value=BatteryStatus(100, False, "UNPLUGGED")), \
             patch("syncoid.power_net.get_network_info",
                   return_value=NetworkInfo(True, True, "wifi")):
            ok, reason = check_sync_conditions(charging_only=True)
            assert ok is False
            assert "not charging" in reason

    def test_charging_only_allows_when_plugged(self):
        with patch("syncoid.power_net.get_battery_status",
                   return_value=BatteryStatus(50, True, "PLUGGED_AC")), \
             patch("syncoid.power_net.get_network_info",
                   return_value=NetworkInfo(True, True, "wifi")):
            ok, _ = check_sync_conditions(charging_only=True, wifi_only=False)
            assert ok is True

    def test_charging_only_blocks_when_battery_unavailable(self):
        with patch("syncoid.power_net.get_battery_status", return_value=None), \
             patch("syncoid.power_net.get_network_info",
                   return_value=NetworkInfo(True, True, "wifi")):
            ok, reason = check_sync_conditions(charging_only=True, wifi_only=False)
            assert ok is False
            assert "not charging" in reason

    def test_low_battery_blocks(self):
        with patch("syncoid.power_net.get_battery_status",
                   return_value=BatteryStatus(10, False, "UNPLUGGED")), \
             patch("syncoid.power_net.get_network_info",
                   return_value=NetworkInfo(True, True, "wifi")):
            ok, reason = check_sync_conditions(wifi_only=False, min_battery=20)
            assert ok is False
            assert "battery low" in reason
            assert "10%" in reason

    def test_low_battery_ignored_when_charging(self):
        with patch("syncoid.power_net.get_battery_status",
                   return_value=BatteryStatus(5, True, "PLUGGED_USB")), \
             patch("syncoid.power_net.get_network_info",
                   return_value=NetworkInfo(True, True, "wifi")):
            ok, _ = check_sync_conditions(wifi_only=False, min_battery=20)
            assert ok is True

    def test_battery_unavailable_skips_battery_check(self):
        with patch("syncoid.power_net.get_battery_status", return_value=None), \
             patch("syncoid.power_net.get_network_info",
                   return_value=NetworkInfo(True, True, "wifi")):
            ok, _ = check_sync_conditions(wifi_only=False, min_battery=20)
            assert ok is True

    def test_exact_battery_threshold_passes(self):
        with patch("syncoid.power_net.get_battery_status",
                   return_value=BatteryStatus(20, False, "UNPLUGGED")), \
             patch("syncoid.power_net.get_network_info",
                   return_value=NetworkInfo(True, True, "wifi")):
            ok, _ = check_sync_conditions(wifi_only=False, min_battery=20)
            assert ok is True

    def test_one_below_threshold_blocks(self):
        with patch("syncoid.power_net.get_battery_status",
                   return_value=BatteryStatus(19, False, "UNPLUGGED")), \
             patch("syncoid.power_net.get_network_info",
                   return_value=NetworkInfo(True, True, "wifi")):
            ok, _ = check_sync_conditions(wifi_only=False, min_battery=20)
            assert ok is False

    def test_condition_check_order_charging_before_wifi(self):
        """charging_only is checked before wifi_only."""
        with patch("syncoid.power_net.get_battery_status",
                   return_value=BatteryStatus(80, False, "UNPLUGGED")), \
             patch("syncoid.power_net.get_network_info",
                   return_value=NetworkInfo(False, True, "mobile")):
            ok, reason = check_sync_conditions(
                charging_only=True, wifi_only=True, min_battery=20,
            )
            assert ok is False
            # Should fail on charging first, not wifi
            assert "not charging" in reason


class TestGetBatteryStatusWithStubs:
    """Test get_battery_status against the shell stubs (requires stubs on PATH)."""

    def test_default_battery(self, stubs_on_path):
        status = get_battery_status()
        assert status is not None
        assert status.percentage == 80
        assert status.is_charging is False
        assert status.plugged == "UNPLUGGED"

    def test_charging_battery(self, stubs_on_path, monkeypatch):
        monkeypatch.setenv("STUB_BATTERY_PCT", "50")
        monkeypatch.setenv("STUB_BATTERY_PLUGGED", "PLUGGED_AC")
        status = get_battery_status()
        assert status is not None
        assert status.percentage == 50
        assert status.is_charging is True
        assert status.plugged == "PLUGGED_AC"

    def test_usb_charging(self, stubs_on_path, monkeypatch):
        monkeypatch.setenv("STUB_BATTERY_PLUGGED", "PLUGGED_USB")
        status = get_battery_status()
        assert status.is_charging is True

    def test_wireless_charging(self, stubs_on_path, monkeypatch):
        monkeypatch.setenv("STUB_BATTERY_PLUGGED", "PLUGGED_WIRELESS")
        status = get_battery_status()
        assert status.is_charging is True


class TestGetNetworkInfoWithStubs:
    def test_wifi_connected(self, stubs_on_path):
        info = get_network_info()
        assert info.is_wifi is True
        assert info.network_type == "wifi"

    def test_wifi_disconnected(self, stubs_on_path, monkeypatch):
        monkeypatch.setenv("STUB_WIFI_CONNECTED", "false")
        monkeypatch.setenv("STUB_NET_TYPE", "mobile")
        info = get_network_info()
        assert info.is_wifi is False
        assert info.network_type == "mobile"


class TestNotificationWithStubs:
    def test_send_notification(self, stubs_on_path, tmp_path, monkeypatch):
        log_file = tmp_path / "notif.log"
        monkeypatch.setenv("STUB_NOTIFICATION_LOG", str(log_file))
        assert send_notification("Test Title", "Test Body") is True
        content = log_file.read_text()
        assert "Test Title" in content
        assert "Test Body" in content


class TestWakelockWithStubs:
    def test_acquire(self, stubs_on_path):
        assert acquire_wakelock() is True

    def test_release(self, stubs_on_path):
        assert release_wakelock() is True
