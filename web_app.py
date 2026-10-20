"""WhyNot-HushTalk Web Chat Application Backend.

Provides a FastAPI server with REST endpoints and WebSockets for real-time
covert timing-channel chat, telemetry streaming, and configuration management.
"""

import asyncio
from contextlib import asynccontextmanager
import os
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from hushtalk_node import HushTalkNode
import hushtalk_core as hc

# Global singleton node
node = HushTalkNode(
    target_ip="127.0.0.1",
    port=9999,
    listen_ip="0.0.0.0",
    key=None,
    profile="fast",
    transport="udp",
)
node.start()

# WebSocket active client registry
active_connections: List[WebSocket] = []
event_loop: Optional[asyncio.AbstractEventLoop] = None


def broadcast_node_event(event: Dict[str, Any]) -> None:
    """Callback hooked into HushTalkNode to relay events to WebSockets."""
    global event_loop
    if event_loop and event_loop.is_running():
        asyncio.run_coroutine_threadsafe(_async_broadcast(event), event_loop)


async def _async_broadcast(event: Dict[str, Any]) -> None:
    for ws in list(active_connections):
        try:
            await ws.send_json(event)
        except Exception:
            if ws in active_connections:
                active_connections.remove(ws)


node.subscribe(broadcast_node_event)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global event_loop
    event_loop = asyncio.get_running_loop()
    yield


app = FastAPI(
    title="WhyNot-HushTalk Covert Chat Suite",
    description="Timing-channel covert communication engine by Abduallah Al Raju",
    version="2.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic Request Models
class SendMessageRequest(BaseModel):
    message: str


class ConfigRequest(BaseModel):
    target_ip: Optional[str] = None
    port: Optional[int] = None
    listen_port: Optional[int] = None
    key: Optional[str] = None
    profile: Optional[str] = None
    transport: Optional[str] = None
    payload_style: Optional[str] = None
    auto_ack: Optional[bool] = None


class DemoRequest(BaseModel):
    message: str = "HELLO FROM HUSHTALK"
    profile: str = "fast"
    key: Optional[str] = None


# REST API Endpoints
@app.get("/api/status")
def get_status():
    status = node.get_status()
    status["available_profiles"] = list(hc.PROFILES.keys())
    return status


@app.post("/api/config")
def update_config(req: ConfigRequest):
    updated = node.configure(
        target_ip=req.target_ip,
        port=req.port,
        listen_port=req.listen_port,
        key=req.key,
        profile=req.profile,
        transport=req.transport,
        payload_style=req.payload_style,
        auto_ack=req.auto_ack,
    )
    return {"status": "success", "config": updated}


@app.get("/api/messages")
def get_messages():
    return {"messages": node.get_messages()}


@app.post("/api/messages")
def post_message(req: SendMessageRequest):
    text = req.message.strip()
    if not text:
        return JSONResponse(status_code=400, content={"error": "Message cannot be empty"})
    msg = node.send_chat_message(text)
    return {"status": "enqueued", "message_id": msg.id}


@app.get("/api/telemetry")
def get_telemetry():
    return node.get_telemetry()


@app.post("/api/demo")
def run_demo(req: DemoRequest):
    sim = hc.simulate_run(
        message=req.message,
        key=req.key,
        profile=req.profile,
    )
    return sim


# WebSocket Endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    active_connections.append(websocket)
    try:
        # Send initial state snapshot
        await websocket.send_json({"type": "init", "status": node.get_status(), "messages": node.get_messages()})
        while True:
            # Keepalive / incoming ping
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        if websocket in active_connections:
            active_connections.remove(websocket)
    except Exception:
        if websocket in active_connections:
            active_connections.remove(websocket)


# Static File Serving
web_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
if os.path.exists(web_dir):
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(web_dir, "index.html"))
