"""Smoke test: chat.rom starts against the stub bridge and stays up.

Needs uxn2 and build/chat.rom (`make` at the repo root); skipped otherwise.
Runs under SDL's dummy video driver, so no display is needed. The ROM's
HELLO and PEERS on connect are visible in the stub's log at debug level.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
UXN2 = os.path.join(ROOT, "uxn2", "bin", "uxn2")
ROM = os.path.join(ROOT, "build", "chat.rom")


@unittest.skipUnless(os.path.exists(UXN2) and os.path.exists(ROM), "uxn2 or chat.rom not built")
class ChatRomTest(unittest.TestCase):
    def test_starts_and_talks_to_bridge(self):
        with tempfile.TemporaryDirectory(prefix="deck") as d:
            sock = os.path.join(d, "s")
            with subprocess.Popen(
                [sys.executable, "-m", "cyberdeck_bridge.stub", "--socket", sock, "--disk", d, "-v"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=os.path.join(ROOT, "bridge"),
            ) as stub:
                try:
                    for _ in range(100):
                        if os.path.exists(sock):
                            break
                        time.sleep(0.05)
                    env = dict(os.environ, CYBERDECK_SOCKET=sock, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
                    with subprocess.Popen([UXN2, ROM], env=env, cwd=d, stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT, text=True) as rom:
                        time.sleep(2)
                        still_running = rom.poll() is None
                        rom.terminate()
                        out = rom.communicate(timeout=5)[0]
                    self.assertTrue(still_running, f"chat.rom exited early:\n{out}")
                finally:
                    stub.terminate()
                    log = stub.communicate(timeout=5)[0]
            self.assertIn("client connected", log)
