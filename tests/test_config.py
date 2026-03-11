"""Config module tests — serialization, edge cases, API key detection."""

import json
import os
import textwrap

import pytest

from syncoid.config import Config


class TestConfigDefaults:
    def test_all_defaults(self):
        c = Config()
        assert c.period_hours == 0.5
        assert c.wifi_only is True
        assert c.charging_only is False
        assert c.min_battery_pct == 20
        assert c.max_window_min == 10
        assert c.gui_addr == "127.0.0.1:8384"
        assert c.managed_folders == []
        assert c.enable_wakelock is False
        assert c.notify_on_failure is True
        assert c.notify_on_success is False
        assert c.log_retention_days == 7
        assert c.ondemand_skip_checks is True
        assert c.ondemand_max_wait_min == 5
        assert c.api_key is None

    def test_managed_folders_not_shared_between_instances(self):
        a = Config()
        b = Config()
        a.managed_folders.append("x")
        assert b.managed_folders == []


class TestConfigSaveLoad:
    def test_round_trip(self, tmp_config):
        c = Config()
        c.api_key = "key-123"
        c.period_hours = 4.0
        c.wifi_only = False
        c.charging_only = True
        c.managed_folders = ["photos", "docs"]
        c.gui_addr = "0.0.0.0:9999"
        c.save()

        loaded = Config.load()
        assert loaded.api_key == "key-123"
        assert loaded.period_hours == 4.0
        assert loaded.wifi_only is False
        assert loaded.charging_only is True
        assert loaded.managed_folders == ["photos", "docs"]
        assert loaded.gui_addr == "0.0.0.0:9999"

    def test_load_creates_state_and_logs_dirs(self, tmp_config):
        Config.load()
        assert Config.state_dir().is_dir()
        assert Config.logs_dir().is_dir()

    def test_load_no_config_file_returns_defaults(self, tmp_config):
        c = Config.load()
        assert c.period_hours == 0.5
        assert c.api_key is None

    def test_load_corrupted_json_returns_defaults(self, tmp_config):
        Config.config_dir().mkdir(parents=True, exist_ok=True)
        Config.config_file().write_text("NOT VALID JSON {{{")
        c = Config.load()
        assert c.period_hours == 0.5  # defaults

    def test_load_ignores_unknown_keys(self, tmp_config):
        Config.config_dir().mkdir(parents=True, exist_ok=True)
        Config.config_file().write_text(json.dumps({
            "period_hours": 3.0,
            "unknown_key": "should be ignored",
            "another_fake": 42,
        }))
        c = Config.load()
        assert c.period_hours == 3.0
        assert not hasattr(c, "unknown_key") or c.__class__.__dict__.get("unknown_key") is None

    def test_load_rejects_method_overwrite(self, tmp_config):
        """Config JSON with keys matching method names must not overwrite them."""
        Config.config_dir().mkdir(parents=True, exist_ok=True)
        Config.config_file().write_text(json.dumps({
            "save": "HACKED",
            "load": "HACKED",
            "config_dir": "HACKED",
            "api_key": "legit-key",
        }))
        c = Config.load()
        assert c.api_key == "legit-key"
        # save must still be callable
        c.save()
        assert Config.config_file().exists()

    def test_save_omits_none_api_key(self, tmp_config):
        c = Config()
        c.api_key = None
        c.save()
        data = json.loads(Config.config_file().read_text())
        assert "api_key" not in data

    def test_save_includes_set_api_key(self, tmp_config):
        c = Config()
        c.api_key = "my-key"
        c.save()
        data = json.loads(Config.config_file().read_text())
        assert data["api_key"] == "my-key"


class TestApiKeyDetection:
    def test_detect_from_syncthing_xml(self, tmp_config, tmp_path):
        st_config_dir = tmp_path / ".config" / "syncthing"
        st_config_dir.mkdir(parents=True)
        (st_config_dir / "config.xml").write_text(textwrap.dedent("""\
            <configuration>
                <gui enabled="true">
                    <apikey>detected-key-abc</apikey>
                </gui>
            </configuration>
        """))

        from unittest.mock import patch
        with patch("pathlib.Path.home", return_value=tmp_path):
            key = Config._detect_api_key()
        assert key == "detected-key-abc"

    def test_detect_missing_xml_returns_none(self, tmp_config, tmp_path):
        from unittest.mock import patch
        with patch("pathlib.Path.home", return_value=tmp_path):
            key = Config._detect_api_key()
        assert key is None

    def test_detect_malformed_xml_returns_none(self, tmp_config, tmp_path):
        st_config_dir = tmp_path / ".config" / "syncthing"
        st_config_dir.mkdir(parents=True)
        (st_config_dir / "config.xml").write_text("NOT XML <><><<")

        from unittest.mock import patch
        with patch("pathlib.Path.home", return_value=tmp_path):
            key = Config._detect_api_key()
        assert key is None

    def test_detect_xml_no_apikey_element(self, tmp_config, tmp_path):
        st_config_dir = tmp_path / ".config" / "syncthing"
        st_config_dir.mkdir(parents=True)
        (st_config_dir / "config.xml").write_text("<configuration><gui></gui></configuration>")

        from unittest.mock import patch
        with patch("pathlib.Path.home", return_value=tmp_path):
            key = Config._detect_api_key()
        assert key is None

    def test_load_auto_detects_api_key(self, tmp_config, tmp_path):
        """Config.load() should auto-detect API key when not in config JSON."""
        st_config_dir = tmp_path / ".config" / "syncthing"
        st_config_dir.mkdir(parents=True)
        (st_config_dir / "config.xml").write_text(textwrap.dedent("""\
            <configuration>
                <gui><apikey>auto-key</apikey></gui>
            </configuration>
        """))

        from unittest.mock import patch
        with patch("pathlib.Path.home", return_value=tmp_path):
            c = Config.load()
        assert c.api_key == "auto-key"

    def test_load_prefers_saved_key_over_detected(self, tmp_config, tmp_path):
        """Saved API key should take precedence over auto-detected one."""
        st_config_dir = tmp_path / ".config" / "syncthing"
        st_config_dir.mkdir(parents=True)
        (st_config_dir / "config.xml").write_text(
            "<configuration><gui><apikey>detected</apikey></gui></configuration>"
        )

        c = Config()
        c.api_key = "saved-key"
        c.save()

        from unittest.mock import patch
        with patch("pathlib.Path.home", return_value=tmp_path):
            loaded = Config.load()
        assert loaded.api_key == "saved-key"


class TestConfigDir:
    def test_env_override(self, tmp_path):
        old = os.environ.get("SYNCOID_CONFIG_DIR")
        os.environ["SYNCOID_CONFIG_DIR"] = str(tmp_path / "custom")
        try:
            assert Config.config_dir() == tmp_path / "custom"
        finally:
            if old is not None:
                os.environ["SYNCOID_CONFIG_DIR"] = old
            else:
                os.environ.pop("SYNCOID_CONFIG_DIR", None)
