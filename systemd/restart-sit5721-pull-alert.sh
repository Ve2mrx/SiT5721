#!/bin/bash
# Fired by systemd via restart-sit5721-pull.service's OnFailure=. Sends an
# alert email so a failed restart isn't only visible via journalctl.
#
# Calls msmtp directly rather than `mail`/bsd-mailx: bsd-mailx always exits 0
# even when the underlying send fails (see mbt-ubx-apps/start-get-data.sh's
# send_urgent_mail for how that was found), so it can't be used to detect or
# retry a failed send.

MAIL_FAIL_LOG=~/SiT-restart_mail-failures.log
# Relies on msmtp's own `aliases /etc/aliases` directive in /etc/msmtprc
# (root -> real address) - see project memory alert-config-vs-aliases-todo.
# Overridable via env var for testing without sending a real alert.
recipient="${ALERT_RECIPIENT:-root}"
subject="⚠ URGENT SiT5721: restart-sit5721-pull.service failed on $(hostname)"
body="restart-sit5721-pull.service failed on $(hostname) at $(date -Is). Check: journalctl -u restart-sit5721-pull.service"

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
