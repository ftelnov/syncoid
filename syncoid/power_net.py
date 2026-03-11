"""Battery and network detection via Termux API."""

import json
import subprocess
from dataclasses import dataclass
from typing import Optional, Union


@dataclass
class BatteryStatus:
    percentage: int
    is_charging: bool
    plugged: str


@dataclass
class NetworkInfo:
    is_wifi: bool
    is_connected: bool
    network_type: str


def _run_termux_api(cmd: str) -> Optional[Union[dict, list]]:
    try:
        result = subprocess.run(
            ["termux-" + cmd],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except Exception:
        pass
    return None


def get_battery_status() -> Optional[BatteryStatus]:
    data = _run_termux_api("battery-status")
    if not data or not isinstance(data, dict):
        return None

    plugged = data.get("plugged", "UNPLUGGED")
    is_charging = plugged in ("PLUGGED_AC", "PLUGGED_USB", "PLUGGED_WIRELESS")
    
    return BatteryStatus(
        percentage=data.get("percentage", 0),
        is_charging=is_charging,
        plugged=plugged,
    )


def get_network_info() -> NetworkInfo:
    wifi_info = _run_termux_api("wifi-connectioninfo")
    is_wifi = isinstance(wifi_info, dict) and "ssid" in wifi_info
    
    conn_info = _run_termux_api("connectivity")
    if conn_info and isinstance(conn_info, list) and len(conn_info) > 0:
        net_type = conn_info[0].get("type", "unknown")
        is_connected = net_type in ("wifi", "mobile", "ethernet")
    else:
        net_type = "unknown"
        is_connected = is_wifi
    
    return NetworkInfo(
        is_wifi=is_wifi,
        is_connected=is_connected,
        network_type=net_type,
    )


def check_sync_conditions(
    wifi_only: bool = True,
    charging_only: bool = False,
    min_battery: int = 20,
) -> tuple[bool, str]:
    battery = get_battery_status()
    network = get_network_info()
    
    if charging_only:
        if not battery or not battery.is_charging:
            return False, "not charging (charging_only enabled)"
    
    if wifi_only:
        if not network.is_wifi:
            return False, "not on WiFi (wifi_only enabled)"
    
    if battery and not battery.is_charging:
        if battery.percentage < min_battery:
            return False, f"battery low ({battery.percentage}% < {min_battery}%)"
    
    return True, "conditions met"


def acquire_wakelock() -> bool:
    try:
        subprocess.run(["termux-wake-lock"], check=True, timeout=5)
        return True
    except Exception:
        return False


def release_wakelock() -> bool:
    try:
        subprocess.run(["termux-wake-unlock"], check=True, timeout=5)
        return True
    except Exception:
        return False


def send_notification(title: str, content: str) -> bool:
    try:
        subprocess.run(
            ["termux-notification", "--title", title, "--content", content],
            check=True,
            timeout=10,
        )
        return True
    except Exception:
        return False
