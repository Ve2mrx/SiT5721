#!/bin/sh
# Run after a restart to verify/start the SiT5721 save-state screen.

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if screen -list | grep -qE '\.SiT-save[[:space:]]'; then
	echo "SiT-save screen already running."
	exit 0
fi

"$SCRIPT_DIR/set-SiT-screen.sh"
sleep 1
if screen -list | grep -qE '\.SiT-save[[:space:]]'; then
	echo "SiT-save screen started."
	exit 0
else
	echo "SiT-save screen failed to start!" >&2
	exit 1
fi
