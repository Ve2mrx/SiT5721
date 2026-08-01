#!/bin/bash
# Symlink this project's executable scripts into ~/bin.
# Safe to re-run: skips links that already point here, backs up and
# replaces anything else (stale real file, wrong target, etc).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/bin"

SCRIPTS=(
    restart-SiT5721-pull.sh
    read-SiT5721.py
    write-SiT5721.py
    save-SiT5721.py
    restart-SiT5721.py
    write-default_SiT5721.py
)

mkdir -p "$BIN_DIR"

for name in "${SCRIPTS[@]}"; do
    src="$SCRIPT_DIR/$name"
    dest="$BIN_DIR/$name"

    if [ ! -e "$src" ]; then
        echo "SKIP   $name: not found in $SCRIPT_DIR"
        continue
    fi

    if [ -L "$dest" ] && [ "$(readlink -f "$dest")" = "$(readlink -f "$src")" ]; then
        echo "OK     $name already linked"
        continue
    fi

    if [ -e "$dest" ] || [ -L "$dest" ]; then
        backup="$dest.bak-$(date +%Y%m%d%H%M%S)"
        echo "BACKUP $dest -> $backup"
        mv "$dest" "$backup"
    fi

    ln -s "$src" "$dest"
    echo "LINK   $dest -> $src"
done

# Health-telemetry self-check (save-SiT5721.py's HEALTH,<version>,... fields).
# Read-only: imports the real save-SiT5721.py and exercises the same read
# paths its main() uses on every save-sit5721.timer tick - SiT5721.__init__()
# only ever calls read_* methods over I2C (no writes), and cm4_soc_temp_c()
# is a subprocess call - without running main() itself, which would write
# ~/SiT-settings2.ini and append to ~/sit-health.csv; this check must never
# do either (same "safe to re-run" contract as the symlinking above).
#
# Why here and not just left to sit-status.sh's own WARN (see
# capture-status/sit-status.sh, ~/sit-health-24h.json's "warnings" list):
# that check only fires once the trailing 24h window has enough data to
# judge a field broken - no help on a freshly-installed device with no
# history yet. This catches it at install time instead. Never fails the
# install over it (WARN, not a script-ending error) - this is the
# best-effort sampler, not the register-save/capture it rides along with.
# See ../ubx-data/claude-code-silent-telemetry-failure-brief.md.
health_out=""
health_invocation_failed=0
if ! health_out=$(cd "$SCRIPT_DIR" && python3 -c "
import importlib.util, sys

spec = importlib.util.spec_from_file_location('save_SiT5721', 'save-SiT5721.py')
m = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(m)
except Exception as e:
    print(f'IMPORT_FAIL:{type(e).__name__}: {e}')
    sys.exit(0)

siTime = None
try:
    siTime = m.SiT5721(m.bus, m.address)
except Exception as e:
    print(f'SIT_FAIL:{type(e).__name__}: {e}')

if siTime is not None:
    fields = {
        'resonator_temp_c': siTime.temperature_float,
        'temp_error_c': siTime.temperature_err_float,
        'heater_power_w': siTime.heater_power_float,
        'heater_power_target_w': siTime.heater_power_target_float,
        'supply_v': siTime.supply_voltage_float,
    }
    for field_name, value in fields.items():
        if value is None:
            print(f'FIELD_FAIL:{field_name}: register read returned None')

cm4 = m.cm4_soc_temp_c()
if cm4 is None:
    reason = m._LAST_HEALTH_ERRORS.get('cm4_soc_temp_c', 'unknown reason')
    print(f'FIELD_FAIL:cm4_soc_temp_c: {reason}')
" 2>&1); then
    health_invocation_failed=1
fi

if [ "$health_invocation_failed" -eq 1 ]; then
    echo "WARN   health telemetry self-check: python3 invocation failed: $health_out"
elif [ -z "$health_out" ]; then
    echo "OK     health telemetry: all fields read successfully (5 SiT registers + CM4 SoC temp)"
else
    while IFS= read -r line; do
        case "$line" in
            IMPORT_FAIL:*) echo "WARN   could not import save-SiT5721.py: ${line#IMPORT_FAIL:}" ;;
            SIT_FAIL:*)    echo "WARN   could not read the SiT5721 over I2C: ${line#SIT_FAIL:}" ;;
            FIELD_FAIL:*)  echo "WARN   health field failed to read: ${line#FIELD_FAIL:}" ;;
            *)             echo "WARN   health telemetry self-check: $line" ;;
        esac
    done <<< "$health_out"
fi
