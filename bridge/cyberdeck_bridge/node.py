"""LXMF node: one delivery identity on a (usually shared) Reticulum instance.

Everything here runs on Reticulum's threads or the housekeeping thread.
Events for ROMs are handed to ``on_event(payload)`` as ready-to-send frame
payloads; the caller marshals them onto its event loop.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Callable

import LXMF
import RNS

from . import protocol as p
from .history import History

log = logging.getLogger("bridge.node")


class _AnnounceHandler:
    aspect_filter = "lxmf.delivery"

    def __init__(self, cb: Callable[[bytes, object, bytes | None], None]) -> None:
        self._cb = cb

    def received_announce(self, destination_hash, announced_identity, app_data,
                          announce_packet_hash=None, is_path_response=None) -> None:
        self._cb(destination_hash, announced_identity, app_data)


class Node:
    ANNOUNCE_INTERVAL = 3600
    PATH_TIMEOUT = 40
    HOUSEKEEPING_INTERVAL = 2

    def __init__(self, state_dir: str, disk_dir: str, display_name: str,
                 on_event: Callable[[bytes], None], configdir: str | None = None) -> None:
        self.state_dir = state_dir
        self.display_name = display_name
        self.on_event = on_event
        self.configdir = configdir
        self.history = History(disk_dir)
        self.peers: dict[bytes, dict] = {}
        self._pending: dict[int, LXMF.LXMessage] = {}
        self._pending_lock = threading.Lock()
        self._flags = 0
        self._last_announce = 0.0
        self.rns: RNS.Reticulum | None = None
        self.router: LXMF.LXMRouter | None = None
        self.dest: RNS.Destination | None = None
        os.makedirs(state_dir, mode=0o700, exist_ok=True)

    # ------------------------------------------------------------ lifecycle

    def start(self) -> None:
        # one Reticulum per process; a second node (tests, dev harness) shares it
        self.rns = RNS.Reticulum.get_instance() or RNS.Reticulum(configdir=self.configdir)
        self.identity = self._load_identity()
        self.router = LXMF.LXMRouter(identity=self.identity, storagepath=os.path.join(self.state_dir, "lxmf"))
        self.dest = self.router.register_delivery_identity(self.identity, display_name=self.display_name)
        self.router.register_delivery_callback(self._on_lxmf_delivery)
        RNS.Transport.register_announce_handler(_AnnounceHandler(self._on_announce))
        self._load_peers()
        log.info("LXMF address %s (%s)", RNS.prettyhexrep(self.dest.hash), self.display_name)
        self.announce()
        threading.Thread(target=self._housekeeping, name="housekeeping", daemon=True).start()

    def _load_identity(self) -> RNS.Identity:
        path = os.path.join(self.state_dir, "identity")
        if os.path.exists(path):
            identity = RNS.Identity.from_file(path)
            if identity:
                return identity
            log.warning("identity file unreadable, creating a new one")
        identity = RNS.Identity()
        identity.to_file(path)
        os.chmod(path, 0o600)
        log.info("created new identity")
        return identity

    def _load_peers(self) -> None:
        path = os.path.join(self.state_dir, "peers.json")
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.peers = {bytes.fromhex(k): v for k, v in data.items()}
        except (OSError, ValueError) as e:
            log.warning("could not load peers.json: %s", e)

    def _save_peers(self) -> None:
        path = os.path.join(self.state_dir, "peers.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k.hex(): v for k, v in self.peers.items()}, f, indent=1)
        os.replace(tmp, path)
        self.history.write_peers(self.peers)

    # ------------------------------------------------------------- queries

    @property
    def hash(self) -> bytes:
        return self.dest.hash if self.dest else bytes(p.HASH_LEN)

    def flags(self) -> int:
        f = 0
        if self.rns is not None:
            f |= p.STATE_RNS_UP
            for iface in list(RNS.Transport.interfaces):
                if "RNode" in type(iface).__name__ and getattr(iface, "online", False):
                    f |= p.STATE_RNODE_ONLINE
                    break
        if self.router is not None and self.router.get_outbound_propagation_node():
            f |= p.STATE_PROPAGATION
        return f

    def peer_name(self, h: bytes) -> str:
        info = self.peers.get(h)
        return info["name"] if info and info.get("name") else h.hex()[:8]

    def peer_flags(self, h: bytes) -> int:
        return p.PEER_HAS_PATH if RNS.Transport.has_path(h) else 0

    def peer_frames(self) -> list[bytes]:
        return [p.peer(h, self.peer_flags(h), self.peer_name(h)) for h in self.peers]

    # ------------------------------------------------------------ commands

    def announce(self) -> None:
        if self.router and self.dest:
            self.router.announce(self.dest.hash)
            self._last_announce = time.time()
            log.info("announced")

    def set_name(self, name: str) -> None:
        name = name.strip() or self.display_name
        self.display_name = name
        if self.dest:
            self.dest.display_name = name
        with open(os.path.join(self.state_dir, "name"), "w", encoding="utf-8") as f:
            f.write(name + "\n")
        self.announce()

    def send(self, ref: int, dest_hash: bytes, text: str) -> None:
        """Blocking; call from a worker thread. Emits DELIVERY frames as it goes."""
        self.on_event(p.delivery(ref, p.DELIVERY_SENDING))
        identity = RNS.Identity.recall(dest_hash)
        if identity is None:
            log.info("no identity for %s, requesting path", dest_hash.hex()[:8])
            RNS.Transport.request_path(dest_hash)
            deadline = time.time() + self.PATH_TIMEOUT
            while time.time() < deadline and RNS.Identity.recall(dest_hash) is None:
                time.sleep(0.5)
            identity = RNS.Identity.recall(dest_hash)
        if identity is None:
            log.warning("no path to %s", dest_hash.hex()[:8])
            self.on_event(p.delivery(ref, p.DELIVERY_FAILED))
            return
        dest = RNS.Destination(identity, RNS.Destination.OUT, RNS.Destination.SINGLE, LXMF.APP_NAME, "delivery")
        msg = LXMF.LXMessage(dest, self.dest, text)
        msg.register_delivery_callback(lambda m, r=ref: self._finish(r, p.DELIVERY_DELIVERED))
        msg.register_failed_callback(lambda m, r=ref: self._finish(r, p.DELIVERY_FAILED))
        with self._pending_lock:
            self._pending[ref] = msg
        self.router.handle_outbound(msg)
        self.history.append(dest_hash, self.display_name, text)
        if dest_hash not in self.peers:
            self.peers[dest_hash] = {"name": "", "seen": time.time()}
            self._save_peers()

    def _finish(self, ref: int, state: int) -> None:
        with self._pending_lock:
            self._pending.pop(ref, None)
        self.on_event(p.delivery(ref, state))

    # ------------------------------------------------------------ callbacks

    def _on_lxmf_delivery(self, message: LXMF.LXMessage) -> None:
        src = message.source_hash
        text = message.content_as_string() or ""
        ts = message.timestamp or time.time()
        lt = time.localtime(ts)
        if src not in self.peers:
            self.peers[src] = {"name": "", "seen": time.time()}
            self._save_peers()
        else:
            self.peers[src]["seen"] = time.time()
        log.info("message from %s (%d bytes)", self.peer_name(src), len(text))
        self.history.append(src, self.peer_name(src), text, ts)
        self.on_event(p.message(src, lt.tm_hour, lt.tm_min, text))

    def _on_announce(self, dest_hash: bytes, identity, app_data) -> None:
        name = LXMF.display_name_from_app_data(app_data) or ""
        info = self.peers.setdefault(dest_hash, {"name": "", "seen": 0})
        info["seen"] = time.time()
        if name:
            info["name"] = name
        self._save_peers()
        log.info("announce from %s", self.peer_name(dest_hash))
        self.on_event(p.peer(dest_hash, self.peer_flags(dest_hash), self.peer_name(dest_hash)))

    # ---------------------------------------------------------- background

    def _housekeeping(self) -> None:
        reported_sent: set[int] = set()
        while True:
            time.sleep(self.HOUSEKEEPING_INTERVAL)
            try:
                f = self.flags()
                if f != self._flags:
                    self._flags = f
                    self.on_event(p.state(f))
                with self._pending_lock:
                    pending = list(self._pending.items())
                for ref, msg in pending:
                    if msg.state == LXMF.LXMessage.SENT and ref not in reported_sent:
                        reported_sent.add(ref)
                        self.on_event(p.delivery(ref, p.DELIVERY_SENT))
                    elif msg.state in (LXMF.LXMessage.DELIVERED, LXMF.LXMessage.FAILED):
                        reported_sent.discard(ref)
                if time.time() - self._last_announce > self.ANNOUNCE_INTERVAL:
                    self.announce()
            except Exception:  # keep the thread alive whatever RNS throws
                log.exception("housekeeping")
