# cyberdeck

A [Varvara](https://wiki.xxiivv.com/site/varvara.html) cyberdeck on an
Orange Pi Zero 2W: boots straight into 100r's Potato, assembles ROMs
on-device with Drifblim, and reaches the Reticulum network through an
RNode via a new Varvara device.

[DESIGN.md](DESIGN.md) has the plan, the device port map, the bridge
protocol and the implementation stages.

## Build on a laptop

Needs a C compiler, make, SDL2 development headers and python3.

```sh
make              # uxn2/bin/uxn2 and build/*.rom
make disk DISK=~/deck   # a Varvara disk directory to run Potato from
cd ~/deck && ~/cyberdeck/uxn2/bin/uxn2 potato.rom
```

## Test

```sh
make venv                       # .venv with rns, lxmf and the bridge
make test PY=.venv/bin/python   # uxn2 suite, device test, protocol, LXMF roundtrip
```

## Provision the Pi

On a fresh Armbian install, as a user with sudo:

```sh
git clone https://github.com/brandonpaiz/cyberdeck ~/cyberdeck
cd ~/cyberdeck
cp deck/deck.env.example deck/deck.env   # edit RNode port and radio settings
sudo deck/setup.sh --check               # see what it would do
sudo deck/setup.sh
sudo reboot
```

The Pi comes up in Potato on tty1. `Ctrl+Alt+F2` gives a login shell and
SSH keeps working. Rerun `setup.sh` after every `git pull`.

## Layout

- `uxn2/` — vendored [uxn2](https://git.sr.ht/~rabbits/uxn2) emulator with
  two patches: a software renderer fallback and the Reticulum device
  (`src/reticulum.c`, spec in `doc/reticulum-device.md`).
- `bridge/` — `cyberdeck-bridge`, the Python LXMF daemon behind the device,
  plus a Reticulum-free stub for testing ROMs.
- `roms/potato/`, `roms/noodle.tal` — 100r sources. Add Left, Nasu, Orca,
  Dexe, Bifurcan sources here as you get them; each is one line in the
  makefile.
- `roms/deck/` — our ROMs. `roms/lib/` — shared includes (font).
- `deck/` — what lands on the Pi: `setup.sh`, systemd units, Reticulum
  config template, sudoers rule.
- `tools/` — small helpers (`icn2tal.py`).
