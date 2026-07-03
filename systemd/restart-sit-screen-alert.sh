#!/bin/bash
# Fired by systemd via restart-sit-screen.service's OnFailure=. Sends an
# alert email so a failed restart isn't only visible via journalctl.
#
# Calls msmtp directly rather than `mail`/bsd-mailx: bsd-mailx always exits 0
# even when the underlying send fails (see mbt-ubx-apps/start-get-data.sh's
# send_urgent_mail for how that was found), so it can't be used to detect or
# retry a failed send.

MAIL_FAIL_LOG=~/SiT-restart_mail-failures.log
ALERT_CONFIG="${ALERT_CONFIG:-/home/ve2mrx/.config/sit-alerts.conf}"
[ -f "$ALERT_CONFIG" ] && . "$ALERT_CONFIG"
if [ -z "$ALERT_RECIPIENT" ]; then
	echo "ALERT_RECIPIENT not set - create $ALERT_CONFIG" >&2
	exit 1
fi
recipient="$ALERT_RECIPIENT"
subject="⚠ URGENT SiT5721: restart-sit-screen.service failed on $(hostname)"
body="restart-sit-screen.service failed on $(hostname) at $(date -Is). Check: journalctl -u restart-sit-screen.service"

attempt=0
delay=5
max_attempts=6
while [ "$attempt" -lt "$max_attempts" ]; do
	attempt=$((attempt + 1))
	if printf 'Subject: %s\nTo: %s\nImportance: high\nX-Priority: 1 (Highest)\nX-MSMail-Priority: High\n\n%s\n' \
			"$subject" "$recipient" "$body" \
			| msmtp "$recipient" 2>>"$MAIL_FAIL_LOG"; then
		exit 0
	fi
	echo "$(date -Is) attempt $attempt/$max_attempts failed, retrying in ${delay}s" >>"$MAIL_FAIL_LOG"
	sleep "$delay"
	delay=$((delay * 2))
done
exit 1
