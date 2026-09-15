#!/usr/bin/env bash
# Provision an Armbian Orange Pi Zero 2W as a cyberdeck.
#
#   sudo deck/setup.sh            apply
#   sudo deck/setup.sh --check    print what would change, touch nothing
#
# Idempotent: every step checks before it changes, so rerun it after each
# git pull. Configuration comes from deck/deck.env (see deck.env.example).
set -euo pipefail

REPO=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CHECK=0
[[ "${1:-}" == "--check" ]] && CHECK=1

if [[ $EUID -ne 0 ]]; then
	echo "run as root: sudo $0 ${1:-}" >&2
	exit 1
fi

ENV_FILE="$REPO/deck/deck.env"
if [[ ! -f "$ENV_FILE" ]]; then
	echo "no deck/deck.env, using deck.env.example defaults" >&2
	ENV_FILE="$REPO/deck/deck.env.example"
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

DECK_USER=${DECK_USER:-deck}
DECK_HOME=/home/$DECK_USER
DISK=$DECK_HOME/deck
VENV=/opt/cyberdeck/venv
REPO_OWNER=$(stat -c %U "$REPO")

log() { printf '\033[1m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
run() {
	if ((CHECK)); then
		note "would: $*"
	else
		"$@"
	fi
}
as_user() { # as_user USER CMD...
	local u=$1
	shift
	run runuser -u "$u" -- "$@"
}

# ---------------------------------------------------------------- packages
log "packages"
# libgl1-mesa-dri carries the Panfrost GLES driver for the Mali G31, so uxn2
# gets an accelerated SDL renderer on KMSDRM instead of the software fallback.
PKGS=(build-essential make libsdl2-dev python3-venv python3-pip rsync sudo libgl1-mesa-dri libgles2 libegl1)
MISSING=()
for p in "${PKGS[@]}"; do
	dpkg -s "$p" >/dev/null 2>&1 || MISSING+=("$p")
done
if ((${#MISSING[@]})); then
	note "installing: ${MISSING[*]}"
	run apt-get update -qq
	run env DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${MISSING[@]}"
else
	note "all present"
fi

# -------------------------------------------------------------------- user
log "user $DECK_USER"
if ! id "$DECK_USER" >/dev/null 2>&1; then
	note "creating"
	run useradd -m -s /bin/bash "$DECK_USER"
fi
GROUPS_WANTED=(video render input audio dialout plugdev tty)
for g in "${GROUPS_WANTED[@]}"; do
	getent group "$g" >/dev/null || continue
	if ! id -nG "$DECK_USER" | tr ' ' '\n' | grep -qx "$g"; then
		note "adding to group $g"
		run usermod -aG "$g" "$DECK_USER"
	fi
done

# ------------------------------------------------------------------- build
log "build uxn2 and ROMs (as $REPO_OWNER)"
as_user "$REPO_OWNER" make -C "$REPO" all
log "install uxn2 to /usr/local/bin"
run make -C "$REPO" install PREFIX=/usr/local

# -------------------------------------------------------------------- disk
log "disk $DISK"
run install -d -o "$DECK_USER" -g "$DECK_USER" "$DISK"
as_user "$DECK_USER" make -C "$REPO" disk DISK="$DISK" UXN2=/usr/local/bin/uxn2

# -------------------------------------------------------------- python env
log "python venv $VENV (rns, lxmf, bridge)"
if [[ ! -x $VENV/bin/pip ]]; then
	note "creating venv"
	run install -d /opt/cyberdeck
	run python3 -m venv "$VENV"
fi
run "$VENV/bin/pip" install -q --upgrade pip rns lxmf
if [[ -f $REPO/bridge/pyproject.toml ]]; then
	run "$VENV/bin/pip" install -q --upgrade "$REPO/bridge"
fi

# --------------------------------------------------------------- reticulum
log "reticulum config"
RNS_DIR=$DECK_HOME/.reticulum
if [[ -f $RNS_DIR/config ]]; then
	note "exists, leaving alone"
else
	RNODE_PORT=${RNODE_PORT:-}
	if [[ -z $RNODE_PORT ]]; then
		mapfile -t SERIALS < <(ls /dev/serial/by-id/ 2>/dev/null || true)
		if ((${#SERIALS[@]} == 1)); then
			RNODE_PORT=/dev/serial/by-id/${SERIALS[0]}
			note "detected RNode port $RNODE_PORT"
		elif ((${#SERIALS[@]} > 1)); then
			note "several USB serial devices, set RNODE_PORT in deck.env:"
			printf '      /dev/serial/by-id/%s\n' "${SERIALS[@]}"
		else
			note "no USB serial device found; RNode interface will be disabled"
		fi
	fi
	RNODE_ENABLED=No
	[[ -n $RNODE_PORT ]] && RNODE_ENABLED=Yes
	export RNODE_ENABLED RNODE_PORT
	export RNODE_FREQUENCY=${RNODE_FREQUENCY:-914875000}
	export RNODE_BANDWIDTH=${RNODE_BANDWIDTH:-125000}
	export RNODE_TXPOWER=${RNODE_TXPOWER:-7}
	export RNODE_SPREADINGFACTOR=${RNODE_SPREADINGFACTOR:-8}
	export RNODE_CODINGRATE=${RNODE_CODINGRATE:-5}
	RENDERED=$(python3 -c 'import os,sys,string; print(string.Template(sys.stdin.read()).substitute(os.environ))' <"$REPO/deck/reticulum/config.template")
	if ((CHECK)); then
		note "would write $RNS_DIR/config (RNode enabled: $RNODE_ENABLED)"
	else
		install -d -o "$DECK_USER" -g "$DECK_USER" -m 700 "$RNS_DIR"
		printf '%s\n' "$RENDERED" >"$RNS_DIR/config"
		chown "$DECK_USER:$DECK_USER" "$RNS_DIR/config"
		note "wrote $RNS_DIR/config (RNode enabled: $RNODE_ENABLED)"
	fi
fi
# The bridge keeps its state here.
run install -d -o "$DECK_USER" -g "$DECK_USER" -m 700 "$DECK_HOME/.cyberdeck"
if [[ -n ${DISPLAY_NAME:-} && ! -f $DECK_HOME/.cyberdeck/name ]]; then
	if ((CHECK)); then
		note "would set display name to $DISPLAY_NAME"
	else
		printf '%s\n' "$DISPLAY_NAME" >"$DECK_HOME/.cyberdeck/name"
		chown "$DECK_USER:$DECK_USER" "$DECK_HOME/.cyberdeck/name"
	fi
fi

# -------------------------------------------------------------------- udev
log "udev rule for the RNode (keeps ModemManager off it)"
if ! cmp -s "$REPO/deck/udev/99-cyberdeck-rnode.rules" /etc/udev/rules.d/99-cyberdeck-rnode.rules; then
	run install -m 644 "$REPO/deck/udev/99-cyberdeck-rnode.rules" /etc/udev/rules.d/99-cyberdeck-rnode.rules
	run udevadm control --reload-rules
	run udevadm trigger --subsystem-match=usb --subsystem-match=tty
fi

# ----------------------------------------------------------------- sudoers
log "sudoers (poweroff/reboot from a ROM)"
SUDO_TMP=$(mktemp)
sed "s/^deck /$DECK_USER /" "$REPO/deck/sudoers.d/cyberdeck" >"$SUDO_TMP"
if visudo -c -q -f "$SUDO_TMP"; then
	run install -m 0440 "$SUDO_TMP" /etc/sudoers.d/cyberdeck
else
	note "sudoers file failed validation, skipped"
fi
rm -f "$SUDO_TMP"

# ----------------------------------------------------------------- systemd
log "systemd units"
UNITS=(cyberdeck.service rnsd.service cyberdeck-build.path cyberdeck-build.service)
ENABLE=(rnsd.service cyberdeck-build.path cyberdeck.service)
if [[ -x $VENV/bin/cyberdeck-bridge ]]; then
	UNITS+=(cyberdeck-bridge.service)
	ENABLE+=(cyberdeck-bridge.service)
else
	note "bridge not installed yet, skipping cyberdeck-bridge.service"
fi
for u in "${UNITS[@]}"; do
	UNIT_TMP=$(mktemp)
	sed -e "s|^User=deck$|User=$DECK_USER|" -e "s|/home/deck|$DECK_HOME|g" \
		"$REPO/deck/systemd/$u" >"$UNIT_TMP"
	if ! cmp -s "$UNIT_TMP" "/etc/systemd/system/$u"; then
		note "installing $u"
		run install -m 644 "$UNIT_TMP" "/etc/systemd/system/$u"
	fi
	rm -f "$UNIT_TMP"
done
run systemctl daemon-reload
for u in "${ENABLE[@]}"; do
	systemctl is-enabled -q "$u" 2>/dev/null || run systemctl enable -q "$u"
done
if systemctl is-enabled -q getty@tty1.service 2>/dev/null; then
	note "disabling getty on tty1 (tty2 stays available)"
	run systemctl disable -q getty@tty1.service
fi
if [[ $(systemctl get-default) != multi-user.target ]]; then
	note "default target -> multi-user (no display manager at boot)"
	run systemctl set-default -q multi-user.target
fi

# ----------------------------------------------------------------- summary
log "done"
note "disk:        $DISK"
note "reticulum:   $RNS_DIR/config"
note "next:        sudo reboot  (Potato on tty1, Ctrl+Alt+F2 for a shell)"
note "logs:        journalctl -u cyberdeck -u rnsd -u cyberdeck-bridge -f"
note "diagnose:    deck/check.sh"
