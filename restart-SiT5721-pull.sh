#!/bin/sh
# Run once after a restart to restore an aging-corrected Pull Value.
# See restart-pull-fix-brief.md. Periodic saving to SiT-settings2.ini is
# handled separately by systemd/save-sit5721.timer, not by this script.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$(readlink -f -- "$0")")" && pwd)

"$SCRIPT_DIR/restart-SiT5721.py"
restart_pull_status=$?
if [ "$restart_pull_status" -eq 1 ]; then
	echo "restart-SiT5721.py failed (I2C write or readback mismatch)!" >&2
	exit 1
fi
# Any other nonzero status is a refusal (no valid prior save, bad clock, etc.)
# - not fatal, just means the Pull wasn't restored.
exit 0
