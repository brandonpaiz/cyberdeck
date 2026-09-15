"""Runs the uxn2 Reticulum device test ROM against the stub bridge.

Needs uxn2 built (uxn2/bin/uxn2) and the test ROM assembled
(uxn2/bin/reticulum.rom); `make test` at the repo root does both.
Skips when either is missing.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
UXN2 = os.path.join(ROOT, "uxn2", "bin", "uxn2")
ROM = os.path.join(ROOT, "uxn2", "bin", "reticulum.rom")


@unittest.skipUnless(os.path.exists(UXN2) and os.path.exists(ROM), "uxn2 or reticulum.rom not built")
class DeviceTest(unittest.TestCase):
    def test_hello_send_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            sock = os.path.join(d, "bridge.sock")
            with subprocess.Popen(
                [sys.executable, "-m", "cyberdeck_bridge.stub", "--socket", sock],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                cwd=os.path.join(ROOT, "bridge"),
            ) as stub:
                for _ in range(100):
                    if os.path.exists(sock):
                        break
                    time.sleep(0.05)
                env = dict(os.environ, CYBERDECK_SOCKET=sock, SDL_VIDEODRIVER="dummy", SDL_AUDIODRIVER="dummy")
                try:
                    r = subprocess.run([UXN2, ROM], env=env, capture_output=True, text=True, timeout=20)
                finally:
                    stub.terminate()
            self.assertEqual(r.returncode, 0, f"uxn2 exit {r.returncode}\nstdout:\n{r.stdout}\nstderr:\n{r.stderr}")
            self.assertEqual(
                r.stdout.splitlines(),
                ["frame 81", "frame 81", "frame 86", "frame 83", "frame 83", "frame 82", "ok"],
            )


if __name__ == "__main__":
    unittest.main()
