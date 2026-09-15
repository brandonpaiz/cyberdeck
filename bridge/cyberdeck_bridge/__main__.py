"""cyberdeck-bridge: LXMF behind the Varvara Reticulum device.

Listens on a Unix socket for uxn2, runs an LXMF router on the local
Reticulum instance, and translates between the two. See DESIGN.md §5-6.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import subprocess

from . import protocol as p
from .node import Node
from .server import Client, Server

log = logging.getLogger("bridge")


class _FrameLogHandler(logging.Handler):
    """Mirrors bridge log lines to ROMs as LOG frames."""

    def __init__(self, emit_frame) -> None:
        super().__init__(level=logging.INFO)
        self._emit = emit_frame

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self._emit(p.log(record.getMessage()))
        except Exception:  # never let logging break the bridge
            pass


class Bridge:
    def __init__(self, socket_path: str, state_dir: str, disk_dir: str, name: str, configdir: str | None) -> None:
        self.loop = asyncio.get_running_loop()
        self.server = Server(socket_path, self.on_command)
        self.server.on_connect = self._on_connect
        self.node = Node(state_dir, disk_dir, name, self.emit, configdir)

    def emit(self, payload: bytes) -> None:
        self.loop.call_soon_threadsafe(self.server.broadcast, payload)

    def _on_connect(self, client: Client) -> None:
        client.send(p.state(self.node.flags()))

    async def run(self) -> None:
        await self.server.start()
        logging.getLogger("bridge").addHandler(_FrameLogHandler(self.emit))
        # Reticulum installs signal handlers, so it must start on the main thread.
        self.node.start()
        self.server.broadcast(p.state(self.node.flags()))
        try:
            await asyncio.Event().wait()
        finally:
            await self.server.close()

    async def on_command(self, client: Client, cmd: p.Command) -> None:
        n = self.node
        if cmd.type == p.HELLO:
            client.send(p.state(n.flags()))
            client.send(p.identity(n.hash, n.display_name))
        elif cmd.type == p.IDENTITY:
            client.send(p.identity(n.hash, n.display_name))
        elif cmd.type == p.SEND:
            self.loop.run_in_executor(None, n.send, cmd.ref, cmd.dest, cmd.text)
        elif cmd.type == p.ANNOUNCE:
            self.loop.run_in_executor(None, n.announce)
        elif cmd.type == p.PEERS:
            for f in n.peer_frames():
                client.send(f)
            client.send(p.peers_end())
        elif cmd.type == p.NAME:
            self.loop.run_in_executor(None, n.set_name, cmd.text)
            client.send(p.identity(n.hash, cmd.text.strip() or n.display_name))
        elif cmd.type == p.POWER:
            self._power(cmd.action)

    def _power(self, action: int) -> None:
        verb = {p.POWER_REBOOT: "reboot", p.POWER_OFF: "poweroff"}.get(action)
        if not verb:
            log.warning("unknown power action %d", action)
            return
        log.info("power: %s", verb)
        try:
            subprocess.Popen(["sudo", "-n", "systemctl", verb])
        except OSError as e:
            log.error("power %s failed: %s", verb, e)


def _default_name(state_dir: str) -> str:
    try:
        with open(os.path.join(state_dir, "name"), encoding="utf-8") as f:
            return f.read().strip() or "cyberdeck"
    except OSError:
        return "cyberdeck"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--socket", default=os.environ.get("CYBERDECK_SOCKET", "/run/cyberdeck/bridge.sock"))
    ap.add_argument("--state", default=os.path.expanduser("~/.cyberdeck"), help="identity, peers, LXMF storage")
    ap.add_argument("--disk", default=os.environ.get("CYBERDECK_DISK", os.path.expanduser("~/deck")),
                    help="Varvara disk; history goes to <disk>/lxmf")
    ap.add_argument("--name", help="LXMF display name (default: <state>/name or 'cyberdeck')")
    ap.add_argument("--rns-config", help="Reticulum config directory (default: ~/.reticulum)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    name = a.name or _default_name(a.state)

    async def amain() -> None:
        await Bridge(a.socket, a.state, a.disk, name, a.rns_config).run()

    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
