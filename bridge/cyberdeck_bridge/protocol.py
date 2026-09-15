"""Frame protocol between uxn2's Reticulum device and the bridge.

Transport: a Unix stream socket carrying frames of ``len*`` (big-endian
short) followed by ``len`` payload bytes. Byte 0 of the payload is the
type. Types 0x01-0x7f travel ROM -> bridge, 0x81-0xff bridge -> ROM.
Shorts are big-endian, hashes are 16-byte LXMF destination hashes, text is
UTF-8. Frames never exceed MAX_FRAME so a ROM can use a fixed buffer.
See DESIGN.md §5.4.
"""
from __future__ import annotations

from dataclasses import dataclass, field

MAX_FRAME = 1024
HASH_LEN = 16
MAX_NAME = 32       # bytes of a display name inside a frame
MAX_TEXT = 900      # bytes of message text inside a frame

# ROM -> bridge
HELLO, SEND, ANNOUNCE, PEERS, IDENTITY, NAME, POWER = 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07
# bridge -> ROM
STATE, MESSAGE, DELIVERY, PEER, PEERS_END, IDENTITY_REPLY, LOG = 0x81, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87

# STATE flags
STATE_RNS_UP, STATE_RNODE_ONLINE, STATE_PROPAGATION = 0x01, 0x02, 0x04
# DELIVERY states
DELIVERY_SENDING, DELIVERY_SENT, DELIVERY_DELIVERED, DELIVERY_FAILED = 0x01, 0x02, 0x03, 0x04
# PEER flags
PEER_HAS_PATH = 0x01
# POWER actions
POWER_REBOOT, POWER_OFF = 0x01, 0x02


class ProtocolError(ValueError):
    pass


def pack(payload: bytes) -> bytes:
    """Prefix a payload with its length for the wire."""
    if not 1 <= len(payload) <= MAX_FRAME:
        raise ProtocolError(f"payload of {len(payload)} bytes out of range")
    return len(payload).to_bytes(2, "big") + payload


class FrameReader:
    """Incremental parser: feed() bytes, iterate complete payloads."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buf += data
        out = []
        while len(self._buf) >= 2:
            n = int.from_bytes(self._buf[:2], "big")
            if n == 0 or n > MAX_FRAME:
                raise ProtocolError(f"bad frame length {n}")
            if len(self._buf) < 2 + n:
                break
            out.append(bytes(self._buf[2:2 + n]))
            del self._buf[:2 + n]
        return out


def _text(s: str, limit: int) -> bytes:
    b = s.encode("utf-8", "replace")
    if len(b) <= limit:
        return b
    b = b[:limit]
    # don't cut a multi-byte sequence in half
    while b and (b[-1] & 0xC0) == 0x80:
        b = b[:-1]
    return b[:-1] if b and b[-1] >= 0xC0 else b


def _name(s: str) -> bytes:
    b = _text(s, MAX_NAME)
    return bytes([len(b)]) + b


# ---------------------------------------------------------- bridge -> ROM

def state(flags: int) -> bytes:
    return bytes([STATE, flags & 0xFF])


def message(src: bytes, hour: int, minute: int, text: str) -> bytes:
    _check_hash(src)
    body = _text(text, MAX_TEXT)
    return bytes([MESSAGE]) + src + bytes([hour, minute]) + len(body).to_bytes(2, "big") + body


def delivery(ref: int, state_: int) -> bytes:
    return bytes([DELIVERY]) + (ref & 0xFFFF).to_bytes(2, "big") + bytes([state_])


def peer(hash_: bytes, flags: int, name: str) -> bytes:
    _check_hash(hash_)
    return bytes([PEER]) + hash_ + bytes([flags & 0xFF]) + _name(name)


def peers_end() -> bytes:
    return bytes([PEERS_END])


def identity(hash_: bytes, name: str) -> bytes:
    _check_hash(hash_)
    return bytes([IDENTITY_REPLY]) + hash_ + _name(name)


def log(text: str) -> bytes:
    body = _text(text, 200)
    return bytes([LOG, len(body)]) + body


# ---------------------------------------------------------- ROM -> bridge

@dataclass
class Command:
    type: int
    ref: int = 0
    dest: bytes = b""
    text: str = ""
    action: int = 0
    fields: dict = field(default_factory=dict)


def parse_command(payload: bytes) -> Command:
    if not payload:
        raise ProtocolError("empty payload")
    t = payload[0]
    body = payload[1:]
    if t in (HELLO, ANNOUNCE, PEERS, IDENTITY):
        return Command(t)
    if t == SEND:
        if len(body) < 2 + HASH_LEN + 2:
            raise ProtocolError("short SEND")
        ref = int.from_bytes(body[:2], "big")
        dest = bytes(body[2:2 + HASH_LEN])
        n = int.from_bytes(body[2 + HASH_LEN:4 + HASH_LEN], "big")
        text = body[4 + HASH_LEN:4 + HASH_LEN + n]
        if len(text) != n:
            raise ProtocolError("SEND text shorter than declared")
        return Command(SEND, ref=ref, dest=dest, text=text.decode("utf-8", "replace"))
    if t == NAME:
        if not body or len(body) < 1 + body[0]:
            raise ProtocolError("short NAME")
        return Command(NAME, text=body[1:1 + body[0]].decode("utf-8", "replace"))
    if t == POWER:
        if not body:
            raise ProtocolError("short POWER")
        return Command(POWER, action=body[0])
    raise ProtocolError(f"unknown command type {t:#04x}")


# ---------------------------------------------------------------- helpers

def _check_hash(h: bytes) -> None:
    if len(h) != HASH_LEN:
        raise ProtocolError(f"hash must be {HASH_LEN} bytes, got {len(h)}")


def encode_send(ref: int, dest: bytes, text: str) -> bytes:
    """ROM-side encoder, used by tests and the stub."""
    _check_hash(dest)
    body = text.encode("utf-8")
    return bytes([SEND]) + (ref & 0xFFFF).to_bytes(2, "big") + dest + len(body).to_bytes(2, "big") + body
