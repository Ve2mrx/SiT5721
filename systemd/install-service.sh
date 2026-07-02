#!/bin/sh
# Installs restart-sit-screen.service as a systemd user unit and enables
# it, so restart-SiT-screen.sh runs automatically after every reboot.
#
# No sudo needed, but the service can only start at boot without an
# active login session if lingering is enabled for this user:
#   loginctl enable-linger "$USER"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
UNIT_DIR="$HOME/.config/systemd/user"

mkdir -p "$UNIT_DIR"
cp "$SCRIPT_DIR/restart-sit-screen.service" "$UNIT_DIR/restart-sit-screen.service"

systemctl --user daemon-reload
systemctl --user enable restart-sit-screen.service

echo "Installed and enabled restart-sit-screen.service."
echo "Run 'systemctl --user start restart-sit-screen.service' to test it now,"
echo "or 'journalctl --user -u restart-sit-screen.service' to see its output."
