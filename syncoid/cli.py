"""Syncoid CLI - Battery-efficient Syncthing scheduler for Termux."""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import Config
from .syncthing import Syncthing
from .power_net import (
    check_sync_conditions,
    get_battery_status,
    get_network_info,
    acquire_wakelock,
    release_wakelock,
    send_notification,
)
from .scheduler import register_job, unregister_job, list_jobs, install_boot_hook, remove_boot_hook
from .watcher import resolve_watch_paths, watch_folders


def log(msg: str, level: str = "INFO"):
    config_dir = Config.config_dir()
    logs_dir = config_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_file = logs_dir / f"syncoid-{datetime.now().strftime('%Y-%m-%d')}.log"
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] [{level}] {msg}"

    with open(log_file, "a") as f:
        f.write(line + "\n")

    print(line)


def cleanup_old_logs(retention_days: int = 7):
    logs_dir = Config.logs_dir()
    if not logs_dir.exists():
        return
    cutoff = datetime.now().timestamp() - retention_days * 86400
    for log_file in logs_dir.glob("syncoid-*.log"):
        if log_file.stat().st_mtime < cutoff:
            log_file.unlink()


def save_last_run(status: str, folders: list[str] | None = None):
    state_dir = Config.state_dir()
    state_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "folders": folders or [],
    }
    (state_dir / "last_run.json").write_text(json.dumps(data))


def cmd_run(args):
    config = Config.load()
    cleanup_old_logs(config.log_retention_days)

    if not config.api_key:
        log("API key not configured. Run: syncoid configure", "ERROR")
        return 1

    if not args.force:
        ok, reason = check_sync_conditions(
            wifi_only=config.wifi_only,
            charging_only=config.charging_only,
            min_battery=config.min_battery_pct,
        )
        if not ok:
            log(f"Skipping sync: {reason}", "INFO")
            return 0

    syncthing = Syncthing(config)

    if config.enable_wakelock:
        acquire_wakelock()

    try:
        log("Starting sync...")

        if not syncthing.is_running():
            if not syncthing.start():
                log("Failed to start Syncthing", "ERROR")
                if config.notify_on_failure:
                    send_notification("Syncoid", "Failed to start Syncthing")
                save_last_run("failed")
                return 1

        folders = config.managed_folders if config.managed_folders else syncthing.list_folders()

        if not folders:
            log("No folders configured", "WARN")
            save_last_run("no_folders")
            return 0

        all_synced = True
        for folder in folders:
            log(f"Scanning folder: {folder}")
            syncthing.scan(folder)

            timeout = config.max_window_min * 60
            if syncthing.wait_synced(folder, timeout=timeout):
                log(f"Folder synced: {folder}")
            else:
                log(f"Folder sync timeout: {folder}", "WARN")
                all_synced = False

        if all_synced:
            log("Sync completed")
            save_last_run("success", folders)
            if config.notify_on_success:
                send_notification("Syncoid", "Sync completed successfully")
            return 0
        else:
            log("Sync completed with warnings", "WARN")
            save_last_run("partial", folders)
            if config.notify_on_failure:
                send_notification("Syncoid", "Sync completed with timeouts")
            return 2

    except Exception as e:
        log(f"Sync failed: {e}", "ERROR")
        if config.notify_on_failure:
            send_notification("Syncoid", f"Sync failed: {e}")
        save_last_run("failed")
        return 1
    finally:
        syncthing.stop()
        if config.enable_wakelock:
            release_wakelock()


def cmd_now(args):
    config = Config.load()

    if not config.api_key:
        log("API key not configured. Run: syncoid configure", "ERROR")
        return 1

    syncthing = Syncthing(config)

    if config.enable_wakelock:
        acquire_wakelock()

    try:
        log("On-demand sync starting...")

        if not syncthing.is_running():
            if not syncthing.start():
                log("Failed to start Syncthing", "ERROR")
                send_notification("Syncoid", "Failed to start Syncthing")
                return 1

        folders = config.managed_folders if config.managed_folders else syncthing.list_folders()

        for folder in folders:
            log(f"Scanning: {folder}")
            syncthing.scan(folder)

        timeout = config.ondemand_max_wait_min * 60
        for folder in folders:
            if syncthing.wait_synced(folder, timeout=timeout):
                log(f"Synced: {folder}")
            else:
                log(f"Timeout: {folder}", "WARN")

        log("On-demand sync completed")
        save_last_run("ondemand_success", folders)
        send_notification("Syncoid", "Sync completed")
        return 0

    except Exception as e:
        log(f"On-demand sync failed: {e}", "ERROR")
        send_notification("Syncoid", f"Sync failed: {e}")
        save_last_run("failed")
        return 1
    finally:
        syncthing.stop()
        if config.enable_wakelock:
            release_wakelock()


def cmd_watch(args):
    config = Config.load()

    if not config.api_key:
        log("API key not configured. Run: syncoid configure", "ERROR")
        return 1

    paths = resolve_watch_paths(config)
    if not paths:
        log("No folder paths found. Ensure Syncthing has configured folders.", "ERROR")
        return 1

    debounce = args.debounce if args.debounce is not None else config.watch_debounce_sec

    log(f"Watching {len(paths)} folder(s) (debounce={debounce}s):")
    for p in paths:
        log(f"  {p}")

    def on_change():
        log("Changes detected, syncing...")
        cmd_run(argparse.Namespace(force=True))

    try:
        watch_folders(
            paths=paths,
            on_change=on_change,
            debounce_sec=debounce,
        )
    except KeyboardInterrupt:
        log("Watcher stopped")
    except RuntimeError as e:
        log(str(e), "ERROR")
        return 1

    return 0


def cmd_configure(args):
    config = Config.load()
    
    if args.api_key:
        config.api_key = args.api_key
    
    if args.period:
        config.period_hours = float(args.period)
    
    if args.wifi_only is not None:
        config.wifi_only = args.wifi_only
    
    if args.charging_only is not None:
        config.charging_only = args.charging_only
    
    if not config.api_key:
        log("No API key detected. Get it from Syncthing Settings → Actions → Show ID", "ERROR")
        return 1
    
    config.save()
    log(f"Configuration saved to {Config.config_file()}")
    
    if register_job(config):
        log(f"Scheduled job registered (every {config.period_hours}h)")
    else:
        log("JobScheduler not available. Install Termux:JobScheduler add-on", "WARN")
    
    if install_boot_hook(config):
        log("Boot hook installed")
    
    return 0


def cmd_status(args):
    config = Config.load()
    
    print(f"Config: {Config.config_file()}")
    print(f"API Key: {'configured' if config.api_key else 'NOT SET'}")
    print(f"Period: {config.period_hours}h")
    print(f"WiFi Only: {config.wifi_only}")
    print(f"Charging Only: {config.charging_only}")
    print()
    
    battery = get_battery_status()
    if battery:
        print(f"Battery: {battery.percentage}% ({'charging' if battery.is_charging else 'discharging'})")
    
    network = get_network_info()
    print(f"Network: {network.network_type} ({'WiFi' if network.is_wifi else 'cellular/other'})")
    print()
    
    last_run_file = Config.state_dir() / "last_run.json"
    if last_run_file.exists():
        last_run = json.loads(last_run_file.read_text())
        print(f"Last Run: {last_run.get('timestamp', 'unknown')}")
        print(f"Status: {last_run.get('status', 'unknown')}")
        folders = last_run.get("folders", [])
        if folders:
            label = ", ".join(folders) if isinstance(folders, list) else folders
            print(f"Folders: {label}")
    else:
        print("Last Run: never")
    
    print()
    jobs = list_jobs()
    if jobs:
        print(f"Scheduled Jobs: {len(jobs)}")
        for job in jobs:
            print(f"  - Job {job.get('id')}: period={job.get('periodMs', 0)/3600000:.1f}h")
    else:
        print("Scheduled Jobs: none")

    return 0


def cmd_enable(args):
    config = Config.load()
    
    if not config.api_key:
        log("Run 'syncoid configure' first", "ERROR")
        return 1
    
    if register_job(config):
        log("Scheduled sync enabled")
        install_boot_hook(config)
        return 0
    else:
        log("Failed to register job. Install Termux:JobScheduler add-on", "ERROR")
        return 1


def cmd_disable(args):
    if unregister_job():
        log("Scheduled sync disabled")
        return 0
    return 1


def cmd_watch_boot(args):
    """Enable or disable auto-start of watch mode on boot via Termux:Boot."""
    config = Config.load()

    if args.action == "enable":
        if install_boot_hook(config, watch=True):
            log("Boot hook installed: watch mode will start on boot")
            return 0
        else:
            log("Failed to install boot hook", "ERROR")
            return 1
    else:
        if remove_boot_hook():
            # Re-install without watch if periodic schedule is active
            jobs = list_jobs()
            if jobs:
                install_boot_hook(config, watch=False)
                log("Boot hook updated: watch removed, periodic schedule kept")
            else:
                log("Boot hook removed")
            return 0
        return 1


def main():
    parser = argparse.ArgumentParser(
        prog="syncoid",
        description="Battery-efficient Syncthing scheduler for Termux",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    p_run = subparsers.add_parser("run", help="Run sync (called by scheduler)")
    p_run.add_argument("--force", "-f", action="store_true", help="Skip condition checks")
    p_run.set_defaults(func=cmd_run)
    
    p_now = subparsers.add_parser("now", help="Sync now (on-demand)")
    p_now.set_defaults(func=cmd_now)

    p_watch = subparsers.add_parser("watch", help="Watch folders and sync on change")
    p_watch.add_argument("--debounce", type=float, default=None, help="Seconds to wait after last change (default: config)")
    p_watch.set_defaults(func=cmd_watch)

    p_configure = subparsers.add_parser("configure", help="Configure and register job")
    p_configure.add_argument("--api-key", help="Syncthing API key")
    p_configure.add_argument("--period", type=float, help="Sync period in hours")
    p_configure.add_argument("--wifi-only", type=lambda x: x.lower() == "true", help="WiFi only (true/false)")
    p_configure.add_argument("--charging-only", type=lambda x: x.lower() == "true", help="Charging only (true/false)")
    p_configure.set_defaults(func=cmd_configure)
    
    p_status = subparsers.add_parser("status", help="Show status")
    p_status.set_defaults(func=cmd_status)
    
    p_enable = subparsers.add_parser("enable", help="Enable scheduled sync")
    p_enable.set_defaults(func=cmd_enable)
    
    p_disable = subparsers.add_parser("disable", help="Disable scheduled sync")
    p_disable.set_defaults(func=cmd_disable)

    p_watch_boot = subparsers.add_parser("watch-boot", help="Auto-start watch on boot")
    p_watch_boot.add_argument("action", choices=["enable", "disable"], help="Enable or disable")
    p_watch_boot.set_defaults(func=cmd_watch_boot)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
