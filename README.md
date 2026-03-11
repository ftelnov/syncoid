# Syncoid

Battery-efficient manual Syncthing sync for Android/Termux.

Syncthing normally runs 24/7, draining battery. Syncoid keeps it off and only starts it when needed — on a schedule, on demand, or when your files actually change.

## How it works

```
Files changed ──→ inotify wakes syncoid (zero battery while idle)
                        │
Schedule fires ──→ JobScheduler wakes syncoid (respects Doze)
                        │
Tap shortcut ────→ on-demand sync
                        │
                   ┌────▼────┐
                   │ Syncoid │
                   └────┬────┘
                        │
              check conditions (WiFi? battery? charging?)
                        │
              start Syncthing → scan → wait for sync → stop Syncthing
```

Syncthing runs only during the sync window (seconds to minutes), then gets shut down immediately.

## Requirements

Install from F-Droid (all from the same source — **not** Google Play):

- **Termux** — terminal emulator
- **Termux:API** — battery/network/notification access
- **Termux:JobScheduler** — periodic scheduling (optional, for scheduled mode)
- **Termux:Widget** — home screen shortcut (optional)

Inside Termux:

```bash
pkg install python git syncthing termux-api
```

For file-watch mode (recommended):

```bash
pkg install inotify-tools
```

## Install

One-liner:

```bash
curl -fsSL https://raw.githubusercontent.com/ftelnov/syncoid/master/install.sh | bash
```

The installer auto-detects and installs missing Termux packages (`python`, `git`, `syncthing`, `termux-api`, `inotify-tools`) — no need to install them manually beforehand.

Manual:

```bash
pip install git+https://github.com/ftelnov/syncoid.git
syncoid configure
```

## First-time Syncthing setup

If you've never used Syncthing before, follow these steps to get it running on your phone and connected to another device (PC, laptop, server, another phone).

### 1. Initialize Syncthing on your phone

```bash
syncthing
```

Wait until you see `GUI and API listening on 127.0.0.1:8384` in the output, then press **Ctrl-C**. This creates the config and generates your device ID and API key. Syncoid will auto-detect the API key from here.

### 2. Get your phone's Device ID

```bash
syncthing --device-id
```

Copy this string — you'll need it on the other device. It looks like `XXXXXXX-XXXXXXX-XXXXXXX-XXXXXXX-XXXXXXX-XXXXXXX-XXXXXXX-XXXXXXX`.

### 3. Connect the two devices

**On your PC** (Syncthing web UI at 127.0.0.1:8384):

1. Go to **Actions** (top right) > **Show ID** — copy this ID
2. Click **Add Remote Device**
3. Paste your **phone's Device ID** (from step 2)
4. Give it a name (e.g. "Phone")
5. Click **Save**

**On your phone**, start Syncthing temporarily with the GUI exposed:

```bash
syncthing --gui-address=0.0.0.0:8384
```

Find your phone's IP (`ifconfig wlan0` in another Termux session), then open `http://PHONE_IP:8384` from your PC browser.

In the phone's web UI:
1. Click **Add Remote Device**
2. Paste your **PC's Device ID**
3. Click **Save**

Both devices should show as "Connected" within a few seconds (if on the same network).

### 4. Create a shared folder

Make sure Termux has storage permission first:

```bash
termux-setup-storage
```

**On your PC** (web UI at 127.0.0.1:8384):

1. Click **Add Folder**
2. Set **Folder Label** (e.g. "Photos") and **Folder Path** (e.g. `~/Sync/Photos`)
3. Go to the **Sharing** tab, check your phone device
4. Click **Save**

**On your phone** (web UI still open from step 4):

A prompt appears asking to accept the shared folder. Click **Add**, set the local path, and save.

If the prompt doesn't appear, add the folder manually:
1. Click **Add Folder**
2. Use the **same Folder ID** as on the PC (visible in the PC's folder settings)
3. Set the path to a local phone directory
4. Go to **Sharing**, check the PC device
5. Click **Save**

Common phone paths:

| Content | Path |
|---|---|
| Camera photos | `/storage/emulated/0/DCIM` |
| Documents | `/storage/emulated/0/Documents` |
| Downloads | `/storage/emulated/0/Download` |
| Custom folder | `/data/data/com.termux/files/home/sync` |

When done, stop Syncthing on the phone (Ctrl-C in Termux). Syncoid will manage it from here.

### 5. Install Syncoid and test

```bash
curl -fsSL https://raw.githubusercontent.com/ftelnov/syncoid/master/install.sh | bash
```

Then test:

```bash
syncoid now
```

Syncoid starts Syncthing, scans all folders, waits for sync to complete, then shuts it down. If both devices are on the same network, files should appear on the other side within seconds.

If this is your first sync with a large folder, increase the sync window in `~/.config/syncoid/config.json`:

```json
{ "max_window_min": 30 }
```

Then run `syncoid now` again.

### 6. Start watching

```bash
syncoid watch
```

From now on, any file you save, photo you take, or document you edit gets synced automatically — without Syncthing running 24/7.

## Usage

### Sync now

```bash
syncoid now
```

Starts Syncthing, scans all folders, waits for completion, stops Syncthing.

### Watch mode (recommended)

```bash
syncoid watch
```

Watches your Syncthing folders using inotify. When a file changes, waits for a quiet period (default 5s), then syncs. **Near-zero battery cost** — the process sleeps on a kernel syscall between events, using no CPU.

Best for: instant push of local changes (photos, notes, documents).

Pair with a periodic schedule for pulling remote changes:

```bash
# Terminal 1: instant local sync
syncoid watch

# Configured separately: periodic remote pull
syncoid configure --period 2
syncoid enable
```

### Running watch in background

`syncoid watch` needs to stay running. Three options:

**tmux (recommended):**

```bash
pkg install tmux
tmux new -s syncoid -d 'syncoid watch'   # start detached
tmux attach -t syncoid                    # reattach to see logs
```

**Auto-start on boot (Termux:Boot):**

```bash
# Install Termux:Boot from F-Droid, then:
syncoid watch-boot enable     # creates ~/.termux/boot/syncoid-boot.sh
syncoid watch-boot disable    # removes it
```

After enabling, watch mode starts automatically every time your phone reboots. You don't need to open Termux manually — Termux:Boot launches it in the background.

**nohup (quick & dirty):**

```bash
nohup syncoid watch >> ~/.config/syncoid/logs/watch.log 2>&1 &
```

Termux must remain in the background (don't swipe it away). To prevent Android from killing Termux, go to **Settings > Apps > Termux > Battery > Unrestricted**.

### Periodic schedule

```bash
syncoid configure --period 2              # every 2 hours
syncoid configure --wifi-only true        # only on WiFi
syncoid configure --charging-only true    # only when charging

syncoid enable                            # start the schedule
syncoid disable                           # stop it
```

Uses Android's JobScheduler via Termux:JobScheduler. Respects Doze mode. Survives reboots (boot hook auto-installed).

### Status

```bash
syncoid status
```

Shows config, battery, network, last sync result, and active jobs.

### Home screen shortcut

1. Install **Termux:Widget** from F-Droid
2. Long-press home screen → Widgets → Termux:Widget
3. Tap **sync-now** to sync instantly

## Configuration

Stored at `~/.config/syncoid/config.json`:

```json
{
  "period_hours": 0.5,
  "wifi_only": true,
  "charging_only": false,
  "min_battery_pct": 20,
  "max_window_min": 10,
  "managed_folders": [],
  "enable_wakelock": false,
  "notify_on_failure": true,
  "notify_on_success": false,
  "watch_debounce_sec": 5.0,
  "log_retention_days": 7,
  "ondemand_max_wait_min": 5
}
```

| Setting | Default | Description |
|---|---|---|
| `period_hours` | 0.5 | Scheduled sync interval |
| `wifi_only` | true | Only sync on WiFi |
| `charging_only` | false | Only sync when plugged in |
| `min_battery_pct` | 20 | Skip sync below this battery level (unless charging) |
| `max_window_min` | 10 | Max time to wait for a folder to finish syncing |
| `managed_folders` | [] | Folder IDs to sync (empty = all Syncthing folders) |
| `enable_wakelock` | false | Hold wakelock during sync (usually unnecessary) |
| `notify_on_failure` | true | Android notification on sync failure |
| `notify_on_success` | false | Android notification on sync success |
| `watch_debounce_sec` | 5.0 | Seconds to wait after last file change before syncing |
| `log_retention_days` | 7 | Auto-delete logs older than this |
| `ondemand_max_wait_min` | 5 | Max wait for on-demand sync |
| `gui_addr` | 127.0.0.1:8384 | Syncthing API address |

Override config directory:

```bash
export SYNCOID_CONFIG_DIR=/custom/path
```

## Battery guide

**Best setup for most people:**

```bash
# Install
pkg install python git syncthing termux-api inotify-tools
pip install git+https://github.com/ftelnov/syncoid.git
syncoid configure

# Run watch in a Termux session (or tmux/screen)
syncoid watch
```

This gives you instant sync when files change, with zero battery drain while idle.

**If you also want periodic remote pulls:**

```bash
syncoid configure --period 2
syncoid enable
```

**Maximum battery saving (charge-only sync):**

Edit `~/.config/syncoid/config.json`:

```json
{
  "wifi_only": true,
  "charging_only": true,
  "period_hours": 4
}
```

**What each mode costs:**

| Mode | Battery while idle | Sync trigger |
|---|---|---|
| `syncoid watch` | ~0 (kernel sleep) | File change |
| Periodic (JobScheduler) | ~0 (Doze-aware) | Timer |
| `syncoid now` | N/A | Manual |
| Syncthing always-on | Continuous drain | Immediate |

## Logs

Written to `~/.config/syncoid/logs/syncoid-YYYY-MM-DD.log`. Auto-cleaned after `log_retention_days` (default 7).

Last sync result stored in `~/.config/syncoid/state/last_run.json`.

## Development

Run the test suite (requires Docker):

```bash
docker compose -f docker-compose.test.yml up --build --abort-on-container-exit
```

This starts a real Syncthing instance, installs Termux API stubs, and runs 126 tests covering:

- Unit tests (config, conditions, Syncthing client)
- Integration tests (real Syncthing API, inotify watcher, CLI flows)
- Stub validation (battery, WiFi, job scheduler, notifications)

Run unit tests locally (no Docker):

```bash
PYTHONPATH=. python -m pytest tests/test_syncoid.py tests/test_config.py tests/test_power_net.py -v
```

## License

MIT
