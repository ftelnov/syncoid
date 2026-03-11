"""Shared test fixtures."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_config(tmp_path):
    """Provide a temporary SYNCOID_CONFIG_DIR and restore after test."""
    old = os.environ.get("SYNCOID_CONFIG_DIR")
    os.environ["SYNCOID_CONFIG_DIR"] = str(tmp_path)
    yield tmp_path
    if old is not None:
        os.environ["SYNCOID_CONFIG_DIR"] = old
    else:
        os.environ.pop("SYNCOID_CONFIG_DIR", None)


@pytest.fixture
def stubs_on_path():
    """Ensure tests/stubs/ is on PATH (for local runs outside Docker)."""
    stubs_dir = str(Path(__file__).parent / "stubs")
    old_path = os.environ.get("PATH", "")
    if stubs_dir not in old_path:
        os.environ["PATH"] = f"{stubs_dir}:{old_path}"
    yield stubs_dir
    os.environ["PATH"] = old_path
