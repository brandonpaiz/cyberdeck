# Cyberdeck design

A Varvara cyberdeck on an Orange Pi Zero 2W that boots straight into
Potato, lets you write and assemble ROMs without leaving Varvara, and talks
to the Reticulum network through an RNode via a new Varvara device.

This document is the agreed plan and, as stages land, the record of what
was built. Each section ends with what "done" looks like.

Decisions already made (from the interview on 2026-09-15):

| Topic | Decision |
|---|---|
| Hardware | Orange Pi Zero 2W, Armbian, HDMI display, USB keyboard, USB RNode |
| Boot | Bare console kiosk: uxn2 on tty1 over SDL2 KMSDRM, no X or Wayland |
| Chat protocol | LXMF, so the deck interoperates with Sideband, MeshChat and NomadNet |
| LoRa band | US/Canada 915 MHz (defaults below, tune later) |
| Provisioning | One idempotent `setup.sh` run over SSH on a fresh Armbian install |
| Linux user | Dedicated `deck` user owns everything |
| Dev harness | Linux laptop; whole stack runs locally, two decks chat on localhost |
| Extra ROMs | Potato, Left, Nasu, Noodle, Orca, Dexe, Bifurcan, Drifblim |
| Delivery order | This design doc first, then implementation in stages |

Constraints discovered along the way:

- This build environment cannot reach `git.sr.ht`, `100r.co` or
  `wiki.xxiivv.com`. The 100r ROM sources have to be committed by you.
  PyPI is reachable, so the Reticulum stack can be installed and tested here.
- uxn2 in this repo is dated 18 Aug 2026 and is a single C file. Upstream
  moves quickly, so every change to it is kept as a small, separable patch.
- The vendored uxn2 has audio on pages `30`–`60` (the README says `40`–`70`,
  which is stale). Free device pages are `70`, `d0`, `e0` and `f0`.

## 1. System overview

```
                 Orange Pi Zero 2W (Armbian, no display server)
 ┌───────────────────────────────────────────────────────────────────┐
 │  tty1                                                             │
 │  ┌───────────────────────────┐   unix socket    ┌──────────────┐  │
 │  │ uxn2 -f potato.rom        │◄────────────────►│ cyberdeck-   │  │
 │  │  (SDL2 KMSDRM, fullscreen)│ /run/cyberdeck/  │ bridge (py)  │  │
 │  │  Varvara devices:         │   bridge.sock    │  LXMF router │  │
 │  │   …, file, datetime,      │                  └──────┬───────┘  │
 │  │   reticulum @d0 (new)     │                         │ shared   │
 │  └───────────────────────────┘                         │ instance │
 │        │ file device                             ┌─────▼───────┐  │
 │        ▼                                         │ rnsd        │  │
 │  /home/deck/deck/  (the "disk")                  │  AutoIface  │  │
 │    potato.rom left.rom chat.rom …                │  RNodeIface │  │
 │    src/*.tal  (edit in Left, auto-assembled)     └─────┬───────┘  │
 │    lxmf/<peer>.txt (history written by bridge)         │ USB      │
 └────────────────────────────────────────────────────────┼──────────┘
                                                          ▼
                                                   RNode (LoRa 915 MHz)
```

Three long-running processes, all systemd services running as user `deck`:

1. **uxn2** owns the display and keyboard and runs `potato.rom` as the shell.
   Every other ROM is launched from Potato. When a ROM halts, uxn2 exits and
   systemd restarts it into Potato about a second later.
2. **rnsd** is the stock Reticulum daemon. It owns the RNode serial port and
   the LAN AutoInterface and exposes a shared instance to local programs.
3. **cyberdeck-bridge** is a small Python daemon that runs an LXMF router on
   top of the shared instance and speaks a tiny framed protocol to uxn2 over
   a Unix socket. It also writes plain-text history files into the disk so
   ROMs can read conversations with the ordinary File device.

The Varvara side never sees Python, LoRa or cryptography. It sees a device
that delivers and accepts frames, and a folder of text files.

## 2. Repository layout

```
cyberdeck/
├── README.md
├── DESIGN.md                 this file
├── makefile                  top level: uxn2, roms, bridge venv, dev harness
├── uxn2/                     vendored emulator (upstream + patches below)
│   └── src/
│       ├── uxn2.c            upstream, minimally touched
│       └── reticulum.c       the new device, included from uxn2.c
├── roms/
│   ├── 100r/                 upstream .tal sources you commit (potato, left, …)
│   ├── deck/                 our ROMs: chat.tal, later nomad.tal
│   ├── lib/                  shared .tal includes (font, text, frame helpers)
│   └── makefile              %.rom: %.tal rules using drifblim.rom
├── bridge/
│   ├── pyproject.toml        package `cyberdeck_bridge`, deps rns + lxmf
│   ├── cyberdeck_bridge/
│   │   ├── __main__.py       entry point `cyberdeck-bridge`
│   │   ├── protocol.py       frame encode/decode (pure functions, unit tested)
│   │   ├── server.py         asyncio Unix socket server, fan-out to clients
│   │   ├── node.py           LXMF router wrapper (identity, announce, send, recv)
│   │   └── history.py        writes lxmf/<hash>.txt and peers.txt on the disk
│   └── tests/
├── deck/                     everything that lands on the Pi
│   ├── setup.sh              idempotent provisioning
│   ├── deck.env.example      RNODE_PORT, RNODE_FREQUENCY, DISPLAY_NAME, …
│   ├── systemd/
│   │   ├── cyberdeck.service         uxn2 kiosk on tty1
│   │   ├── cyberdeck-bridge.service
│   │   ├── rnsd.service
│   │   ├── cyberdeck-build.path      watches ~/deck/src for .tal changes
│   │   └── cyberdeck-build.service   assembles changed ROMs headlessly
│   └── reticulum/config.template
├── dev/                      laptop harness (two decks on one machine)
│   ├── run-dev.sh
│   └── reticulum-dev-config
└── doc/
    └── reticulum-device.md   the device spec, wiki style, for ROM authors
```

Done when: the tree exists with a top-level `make` that builds uxn2 and
every ROM whose source is present, and `make test` runs the bridge unit
tests and the headless uxn2 device test.

## 3. Boot into Potato (kiosk)

### 3.1 Why KMSDRM

You already run Varvara under i3, so the DRM driver for the H618's HDMI
output works on your kernel. Debian and Ubuntu build `libsdl2` with the
KMSDRM video backend, which draws to the DRM device directly and reads
keyboards through evdev. That removes X, i3 and the login manager from the
boot path and from RAM.

One risk: uxn2 asks SDL for an accelerated renderer. On KMSDRM that means
GLES through Mesa's Panfrost driver for the Mali G31. If your Armbian
image lacks working GLES, `SDL_CreateRenderer` fails and uxn2 exits.
Mitigation is a two-line patch to uxn2: retry with flags `0` so SDL falls
back to its software renderer, which on KMSDRM uses dumb buffers and is
plenty for a 1-bit 640x480 screen. Plan B, if KMSDRM itself refuses to
start on this kernel, is the `cage` Wayland kiosk with the same service
layout; only the `ExecStart` line changes.

### 3.2 The `cyberdeck.service` unit

```ini
[Unit]
Description=Cyberdeck Varvara console
After=systemd-user-sessions.service cyberdeck-bridge.service
Wants=cyberdeck-bridge.service
Conflicts=getty@tty1.service

[Service]
User=deck
PAMName=login
WorkingDirectory=/home/deck/deck
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=SDL_AUDIODRIVER=alsa
Environment=CYBERDECK_SOCKET=/run/cyberdeck/bridge.sock
ExecStart=/usr/local/bin/uxn2 -f potato.rom
StandardInput=tty
StandardOutput=journal
StandardError=journal
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
Restart=always
RestartSec=1

[Install]
WantedBy=multi-user.target
```

`PAMName=login` gives the process a logind seat session, so it receives the
device ACLs for `/dev/dri/*` and `/dev/input/*` the same way a console
login would. The `deck` user is also put in `video`, `render`, `input`,
`audio` and `dialout` as a fallback.

`Restart=always` is what makes "a ROM halts, you are back in Potato" work.
`RestartSec=1` keeps it from spinning if a ROM is broken; the journal has
the error.

### 3.3 Getting back to Linux

- `Ctrl+Alt+F2` switches to tty2, where a normal getty login stays enabled.
- SSH is untouched.
- `sudo systemctl stop cyberdeck` frees the display; `startx` still works
  if you want i3 for a session.
- `setup.sh` runs `systemctl set-default multi-user.target` and disables
  `getty@tty1`. It does not uninstall i3 or the display manager; it only
  stops them from starting at boot.

### 3.4 The disk: `/home/deck/deck/`

uxn2's working directory. The File device is not sandboxed in uxn2, but
by convention everything ROMs touch lives here:

```
/home/deck/deck/
├── potato.rom left.rom nasu.rom noodle.rom orca.rom dexe.rom bifurcan.rom
├── drifblim.rom chat.rom
├── src/            your .tal files, edited in Left
│   ├── makefile    copied from roms/makefile, %.rom: %.tal
│   └── build.log   assembler output from the last automatic build
├── lxmf/           written by the bridge, read by chat.rom or Left
│   ├── peers.txt   one line per known peer: <hash hex> <name>
│   └── <hash>.txt  one line per message: <date> <time> <name>: <text>
└── fonts/ etc      whatever the 100r ROMs expect next to them
```

`setup.sh` (and later `make install-roms` over SSH) copies freshly built
ROMs into the top level and never touches `src/` or `lxmf/`.

Done when: a fresh Armbian install, after `deck/setup.sh`, reboots into
Potato fullscreen with keyboard working, `Ctrl+Alt+F2` gives a shell, and
`journalctl -u cyberdeck` shows no renderer errors.

## 4. Writing and assembling ROMs on the deck

What Potato's source settled (read after the sources landed):

- Potato launches a ROM by copying it over memory with a zero-page loader
  (`load-rom` in `assets.tal`). No arguments reach the launched ROM, and
  there is no way back except the ROM halting, which makes uxn2 exit and
  systemd restart Potato. That matches the kiosk design.
- Potato's built-in Text app is a viewer, not an editor. Editing `.tal`
  on the deck needs Left, whose source is not in the repo yet.
- The "assemble from Potato" wrapper idea is dropped: Drifblim needs file
  arguments and Potato cannot pass them.

So assembling on the deck is automatic. Drifblim runs inside uxn2
headlessly (uxn2 never opens a window for a ROM that halts before setting
a screen vector):

```
uxn2 drifblim.rom src/foo.tal foo.rom
```

A systemd path unit (`cyberdeck-build.path`) watches `~/deck/src`. When a
file there changes, `cyberdeck-build.service` runs `make` in that folder;
its one rule assembles every `src/*.tal` into `../*.rom`, so the ROM
appears on the desktop next to `potato.rom`. Assembler output goes to
`~/deck/build.log`, one level up so writing it does not retrigger the
watcher; open it from Potato to read errors.

Shared includes live in `src/lib/` and are pulled in with `~lib/name.tal`
(Drifblim resolves `~` from the working directory). `src/lib/atari8.tal`
is the Atari 8-bit 8x8 font Potato uses, generated from
`roms/potato/etc/font.icn` by `tools/icn2tal.py`. `src/hello.tal` is a
minimal starting ROM that uses it.

From a laptop, `make` at the repo root builds the same ROMs into `build/`
and `make disk DISK=path` populates a disk directory without touching a
user's `src/`, `lxmf/`, `.theme` or `.wallpaper`.

Done when: editing `src/hello.tal` on the deck yields `hello.rom` on the
desktop without leaving Varvara, and a syntax error shows up in
`build.log`. Verified so far: the repo-side build assembles Potato,
Noodle and hello, and all three run under uxn2.

## 5. The Reticulum device (page `d0`)

### 5.1 Design choice

The device carries **opaque frames** between a ROM and the bridge. It does
not know what LXMF is. That keeps the C side at roughly 120 lines, keeps
the protocol changeable without touching the emulator, and lets a future
NomadNet ROM reuse the same device with new frame types.

Frames are limited to 1024 bytes so a ROM can use a fixed buffer. The
bridge truncates long incoming messages in the frame and writes the full
text to the history file.

### 5.2 Port map

```
|d0 @Reticulum &vector $2 &status $1 &queue $1 &count $2 &length $2 &addr $2 &read $1 &write $1 &pad $4
```

| Port | Name | Dir | Meaning |
|---|---|---|---|
| `d0` | `vector*` | write | Called once each time a frame is queued for the ROM |
| `d2` | `status` | read | Bit 0: socket to bridge connected. Bit 1: Reticulum up. Bit 2: an RNode interface is online. Bit 3: a frame was dropped because the queue was full (cleared by the next `read`) |
| `d3` | `queue` | read | Number of frames waiting to be read |
| `d4` | `count*` | read | Bytes moved by the last `read` or `write`; `0000` means nothing happened |
| `d6` | `length*` | write | Buffer size for `read`, or bytes to send for `write` |
| `d8` | `addr*` | write | Memory address of the buffer |
| `da` | `read` | write | Any value: copy the oldest frame into `addr`, at most `length` bytes, pop it, set `count` |
| `db` | `write` | write | Any value: send `length` bytes at `addr` as one frame, set `count` (`0000` if not connected) |

Reading a frame:

```
@on-reticulum ( -> )
	;buf .Reticulum/addr DEO2
	#0400 .Reticulum/length DEO2
	#01 .Reticulum/read DEO
	.Reticulum/count DEI2 #0000 EQU2 ?{ ;buf handle-frame }
	.Reticulum/queue DEI ?on-reticulum
	BRK
```

Sending: fill a buffer, set `addr` and `length`, write to `write`.

Status bits 1 and 2 are copied from the bridge's most recent `STATE`
frame; bit 0 is the emulator's own socket state.

### 5.3 Emulator implementation

- `uxn2/src/reticulum.c`, included from `uxn2.c` next to the other device
  sections, plus table entries for `d2`, `d3`, `d4`, `d5`, `da`, `db`.
- On `emu_init`, connect to `$CYBERDECK_SOCKET`, else
  `$XDG_RUNTIME_DIR/cyberdeck.sock`, else `/run/cyberdeck/bridge.sock`.
  If the connect fails, a reader thread retries every two seconds, so the
  order in which the services start does not matter.
- The reader thread reads `len*` + payload and pushes an SDL user event,
  exactly like uxn2's existing stdin thread. The main loop appends the
  frame to a 16-slot ring and calls the vector. This keeps all Uxn
  evaluation on the main thread.
- Ring full: drop the new frame and set status bit 3.
- The device is harmless when no bridge exists (headless assembling, a
  laptop without Reticulum): status reads `00`, `write` sets `count` to
  `0000`.
- Second patch: software-renderer fallback described in 3.1.
- Both patches are also kept as `.patch` files under `uxn2/patches/` so
  they can be reapplied to a newer upstream `uxn2.c`.

### 5.4 Frame protocol (uxn2 ⇄ bridge)

Transport: Unix stream socket. Each frame is `len*` (big-endian short,
like Uxn) followed by `len` bytes. Byte 0 of the payload is the type.
Types `01`–`7f` go ROM to bridge, `81`–`ff` go bridge to ROM. Shorts are
big-endian. Hashes are the 16-byte LXMF destination hashes. Text is UTF-8;
the chat ROM renders ASCII and shows `?` for anything else.

ROM → bridge:

| Type | Name | Payload | Effect |
|---|---|---|---|
| `01` | `HELLO` | | Bridge replies `STATE` then `IDENTITY` (a `STATE` also arrives on connect, before any `HELLO`) |
| `02` | `SEND` | `ref* dest[16] len* text` | Queue an LXMF message; `ref` is chosen by the ROM and echoed in `DELIVERY` |
| `03` | `ANNOUNCE` | | Announce our delivery destination now |
| `04` | `PEERS` | | Bridge replies one `PEER` per known peer, then `PEERS_END` |
| `05` | `IDENTITY` | | Bridge replies `IDENTITY` |
| `06` | `NAME` | `len name` | Set and persist our display name |
| `07` | `POWER` | `01` reboot / `02` poweroff | Bridge calls `systemctl` (sudoers rule installed by setup.sh) |

Bridge → ROM:

| Type | Name | Payload | When |
|---|---|---|---|
| `81` | `STATE` | `flags` | Sent when a client connects, in reply to `HELLO`, and whenever the flags change. Bit 0 Reticulum up, bit 1 RNode online, bit 2 propagation node configured |
| `82` | `MESSAGE` | `src[16] hh mm len* text` | A message arrived. Local hour and minute are pre-split so the ROM needs no time math; full timestamps are in the history file |
| `83` | `DELIVERY` | `ref* state` | `01` sending, `02` sent, `03` delivered, `04` failed |
| `84` | `PEER` | `hash[16] flags len name` | An announce was heard, or in reply to `PEERS`. Flag bit 0: a path is known |
| `85` | `PEERS_END` | | Ends a `PEERS` reply |
| `86` | `IDENTITY` | `hash[16] len name` | Reply to `HELLO` or `IDENTITY` |
| `87` | `LOG` | `len text` | Bridge log line at INFO or above, for a status bar |

Done when: `etc/tests/reticulum.tal` run headlessly against a stub bridge
script exchanges `HELLO`/`STATE` and a `SEND`/`DELIVERY` round trip, and
the test is part of `make test` on x86. **Done**: `bridge/tests/test_device.py`
runs the ROM against `cyberdeck_bridge.stub` under SDL's dummy video
driver, which also exercises the software-renderer fallback.

## 6. The bridge

Python 3.11+, packaged in `bridge/`, installed into
`/home/deck/cyberdeck/.venv` with `rns` and `lxmf` from PyPI (verified
against rns 1.5.4 and lxmf 1.1.1).

Responsibilities, one module each:

- **node.py** wraps `LXMF.LXMRouter`. On start it loads or creates an
  `RNS.Identity` at `~/.cyberdeck/identity` (mode 600), calls
  `register_delivery_identity(identity, display_name)`,
  `register_delivery_callback`, and `RNS.Transport.register_announce_handler`
  filtered to the `lxmf.delivery` aspect. It announces on start, on
  `ANNOUNCE`, and hourly. For `SEND` it builds an `LXMessage`, requests a
  path with `RNS.Transport.request_path` if `has_path` is false, hands it to
  `handle_outbound`, and polls the message state to emit `DELIVERY`. It
  lets LXMF pick opportunistic versus direct delivery; short messages over
  LoRa go as single packets, longer ones open a link.
- **server.py** is an asyncio Unix socket server. Several uxn2 clients may
  connect at once (the laptop harness does this); events fan out to all.
- **protocol.py** is pure encode/decode with unit tests, shared by the
  stub bridge used in the uxn2 device test.
- **history.py** appends to `~/deck/lxmf/<hash>.txt` and rewrites
  `peers.txt` when a peer's name changes. Peers are also persisted to
  `~/.cyberdeck/peers.json` because announces on LoRa are rare and you
  want the list back after a reboot.

State lives in `~/.cyberdeck/` (identity, peers, LXMF router storage) and
`~/.reticulum/` (stock RNS config and known destinations). The disk only
gets the human-readable text files.

Propagation nodes (store-and-forward for offline peers) are supported by
LXMF and are a later config option, not part of the first cut.

Done when: two bridges on one machine, each with its own state directory
and socket, deliver a message from one to the other, and the receiving
side's `lxmf/<hash>.txt` has the line. **Done**:
`bridge/tests/test_lxmf_roundtrip.py` starts two bridge processes with
separate Reticulum instances joined by a localhost TCP interface (RNS does
not loop packets back inside one instance, so one process cannot host both
ends) and drives them over their sockets like uxn2 would.

Two facts learned from the real library: `RNS.Reticulum()` must be created
on the main thread because it installs signal handlers, and announce
handlers are called with keyword arguments including
`announce_packet_hash`, so the handler signature must name them.

## 7. Reticulum configuration

`setup.sh` renders `deck/reticulum/config.template` to
`/home/deck/.reticulum/config` only if that file does not exist yet, using
values from `deck/deck.env`:

```ini
[reticulum]
  enable_transport = No
  share_instance = Yes
  instance_name = default

[logging]
  loglevel = 4

[interfaces]
  [[LAN]]
    type = AutoInterface
    enabled = Yes

  [[RNode]]
    type = RNodeInterface
    enabled = Yes
    port = ${RNODE_PORT}
    frequency = 914875000
    bandwidth = 125000
    txpower = 7
    spreadingfactor = 8
    codingrate = 5
```

The AutoInterface means the deck and your laptop find each other over WiFi
with no configuration, which is how you test before the RNode is plugged
in and how the laptop harness reaches the deck.

`RNODE_PORT` should be a stable path under `/dev/serial/by-id/`. If exactly
one USB serial device is present, `setup.sh` fills it in; otherwise it
prints the candidates and stops. The RNode must already be running RNode
firmware; `rnodeconf`, which ships with `rns`, does that flashing and is
available in the venv.

The 915 MHz defaults above are the common Reticulum community settings for
North America. Adjust `frequency`, `txpower` and `spreadingfactor` to your
antenna and range needs; they are plain edits to the config.

## 8. The chat ROM

`roms/deck/chat.tal`, launched from Potato. Implemented:

- Screen: peer list on the left (unread marker, `>` when a path is known,
  name), the selected conversation on the right, a compose line, and a
  status line showing delivery state and the bridge's log lines. The
  title bar shows our display name, address prefix and three flags:
  `B` bridge socket, `R` Reticulum up, `L` RNode online.
- Keys: Up/Down select a peer, Enter send, Backspace edit, Tab or Ctrl+A
  announce, Ctrl+P refresh the peer list, Esc or Ctrl+Q halt (which
  returns you to Potato). F-keys are taken by uxn2 itself.
- On peer selection, and on every `MESSAGE` or `DELIVERY` for the selected
  peer, it re-reads `lxmf/<hash>.txt` with the File device and shows the
  tail, dropping the date so lines read `HH:MM name: text`. A long file is
  read in 8K chunks and only the last chunk is kept. Messages for other
  peers set an unread marker.
- Peers arrive as `PEER` frames (in reply to `PEERS` on connect, and on
  every announce). A message from an unknown peer adds it under its hash
  prefix until an announce supplies a name.
- The font is Potato's Atari 8-bit face via `~lib/atari8.tal`.

Two Drifblim facts shaped the source: `~include` never returns to the
including file, so the include is the last token and the ROM's buffers are
reserved before it (they are zero bytes in the ROM); and `OVR2` on a stack
with a byte on top is misaligned, so byte copies go through the return
stack.

Verified with the stub bridge under Xvfb (screenshots of every state) and
by `bridge/tests/test_chat_rom.py`. Not yet verified: against a real peer
such as Sideband, which needs the deck or the laptop harness on a network
with one.

## 9. Laptop dev harness

`dev/run-dev.sh` (also `make dev`):

1. Builds uxn2 and the ROMs.
2. Starts `rnsd` with `dev/reticulum-dev-config` (AutoInterface only) if
   no shared instance is running.
3. Starts two bridges: `--state ~/.cyberdeck-dev/a --socket /tmp/deck-a.sock`
   and the same for `b`, with display names `deck-a` and `deck-b`.
4. Launches two uxn2 windows with `CYBERDECK_SOCKET` pointing at each
   socket, both running `chat.rom` from a scratch disk under `dev/disk-*`.

Because your laptop's Reticulum instance also has an AutoInterface, the
same bridges see the real deck when it is on the same WiFi.

## 10. Provisioning: `deck/setup.sh`

Run as root on the Pi from a clone at `/home/deck/cyberdeck` (or it clones
there). Every step checks before it changes, so it is safe to rerun after
every `git pull`:

1. `apt install` build-essential, libsdl2-dev, python3-venv, rsync,
   inotify-tools.
2. Create user `deck` with the groups listed in 3.2; create
   `/home/deck/deck` and subfolders.
3. Build `uxn2` and install to `/usr/local/bin/uxn2`.
4. Build `drifblim.rom`, then every ROM with a source under `roms/`, and
   install them into the disk.
5. Create the venv, `pip install -e bridge/` (brings rns and lxmf).
6. Render the Reticulum config if missing (section 7).
7. Install a sudoers drop-in allowing `deck` to run
   `systemctl poweroff` and `systemctl reboot` without a password (for the
   `POWER` frame).
8. Install and enable the systemd units, disable `getty@tty1`, set the
   default target to `multi-user`.
9. Print a summary: Reticulum identity hash, RNode port, and the reminder
   to reboot.

A `deck/setup.sh --check` mode reports what would change without doing it.

## 11. Stage 2: NomadNet

Not designed in detail yet, but the current plan leaves room for it:

- NomadNet nodes are `nomadnetwork.node` destinations serving micron
  pages over RNS links. The bridge gains `FETCH hash len path` and a
  chunked `PAGE` reply; `PEER` gains a flag for "is a node".
- A `nomad.tal` ROM renders a micron subset (headings, lists, links) with
  the same text helpers as the chat ROM and follows links with more
  `FETCH` frames.
- LXMF propagation node support in the bridge comes in the same stage,
  since NomadNet nodes usually run one.

## 12. Implementation stages

Each stage is one branch and one review.

1. **Skeleton and kiosk.** Repo layout, top-level makefile, `setup.sh`,
   systemd units, uxn2 renderer fallback. Done in the repo; needs the
   on-hardware check: boots into Potato, auto-assemble works.
2. **Device and bridge, headless.** `reticulum.c`, protocol, bridge with
   stub tests, `etc/tests/reticulum.tal`. Done; `make test` covers the
   device, the protocol and a two-process LXMF roundtrip.
3. **Chat ROM and dev harness.** `chat.tal`, `run-dev.sh`, two decks on a
   laptop. Done in the repo; still to verify against Sideband over WiFi.
4. **RNode on the deck.** Config rendering, port detection, end-to-end over
   LoRa.
5. **NomadNet** as sketched in section 11.

## 13. Open questions and risks

- **GLES on your Armbian image.** Check `ls /dev/dri` and `uname -r` on
  the Pi. Vendor 6.1 kernels and mainline "edge" kernels differ in
  Panfrost support; the software fallback covers both, at some CPU cost.
- **Left is missing.** Potato's Text app cannot edit, so until Left's
  source is added to `roms/`, editing `.tal` on the deck means SSH. The
  build pipeline itself works without it.
- **Other ROM sources.** Nasu is only present as a binary
  (`roms/potato/etc/nasu.rom`), and Orca, Dexe and Bifurcan are not in the
  repo yet. Each is one line in the top-level makefile once its source
  is committed.
- **RNode board.** Port detection assumes a USB serial RNode. A BLE RNode
  is supported by RNS (`port = ble://…`) but changes the udev story.
- **LoRa timing.** At SF8/125 kHz a direct LXMF delivery takes several
  seconds and an announce is heard only when a peer sends one. The ROM
  should show "sending" states plainly rather than look frozen.
- **Frame size.** 1024 bytes per frame is a ROM-side simplification. If a
  future ROM needs more (NomadNet pages), the protocol gains chunking on
  the bridge side without any change to the device.
- **Keeping up with upstream uxn2.** Patches are small and separable; the
  device lives in its own file. Re-vendoring upstream is: copy `uxn2.c`,
  reapply two patches, rebuild, run `make test`.
