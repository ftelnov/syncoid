"""JobScheduler integration for Termux."""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from .config import Config


BOOT_DIR = Path.home() / ".termux" / "boot"


def _find_script(name: str) -> str:
    """Find a syncoid script, preferring PATH over repo-relative location."""
    found = shutil.which(name)
    if found:
        return found
    repo_script = Path(__file__).parent.parent / "scripts" / name
    if repo_script.exists():
        return str(repo_script)
    return name


def register_job(
    config: Config,
    job_id: int = 0,
) -> bool:
    period_ms = int(config.period_hours * 60 * 60 * 1000)

    cmd = [
        "termux-job-scheduler",
        "--job-id", str(job_id),
        "--period-ms", str(period_ms),
        "--script", _find_script("syncoid-run"),
    ]

    if config.wifi_only:
        cmd.append("--network")
        cmd.append("unmetered")

    if config.charging_only:
        cmd.append("--charging")
        cmd.append("true")

    try:
        subprocess.run(cmd, check=True, timeout=30)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def unregister_job(job_id: int = 0) -> bool:
    try:
        subprocess.run(
            ["termux-job-scheduler", "--cancel", "--job-id", str(job_id)],
            check=True,
            timeout=10,
        )
        return True
    except Exception:
        return False


def list_jobs() -> list[dict]:
    try:
        result = subprocess.run(
            ["termux-job-scheduler", "--list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout) if result.stdout.strip() else []
    except Exception:
        pass
    return []


def install_boot_hook(config: Config, watch: bool = False) -> bool:
    """Install a Termux:Boot hook.

    If *watch* is True, the boot script starts ``syncoid watch`` in the
    background **and** re-registers the periodic job.  Otherwise it only
    re-registers the periodic job.
    """
    BOOT_DIR.mkdir(parents=True, exist_ok=True)

    hook_script = BOOT_DIR / "syncoid-boot.sh"

    lines = [
        "#!/usr/bin/env bash",
        "# Syncoid boot hook — auto-generated, do not edit",
        "python3 -m syncoid enable 2>/dev/null",
    ]

    if watch:
        lines.append(
            "nohup python3 -m syncoid watch "
            ">> ~/.config/syncoid/logs/watch.log 2>&1 &"
        )

    try:
        hook_script.write_text("\n".join(lines) + "\n")
        hook_script.chmod(0o755)
        return True
    except Exception:
        return False


def remove_boot_hook() -> bool:
    hook_script = BOOT_DIR / "syncoid-boot.sh"
    try:
        hook_script.unlink(missing_ok=True)
        return True
    except Exception:
        return False
