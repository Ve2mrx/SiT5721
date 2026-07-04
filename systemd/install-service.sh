#!/bin/sh
# Installs the SiT5721 system-wide systemd units and enables them:
# - restart-sit5721-pull.service (+ its OnFailure= alert unit): runs
#   restart-SiT5721-pull.sh after every reboot - ordered after real network
#   availability (After=network-online.target), with an email alert if it
#   ever fails. (Renamed 2026-07-04 from restart-sit-screen.service - it
#   hasn't touched any screen since the SiT-save screen->timer conversion;
#   it only restores the aging-corrected Pull Value.)
# - save-sit5721.timer (+ save-sit5721.service): periodically saves
#   register state to SiT-settings2.ini, replacing the old
#   `screen -d -m watch -n 600 save-SiT5721.py` kludge.
#
# Needs root - run with sudo. Also disables/removes old units this replaces,
# so they don't run a second time at boot.

if [ "$(id -u)" -ne 0 ]; then
	echo "This installs system units; re-run with sudo." >&2
	exit 1
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
UNIT_DIR="/etc/systemd/system"

cp "$SCRIPT_DIR/restart-sit5721-pull.service" "$UNIT_DIR/restart-sit5721-pull.service"
cp "$SCRIPT_DIR/restart-sit5721-pull-alert.service" "$UNIT_DIR/restart-sit5721-pull-alert.service"
cp "$SCRIPT_DIR/save-sit5721.service" "$UNIT_DIR/save-sit5721.service"
cp "$SCRIPT_DIR/save-sit5721.timer" "$UNIT_DIR/save-sit5721.timer"

systemctl daemon-reload
systemctl enable restart-sit5721-pull.service
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

OLD_SYSTEM_UNITS=(restart-sit-screen.service restart-sit-screen-alert.service)
for old_unit in "${OLD_SYSTEM_UNITS[@]}"; do
	if [ -f "$UNIT_DIR/$old_unit" ]; then
		echo "Removing superseded system unit $old_unit (renamed to restart-sit5721-pull*)..."
		systemctl disable --now "$old_unit" 2>/dev/null
		rm -f "$UNIT_DIR/$old_unit"
	fi
done

echo "Installed and enabled restart-sit5721-pull.service (system unit)."
echo "Run 'systemctl start restart-sit5721-pull.service' to test it now,"
echo "or 'journalctl -u restart-sit5721-pull.service' to see its output."
echo "restart-sit5721-pull-alert.service fires automatically via OnFailure=;"
echo "it is not enabled/started directly."
echo
echo "Installed and started save-sit5721.timer (system unit)."
echo "Run 'systemctl list-timers save-sit5721.timer' to see next run,"
echo "or 'journalctl -u save-sit5721.service' to see its output."
