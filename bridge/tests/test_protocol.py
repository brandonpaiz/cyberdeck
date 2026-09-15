import unittest

from cyberdeck_bridge import protocol as p


class ProtocolTest(unittest.TestCase):
    def test_pack_and_reader_roundtrip(self):
        frames = [p.state(1), p.log("hello"), p.peers_end()]
        wire = b"".join(p.pack(f) for f in frames)
        r = p.FrameReader()
        got = []
        for i in range(0, len(wire), 3):  # feed in awkward chunks
            got += r.feed(wire[i:i + 3])
        self.assertEqual(got, frames)

    def test_reader_rejects_bad_length(self):
        with self.assertRaises(p.ProtocolError):
            p.FrameReader().feed(b"\x00\x00")
        with self.assertRaises(p.ProtocolError):
            p.FrameReader().feed(b"\xff\xff")

    def test_send_roundtrip(self):
        dest = bytes(range(16))
        cmd = p.parse_command(p.encode_send(0x1234, dest, "héllo"))
        self.assertEqual((cmd.type, cmd.ref, cmd.dest, cmd.text), (p.SEND, 0x1234, dest, "héllo"))

    def test_message_truncates_at_utf8_boundary(self):
        text = "é" * 600  # 1200 bytes
        f = p.message(bytes(16), 1, 2, text)
        self.assertLessEqual(len(f), p.MAX_FRAME)
        n = int.from_bytes(f[19:21], "big")
        body = f[21:21 + n]
        self.assertEqual(len(body), n)
        body.decode("utf-8")  # must not raise

    def test_message_layout(self):
        src = bytes(range(16))
        f = p.message(src, 23, 59, "hi")
        self.assertEqual(f, bytes([p.MESSAGE]) + src + bytes([23, 59, 0, 2]) + b"hi")

    def test_peer_and_identity(self):
        h = bytes(range(16))
        self.assertEqual(p.peer(h, 1, "bob"), bytes([p.PEER]) + h + b"\x01\x03bob")
        self.assertEqual(p.identity(h, "me"), bytes([p.IDENTITY_REPLY]) + h + b"\x02me")

    def test_parse_simple_commands(self):
        for t in (p.HELLO, p.ANNOUNCE, p.PEERS, p.IDENTITY):
            self.assertEqual(p.parse_command(bytes([t])).type, t)
        self.assertEqual(p.parse_command(bytes([p.NAME, 3]) + b"abc").text, "abc")
        self.assertEqual(p.parse_command(bytes([p.POWER, p.POWER_OFF])).action, p.POWER_OFF)
        with self.assertRaises(p.ProtocolError):
            p.parse_command(bytes([0x7f]))
        with self.assertRaises(p.ProtocolError):
            p.parse_command(bytes([p.SEND, 0, 1]))


if __name__ == "__main__":
    unittest.main()
