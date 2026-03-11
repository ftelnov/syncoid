"""Syncthing REST API client."""

import os
import subprocess
import time
import shutil
from pathlib import Path
from typing import Optional
import urllib.request
import urllib.error
import json

from .config import Config


class Syncthing:
    def __init__(self, config: Config):
        self.config = config
        self.base_url = f"http://{config.gui_addr}"
        self.pid_file = Config.state_dir() / "syncthing.pid"
    
    def _request(self, endpoint: str, method: str = "GET", data: Optional[dict] = None) -> Optional[dict]:
        url = f"{self.base_url}/rest/{endpoint}"
        headers: dict[str, str] = {"X-API-Key": self.config.api_key or ""}

        if data:
            body = json.dumps(data).encode()
            headers["Content-Type"] = "application/json"
        else:
            body = None

        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        with urllib.request.urlopen(req, timeout=30) as resp:
            if resp.status == 204:
                return {}
            body = resp.read().decode()
            if not body.strip():
                return {}
            return json.loads(body)
    
    def _find_binary(self) -> Optional[str]:
        candidates = [
            os.environ.get("SYNCTHING_BIN", ""),
            shutil.which("syncthing"),
            str(Path.home() / "go/bin/syncthing"),
            str(Path.home() / ".local/bin/syncthing"),
            "/data/data/com.termux/files/usr/bin/syncthing",
        ]
        for path in candidates:
            if path and Path(path).exists():
                return path
        return None
    
    def is_running(self) -> bool:
        if not self.pid_file.exists():
            return False
        try:
            pid = int(self.pid_file.read_text().strip())
            os.kill(pid, 0)
            return True
        except (ValueError, ProcessLookupError, PermissionError):
            self.pid_file.unlink(missing_ok=True)
            return False
    
    def start(self) -> bool:
        if self.is_running():
            return True
        
        binary = self._find_binary()
        if not binary:
            raise RuntimeError("Syncthing binary not found")
        
        env = os.environ.copy()
        env["STNOUPGRADE"] = "1"
        
        proc = subprocess.Popen(
            [binary, "--no-browser", f"--gui-address={self.config.gui_addr}"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        
        self.pid_file.write_text(str(proc.pid))
        return self.wait_ready(timeout=30)
    
    def stop(self) -> None:
        if not self.is_running():
            self.pid_file.unlink(missing_ok=True)
            return

        try:
            self._request("system/shutdown", method="POST")
        except Exception:
            pass
        for _ in range(10):
            if not self.is_running():
                break
            time.sleep(1)
        
        if self.is_running():
            try:
                pid = int(self.pid_file.read_text().strip())
                os.kill(pid, 9)
            except (ValueError, OSError):
                pass  # PID file corrupt or process already gone
        
        self.pid_file.unlink(missing_ok=True)
    
    def wait_ready(self, timeout: int = 30) -> bool:
        for _ in range(timeout):
            if not self.is_running():
                return False
            try:
                result = self._request("system/ping")
                if result is not None:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False
    
    def scan(self, folder: Optional[str] = None) -> bool:
        endpoint = "db/scan"
        if folder:
            endpoint += f"?folder={folder}"
        try:
            self._request(endpoint, method="POST")
            return True
        except Exception:
            return False

    def folder_status(self, folder: str) -> dict:
        try:
            return self._request(f"db/status?folder={folder}") or {}
        except Exception:
            return {}

    def needs_sync(self, folder: str) -> bool:
        status = self.folder_status(folder)
        return status.get("needBytes", 0) > 0 or status.get("state") != "idle"

    def wait_synced(self, folder: str, timeout: int = 300) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            status = self.folder_status(folder)
            if status.get("state") == "idle" and status.get("needBytes", 0) == 0:
                return True
            time.sleep(5)
        return False

    def list_folders(self) -> list[str]:
        try:
            folders = self._request("config/folders") or []
            return [f["id"] for f in folders if "id" in f]
        except Exception:
            return []

    def system_status(self) -> dict:
        try:
            return self._request("system/status") or {}
        except Exception:
            return {}
