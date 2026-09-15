# Cyberdeck: notes for Claude Code sessions

Varvara cyberdeck on an Orange Pi Zero 2W. Read `DESIGN.md` first: it is
the plan and the record of what each stage settled. `doc/reticulum-device.md`
is the device and frame protocol spec for ROM authors.

## State (2026-09-15)

- Stages 1-3 are in the repo and pass `make test` on x86: build system and
  kiosk units, the Reticulum device in uxn2, the LXMF bridge, the chat ROM,
  the laptop dev harness.
- Stage 4 (RNode on the real deck) is in progress. Provisioning has run on
  the Pi (user `brandon`, repo at `~/cyberdeck`) up to the disk step; the
  disk-step ownership bug was fixed in `deck/setup.sh`. Next: rerun
  `sudo deck/setup.sh`, reboot, run `deck/check.sh --rnode`, and get uxn2
  showing Potato on tty1 over KMSDRM.
- Known hardware: kernel `6.18.51-current-sunxi64`, `/dev/dri/card0`,
  `card1`, `renderD128` (sun4i display + Panfrost GPU); RNode is an
  ESP32-S3 with native USB at
  `/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_E8:F6:0A:80:F8:48-if00`.
- Stage 5 (NomadNet ROM) is only sketched in DESIGN.md §11.

## Commands

```sh
make                          # uxn2/bin/uxn2 and build/*.rom
make venv                     # .venv with rns, lxmf and the bridge (editable)
make test PY=.venv/bin/python # uxn2 suite, device test, chat smoke test, protocol, LXMF roundtrip
make disk DISK=~/deck         # populate a Varvara disk directory
dev/run-dev.sh --stub         # chat ROM against the Reticulum-free stub bridge
dev/run-dev.sh                # two decks over a local Reticulum instance
sudo deck/setup.sh [--check]  # provision the Pi (idempotent)
deck/check.sh [--rnode]       # diagnostics on the Pi
```

On the Pi: services are `cyberdeck` (uxn2 on tty1), `rnsd`,
`cyberdeck-bridge`, `cyberdeck-build.path`. Logs:
`journalctl -u cyberdeck -u rnsd -u cyberdeck-bridge -b`. Ctrl+Alt+F2 is a
shell. The disk is `/home/deck/deck`; bridge state is `/home/deck/.cyberdeck`;
Reticulum config is `/home/deck/.reticulum/config` (setup.sh never overwrites it).

## Conventions and gotchas

- `uxn2/` is vendored upstream. Keep changes to `uxn2.c` minimal; the
  device lives in `uxn2/src/reticulum.c`. Re-vendoring means copying the
  new `uxn2.c`, reapplying the hooks (grep `ret_`) and the renderer
  fallback, then `make test`.
- Drifblim's `~include` never returns to the including file: the include
  must be the last token, and buffers (`$` padding) go before it.
- In Uxntal, `OVR2`/`SWP2` on a stack with a single byte on top are
  misaligned; move bytes through the return stack (see `copy-n` in chat.tal).
- `RNS.Reticulum()` must be created on the main thread (signal handlers),
  and only once per process. Announce handlers need
  `receive_path_responses = True` to learn names from path responses.
- The bridge frame protocol is defined once in `bridge/cyberdeck_bridge/protocol.py`
  and mirrored in `doc/reticulum-device.md` and DESIGN.md §5.4; change all three.
- ROM assembly is headless (`uxn2 drifblim.rom in.tal out.rom`); the
  Drifblim bootstrap needs `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`.
- Drifblim has a short path buffer; keep temp files on short paths.
- Screenshots of ROMs under Xvfb: `import -window root +repage ...`, drive
  keys with `xdotool`. Don't `pkill -f` on a pattern that matches your own shell.
- The 100r sources (`roms/potato`, `roms/noodle.tal`) are upstream; don't
  edit them. Left, Orca, Dexe, Bifurcan sources are not in the repo yet;
  Nasu is binary-only (`roms/potato/etc/nasu.rom`).
- Commit as the repo owner; no model names in commits or code.
