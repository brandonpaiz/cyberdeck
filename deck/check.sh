#!/usr/bin/env bash
# Diagnostics for a provisioned deck. Run on the Pi and paste the output.
#
#   deck/check.sh            services, display, RNode, recent logs
#   deck/check.sh --rnode    also stop rnsd briefly and query the RNode firmware
set -uo pipefail
VENV=/opt/cyberdeck/venv
DECK_USER=${DECK_USER:-deck}
hr() { printf '\n== %s\n' "$*"; }

hr "system"
uname -r
grep -m1 PRETTY_NAME /etc/os-release
df -h / | tail -1
free -m | sed -n 2p

hr "services"
for u in cyberdeck rnsd cyberdeck-bridge cyberdeck-build.path; do
	printf '%-22s %s / %s\n' "$u" "$(systemctl is-enabled "$u" 2>&1)" "$(systemctl is-active "$u" 2>&1)"
done
printf '%-22s %s\n' "default target" "$(systemctl get-default)"
printf '%-22s %s\n' "getty@tty1" "$(systemctl is-enabled getty@tty1 2>&1)"

hr "display (DRM cards and which have connectors)"
for c in /dev/dri/card*; do
	n=$(basename "$c")
	drv=$(basename "$(readlink -f /sys/class/drm/$n/device/driver 2>/dev/null)" 2>/dev/null)
	conns=$(ls -d /sys/class/drm/$n-* 2>/dev/null | wc -l)
	printf '%-8s driver=%-12s connectors=%s\n' "$n" "${drv:-?}" "$conns"
done
ls /sys/class/drm/ | grep -E 'card[0-9]+-' | while read -r c; do printf '%-20s %s\n' "$c" "$(cat /sys/class/drm/$c/status 2>/dev/null)"; done
printf 'GLES libs: '; ls /usr/lib/*/libGLESv2.so.2 /usr/lib/*/dri/panfrost_dri.so 2>/dev/null | tr '\n' ' '; echo
journalctl -u cyberdeck -b --no-pager -q | grep -iE 'sdl|render|error|could not' | tail -5
systemctl is-active -q cyberdeck || echo "cyberdeck.service is not running: sudo systemctl start cyberdeck (or reboot)"

hr "RNode"
ls -l /dev/serial/by-id/ 2>/dev/null || echo "no USB serial devices"
systemctl is-active ModemManager >/dev/null 2>&1 && echo "ModemManager is running (udev rule should keep it off the RNode)"
grep -A8 '\[\[RNode\]\]' "/home/$DECK_USER/.reticulum/config" 2>/dev/null | grep -E 'enabled|port|frequency'
if [[ -x $VENV/bin/rnstatus ]]; then
	sudo -u "$DECK_USER" "$VENV/bin/rnstatus" 2>&1 | head -40
fi
if [[ "${1:-}" == "--rnode" && -x $VENV/bin/rnodeconf ]]; then
	port=$(ls /dev/serial/by-id/* 2>/dev/null | head -1)
	if [[ -n $port ]]; then
		echo "stopping rnsd to query $port ..."
		sudo systemctl stop rnsd cyberdeck-bridge
		sudo -u "$DECK_USER" "$VENV/bin/rnodeconf" -i "$port" 2>&1 | tail -30
		sudo systemctl start rnsd cyberdeck-bridge
	fi
fi

hr "bridge and disk (as $DECK_USER)"
sudo -u "$DECK_USER" sh -c 'ls -la ~/.cyberdeck; echo "disk:"; ls ~/deck; echo "lxmf:"; ls ~/deck/lxmf; echo "build.log:"; tail -3 ~/deck/build.log' 2>&1

hr "recent logs"
journalctl -u cyberdeck -u rnsd -u cyberdeck-bridge -b --no-pager -q -n 25
