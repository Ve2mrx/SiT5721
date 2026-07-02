#!/bin/sh
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if screen -list | grep -qE '\.SiT-save[[:space:]]'; then
	echo "A SiT-save screen session is already running." >&2
	echo "Use get-SiT-screen.sh to reattach, or 'screen -X -S SiT-save quit' to stop it first." >&2
	exit 1
fi

cd "$SCRIPT_DIR"
screen -d -m -S SiT-save watch -n 600 "$SCRIPT_DIR/save-SiT5721.py" "$SCRIPT_DIR/SiT-settings2.ini"
