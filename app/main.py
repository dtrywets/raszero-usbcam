"""RasZero USB camera web UI and RTSP control."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from stream import StreamConfig, StreamManager
from v4l2 import (
    get_current_format,
    get_device_info,
    list_controls,
    list_devices,
    list_formats,
    pick_capture_device,
    set_control,
    set_format,
)

DEVICE = os.environ.get("RASZERO_DEVICE", "")
streams = StreamManager()


class ControlUpdate(BaseModel):
    name: str
    value: str | int | bool


class FormatUpdate(BaseModel):
    width: int
    height: int
    pixel_format: str = "MJPG"


class StreamSettings(BaseModel):
    width: int | None = None
    height: int | None = None
    pixel_format: str | None = None
    fps: int | None = Field(default=None, ge=1, le=60)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    device = pick_capture_device(DEVICE or None)
    fmt = get_current_format(device)
    streams.update_config(
        device=device,
        width=fmt.get("width") or 640,
        height=fmt.get("height") or 480,
        pixel_format=fmt.get("pixel_format") or "MJPG",
    )
    yield
    streams.stop_all()


app = FastAPI(title="RasZero USB Cam", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    with open(path, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/devices")
async def api_devices() -> list[dict]:
    return list_devices()


@app.get("/api/camera")
async def api_camera() -> dict:
    device = streams.config.device
    return {
        "info": get_device_info(device),
        "format": get_current_format(device),
        "controls": [c.to_dict() for c in list_controls(device)],
        "formats": [f.to_dict() for f in list_formats(device)],
        "stream": streams.status(),
    }


@app.patch("/api/controls")
async def api_set_control(body: ControlUpdate) -> dict:
    try:
        set_control(streams.config.device, body.name, body.value)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "name": body.name, "value": body.value}


@app.post("/api/format")
async def api_set_format(body: FormatUpdate) -> dict:
    streams.stop_all()
    try:
        set_format(streams.config.device, body.width, body.height, body.pixel_format)
        streams.update_config(
            width=body.width,
            height=body.height,
            pixel_format=body.pixel_format,
        )
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"ok": True, "format": get_current_format(streams.config.device)}


@app.patch("/api/stream/settings")
async def api_stream_settings(body: StreamSettings) -> dict:
    streams.update_config(**body.model_dump(exclude_none=True))
    return streams.status()


@app.get("/api/stream/status")
async def api_stream_status() -> dict:
    return streams.status()


@app.post("/api/stream/rtsp/start")
async def api_rtsp_start() -> dict:
    proc = streams.start_rtsp()
    if proc.poll() is not None:
        err = (proc.stderr.read() if proc.stderr else b"").decode(errors="replace")
        raise HTTPException(500, f"RTSP-Stream start fehlgeschlagen: {err}")
    return streams.status()


@app.post("/api/stream/rtsp/stop")
async def api_rtsp_stop() -> dict:
    streams.stop_rtsp()
    return streams.status()


@app.get("/preview.mjpg")
async def preview_mjpg(request: Request) -> StreamingResponse:
    async def generate():
        async for chunk in streams.mjpeg_generator():
            if await request.is_disconnected():
                break
            yield chunk

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=ffmpeg",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.environ.get("RASZERO_HOST_BIND", "0.0.0.0"),
        port=int(os.environ.get("RASZERO_PORT", "8080")),
        reload=False,
    )
