# Brief for Claude Code: aging-corrected restart Pull Value (SiT5721)

Prepared 2026-07-03. Verify all claims against the actual files before coding —
they may have changed.

## Goal
On power failure the SiT5721 resets (Pull / Aging / Total offset → 0). The restart
procedure reloads the last saved **Total Offset Written** as the new Pull Value,
but does **not** account for the time elapsed since that value was saved, so the
Pull is offset (frequency drifts during the gap). Today this is patched by running
a few days with the wrong Pull, then recalculating. Fix: extrapolate the offset
forward by the aging that occurred during the gap, so the restart Pull is close to
correct immediately.

## The fix (validated)
The SiT builds its output as roughly `Total = Pull + Aging × uptime`. Extrapolate
the saved offset across the gap:

```
Pull_restart = last_Total_Offset_Written + Aging × Δt
Aging_restart = last_Aging_Compensation        # reuse; it's stable
```
- `Aging` = aging_compensation (part/s), the value being reused
- `Δt`   = seconds from the settings save time to restart = now_utc − saved_datetime
- Units: part + (part/s)·s = part ✓; sign follows the SiT's own aging convention.

Validation against 96 days of data: `Aging × (96·86400)` = −6.97e-16 × 8.29e6 =
**−5.78e-9**, vs the measured Total-Offset drift 0.1232→0.1176 ppm = **−5.6e-9**.
Same sign and magnitude → the extrapolation genuinely tracks the real offset.

## Files — what to change
Everything needed is already persisted; **do not** add fields.

- `SiT-settings2.ini` — **no change.** `[Current]` already has `datetime`,
  `total_offset_written`, `aging_compensation`, `pull_range`, `max_freq_ramp_rate`.
- `save-SiT5721.py` — **no code change** (it already writes `datetime = now(UTC)`
  on each save). Operational: make sure it runs **frequently** (systemd timer,
  e.g. every few minutes) so the saved total is always near any power-fail instant,
  keeping Δt ≈ the outage and minimising unpowered-aging error. Check `systemd/`.
- `read-SiT5721.py` — **leave as-is** (read-only diagnostic).
- `write-SiT5721.py` — **leave as-is** for the manual "recalculated-value"
  reprogramming after a few days (the safety net). Keep the two roles separate.

## New file to create: `restart-SiT5721.py`
Reuse the `SiT5721_settings` class from `save-SiT5721.py` and the `SiT5721` lib
(`mbt_SiT5721_lib.py`). Confirm signatures before use:
- `SiT5721_settings.read_file(file, "Current")` returns
  `(total_offset_written, pull_range, aging_compensation, max_freq_ramp_rate, datetime, config_ver)`.
- `SiT5721` lib methods (see write-SiT5721.py): `set_pull_value`, `set_aging_comp`,
  `set_pull_range`, `set_max_freq_ramp_rate`, plus read/print methods. Bus =
  `smbus.SMBus(0)`, address `0x60`. Registers are 4-byte float32 (values get
  truncated to float32 on write — expected).

Sketch:
```python
total, prange, aging, ramp, saved_dt, ver = cfg.read_file("SiT-settings2.ini", "Current")
dt = (datetime.now(timezone.utc) - datetime.fromisoformat(saved_dt)).total_seconds()
new_pull = total + aging * dt          # aging-corrected restart pull
siTime.set_pull_value(new_pull)
siTime.set_aging_comp(aging)           # reuse
siTime.set_pull_range(prange)
siTime.set_max_freq_ramp_rate(ramp)
# read back + verify each register matches (mirror save-SiT5721.py's match/MISMATCH checks)
```
Also: refuse to run if settings are default/NaN or `saved_dt` is the 1970 epoch
(means no valid save); print Δt and both Pull values; guard a negative/huge Δt.

## systemd
Add a oneshot unit to run `restart-SiT5721.py` once at boot (after I²C is up),
before the disciplining/`get-data.py` flow starts. Model it on the existing units
in `systemd/`.

## Caveat to keep in mind
During a power *outage* the SiT is off; crystal aging while unpowered ≠ while
running (retrace/warmup on re-power). So `Aging × Δt` is a good extrapolation for
the powered interval after the last save; long outages retain some residual error.
Keep the "run a day or two, then recalc from the spreadsheet" step as a safety net
— just with a much smaller starting error now.

## Acceptance
- Dry-run mode (compute + print, no I²C write) matches a hand calc:
  `new_pull = total + aging·Δt`.
- On a real restart, read-back Pull/Aging/Range/Ramp match what was written.
- After a known Δt, the first days' measured frequency error is markedly smaller
  than with the old (uncorrected) restart.
