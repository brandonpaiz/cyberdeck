#!/usr/bin/env bash
# Laptop dev harness: two decks chatting on one machine.
#
#   make venv && dev/run-dev.sh            two uxn2 windows, real LXMF over a local RNS instance
#   dev/run-dev.sh --stub                  one uxn2 window against the Reticulum-free stub bridge
#   dev/run-dev.sh --rom build/hello.rom   run another ROM instead of chat.rom
#
# Everything lives under dev/state (gitignored): two bridge state dirs, two
# disks, a throwaway Reticulum config with AutoInterface only (so the decks
# also see a real cyberdeck on the same LAN). Ctrl+C stops it all.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
STATE=$ROOT/dev/state
PY=$ROOT/.venv/bin/python
UXN2=$ROOT/uxn2/bin/uxn2
ROM=$ROOT/build/chat.rom
STUB=0

while [[ $# -gt 0 ]]; do
	case $1 in
	--stub) STUB=1 ;;
	--rom) ROM=$(realpath "$2"); shift ;;
	*) echo "unknown option $1" >&2; exit 1 ;;
	esac
	shift
done

[[ -x $UXN2 ]] || make -C "$ROOT" all
[[ -f $ROM ]] || make -C "$ROOT" roms
if [[ ! -x $PY ]]; then
	echo "no .venv; run 'make venv' first" >&2
	exit 1
fi
mkdir -p "$STATE"

PIDS=()
cleanup() { kill "${PIDS[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

disk() { # disk NAME -> populates dev/state/NAME/disk, prints its path
	local d=$STATE/$1/disk
	make -C "$ROOT" -s disk DISK="$d" >/dev/null
	echo "$d"
}

if ((STUB)); then
	SOCK=$STATE/stub.sock
	DISK=$(disk stub)
	"$PY" -m cyberdeck_bridge.stub --socket "$SOCK" --disk "$DISK" &
	PIDS+=($!)

	sleep 0.5
	(cd "$DISK" && CYBERDECK_SOCKET=$SOCK "$UXN2" -2 "$ROM")
	exit 0
fi

RNS_DIR=$STATE/reticulum
if [[ ! -f $RNS_DIR/config ]]; then
	mkdir -p "$RNS_DIR"
	cp "$ROOT/dev/reticulum-dev-config" "$RNS_DIR/config"
fi

for who in a b; do
	DISK_VAR=$(disk "$who")
	"$PY" -m cyberdeck_bridge --socket "$STATE/$who/bridge.sock" --state "$STATE/$who/state" \
		--disk "$DISK_VAR" --name "deck-$who" --rns-config "$RNS_DIR" >"$STATE/$who/bridge.log" 2>&1 &
	PIDS+=($!)
done
echo "bridges starting; logs in $STATE/{a,b}/bridge.log"
sleep 3

for who in a b; do
	(cd "$STATE/$who/disk" && CYBERDECK_SOCKET=$STATE/$who/bridge.sock "$UXN2" -2 "$ROM") &
	PIDS+=($!)
done
echo "two decks running (deck-a, deck-b). Tab announces; pick the other deck with Up/Down and chat."
wait "${PIDS[@]: -2}"
