"""Live watcher integration test — requires inotifywait.

Verifies that file changes actually trigger the callback with proper debouncing.
"""

import os
import shutil
import threading
import time
from pathlib import Path

import pytest

from syncoid.watcher import watch_folders, _check_inotifywait


pytestmark = pytest.mark.skipif(
    not shutil.which("inotifywait"),
    reason="inotifywait not installed",
)


class TestWatchFoldersLive:
    def test_detects_file_creation(self, tmp_path):
        """Creating a file triggers the callback after debounce."""
        triggered = threading.Event()
        trigger_count = [0]

        def on_change():
            trigger_count[0] += 1
            triggered.set()

        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()

        watcher = threading.Thread(
            target=watch_folders,
            args=([watch_dir], on_change),
            kwargs={"debounce_sec": 0.5},
            daemon=True,
        )
        watcher.start()

        # Give inotifywait time to set up watches
        time.sleep(0.5)

        # Create a file
        (watch_dir / "test.txt").write_text("hello")

        # Wait for callback (debounce 0.5s + slack)
        assert triggered.wait(timeout=5), "Callback was not triggered"
        assert trigger_count[0] == 1

    def test_debounce_batches_rapid_changes(self, tmp_path):
        """Multiple rapid changes should result in a single callback."""
        trigger_count = [0]
        done = threading.Event()

        def on_change():
            trigger_count[0] += 1
            done.set()

        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()

        watcher = threading.Thread(
            target=watch_folders,
            args=([watch_dir], on_change),
            kwargs={"debounce_sec": 1.0},
            daemon=True,
        )
        watcher.start()
        time.sleep(0.5)

        # Rapid burst of 5 file writes
        for i in range(5):
            (watch_dir / f"file{i}.txt").write_text(f"data {i}")
            time.sleep(0.1)

        # Wait for the single debounced callback
        assert done.wait(timeout=5), "Callback was not triggered"

        # Give a bit more time to see if extra callbacks fire
        time.sleep(1.5)
        assert trigger_count[0] == 1, f"Expected 1 callback, got {trigger_count[0]}"

    def test_ignores_syncthing_internal_files(self, tmp_path):
        """Files matching ignore patterns should not trigger callback."""
        triggered = threading.Event()

        def on_change():
            triggered.set()

        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()

        watcher = threading.Thread(
            target=watch_folders,
            args=([watch_dir], on_change),
            kwargs={"debounce_sec": 0.3},
            daemon=True,
        )
        watcher.start()
        time.sleep(0.5)

        # Create Syncthing internal files — should be ignored
        st_versions = watch_dir / ".stversions"
        st_versions.mkdir()
        (st_versions / "old_file.txt").write_text("version")
        (watch_dir / ".stfolder").mkdir(exist_ok=True)

        # These should NOT trigger
        time.sleep(1.5)
        assert not triggered.is_set(), "Callback triggered for ignored files"

        # Now create a real file — should trigger
        (watch_dir / "real_file.txt").write_text("data")
        assert triggered.wait(timeout=5), "Callback not triggered for real file"

    def test_subdirectory_changes_detected(self, tmp_path):
        """Changes in nested subdirectories are detected (recursive)."""
        triggered = threading.Event()

        def on_change():
            triggered.set()

        watch_dir = tmp_path / "watched"
        sub = watch_dir / "a" / "b" / "c"
        sub.mkdir(parents=True)

        watcher = threading.Thread(
            target=watch_folders,
            args=([watch_dir], on_change),
            kwargs={"debounce_sec": 0.3},
            daemon=True,
        )
        watcher.start()
        time.sleep(0.5)

        (sub / "deep_file.txt").write_text("deep data")
        assert triggered.wait(timeout=5), "Callback not triggered for nested file"

    def test_events_during_sync_are_ignored(self, tmp_path):
        """Events that arrive while on_change is running don't trigger re-entry."""
        trigger_count = [0]
        sync_started = threading.Event()
        sync_done = threading.Event()

        def slow_on_change():
            trigger_count[0] += 1
            sync_started.set()
            # Simulate a 1-second sync
            time.sleep(1.0)
            sync_done.set()

        watch_dir = tmp_path / "watched"
        watch_dir.mkdir()

        watcher = threading.Thread(
            target=watch_folders,
            args=([watch_dir], slow_on_change),
            kwargs={"debounce_sec": 0.3},
            daemon=True,
        )
        watcher.start()
        time.sleep(0.5)

        # First change triggers sync
        (watch_dir / "file1.txt").write_text("trigger")
        assert sync_started.wait(timeout=5)

        # While sync is running, create more files — should be ignored
        (watch_dir / "file2.txt").write_text("during sync")
        (watch_dir / "file3.txt").write_text("during sync")

        assert sync_done.wait(timeout=5)

        # Wait to ensure no extra callbacks
        time.sleep(2.0)
        assert trigger_count[0] == 1
