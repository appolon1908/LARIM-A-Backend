from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from larimia.realtime import hub

router = APIRouter()

@router.websocket("/bookings/{booking_id}")
async def booking_stream(websocket: WebSocket, booking_id: str):
    topic = f"booking:{booking_id}"
    await hub.connect(topic, websocket)
    try:
        await websocket.send_json({"type": "connected", "topic": topic})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(topic, websocket)

@router.websocket("/ops/dispatch")
async def ops_dispatch_stream(websocket: WebSocket):
    topic = "ops:dispatch"
    await hub.connect(topic, websocket)
    try:
        await websocket.send_json({"type": "connected", "topic": topic})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(topic, websocket)

@router.websocket("/providers/{provider_id}/offers")
async def provider_offer_stream(websocket: WebSocket, provider_id: str):
    topic = f"provider:{provider_id}:offers"
    await hub.connect(topic, websocket)
    try:
        await websocket.send_json({"type": "connected", "topic": topic})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(topic, websocket)
