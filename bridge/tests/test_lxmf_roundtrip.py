"""End to end: two bridges, two Reticulum instances joined over localhost TCP.

Starts `cyberdeck_bridge` twice (alice, bob), each with its own throwaway
Reticulum config, talks to both over their Unix sockets exactly as uxn2
would, and checks that a message from alice reaches bob, that alice sees
it delivered, and that bob's history file has the line.

Needs rns and lxmf importable; skipped otherwise. Takes ~10-20 s.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

try:
    import RNS  # noqa: F401
    import LXMF  # noqa: F401
    HAVE_RNS = True
except ImportError:
    HAVE_RNS = False

from cyberdeck_bridge import protocol as p

BRIDGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

SERVER_CONFIG = """
[reticulum]
  enable_transport = No
  share_instance = No
[logging]
  loglevel = 3
[interfaces]
  [[loop]]
    type = TCPServerInterface
    enabled = Yes
    listen_ip = 127.0.0.1
    listen_port = {port}
"""

CLIENT_CONFIG = """
[reticulum]
  enable_transport = No
  share_instance = No
[logging]
  loglevel = 3
[interfaces]
  [[loop]]
    type = TCPClientInterface
    enabled = Yes
    target_host = 127.0.0.1
    target_port = {port}
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class DeckClient:
    """Talks to a bridge socket the way the uxn2 device does."""

    def __init__(self, path: str, timeout: float = 30) -> None:
        deadline = time.time() + timeout
        while True:
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(path)
                break
            except OSError:
                self.sock.close()
                if time.time() > deadline:
                    raise
                time.sleep(0.2)
        self.sock.settimeout(0.5)
        self.reader = p.FrameReader()
        self.frames: list[bytes] = []

    def send(self, payload: bytes) -> None:
        self.sock.sendall(p.pack(payload))

    def wait(self, frame_type: int, timeout: float, pred=lambda f: True) -> bytes:
        deadline = time.time() + timeout
        while time.time() < deadline:
            for i, f in enumerate(self.frames):
                if f[0] == frame_type and pred(f):
                    return self.frames.pop(i)
            try:
                data = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not data:
                raise AssertionError("bridge closed the socket")
            self.frames += self.reader.feed(data)
        raise AssertionError(f"no frame {frame_type:#04x} within {timeout}s; got {[hex(f[0]) for f in self.frames]}")

    def close(self) -> None:
        self.sock.close()


@unittest.skipUnless(HAVE_RNS, "rns/lxmf not installed")
class RoundtripTest(unittest.TestCase):
    def _bridge(self, d: str, who: str, config: str) -> tuple[subprocess.Popen, str, str]:
        cfg = os.path.join(d, who, "rns")
        os.makedirs(cfg)
        with open(os.path.join(cfg, "config"), "w") as f:
            f.write(config)
        sock = os.path.join(d, who, "bridge.sock")
        disk = os.path.join(d, who, "disk")
        log = open(os.path.join(d, who, "log"), "w")
        proc = subprocess.Popen(
            [sys.executable, "-m", "cyberdeck_bridge", "--socket", sock, "--state", os.path.join(d, who, "state"),
             "--disk", disk, "--name", who, "--rns-config", cfg],
            cwd=BRIDGE_DIR, stdout=log, stderr=subprocess.STDOUT,
        )
        self.addCleanup(log.close)
        return proc, sock, disk

    def test_alice_messages_bob(self):
        port = _free_port()
        with tempfile.TemporaryDirectory() as d:
            pa, sock_a, _ = self._bridge(d, "alice", SERVER_CONFIG.format(port=port))
            pb, sock_b, disk_b = self._bridge(d, "bob", CLIENT_CONFIG.format(port=port))
            clients = []
            try:
                a, b = DeckClient(sock_a), DeckClient(sock_b)
                clients += [a, b]
                for c in (a, b):
                    c.wait(p.STATE, 30, lambda f: f[1] & p.STATE_RNS_UP)
                    c.send(bytes([p.HELLO]))
                ident_a = a.wait(p.IDENTITY_REPLY, 10)
                ident_b = b.wait(p.IDENTITY_REPLY, 10)
                hash_a, hash_b = ident_a[1:17], ident_b[1:17]
                self.assertEqual(ident_b[18:18 + ident_b[17]], b"bob")

                # bob's first announce may predate the TCP link coming up
                # (RNS retries the connection every 5 s), so re-announce
                # until alice hears it.
                peer = None
                for _ in range(8):
                    b.send(bytes([p.ANNOUNCE]))
                    try:
                        peer = a.wait(p.PEER, 5, lambda f: f[1:17] == hash_b)
                        break
                    except AssertionError:
                        continue
                self.assertIsNotNone(peer, "alice never heard bob's announce")
                self.assertEqual(peer[19:19 + peer[18]], b"bob")

                a.send(p.encode_send(7, hash_b, "hello bob"))
                msg = b.wait(p.MESSAGE, 60)
                self.assertEqual(msg[1:17], hash_a)
                n = int.from_bytes(msg[19:21], "big")
                self.assertEqual(msg[21:21 + n], b"hello bob")
                a.wait(p.DELIVERY, 60, lambda f: f[1:3] == b"\x00\x07" and f[3] == p.DELIVERY_DELIVERED)

                with open(os.path.join(disk_b, "lxmf", hash_a.hex() + ".txt"), encoding="utf-8") as f:
                    self.assertIn(": hello bob", f.read())
                # bob may have missed alice's start-up announce (his TCP link
                # came up late); the bridge then requests a path, and the
                # path response tells him her name.
                peer_a = b.wait(p.PEER, 30, lambda f: f[1:17] == hash_a and f[19:19 + f[18]] == b"alice")
                self.assertEqual(peer_a[19:19 + peer_a[18]], b"alice")
            finally:
                for c in clients:
                    c.close()
                for proc in (pa, pb):
                    proc.terminate()
                for proc in (pa, pb):
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                if os.environ.get("KEEP_LOGS"):
                    for who in ("alice", "bob"):
                        with open(os.path.join(d, who, "log"), encoding="utf-8") as f:
                            print(f"--- {who} log ---\n{f.read()}")


if __name__ == "__main__":
    unittest.main()
