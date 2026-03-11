"""Tests that verify the Termux API stubs work correctly."""

import json
import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def stubs_in_path(stubs_on_path):
    yield


class TestBatteryStub:
    def test_default_output(self):
        result = subprocess.run(
            ["termux-battery-status"], capture_output=True, text=True, timeout=5
        )
        data = json.loads(result.stdout)
        assert data["percentage"] == 80
        assert data["plugged"] == "UNPLUGGED"
        assert data["status"] == "DISCHARGING"

    def test_charging(self):
        env = {**os.environ, "STUB_BATTERY_PCT": "50", "STUB_BATTERY_PLUGGED": "PLUGGED_AC"}
        result = subprocess.run(
            ["termux-battery-status"], capture_output=True, text=True, timeout=5, env=env
        )
        data = json.loads(result.stdout)
        assert data["percentage"] == 50
        assert data["plugged"] == "PLUGGED_AC"
        assert data["status"] == "CHARGING"


class TestWifiStub:
    def test_connected(self):
        result = subprocess.run(
            ["termux-wifi-connectioninfo"], capture_output=True, text=True, timeout=5
        )
        data = json.loads(result.stdout)
        assert "ssid" in data
        assert data["ssid"] == "TestNetwork"

    def test_disconnected(self):
        env = {**os.environ, "STUB_WIFI_CONNECTED": "false"}
        result = subprocess.run(
            ["termux-wifi-connectioninfo"], capture_output=True, text=True, timeout=5, env=env
        )
        data = json.loads(result.stdout)
        assert "ssid" not in data


class TestJobSchedulerStub:
    def test_register_and_list(self, tmp_path):
        env = {**os.environ, "STUB_JOBS_DIR": str(tmp_path)}

        # Register a job
        subprocess.run(
            ["termux-job-scheduler",
             "--job-id", "1",
             "--period-ms", "3600000",
             "--script", "/tmp/test.sh",
             "--network", "unmetered"],
            check=True, timeout=5, env=env,
        )

        # List jobs
        result = subprocess.run(
            ["termux-job-scheduler", "--list"],
            capture_output=True, text=True, timeout=5, env=env,
        )
        jobs = json.loads(result.stdout)
        assert len(jobs) == 1
        assert jobs[0]["id"] == 1
        assert jobs[0]["periodMs"] == 3600000

        # Cancel
        subprocess.run(
            ["termux-job-scheduler", "--cancel", "--job-id", "1"],
            check=True, timeout=5, env=env,
        )

        # List again
        result = subprocess.run(
            ["termux-job-scheduler", "--list"],
            capture_output=True, text=True, timeout=5, env=env,
        )
        jobs = json.loads(result.stdout)
        assert len(jobs) == 0
