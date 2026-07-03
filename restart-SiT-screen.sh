#!/bin/sh
# Run after a restart to restore an aging-corrected Pull Value, then
# verify/start the SiT5721 save-state screen. See restart-pull-fix-brief.md.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if screen -list | grep -qE '\.SiT-save[[:space:]]'; then
	echo "SiT-save screen already running."
	exit 0
fi

"$SCRIPT_DIR/restart-SiT5721.py"
restart_pull_status=$?
if [ "$restart_pull_status" -eq 1 ]; then
	echo "restart-SiT5721.py failed (I2C write or readback mismatch)!" >&2
	exit 1
fi
# Any other nonzero status is a refusal (no valid prior save, bad clock, etc.)
# - not fatal to starting the save screen, just means the Pull wasn't restored.

"$SCRIPT_DIR/set-SiT-screen.sh"
sleep 1
if screen -list | grep -qE '\.SiT-save[[:space:]]'; then
	echo "SiT-save screen started."
	exit 0
else
	echo "SiT-save screen failed to start!" >&2
	exit 1
fi
