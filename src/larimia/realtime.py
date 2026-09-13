import asyncio
from collections import defaultdict

from fastapi import WebSocket


class ConnectionHub:
    def __init__(self) -> None:
        self._topics: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, topic: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._topics[topic].add(websocket)

    async def disconnect(self, topic: str, websocket: WebSocket) -> None:
        async with self._lock:
            self._topics[topic].discard(websocket)

    async def publish(self, topic: str, payload: dict) -> None:
        dead: list[WebSocket] = []
        async with self._lock:
            sockets = list(self._topics.get(topic, set()))
        for ws in sockets:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._topics[topic].discard(ws)


hub = ConnectionHub()
