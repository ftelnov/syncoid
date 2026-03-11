"""Scheduler module tests — job registration, boot hook, with stubs."""

import json
import os
import stat

import pytest

from syncoid.config import Config
from syncoid.scheduler import (
    register_job,
    unregister_job,
    list_jobs,
    install_boot_hook,
    remove_boot_hook,
    _find_script,
)


class TestRegisterJob:
    def test_register_and_list(self, tmp_config, stubs_on_path, tmp_path, monkeypatch):
        monkeypatch.setenv("STUB_JOBS_DIR", str(tmp_path))

        config = Config()
        config.api_key = "test"
        config.period_hours = 2.0
        config.wifi_only = True
        config.charging_only = False

        assert register_job(config) is True

        jobs = list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["periodMs"] == 7200000  # 2h in ms
        assert jobs[0]["network"] == "unmetered"

    def test_register_with_charging(self, tmp_config, stubs_on_path, tmp_path, monkeypatch):
        monkeypatch.setenv("STUB_JOBS_DIR", str(tmp_path))

        config = Config()
        config.api_key = "test"
        config.period_hours = 0.5
        config.wifi_only = False
        config.charging_only = True

        assert register_job(config) is True

        jobs = list_jobs()
        assert len(jobs) == 1
        # charging should be true in the registered job
        assert jobs[0]["charging"] is True

    def test_register_no_constraints(self, tmp_config, stubs_on_path, tmp_path, monkeypatch):
        monkeypatch.setenv("STUB_JOBS_DIR", str(tmp_path))

        config = Config()
        config.api_key = "test"
        config.wifi_only = False
        config.charging_only = False

        assert register_job(config) is True

        jobs = list_jobs()
        assert len(jobs) == 1
        assert jobs[0]["network"] == ""
        assert jobs[0]["charging"] is False


class TestUnregisterJob:
    def test_unregister(self, tmp_config, stubs_on_path, tmp_path, monkeypatch):
        monkeypatch.setenv("STUB_JOBS_DIR", str(tmp_path))

        config = Config()
        config.api_key = "test"
        register_job(config)
        assert len(list_jobs()) == 1

        assert unregister_job() is True
        assert len(list_jobs()) == 0

    def test_unregister_nonexistent(self, tmp_config, stubs_on_path, tmp_path, monkeypatch):
        monkeypatch.setenv("STUB_JOBS_DIR", str(tmp_path))
        # Nothing registered, cancel should still succeed (stub removes file if exists)
        assert unregister_job() is True


class TestBootHook:
    def test_install_creates_script(self, tmp_config, tmp_path, monkeypatch):
        boot_dir = tmp_path / ".termux" / "boot"
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        config = Config()
        assert install_boot_hook(config) is True

        hook = boot_dir / "syncoid-boot.sh"
        assert hook.exists()
        content = hook.read_text()
        assert "syncoid enable" in content
        assert "syncoid watch" not in content
        assert hook.stat().st_mode & stat.S_IXUSR

    def test_install_with_watch(self, tmp_config, tmp_path, monkeypatch):
        boot_dir = tmp_path / ".termux" / "boot"
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

        config = Config()
        assert install_boot_hook(config, watch=True) is True

        hook = boot_dir / "syncoid-boot.sh"
        content = hook.read_text()
        assert "syncoid enable" in content
        assert "syncoid watch" in content
        assert "nohup" in content

    def test_remove_boot_hook(self, tmp_path, monkeypatch):
        boot_dir = tmp_path / ".termux" / "boot"
        boot_dir.mkdir(parents=True)
        hook = boot_dir / "syncoid-boot.sh"
        hook.write_text("#!/bin/sh\n")

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        # Reimport to pick up patched home
        from syncoid import scheduler
        monkeypatch.setattr(scheduler, "BOOT_DIR", boot_dir)

        assert remove_boot_hook() is True
        assert not hook.exists()


class TestFindScript:
    def test_finds_in_repo(self):
        """Should find scripts/syncoid-run relative to the package."""
        path = _find_script("syncoid-run")
        assert "syncoid-run" in path

    def test_returns_name_when_not_found(self):
        path = _find_script("nonexistent-script-xyz")
        assert path == "nonexistent-script-xyz"
