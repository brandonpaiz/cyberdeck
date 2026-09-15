# cyberdeck

A [Varvara](https://wiki.xxiivv.com/site/varvara.html) cyberdeck on an
Orange Pi Zero 2W: boots straight into 100r's Potato, assembles ROMs
on-device with Drifblim, and reaches the Reticulum network through an
RNode via a new Varvara device.

Status: design phase. Read [DESIGN.md](DESIGN.md) for the plan, the
device port map, the bridge protocol and the implementation stages.

## Layout

- `uxn2/` — vendored [uxn2](https://git.sr.ht/~rabbits/uxn2) emulator
  (SDL2). Will carry two small patches: the Reticulum device and a
  software-renderer fallback.
- `roms/100r/` — put the 100r `.tal` sources here (potato, left, nasu,
  noodle, orca, dexe, bifurcan, drifblim). They cannot be fetched from
  sourcehut in the build environment.

Everything else in the layout described in DESIGN.md lands in stage 1.
