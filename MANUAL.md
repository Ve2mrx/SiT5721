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

Since 2026-08-01, `install.sh` also runs a **read-only health-telemetry
self-check** after symlinking: imports `save-SiT5721.py` and exercises
the same read paths its `main()` uses (SiT registers via
`SiT5721.__init__()`, CM4 SoC temp via `cm4_soc_temp_c()`) without
running `main()` itself, so `~/SiT-settings2.ini`/`~/sit-health.csv` are
never touched. Prints `OK` if every field read cleanly, or one `WARN`
line per broken field with the real exception text otherwise - never
fails the install over it (best-effort sampler, not the register-save).
Catches a dead register or missing `vcgencmd` immediately instead of
waiting up to 24h for `sit-status.sh`'s own warning to have enough
window data to judge (see [Key files/paths](#key-filespaths) below and
`ubx-data/claude-code-silent-telemetry-failure-brief.md`). Originally
added to `../ubx-data/reinstall.sh`, then moved here (git-tracked,
available on a standalone `./install.sh` too, matches that script's own
pattern of delegating repo-specific checks to each repo) - see that
file's dated changelog for the move and the accompanying
`run_installers()` fix (it used to discard `install.sh`'s output
entirely, which would have swallowed this warning).

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

  Since 2026-08-01, each run also appends a versioned
  `HEALTH,<version>,...` line to `~/sit-health.csv` (UTC timestamp,
  resonator temp, temp error, heater power + target, supply voltage, CM4
  SoC temp) - `HEALTH_LINE_VERSION` in `save-SiT5721.py` (currently 2),
  bumped alongside any future field-list change, same convention as
  mbt-ubx-apps' `CSV_LINE_VERSION`/`CSV_LINE_FIELDS_V<N>` (adopted here
  before this file had more than one unversioned row in production - a
  reader can dispatch on version instead of guessing column count).
  `SiT5721.__init__()` already calls `read_SiT_operation()` to populate the
  SiT fields, so those are free (no extra I2C traffic); CM4 SoC temp is a
  `vcgencmd measure_temp` subprocess call (`cm4_soc_temp_c()`, best-effort -
  empty column if it fails). The whole append is wrapped in a bare
  `try`/`except: pass` so a logging failure can never affect the actual
  register-save this timer exists for. 144 samples/day this way, vs. the
  once-daily spot values mbt-ubx-apps' capture logs - enough for a real
  daily mean and to resolve diurnal structure. Motivation and design:
  `ubx-data/claude-code-health-logging-patch.md`. No new systemd unit -
  this rides along on the existing timer.

  **Why `vcgencmd` here but sysfs in `get-data.py`**: this sampler's writes
  are already best-effort and 10-min cadence can absorb a subprocess call
  failing/blocking; the daily capture path cannot - `vcgencmd` talks to the
  VideoCore mailbox and can block, fail on a missing package, or fail on
  `/dev/vcio` permissions, none of which may ever touch a capture. See
  `ubx-data/claude-code-throttle-note.md`, which also proposes a *second*,
  not-yet-implemented column here - `vcgencmd get_throttled`'s sticky
  under/over-voltage bits, logged as raw hex - as a lead on the cycle-day-20
  drift instability (a sagging/noisy CM4 rail). Deliberately not started
  yet: that note says explicitly to do it only after this patch has landed
  and settled.

  Also since 2026-08-01: each run recomputes trailing-24h statistics
  (mean/min/max/population-sd, plus `n` and the window bounds) over
  `~/sit-health.csv` and atomically writes them to `~/sit-health-24h.json`
  (`compute_health_window_stats()`). Capture-time independent by
  construction - the window is anchored on "now", not on when/whether a
  capture ran, so this is unaffected by mbt-ubx-apps' daily capture timing.
  Reads only the tail of the log (bounded to 64 KB, ~5.5 days at this
  sample rate) so this stays O(1) as the log grows. `n` is reported
  honestly rather than extrapolated - expect a small `n` for the first 24h
  after this was deployed, and after any gap in samples (reboot, missed
  runs). Best-effort, same reasoning as the health-log append. Tested
  against synthetic logs (known ramp + outlier, a window spanning >24h,
  a 3-sample partial window, corrupt/truncated lines, missing/empty file,
  and capture-time independence) before being wired into real runs.

  **Since 2026-08-01: failures are surfaced, not just silently empty**
  (`ubx-data/claude-code-silent-telemetry-failure-brief.md`). `None` from a
  failed read used to just become an empty CSV field indistinguishable from
  "sampler hasn't run long enough yet." Now: `cm4_soc_temp_c()` records
  *why* it failed in a module-level `_LAST_HEALTH_ERRORS` dict (cleared on
  success, never raises - a bad read still can't affect the register-save);
  `compute_health_window_stats()` adds a `warnings` list (always present,
  `[]` when healthy) to `sit-health-24h.json` - one entry per field in
  `HEALTH_CSV_FIELDS_ALL` with `n == 0` while the window has rows, appending
  the recorded reason when there is one. The one subtlety: a field that's
  simply *newer* than the window (right after a `HEALTH_LINE_VERSION` bump,
  for up to 24h while older-version rows age out) must **not** warn - told
  apart because a sample's parsed dict only carries a key for fields its own
  version's field list includes, so "no sample even carries the key" means
  "too new" rather than "broken." Verified against all 6 cases in the
  brief's test plan (healthy, broken field with/without a recorded reason,
  version-bump window, mixed V1/V2 window, missing/empty/corrupt file) plus
  a real live run. `capture-status/sit-status.sh` reads this file and
  reports **WARN** (not FAIL/NO-GO - diagnostic only, no email alert) for a
  non-empty `warnings` list or a stale/missing file - see that project's
  manual.

  Not yet consumed anywhere else - the next step (deferred until this has
  run long enough to trust) is having mbt-ubx-apps' `get-data.py` copy
  these cooked values into its own CSV line.

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
  mbt-ubx-apps, per the normal drift-correction workflow): append a row to
  **`~/SiT5721-pull-values.csv`**, then `./write-SiT5721.py` to review the plan
  and `./write-SiT5721.py --commit` to apply it. Deliberately manual - the
  decision to re-tune is never automated.
  - ⚠ **Dry run is the default.** Nothing is written without `--commit`. The
    pre-2026-08-05 version wrote all four registers on *every* run, so merely
    inspecting the device changed it. Use `--show` to read and stop.
  - Values live **outside the repo** (like `SiT-settings2.ini`), so a
    `git checkout`/reset cannot destroy the calibration history, and they
    survive a `git pull` on the device. Override with `--file`.
  - Missing values file -> an annotated example is written there and the
    script exits **without touching the device**.
  - **`pull` is the raw Pull register value and is written verbatim** - copy it
    from the workbook, `Calc-new-<cycle>` **row 75, last DAY column** (not the
    rightmost; skeleton columns carry copies). The script does *not* recompute
    it. The workbook already converts target -> register (row 75 = row 73 -
    row 74) using the uptime at *calculation* time; redoing that on the device
    would use the uptime at *write* time and give a different number. After a
    power loss, where uptime is ~0, it would collapse to `pull = target` and be
    wrong by the whole accumulated compensation - 0.89 ppb on the real
    2026-03-28 re-tune, in exactly the scenario the script is used for.
  - `target_pull` (workbook row 73) is recorded in the CSV for provenance only.
    `SiT5721.pull_for_target()` exists but is **deliberately unwired**, as
    `calc_SiT_new_pull_value_from_target()` was before it.
  - Registers are written constraints-first (range, ramp, aging, pull), then
    read back and verified, then appended to `~/SiT5721-write-log.csv`.
  - Refuses to write on: `target_pull = 0` (would wipe the calibration),
    an aging exponent outside +/-1e-12, a Pull that exceeds Pull Range, or a
    device that is not `good, stabilized`. Override with `--allow-zero` /
    `--force`.
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
| `~/sit-health.csv` | Append-only health-telemetry log, one line per `save-SiT5721.py` run (every 10 min) - see above. Pushed to the NAS best-effort by mbt-ubx-apps' `nas-sync.sh` |
| `~/sit-health-24h.json` | Cooked trailing-24h statistics over `~/sit-health.csv`, rewritten atomically every run - see above |
| `~/SiT5721-pull-values.csv` | **Calibration values + history for this device**, read by `write-SiT5721.py` (last row wins). Untracked, local only; an annotated example is created if missing |
| `~/SiT5721-write-log.csv` | Append-only audit of every committed write: intended target, derived Pull, and the device's before/after readings |
| `write-SiT5721_history.txt` | *Superseded 2026-08-05* by `~/SiT5721-pull-values.csv`. Manually-maintained log of past calibration values (untracked, local only) |
| `~/SiT-power-loss-mark.json` | Written by `restart-SiT5721.py` on a confirmed power-loss recalc; consumed by mbt-ubx-apps' `restart-calib.sh` |
| `~/SiT-restart_mail-failures.log` | Retry/failure log for `restart-sit5721-pull-alert.sh`'s mail sends |
| `lib/mbt-SiT5721-lib/` | Git submodule (shared with mbt-ubx-apps) - `SiT5721` I2C class |
| `../ubx-data/reinstall.sh` | Whole-device provisioning/health check (OS packages, I2C/serial, venv, repos, systemd, mail) - see its own header |

## Known issues / troubleshooting log

**2026-07-08 — `cook_f32()` now applied at settings-file read time, not
just at comparison time.** Follow-up to the fix below: applying
`cook_f32()` only inside the `checks` tuple worked, but meant every future
call site using `total`/`prange`/`aging`/`ramp` would have to separately
remember to cook them before comparing against a chip readback - the same
gap that let 3 of 4 fields go uncooked for a while. `read_settings()` now
cooks all four numeric fields through float32 right where they're parsed
from the ini file, since that's their true precision regardless of the
file's text representation (the SiT5721's registers are float32). Only
`new_pull` still needs `cook_f32()` at comparison time, since it's freshly
computed (`total + aging * delta_t`) rather than a direct passthrough
read. Commit `0f664cc`.

**2026-07-08 — `cook_f32()` fixed for the Aging/Pull Range/Max Freq Ramp
Rate readback checks, not just Pull Value.** The `checks` tuple only
rounded the Pull Value's expected value through `cook_f32()` before
comparing against the chip's readback; the other three fields compared
raw ini-file floats directly, which could in theory false-MISMATCH (->
alert email) against a hand-edited, non-float32-clean settings value.
Didn't affect the real 2026-07-06/07 power-loss event below, since those
values happened to round-trip cleanly already. Commit `a64c9db`.

**2026-07-06/07 — real power-loss recalc verified live, for real, by the
Trixie OS switch.** The CM4 reflash/reboot genuinely power-cycled the
SiT5721 (it's evidently not on an independent power rail from the CM4),
so `restart-sit5721-pull.service`'s boot-time run
(2026-07-06 22:10:06 EDT) hit the real `is_at_defaults()` → write →
readback-verify path in `restart-SiT5721.py` for the first time, not just
in dry-run. Confirmed correct via an independent readback well after the
write: `get-data.py`'s later capture (`~/SiT-calib_output.txt`) shows the
live chip reporting `SiT Pull Value +0.1173464 ppm`, an exact match to the
`restart_pull_value` computed and written at boot (see the archived
`~/SiT-calib_archive/SiT-power-loss-mark_2026-07-07T021006.json`). The
mbt-ubx-apps side of the hand-off (archive-and-restart) also worked
end-to-end — see that project's manual. One real gap this exposed: the
confirmation email from that event failed to send, because it was the
very first boot after the reflash and `/etc/msmtprc` hadn't been
redeployed yet (not a logic bug) — since fixed, see `~/TRIXIE-MIGRATION.md`.

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

- The aging-corrected restart Pull fix has no automated regression test;
  changes here should be re-verified with `--dry-run` against the live
  `SiT-settings2.ini` before trusting a real write.
