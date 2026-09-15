"""Plain-text conversation history on the Varvara disk.

lxmf/<hash hex>.txt   one line per message:  YYYY-MM-DD HH:MM name: text
lxmf/peers.txt        one line per peer:     <hash hex> name

ROMs read these with the ordinary File device, so the chat ROM needs no
persistence of its own.
"""
from __future__ import annotations

import os
import threading
import time


class History:
    def __init__(self, disk_dir: str) -> None:
        self.dir = os.path.join(disk_dir, "lxmf")
        self._lock = threading.Lock()
        os.makedirs(self.dir, exist_ok=True)

    def conversation_path(self, peer_hash: bytes) -> str:
        return os.path.join(self.dir, peer_hash.hex() + ".txt")

    def append(self, peer_hash: bytes, name: str, text: str, ts: float | None = None) -> None:
        ts = time.time() if ts is None else ts
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
        line = f"{stamp} {name}: {text.replace(chr(10), ' ')}\n"
        with self._lock, open(self.conversation_path(peer_hash), "a", encoding="utf-8") as f:
            f.write(line)

    def write_peers(self, peers: dict[bytes, dict]) -> None:
        tmp = os.path.join(self.dir, ".peers.txt.tmp")
        with self._lock:
            with open(tmp, "w", encoding="utf-8") as f:
                for h, info in sorted(peers.items(), key=lambda kv: kv[1].get("name", "")):
                    f.write(f"{h.hex()} {info.get('name', '')}\n")
            os.replace(tmp, os.path.join(self.dir, "peers.txt"))
