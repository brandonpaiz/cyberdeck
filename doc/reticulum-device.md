# Reticulum device (page `d0`)

A cyberdeck extension to Varvara, implemented in `uxn2/src/reticulum.c`.
It moves opaque frames between a ROM and the `cyberdeck-bridge` daemon
over a Unix socket. The bridge does the Reticulum and LXMF work.

```
|d0 @Reticulum &vector $2 &status $1 &queue $1 &count $2 &length $2 &addr $2 &read $1 &write $1 &pad $4
```

| Port | Name | Dir | Meaning |
|---|---|---|---|
| `d0` | `vector*` | write | Called once each time a frame is queued for the ROM |
| `d2` | `status` | read | Bit 0 socket to bridge connected. Bit 1 Reticulum up. Bit 2 RNode online. Bit 3 a frame was dropped (queue full); cleared by the next `read` |
| `d3` | `queue` | read | Frames waiting to be read (up to 16) |
| `d4` | `count*` | read | Bytes moved by the last `read` or `write`; `0000` means nothing happened |
| `d6` | `length*` | write | Buffer size for `read`, or bytes to send for `write` |
| `d8` | `addr*` | write | Memory address of the buffer |
| `da` | `read` | write | Any value: copy the oldest frame into `addr`, at most `length` bytes, pop it, set `count` |
| `db` | `write` | write | Any value: send `length` bytes at `addr` as one frame, set `count` (`0000` if not connected or `length` > 1024) |

Frames are at most 1024 bytes. Without a bridge the device is inert:
`status` reads `00`, `write` leaves `count` at `0000`.

## Reading

```
@on-reticulum ( -> )
	&again
	;buf .Reticulum/addr DEO2
	#0400 .Reticulum/length DEO2
	#01 .Reticulum/read DEO
	.Reticulum/count DEI2 ORAk ?{ POP2 BRK }
	POP2 ;buf handle-frame
	.Reticulum/queue DEI ?&again
	BRK
```

## Writing

```
;cmd-hello #0001 send

@send ( payload* len* -- )
	.Reticulum/length DEO2
	.Reticulum/addr DEO2
	#01 .Reticulum/write DEO
	JMP2r

@cmd-hello 01
```

## Frames

Byte 0 is the type. Shorts are big-endian, hashes are 16-byte LXMF
destination hashes, text is UTF-8.

ROM to bridge:

| Type | Name | Payload |
|---|---|---|
| `01` | `HELLO` | reply: `STATE`, `IDENTITY` |
| `02` | `SEND` | `ref* dest[16] len* text` — `ref` comes back in `DELIVERY` |
| `03` | `ANNOUNCE` | announce our address now |
| `04` | `PEERS` | reply: one `PEER` per known peer, then `PEERS_END` |
| `05` | `IDENTITY` | reply: `IDENTITY` |
| `06` | `NAME` | `len name` — set our display name |
| `07` | `POWER` | `01` reboot, `02` power off |

Bridge to ROM:

| Type | Name | Payload |
|---|---|---|
| `81` | `STATE` | `flags` — bit 0 Reticulum up, bit 1 RNode online, bit 2 propagation node configured. Sent on connect, after `HELLO`, and on change |
| `82` | `MESSAGE` | `src[16] hh mm len* text` |
| `83` | `DELIVERY` | `ref* state` — `01` sending, `02` sent, `03` delivered, `04` failed |
| `84` | `PEER` | `hash[16] flags len name` — flag bit 0: a path is known |
| `85` | `PEERS_END` | |
| `86` | `IDENTITY` | `hash[16] len name` |
| `87` | `LOG` | `len text` — a bridge log line |

Conversation history is not carried in frames. The bridge appends every
message to `lxmf/<hash hex>.txt` in the disk directory, and keeps
`lxmf/peers.txt`, for ROMs to read with the File device.

## Testing without Reticulum

`cyberdeck-stub-bridge --socket /tmp/deck.sock` answers like a bridge
with one fake peer and echoes every `SEND` back as a `MESSAGE`. Point
uxn2 at it with `CYBERDECK_SOCKET=/tmp/deck.sock`.
