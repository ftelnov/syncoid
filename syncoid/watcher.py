"""Filesystem watcher using inotify — near-zero battery cost.

The process blocks on a kernel syscall between events, consuming no CPU.
Only wakes when files actually change, then debounces and triggers sync.
"""

import os
import select
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable, Optional

from .config import Config

# Patterns to exclude from inotify — Syncthing internals and temp files.
SYNCTHING_IGNORE = [
    r"\.stfolder",
    r"\.stversions",
    r"\.stignore",
    r"\.syncthing\.",
    r"~syncthing~",
]


def get_folder_paths(config: Optional[Config] = None) -> dict[str, Path]:
    """Read Syncthing's config.xml to get folder_id -> filesystem path mapping."""
    st_config = Config._syncthing_config_xml()
    if not st_config.exists():
        return {}

    try:
        tree = ET.parse(st_config)
        folders = {}
        for elem in tree.findall(".//folder"):
            fid = elem.get("id")
            fpath = elem.get("path")
            if fid and fpath:
                folders[fid] = Path(fpath).expanduser().resolve()
        return folders
    except Exception:
        return {}


def resolve_watch_paths(config: Config) -> list[Path]:
    """Resolve which directories to watch based on config."""
    folder_map = get_folder_paths(config)
    if not folder_map:
        return []

    if config.managed_folders:
        paths = [folder_map[fid] for fid in config.managed_folders if fid in folder_map]
    else:
        paths = list(folder_map.values())

    return [p for p in paths if p.is_dir()]


def _check_inotifywait() -> str:
    path = shutil.which("inotifywait")
    if not path:
        raise RuntimeError(
            "inotifywait not found. Install with: pkg install inotify-tools"
        )
    return path


def _build_exclude_regex(patterns: list[str]) -> str:
    return "(" + "|".join(patterns) + ")"


def watch_folders(
    paths: list[Path],
    on_change: Callable[[], None],
    debounce_sec: float = 5.0,
    ignore_patterns: Optional[list[str]] = None,
) -> None:
    """Watch folders for changes using inotifywait. Blocks indefinitely.

    Calls on_change when files are modified and no further changes
    happen for debounce_sec seconds. Events during on_change execution
    are drained but ignored (prevents Syncthing's own writes from
    triggering another sync).
    """
    binary = _check_inotifywait()
    patterns = ignore_patterns or SYNCTHING_IGNORE
    exclude = _build_exclude_regex(patterns)

    str_paths = [str(p) for p in paths]
    if not str_paths:
        raise RuntimeError("No directories to watch")

    cmd = [
        binary,
        "-m",  # monitor (continuous)
        "-r",  # recursive
        "-e", "modify,create,delete,moved_to",
        "--exclude", exclude,
        "--format", "%w%f",
    ] + str_paths

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    try:
        _event_loop(proc, debounce_sec, on_change)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _drain_pipe(pipe, timeout: float = 0.1) -> None:
    """Read and discard all buffered data from a pipe."""
    while True:
        ready, _, _ = select.select([pipe], [], [], timeout)
        if not ready:
            break
        line = pipe.readline()
        if not line:
            break


def _event_loop(
    proc: subprocess.Popen,
    debounce_sec: float,
    on_change: Callable[[], None],
) -> None:
    """Read inotifywait stdout, debounce events, call on_change."""
    syncing = False
    last_event = 0.0
    pending = False

    if proc.stdout is None:
        return

    while proc.poll() is None:
        ready, _, _ = select.select([proc.stdout], [], [], 1.0)

        if ready:
            line = proc.stdout.readline()
            if not line:
                break  # inotifywait exited

            if syncing:
                continue  # drain events while sync is running

            last_event = time.monotonic()
            pending = True

        if pending and not syncing:
            elapsed = time.monotonic() - last_event
            if elapsed >= debounce_sec:
                pending = False
                syncing = True
                try:
                    on_change()
                finally:
                    # Drain events that arrived during sync before resuming
                    _drain_pipe(proc.stdout)
                    syncing = False
