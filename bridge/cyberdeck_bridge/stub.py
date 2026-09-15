"""A bridge without Reticulum, for testing the uxn2 device and ROMs.

Replies to HELLO with STATE and IDENTITY, acknowledges SEND with a
DELIVERY sequence and echoes the text back as a MESSAGE from a fake peer,
answers PEERS with one fake peer. With --disk it also appends history
lines to <disk>/lxmf like the real bridge does.

Run: cyberdeck-stub-bridge --socket PATH [--disk DIR]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import time

from . import protocol as p
from .history import History
from .server import Client, Server

SELF_HASH = bytes(range(16))
PEER_HASH = bytes(range(0x10, 0x20))


class Stub:
    def __init__(self, path: str, disk: str | None = None) -> None:
        self.server = Server(path, self.on_command)
        self.server.on_connect = lambda c: c.send(p.state(p.STATE_RNS_UP))
        self.history = History(disk) if disk else None
        self.name = "stub"

    async def on_command(self, client: Client, cmd: p.Command) -> None:
        if cmd.type == p.HELLO:
            client.send(p.state(p.STATE_RNS_UP))
            client.send(p.identity(SELF_HASH, "stub"))
        elif cmd.type == p.IDENTITY:
            client.send(p.identity(SELF_HASH, "stub"))
        elif cmd.type == p.SEND:
            client.send(p.delivery(cmd.ref, p.DELIVERY_SENDING))
            if self.history:
                self.history.append(cmd.dest, self.name, cmd.text)
            client.send(p.delivery(cmd.ref, p.DELIVERY_DELIVERED))
            reply = "echo: " + cmd.text
            if self.history:
                self.history.append(cmd.dest, "echo", reply)
            lt = time.localtime()
            client.send(p.message(cmd.dest, lt.tm_hour, lt.tm_min, reply))
        elif cmd.type == p.PEERS:
            client.send(p.peer(PEER_HASH, p.PEER_HAS_PATH, "echo"))
            client.send(p.peers_end())
        elif cmd.type == p.ANNOUNCE:
            client.send(p.log("announced"))
        elif cmd.type == p.NAME:
            self.name = cmd.text
            client.send(p.identity(SELF_HASH, cmd.text))
        elif cmd.type == p.POWER:
            client.send(p.log(f"power action {cmd.action} ignored by stub"))


async def run(path: str, disk: str | None) -> None:
    stub = Stub(path, disk)
    await stub.server.start()
    print(f"stub bridge listening on {path}", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await stub.server.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--socket", required=True)
    ap.add_argument("--disk", help="write lxmf/ history files under this disk directory")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO, format="%(name)s: %(message)s")
    try:
        asyncio.run(run(a.socket, a.disk))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
