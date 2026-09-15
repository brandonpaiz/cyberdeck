"""Unix socket server: accepts uxn2 clients, parses their frames, fans events out."""
from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable

from . import protocol

log = logging.getLogger("bridge.server")

CommandHandler = Callable[["Client", protocol.Command], Awaitable[None]]


class Client:
    def __init__(self, writer: asyncio.StreamWriter) -> None:
        self.writer = writer

    def send(self, payload: bytes) -> None:
        try:
            self.writer.write(protocol.pack(payload))
        except protocol.ProtocolError as e:
            log.warning("dropping oversize frame: %s", e)


class Server:
    def __init__(self, path: str, on_command: CommandHandler) -> None:
        self.path = path
        self.on_command = on_command
        self.clients: set[Client] = set()
        self._server: asyncio.AbstractServer | None = None
        self.on_connect: Callable[[Client], None] | None = None

    async def start(self) -> None:
        if os.path.exists(self.path):
            os.unlink(self.path)
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self._server = await asyncio.start_unix_server(self._handle, path=self.path)
        os.chmod(self.path, 0o660)
        log.info("listening on %s", self.path)

    async def close(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for c in list(self.clients):
            c.writer.close()
        if os.path.exists(self.path):
            os.unlink(self.path)

    def broadcast(self, payload: bytes) -> None:
        for c in list(self.clients):
            c.send(payload)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        client = Client(writer)
        self.clients.add(client)
        log.info("client connected (%d total)", len(self.clients))
        if self.on_connect:
            self.on_connect(client)
        frames = protocol.FrameReader()
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                for payload in frames.feed(data):
                    try:
                        cmd = protocol.parse_command(payload)
                    except protocol.ProtocolError as e:
                        log.warning("bad command from client: %s", e)
                        continue
                    await self.on_command(client, cmd)
                await writer.drain()
        except (ConnectionResetError, BrokenPipeError, protocol.ProtocolError) as e:
            log.info("client dropped: %s", e)
        finally:
            self.clients.discard(client)
            writer.close()
            log.info("client disconnected (%d total)", len(self.clients))
