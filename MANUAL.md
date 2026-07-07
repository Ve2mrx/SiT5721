# SiT5721 — install & operations manual

Manages the SiT5721 GPSDO's calibration state: periodically saves its
register state (Pull Value / Aging Compensation / Pull Range / Max Freq
Ramp Rate / Total Offset Written) to survive restarts, and restores an
aging-corrected Pull Value automatically after a reboot.

Companion project: [mbt-ubx-apps](../ubx-data/mbt-ubx-apps/) (the GNSS
capture side that reads this same chip to measure calibration drift).
Shared alert email config is documented in both manuals identically — see
[Alert email configuration](#alert-email-configuration). See also
[capture-status](../ubx-data/capture-status/) for a one-shot Go/No-go
health check spanning both projects.

**Keep this file up to date** whenever install steps, file paths, or the
systemd/email setup change.

## Hardware & OS prerequisites

- SiT5721 GPSDO on I2C bus 0, address `0x60` — needs the `i2c-dev` kernel
  module loaded (creates `/dev/i2c-0`) and persisted across reboots via
  `sudo raspi-config` → Interface Options → I2C → Enable (that's the step
  that actually persists `i2c-dev`, not just the `dtparam=i2c_arm=on` it
  also sets). Easy to miss on a fresh image if the I2C buses were instead
  hand-added to `config.txt`, as on this hardware
  (`i2c_vc`/`i2c5`/`i2c_csi_dsi`) — see mbt-ubx-apps' manual for the
  2026-07-06/07 incident this caused there.
- OS packages: `python3-smbus`, `screen`, `msmtp`, `msmtp-mta`
  (`apt install python3-smbus screen msmtp msmtp-mta`)
- `/etc/msmtprc` configured with a working SMTP account (shared with
  mbt-ubx-apps — this host uses a Gmail relay). Contains a plaintext
  password — never echo/paste its contents into chat, commits, or logs.

No Python venv is needed here (unlike mbt-ubx-apps) — everything runs
against the system Python3 with `python3-smbus` installed system-wide.

## 1. Install

```sh
git clone --recurse-submodules <SiT5721-url> SiT5721
cd SiT5721
./install.sh          # symlinks this repo's scripts into ~/bin
```

`read-SiT5721.py`, `restart-SiT5721.py` and `save-SiT5721.py` import the
SiT5721 I2C library from `lib/mbt-SiT5721-lib`, a git submodule shared
with mbt-ubx-apps (single source of truth — see that submodule's own
README). If you cloned without `--recurse-submodules`, run
`git submodule update --init` before running any of them.

For provisioning a whole fresh device (OS reinstall/SD-card swap) rather
than just this repo, see
[../ubx-data/reinstall.sh](../ubx-data/reinstall.sh) — it drives the
steps above plus the mbt-ubx-apps/capture-status repos, OS packages,
I2C/serial checks, and systemd units in one idempotent, re-runnable
pass.

## 2. Alert email configuration

`systemd/restart-sit5721-pull-alert.sh` defaults `ALERT_RECIPIENT` to
`root` and relies on `/etc/msmtprc`'s `aliases /etc/aliases` directive
(added 2026-07-04, see mbt-ubx-apps' project memory
`alert-config-vs-aliases-todo`) to resolve that to a real deliverable
address - no per-host config file needed anymore (retired
`~/.config/sit-alerts.conf`, shared with mbt-ubx-apps, the same day).
On a host without that directive configured, `msmtp` does not consult
`/etc/aliases` on its own, so `root` would fail - either add the
directive there too, or override the default:
`ALERT_RECIPIENT="you@example.com" ./restart-sit5721-pull-alert.sh`.

Emails sent by this project:
- **Urgent** (`Importance: high`): `restart-sit5721-pull.service` failed
  outright (`OnFailure=`).

There is currently no normal-priority confirmation email on this side
(mbt-ubx-apps has one for its own reboot/TOW-resume path, and now also
one for a detected-and-recalculated power loss - see that project's
manual).

## 3. systemd services (boot-time automation)

```sh
cd systemd
sudo ./install-service.sh
```

Installs and enables:
- `restart-sit5721-pull.service` — runs `restart-SiT5721-pull.sh` once
  after every boot, ordered after `network-online.target`: restores an
  aging-corrected Pull Value (`restart-SiT5721.py`). (Renamed 2026-07-04
  from `restart-sit-screen.service` — it hasn't managed any screen since
  the `SiT-save` screen→timer conversion; today it only restores Pull.)
  mbt-ubx-apps' `restart-calib.service` runs `After=` this one, so a real
  power-loss recalc (if any) is already applied and marked before that
  side checks anything - see that project's manual for the mark/archive
  behavior this enables.
- `restart-sit5721-pull-alert.service` — fires automatically via
  `restart-sit5721-pull.service`'s `OnFailure=`; not started directly.
- `save-sit5721.timer` + `save-sit5721.service` — periodically (every 10
  minutes, `OnUnitActiveSec=600` in `save-sit5721.timer`) runs
  `save-SiT5721.py` to persist register state to `~/SiT-settings2.ini`
  (relocated 2026-07-07 from `SiT-settings2.ini` inside this repo to
  `$HOME` — see [Key files/paths](#key-filespaths)). Replaces an older
  `screen`+`watch` mechanism (retired 2026-07-03) — the interval is now a
  normal systemd parameter, not a shell one-liner.

## Operations

- **Check the save timer**: `systemctl list-timers save-sit5721.timer`,
  `journalctl -u save-sit5721.service`
- **Check the last save without journalctl**: `cat SiT-save_status.txt`
  (mirrors `save-SiT5721.py`'s terminal output, written atomically each run)
- **Check boot-time restore logs**: `journalctl -u restart-sit5721-pull.service`
- **Dry-run the restart Pull calculation** (no I2C write):
  `./restart-SiT5721.py --dry-run` (dry-run never writes the power-loss
  mark file below, even if registers are currently at defaults)
- **Manual recalibration** (after a few days of fresh capture data from
  mbt-ubx-apps, per the normal drift-correction workflow): edit
  `write-SiT5721.py`'s hardcoded `new_pull_value`/`target_pull_value`/
  `new_aging_compensation`, then run it. This is a deliberate manual step,
  not automated.
- **Mail failures**: check `~/SiT-restart_mail-failures.log` if an
  expected alert never arrived.

## Power-loss detection and marking

`restart-SiT5721.py` checks the chip's registers (already read by
`SiT5721.__init__()`) *before* writing the recalculated Pull Value. If
they're still at hardware power-on defaults, this restart follows a real
power loss (not just an OS reboot with the chip staying powered). Once
the recalculated values are written and read back verified, it leaves
`~/SiT-power-loss-mark.json` (timestamp, Δt, aging, old total, new Pull)
for mbt-ubx-apps' `restart-calib.sh` to pick up: that script archives the
prior `SiT-calib_output.txt`/`parsed_records.json`/`.csv` and starts a
fresh calibration epoch, then emails a normal-priority notice. See that
project's manual for the consuming side. Nothing here needs to change if
that hand-off's file format ever changes shape — this side only ever
writes it, never reads it back.

## Key files/paths

| Path | Purpose |
|---|---|
| `~/SiT-settings2.ini` | Persisted register state, read by `restart-SiT5721.py` on boot. Relocated 2026-07-07 from `SiT-settings2.ini` inside this repo to `$HOME` (`restart-SiT5721.py`'s `DEFAULT_SETTINGS_FILE`, `save-SiT5721.py`'s default, and `systemd/save-sit5721.service`'s `ExecStart` arg all updated together, commit `775e78a`) - has a `[DEFAULT]` section with its own always-`1970-01-01` stub `datetime` - the real save timestamp is under `[Current]`; anything parsing this file must anchor on `[Current]`, not just grep the first `datetime` line (this bit `reinstall.sh` once). Also read-only pushed to the NAS by mbt-ubx-apps' `../ubx-data/nas-sync/` (one-way, never written back) - see that project's manual |
| `SiT-save_status.txt` | Last terminal output of `save-SiT5721.py`, for monitoring |
| `write-SiT5721_history.txt` | Manually-maintained log of past calibration values (untracked, local only) |
| `~/SiT-power-loss-mark.json` | Written by `restart-SiT5721.py` on a confirmed power-loss recalc; consumed by mbt-ubx-apps' `restart-calib.sh` |
| `~/SiT-restart_mail-failures.log` | Retry/failure log for `restart-sit5721-pull-alert.sh`'s mail sends |
| `lib/mbt-SiT5721-lib/` | Git submodule (shared with mbt-ubx-apps) - `SiT5721` I2C class |
| `../ubx-data/reinstall.sh` | Whole-device provisioning/health check (OS packages, I2C/serial, venv, repos, systemd, mail) - see its own header |

## Known issues / troubleshooting log

**2026-07-06/07 — `restart-SiT5721-pull.sh`'s `SCRIPT_DIR` broke when
invoked via its `~/bin/` symlink.** It derived its own directory with
`dirname -- "$0"`, which doesn't resolve symlinks — running
`~/bin/restart-SiT5721-pull.sh` directly made `SCRIPT_DIR` resolve to
`~/bin` instead of this repo, so `"$SCRIPT_DIR/restart-SiT5721.py"`
happened to still work only because `~/bin/restart-SiT5721.py` is
*also* a symlink to the same file — coincidental, not by design.
`restart-sit5721-pull.service` was never exposed to this (its
`ExecStart=` uses the real absolute path). Fixed by resolving `$0`
through `readlink -f` before taking `dirname` of it (commit `67c225f`).
Same fix applied the same session to mbt-ubx-apps' `start-get-data.sh`
(which *did* break in practice there — see that project's manual),
`set-calib-screen.sh`, and `restart-calib.sh`.

## Known limitations (see project TODOs for detail)

- `restart-SiT5721.py`'s real I2C write path hasn't been exercised
  against an actual post-reset chip yet (only dry-run verified) — the
  first real reset will be its first real test.
- The aging-corrected restart Pull fix has no automated regression test;
  changes here should be re-verified with `--dry-run` against the live
  `SiT-settings2.ini` before trusting a real write.
