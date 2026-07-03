#!/bin/sh
# Installs the SiT5721 system-wide systemd units and enables them:
# - restart-sit-screen.service (+ its OnFailure= alert unit): runs
#   restart-SiT-screen.sh after every reboot - ordered after real network
#   availability (After=network-online.target), with an email alert if it
#   ever fails.
# - save-sit5721.timer (+ save-sit5721.service): periodically saves
#   register state to SiT-settings2.ini, replacing the old
#   `screen -d -m watch -n 600 save-SiT5721.py` kludge.
#
# Needs root - run with sudo. Also disables/removes the old --user unit
# this replaces, so it doesn't run a second time at boot.

if [ "$(id -u)" -ne 0 ]; then
	echo "This installs system units; re-run with sudo." >&2
	exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
UNIT_DIR="/etc/systemd/system"

cp "$SCRIPT_DIR/restart-sit-screen.service" "$UNIT_DIR/restart-sit-screen.service"
cp "$SCRIPT_DIR/restart-sit-screen-alert.service" "$UNIT_DIR/restart-sit-screen-alert.service"
cp "$SCRIPT_DIR/save-sit5721.service" "$UNIT_DIR/save-sit5721.service"
cp "$SCRIPT_DIR/save-sit5721.timer" "$UNIT_DIR/save-sit5721.timer"

systemctl daemon-reload
systemctl enable restart-sit-screen.service
systemctl enable --now save-sit5721.timer

OLD_USER_UNIT="/home/ve2mrx/.config/systemd/user/restart-sit-screen.service"
if [ -f "$OLD_USER_UNIT" ]; then
	echo "Disabling superseded --user unit..."
	# sudo -u alone doesn't give systemctl --user a session bus; XDG_RUNTIME_DIR
	# has to be set explicitly or it fails with "Failed to connect to bus".
	sudo -u ve2mrx XDG_RUNTIME_DIR=/run/user/1000 systemctl --user disable restart-sit-screen.service
	rm -f "$OLD_USER_UNIT"
	sudo -u ve2mrx XDG_RUNTIME_DIR=/run/user/1000 systemctl --user daemon-reload
fi

echo "Installed and enabled restart-sit-screen.service (system unit)."
echo "Run 'systemctl start restart-sit-screen.service' to test it now,"
echo "or 'journalctl -u restart-sit-screen.service' to see its output."
echo "restart-sit-screen-alert.service fires automatically via OnFailure=;"
echo "it is not enabled/started directly."
echo
echo "Installed and started save-sit5721.timer (system unit)."
echo "Run 'systemctl list-timers save-sit5721.timer' to see next run,"
echo "or 'journalctl -u save-sit5721.service' to see its output."
