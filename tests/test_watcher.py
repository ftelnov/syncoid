"""Watcher module tests — folder path resolution, exclude patterns, debounce."""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from syncoid.config import Config
from syncoid.watcher import (
    get_folder_paths,
    resolve_watch_paths,
    _build_exclude_regex,
    SYNCTHING_IGNORE,
)


class TestGetFolderPaths:
    def test_parses_syncthing_xml(self, tmp_path):
        st_dir = tmp_path / ".config" / "syncthing"
        st_dir.mkdir(parents=True)
        (st_dir / "config.xml").write_text(textwrap.dedent("""\
            <configuration>
                <folder id="photos" path="/sdcard/DCIM" type="sendreceive"/>
                <folder id="docs" path="/sdcard/Documents" type="sendreceive"/>
            </configuration>
        """))

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = get_folder_paths()

        assert "photos" in result
        assert "docs" in result
        assert result["photos"] == Path("/sdcard/DCIM").resolve()
        assert result["docs"] == Path("/sdcard/Documents").resolve()

    def test_missing_xml_returns_empty(self, tmp_path):
        with patch("pathlib.Path.home", return_value=tmp_path):
            assert get_folder_paths() == {}

    def test_malformed_xml_returns_empty(self, tmp_path):
        st_dir = tmp_path / ".config" / "syncthing"
        st_dir.mkdir(parents=True)
        (st_dir / "config.xml").write_text("NOT XML {{{")

        with patch("pathlib.Path.home", return_value=tmp_path):
            assert get_folder_paths() == {}

    def test_folder_without_path_skipped(self, tmp_path):
        st_dir = tmp_path / ".config" / "syncthing"
        st_dir.mkdir(parents=True)
        (st_dir / "config.xml").write_text(textwrap.dedent("""\
            <configuration>
                <folder id="no-path" type="sendreceive"/>
                <folder id="has-path" path="/data" type="sendreceive"/>
            </configuration>
        """))

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = get_folder_paths()

        assert "no-path" not in result
        assert "has-path" in result

    def test_expands_home_tilde(self, tmp_path):
        st_dir = tmp_path / ".config" / "syncthing"
        st_dir.mkdir(parents=True)
        (st_dir / "config.xml").write_text(
            '<configuration><folder id="f" path="~/sync" type="sendreceive"/></configuration>'
        )

        with patch("pathlib.Path.home", return_value=tmp_path):
            result = get_folder_paths()

        assert "f" in result
        assert "~" not in str(result["f"])


class TestResolveWatchPaths:
    def _setup_folders(self, tmp_path):
        """Create real directories and a syncthing config.xml pointing to them."""
        sync_a = tmp_path / "sync_a"
        sync_b = tmp_path / "sync_b"
        sync_a.mkdir()
        sync_b.mkdir()

        st_dir = tmp_path / ".config" / "syncthing"
        st_dir.mkdir(parents=True)
        (st_dir / "config.xml").write_text(textwrap.dedent(f"""\
            <configuration>
                <folder id="alpha" path="{sync_a}" type="sendreceive"/>
                <folder id="beta" path="{sync_b}" type="sendreceive"/>
            </configuration>
        """))
        return sync_a, sync_b

    def test_resolves_all_folders(self, tmp_config, tmp_path):
        sync_a, sync_b = self._setup_folders(tmp_path)

        config = Config()
        config.api_key = "test"
        config.managed_folders = []  # watch all

        with patch("pathlib.Path.home", return_value=tmp_path):
            paths = resolve_watch_paths(config)

        resolved = {p.resolve() for p in paths}
        assert sync_a.resolve() in resolved
        assert sync_b.resolve() in resolved

    def test_respects_managed_folders(self, tmp_config, tmp_path):
        sync_a, sync_b = self._setup_folders(tmp_path)

        config = Config()
        config.api_key = "test"
        config.managed_folders = ["alpha"]  # only alpha

        with patch("pathlib.Path.home", return_value=tmp_path):
            paths = resolve_watch_paths(config)

        assert len(paths) == 1
        assert paths[0].resolve() == sync_a.resolve()

    def test_skips_nonexistent_dirs(self, tmp_config, tmp_path):
        st_dir = tmp_path / ".config" / "syncthing"
        st_dir.mkdir(parents=True)
        (st_dir / "config.xml").write_text(
            '<configuration><folder id="gone" path="/nonexistent/path/xyz" type="sendreceive"/></configuration>'
        )

        config = Config()
        config.api_key = "test"

        with patch("pathlib.Path.home", return_value=tmp_path):
            paths = resolve_watch_paths(config)

        assert paths == []

    def test_no_syncthing_config(self, tmp_config, tmp_path):
        config = Config()
        with patch("pathlib.Path.home", return_value=tmp_path):
            assert resolve_watch_paths(config) == []


class TestBuildExcludeRegex:
    def test_default_patterns(self):
        regex = _build_exclude_regex(SYNCTHING_IGNORE)
        assert r"\.stfolder" in regex
        assert r"\.stversions" in regex
        assert r"~syncthing~" in regex
        assert regex.startswith("(")
        assert regex.endswith(")")

    def test_single_pattern(self):
        assert _build_exclude_regex([r"\.tmp"]) == r"(\.tmp)"

    def test_custom_patterns(self):
        regex = _build_exclude_regex([r"\.bak", r"\.swp"])
        assert regex == r"(\.bak|\.swp)"


class TestWatchDebounceConfig:
    def test_default_value(self):
        c = Config()
        assert c.watch_debounce_sec == 5.0

    def test_save_load_round_trip(self, tmp_config):
        c = Config()
        c.watch_debounce_sec = 10.0
        c.api_key = "k"
        c.save()

        loaded = Config.load()
        assert loaded.watch_debounce_sec == 10.0
