# SiT5721 — install & operations manual

Manages the SiT5721 GPSDO's calibration state: periodically saves its
register state (Pull Value / Aging Compensation / Pull Range / Max Freq
Ramp Rate / Total Offset Written) to survive restarts, and restores an
aging-corrected Pull Value automatically after a reboot.

Companion project: [mbt-ubx-apps](../ubx-data/mbt-ubx-apps/) (the GNSS
capture side that reads this same chip to measure calibration drift).
Shared alert email config is documented in both manuals identically — see
[Alert email configuration](#alert-email-configuration).

**Keep this file up to date** whenever install steps, file paths, or the
systemd/email setup change.

## Hardware & OS prerequisites

- SiT5721 GPSDO on I2C bus 0, address `0x60`
- OS packages: `python3-smbus`, `screen`, `msmtp`, `msmtp-mta`
  (`apt install python3-smbus screen msmtp msmtp-mta`)
- `/etc/msmtprc` configured with a working SMTP account (shared with
  mbt-ubx-apps — this host uses a Gmail relay). Contains a plaintext
  password — never echo/paste its contents into chat, commits, or logs.

No Python venv is needed here (unlike mbt-ubx-apps) — everything runs
against the system Python3 with `python3-smbus` installed system-wide.

## 1. Install

```sh
cd SiT5721
./install.sh          # symlinks this repo's scripts into ~/bin
```

## 2. Alert email configuration

Shared with mbt-ubx-apps. Create (once, host-wide, **not** tracked by
either git repo):

```sh
mkdir -p ~/.config
cat > ~/.config/sit-alerts.conf <<'EOF'
ALERT_RECIPIENT="you@example.com"
EOF
```

`systemd/restart-sit-screen-alert.sh` sources this file and refuses to
send (fails loud in the log, not silently) if `ALERT_RECIPIENT` is unset.
The recipient **must** be a real, directly-deliverable address — `msmtp`
does not consult `/etc/aliases`.

Emails sent by this project:
- **Urgent** (`Importance: high`): `restart-sit-screen.service` failed
  outright (`OnFailure=`).

There is currently no normal-priority confirmation email on this side
(mbt-ubx-apps has one for its own reboot/TOW-resume path).

## 3. systemd services (boot-time automation)

```sh
cd systemd
sudo ./install-service.sh
```

Installs and enables:
- `restart-sit-screen.service` — runs `restart-SiT-screen.sh` once after
  every boot, ordered after `network-online.target`: restores an
  aging-corrected Pull Value (`restart-SiT5721.py`), then verifies/starts
  the `SiT-save` screen if it isn't already running.
- `restart-sit-screen-alert.service` — fires automatically via
  `restart-sit-screen.service`'s `OnFailure=`; not started directly.
- `save-sit5721.timer` + `save-sit5721.service` — periodically (every 10
  minutes, `OnUnitActiveSec=600` in `save-sit5721.timer`) runs
  `save-SiT5721.py` to persist register state to `SiT-settings2.ini`.
  Replaces an older `screen`+`watch` mechanism (retired 2026-07-03) — the
  interval is now a normal systemd parameter, not a shell one-liner.

## Operations

- **Check the save timer**: `systemctl list-timers save-sit5721.timer`,
  `journalctl -u save-sit5721.service`
- **Check the last save without journalctl**: `cat SiT-save_status.txt`
  (mirrors `save-SiT5721.py`'s terminal output, written atomically each run)
- **Check boot-time restore logs**: `journalctl -u restart-sit-screen.service`
- **Dry-run the restart Pull calculation** (no I2C write):
  `./restart-SiT5721.py --dry-run`
- **Manual recalibration** (after a few days of fresh capture data from
  mbt-ubx-apps, per the normal drift-correction workflow): edit
  `write-SiT5721.py`'s hardcoded `new_pull_value`/`target_pull_value`/
  `new_aging_compensation`, then run it. This is a deliberate manual step,
  not automated.
- **Mail failures**: check `~/SiT-restart_mail-failures.log` if an
  expected alert never arrived.

## Key files/paths

| Path | Purpose |
|---|---|
| `SiT-settings2.ini` | Persisted register state (`[Current]` section), read by `restart-SiT5721.py` on boot |
| `SiT-save_status.txt` | Last terminal output of `save-SiT5721.py`, for monitoring |
| `write-SiT5721_history.txt` | Manually-maintained log of past calibration values (untracked, local only) |
| `~/SiT-restart_mail-failures.log` | Retry/failure log for `restart-sit-screen-alert.sh`'s mail sends |
| `~/.config/sit-alerts.conf` | Shared alert recipient config (see above) |

## Known limitations (see project TODOs for detail)

- `restart-SiT5721.py`'s real I2C write path hasn't been exercised
  against an actual post-reset chip yet (only dry-run verified) — the
  first real reset will be its first real test.
- The aging-corrected restart Pull fix has no automated regression test;
  changes here should be re-verified with `--dry-run` against the live
  `SiT-settings2.ini` before trusting a real write.
