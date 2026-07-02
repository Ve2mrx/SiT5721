#!/bin/sh
if screen -list | grep -qE '\.SiT-save[[:space:]]'; then
	echo "A SiT-save screen session is already running." >&2
	echo "Use get-SiT-screen.sh to reattach, or 'screen -X -S SiT-save quit' to stop it first." >&2
	exit 1
fi

cd /home/ve2mrx/project/SiT5721
screen -d -m -S SiT-save watch -n 600 /home/ve2mrx/project/SiT5721/save-SiT5721_dev.py
