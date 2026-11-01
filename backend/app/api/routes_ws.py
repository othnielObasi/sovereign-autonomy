from __future__ import annotations

import asyncio
import json
import logging
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("app.ws")
router = APIRouter()


class WsHub:
    def __init__(self):
        self._clients: Dict[str, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()
        # Keep recent broadcasts per run so late-connecting clients catch up
        self._recent: Dict[str, list] = {}  # run_id → last N messages
        self._RECENT_MAX = 30

    async def connect(self, run_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.setdefault(run_id, set()).add(ws)
            replay = list(self._recent.get(run_id, []))
        # Replay recent messages so late joiners see planning progress / status
        for msg in replay:
            try:
                await ws.send_text(msg)
            except Exception:
                break

    async def disconnect(self, run_id: str, ws: WebSocket) -> None:
        async with self._lock:
            if run_id in self._clients and ws in self._clients[run_id]:
                self._clients[run_id].remove(ws)
                if not self._clients[run_id]:
                    self._clients.pop(run_id, None)

    async def broadcast(self, run_id: str, message: dict) -> None:
        # Copy references to avoid mutation while iterating
        payload = json.dumps(message, ensure_ascii=False)
        async with self._lock:
            clients = list(self._clients.get(run_id, set()))
            # Store for replay to late-connecting clients (skip high-frequency telemetry)
            kind = message.get("kind", "?")
            if kind != "telemetry":
                buf = self._recent.setdefault(run_id, [])
                buf.append(payload)
                if len(buf) > self._RECENT_MAX:
                    self._recent[run_id] = buf[-self._RECENT_MAX:]
        if not clients:
            return

        logger.debug("Broadcasting %s to %d client(s) for %s", kind, len(clients), run_id)
        dead = []
        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        # Clean dead sockets
        for ws in dead:
            await self.disconnect(run_id, ws)


hub = WsHub()


@router.websocket("/ws/runs/{run_id}")
async def ws_run(run_id: str, ws: WebSocket):
    logger.info("WS connect: run=%s", run_id)
    await hub.connect(run_id, ws)

    # Watching a run never restarts it: a robot only moves after an explicit
    # start or resume by an operator.

    try:
        while True:
            _ = await ws.receive_text()
    except WebSocketDisconnect:
        logger.info("WS disconnect: run=%s", run_id)
        await hub.disconnect(run_id, ws)
    except Exception:
        logger.info("WS error/disconnect: run=%s", run_id)
        await hub.disconnect(run_id, ws)
