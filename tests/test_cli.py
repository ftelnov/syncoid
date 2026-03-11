"""CLI command tests — error paths, edge cases, log rotation."""

import json
import os
import time
from argparse import Namespace
from datetime import datetime
from unittest.mock import patch, MagicMock
from pathlib import Path

import pytest

from syncoid.config import Config
from syncoid.syncthing import Syncthing
from syncoid.cli import (
    cmd_run,
    cmd_now,
    cmd_watch,
    cmd_configure,
    cmd_enable,
    cmd_disable,
    cmd_status,
    cmd_watch_boot,
    cleanup_old_logs,
    save_last_run,
    log,
    main,
)


def _patch_lifecycle(**overrides):
    """Mock Syncthing lifecycle. Override individual methods as needed."""
    defaults = dict(
        is_running=lambda self: True,
        start=lambda self: True,
        stop=lambda self: None,
    )
    defaults.update(overrides)
    return patch.multiple(Syncthing, **defaults)


# ---------------------------------------------------------------------------
# cmd_run
# ---------------------------------------------------------------------------
class TestCmdRun:
    def test_no_api_key(self, tmp_config):
        rc = cmd_run(Namespace(force=False))
        assert rc == 1

    def test_start_failure_saves_last_run(self, tmp_config, stubs_on_path):
        config = Config()
        config.api_key = "test"
        config.managed_folders = ["f"]
        config.save()

        with _patch_lifecycle(
            is_running=lambda self: False,
            start=lambda self: False,
        ):
            rc = cmd_run(Namespace(force=True))

        assert rc == 1
        last_run = json.loads((Config.state_dir() / "last_run.json").read_text())
        assert last_run["status"] == "failed"

    def test_exception_saves_last_run(self, tmp_config, stubs_on_path):
        config = Config()
        config.api_key = "test"
        config.managed_folders = ["f"]
        config.save()

        def exploding_scan(self, folder=None):
            raise RuntimeError("boom")

        with _patch_lifecycle(), \
             patch.object(Syncthing, "scan", exploding_scan):
            rc = cmd_run(Namespace(force=True))

        assert rc == 1
        last_run = json.loads((Config.state_dir() / "last_run.json").read_text())
        assert last_run["status"] == "failed"

    def test_no_folders_returns_zero(self, tmp_config, stubs_on_path):
        config = Config()
        config.api_key = "test"
        config.managed_folders = []
        config.save()

        with _patch_lifecycle(), \
             patch.object(Syncthing, "list_folders", lambda self: []):
            rc = cmd_run(Namespace(force=True))

        assert rc == 0
        last_run = json.loads((Config.state_dir() / "last_run.json").read_text())
        assert last_run["status"] == "no_folders"

    def test_partial_sync_returns_two(self, tmp_config, stubs_on_path):
        config = Config()
        config.api_key = "test"
        config.managed_folders = ["a", "b"]
        config.max_window_min = 0  # instant timeout
        config.save()

        call_count = [0]

        def mock_wait(self, folder, timeout=300):
            call_count[0] += 1
            return call_count[0] == 1  # first folder syncs, second times out

        with _patch_lifecycle(), \
             patch.object(Syncthing, "scan", lambda self, f=None: True), \
             patch.object(Syncthing, "wait_synced", mock_wait):
            rc = cmd_run(Namespace(force=True))

        assert rc == 2
        last_run = json.loads((Config.state_dir() / "last_run.json").read_text())
        assert last_run["status"] == "partial"

    def test_syncthing_stop_called_in_finally(self, tmp_config, stubs_on_path):
        """Syncthing.stop() must be called even when an exception occurs."""
        config = Config()
        config.api_key = "test"
        config.managed_folders = ["f"]
        config.save()

        stop_called = []

        def track_stop(self):
            stop_called.append(True)

        with _patch_lifecycle(stop=track_stop), \
             patch.object(Syncthing, "scan", lambda s, f=None: (_ for _ in ()).throw(RuntimeError("boom"))):
            cmd_run(Namespace(force=True))

        assert len(stop_called) == 1


# ---------------------------------------------------------------------------
# cmd_now
# ---------------------------------------------------------------------------
class TestCmdNow:
    def test_no_api_key(self, tmp_config):
        rc = cmd_now(Namespace())
        assert rc == 1

    def test_exception_saves_last_run(self, tmp_config, stubs_on_path):
        config = Config()
        config.api_key = "test"
        config.managed_folders = ["f"]
        config.save()

        def exploding_scan(self, folder=None):
            raise RuntimeError("boom")

        with _patch_lifecycle(), \
             patch.object(Syncthing, "scan", exploding_scan):
            rc = cmd_now(Namespace())

        assert rc == 1
        last_run = json.loads((Config.state_dir() / "last_run.json").read_text())
        assert last_run["status"] == "failed"

    def test_start_failure(self, tmp_config, stubs_on_path):
        config = Config()
        config.api_key = "test"
        config.save()

        with _patch_lifecycle(
            is_running=lambda self: False,
            start=lambda self: False,
        ):
            rc = cmd_now(Namespace())

        assert rc == 1

    def test_syncthing_stop_called_in_finally(self, tmp_config, stubs_on_path):
        config = Config()
        config.api_key = "test"
        config.managed_folders = ["f"]
        config.save()

        stop_called = []

        def track_stop(self):
            stop_called.append(True)

        with _patch_lifecycle(stop=track_stop), \
             patch.object(Syncthing, "scan", lambda s, f=None: (_ for _ in ()).throw(RuntimeError)):
            cmd_now(Namespace())

        assert len(stop_called) == 1


# ---------------------------------------------------------------------------
# cmd_watch
# ---------------------------------------------------------------------------
class TestCmdWatch:
    def test_no_api_key(self, tmp_config):
        rc = cmd_watch(Namespace(debounce=None))
        assert rc == 1

    def test_no_folders(self, tmp_config):
        config = Config()
        config.api_key = "test"
        config.save()

        with patch("syncoid.cli.resolve_watch_paths", return_value=[]):
            rc = cmd_watch(Namespace(debounce=None))

        assert rc == 1


# ---------------------------------------------------------------------------
# cmd_configure
# ---------------------------------------------------------------------------
class TestCmdConfigure:
    def test_configure_with_api_key(self, tmp_config, stubs_on_path, tmp_path, monkeypatch):
        monkeypatch.setenv("STUB_JOBS_DIR", str(tmp_path))

        args = Namespace(
            api_key="my-key",
            period=2.0,
            wifi_only=None,
            charging_only=None,
        )
        rc = cmd_configure(args)
        assert rc == 0

        loaded = Config.load()
        assert loaded.api_key == "my-key"
        assert loaded.period_hours == 2.0

    def test_configure_no_api_key_fails(self, tmp_config):
        args = Namespace(
            api_key=None,
            period=None,
            wifi_only=None,
            charging_only=None,
        )
        rc = cmd_configure(args)
        assert rc == 1

    def test_configure_sets_wifi_and_charging(self, tmp_config, stubs_on_path, tmp_path, monkeypatch):
        monkeypatch.setenv("STUB_JOBS_DIR", str(tmp_path))

        args = Namespace(
            api_key="k",
            period=None,
            wifi_only=False,
            charging_only=True,
        )
        rc = cmd_configure(args)
        assert rc == 0

        loaded = Config.load()
        assert loaded.wifi_only is False
        assert loaded.charging_only is True


# ---------------------------------------------------------------------------
# cmd_enable / cmd_disable
# ---------------------------------------------------------------------------
class TestCmdEnableDisable:
    def test_enable_no_api_key(self, tmp_config):
        rc = cmd_enable(Namespace())
        assert rc == 1

    def test_enable_with_api_key(self, tmp_config, stubs_on_path, tmp_path, monkeypatch):
        monkeypatch.setenv("STUB_JOBS_DIR", str(tmp_path))

        config = Config()
        config.api_key = "test"
        config.save()

        rc = cmd_enable(Namespace())
        assert rc == 0

    def test_disable(self, tmp_config, stubs_on_path, tmp_path, monkeypatch):
        monkeypatch.setenv("STUB_JOBS_DIR", str(tmp_path))

        config = Config()
        config.api_key = "test"
        config.save()

        register_result = cmd_enable(Namespace())
        assert register_result == 0

        rc = cmd_disable(Namespace())
        assert rc == 0


# ---------------------------------------------------------------------------
# cleanup_old_logs
# ---------------------------------------------------------------------------
class TestCleanupOldLogs:
    def test_removes_old_logs(self, tmp_config):
        logs_dir = Config.logs_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)

        old = logs_dir / "syncoid-2020-01-01.log"
        old.write_text("old log")
        # Set mtime to 2020
        os.utime(old, (0, 0))

        recent = logs_dir / f"syncoid-{datetime.now().strftime('%Y-%m-%d')}.log"
        recent.write_text("recent log")

        cleanup_old_logs(retention_days=7)

        assert not old.exists()
        assert recent.exists()

    def test_no_crash_on_missing_logs_dir(self, tmp_config):
        # logs_dir doesn't exist yet — should not raise
        cleanup_old_logs(retention_days=7)

    def test_keeps_non_matching_files(self, tmp_config):
        logs_dir = Config.logs_dir()
        logs_dir.mkdir(parents=True, exist_ok=True)

        other = logs_dir / "other.txt"
        other.write_text("keep me")
        os.utime(other, (0, 0))

        cleanup_old_logs(retention_days=7)
        assert other.exists()


# ---------------------------------------------------------------------------
# save_last_run
# ---------------------------------------------------------------------------
class TestSaveLastRun:
    def test_saves_with_folders(self, tmp_config):
        save_last_run("success", ["a", "b"])
        data = json.loads((Config.state_dir() / "last_run.json").read_text())
        assert data["status"] == "success"
        assert data["folders"] == ["a", "b"]
        assert "timestamp" in data

    def test_saves_without_folders(self, tmp_config):
        save_last_run("failed")
        data = json.loads((Config.state_dir() / "last_run.json").read_text())
        assert data["folders"] == []

    def test_overwrites_previous(self, tmp_config):
        save_last_run("first")
        save_last_run("second")
        data = json.loads((Config.state_dir() / "last_run.json").read_text())
        assert data["status"] == "second"


# ---------------------------------------------------------------------------
# log function
# ---------------------------------------------------------------------------
class TestLogFunction:
    def test_creates_log_file(self, tmp_config):
        log("test message", "INFO")
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = Config.logs_dir() / f"syncoid-{today}.log"
        assert log_file.exists()
        content = log_file.read_text()
        assert "test message" in content
        assert "[INFO]" in content

    def test_appends_to_existing(self, tmp_config):
        log("first")
        log("second")
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = Config.logs_dir() / f"syncoid-{today}.log"
        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 2

    def test_error_level(self, tmp_config):
        log("something broke", "ERROR")
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = Config.logs_dir() / f"syncoid-{today}.log"
        assert "[ERROR]" in log_file.read_text()


# ---------------------------------------------------------------------------
# cmd_status
# ---------------------------------------------------------------------------
class TestCmdStatus:
    def test_status_no_last_run(self, tmp_config, stubs_on_path, capsys):
        config = Config()
        config.api_key = "test"
        config.save()

        cmd_status(Namespace())
        output = capsys.readouterr().out
        assert "never" in output

    def test_status_with_old_format_folders(self, tmp_config, stubs_on_path, capsys):
        """Status should handle legacy space-separated folder strings."""
        config = Config()
        config.api_key = "test"
        config.save()

        state_dir = Config.state_dir()
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "last_run.json").write_text(json.dumps({
            "timestamp": "2025-01-01T00:00:00",
            "status": "success",
            "folders": "photos docs",  # old string format
        }))

        cmd_status(Namespace())
        output = capsys.readouterr().out
        assert "photos docs" in output

    def test_status_no_api_key(self, tmp_config, stubs_on_path, capsys):
        cmd_status(Namespace())
        output = capsys.readouterr().out
        assert "NOT SET" in output


# ---------------------------------------------------------------------------
# cmd_watch_boot
# ---------------------------------------------------------------------------
class TestCmdWatchBoot:
    def test_enable_installs_hook_with_watch(self, tmp_config, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        config = Config()
        config.api_key = "test"
        config.save()

        rc = cmd_watch_boot(Namespace(action="enable"))
        assert rc == 0

        hook = tmp_path / ".termux" / "boot" / "syncoid-boot.sh"
        assert hook.exists()
        content = hook.read_text()
        assert "syncoid watch" in content
        assert "syncoid enable" in content

    def test_disable_removes_watch(self, tmp_config, stubs_on_path, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        from syncoid import scheduler
        monkeypatch.setattr(scheduler, "BOOT_DIR", tmp_path / ".termux" / "boot")
        monkeypatch.setenv("STUB_JOBS_DIR", str(tmp_path / "jobs"))
        (tmp_path / "jobs").mkdir()

        config = Config()
        config.api_key = "test"
        config.save()

        # First enable
        cmd_watch_boot(Namespace(action="enable"))
        # Then disable
        rc = cmd_watch_boot(Namespace(action="disable"))
        assert rc == 0


# ---------------------------------------------------------------------------
# main() entry point
# ---------------------------------------------------------------------------
class TestMain:
    def test_no_command_shows_help(self, capsys):
        with patch("sys.argv", ["syncoid"]):
            rc = main()
        assert rc == 0
        output = capsys.readouterr().out
        assert "usage" in output.lower() or "syncoid" in output.lower()
