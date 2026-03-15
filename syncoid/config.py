"""Configuration management with auto-detection and sensible defaults."""

import os
import json
from pathlib import Path
from dataclasses import dataclass, field, fields
from typing import Optional
import xml.etree.ElementTree as ET


@dataclass
class Config:
    period_hours: float = 0.5
    wifi_only: bool = True
    charging_only: bool = False
    min_battery_pct: int = 20
    max_window_min: int = 10
    gui_addr: str = "127.0.0.1:8384"
    managed_folders: list[str] = field(default_factory=list)
    enable_wakelock: bool = False
    notify_on_failure: bool = True
    notify_on_success: bool = False
    log_retention_days: int = 7
    ondemand_max_wait_min: int = 5
    watch_debounce_sec: float = 5.0
    default_folder_path: str = "/storage/emulated/0/Sync"
    api_key: Optional[str] = None

    def __post_init__(self):
        if self.period_hours <= 0:
            self.period_hours = 0.5
        if self.min_battery_pct < 0:
            self.min_battery_pct = 0
        elif self.min_battery_pct > 100:
            self.min_battery_pct = 100

    @classmethod
    def config_dir(cls) -> Path:
        return Path(os.environ.get("SYNCOID_CONFIG_DIR", "~/.config/syncoid")).expanduser()
    
    @classmethod
    def config_file(cls) -> Path:
        return cls.config_dir() / "config.json"
    
    @classmethod
    def state_dir(cls) -> Path:
        return cls.config_dir() / "state"
    
    @classmethod
    def logs_dir(cls) -> Path:
        return cls.config_dir() / "logs"
    
    @staticmethod
    def _syncthing_config_xml() -> Path:
        """Locate Syncthing's config.xml respecting env overrides."""
        for env in ("STCONFDIR", "STHOMEDIR"):
            val = os.environ.get(env)
            if val:
                return Path(val).expanduser() / "config.xml"
        # Syncthing v2+ uses XDG state dir; older versions use XDG config dir
        candidates = [
            Path.home() / ".local/state/syncthing/config.xml",
            Path.home() / ".config/syncthing/config.xml",
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]  # default to new location

    @classmethod
    def _detect_api_key(cls) -> Optional[str]:
        st_config = cls._syncthing_config_xml()
        if st_config.exists():
            try:
                tree = ET.parse(st_config)
                elem = tree.find(".//apikey")
                if elem is not None and elem.text:
                    return elem.text.strip()
            except Exception:
                pass
        return None
    
    @classmethod
    def apply_syncthing_defaults(cls, config: "Config") -> None:
        """Set defaultFolderPath in Syncthing's config.xml so accepted folders land in the right place."""
        st_config = cls._syncthing_config_xml()
        if not st_config.exists():
            return
        try:
            tree = ET.parse(st_config)
            root = tree.getroot()
            options = root.find("options")
            if options is None:
                options = ET.SubElement(root, "options")

            dfp = options.find("defaultFolderPath")
            if dfp is None:
                dfp = ET.SubElement(options, "defaultFolderPath")

            if dfp.text != config.default_folder_path:
                dfp.text = config.default_folder_path
                tree.write(str(st_config), xml_declaration=True, encoding="unicode")
                try:
                    Path(config.default_folder_path).mkdir(parents=True, exist_ok=True)
                except OSError:
                    pass
        except Exception:
            pass

    @classmethod
    def load(cls) -> "Config":
        config = cls()
        
        valid_fields = {f.name for f in fields(cls)}
        if cls.config_file().exists():
            try:
                data = json.loads(cls.config_file().read_text())
                for key, value in data.items():
                    if key in valid_fields:
                        setattr(config, key, value)
            except Exception:
                pass
        
        if not config.api_key:
            config.api_key = cls._detect_api_key()
        
        cls.state_dir().mkdir(parents=True, exist_ok=True)
        cls.logs_dir().mkdir(parents=True, exist_ok=True)
        
        return config
    
    def save(self) -> None:
        self.config_dir().mkdir(parents=True, exist_ok=True)
        data = {
            "period_hours": self.period_hours,
            "wifi_only": self.wifi_only,
            "charging_only": self.charging_only,
            "min_battery_pct": self.min_battery_pct,
            "max_window_min": self.max_window_min,
            "gui_addr": self.gui_addr,
            "managed_folders": self.managed_folders,
            "enable_wakelock": self.enable_wakelock,
            "notify_on_failure": self.notify_on_failure,
            "notify_on_success": self.notify_on_success,
            "log_retention_days": self.log_retention_days,
            "ondemand_max_wait_min": self.ondemand_max_wait_min,
            "watch_debounce_sec": self.watch_debounce_sec,
            "default_folder_path": self.default_folder_path,
        }
        if self.api_key:
            data["api_key"] = self.api_key
        
        config_path = self.config_file()
        config_path.write_text(json.dumps(data, indent=2))
        config_path.chmod(0o600)
