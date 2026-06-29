"""FFmpeg-based MJPEG preview and RTSP publishing."""

from __future__ import annotations

import asyncio
import collections
import os
import signal
import subprocess
import threading
from dataclasses import dataclass


@dataclass
class StreamConfig:
    device: str = "/dev/video0"
    width: int = 640
    height: int = 480
    pixel_format: str = "MJPG"
    fps: int = 30
    preview_width: int = 640
    preview_height: int = 480
    preview_fps: int = 15
    rtsp_url: str = "rtsp://127.0.0.1:8554/cam"


def ffmpeg_input_format(pixel_format: str) -> str:
    """Map V4L2 fourcc names to ffmpeg -input_format values."""
    fmt = pixel_format.upper()
    if fmt in ("MJPG", "MJPEG"):
        return "mjpeg"
    if fmt == "YUYV":
        return "yuyv422"
    return pixel_format.lower()


class PreviewBroadcaster:
    """Hält ffmpeg dauerhaft warm und verteilt MJPEG an mehrere HTTP-Clients."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None
        self._running = False
        self._latest = collections.deque[bytes](maxlen=48)
        self._latest_event = threading.Event()
        self._subscribers: set[asyncio.Queue[bytes | None]] = set()
        self._input_args: list[str] = []

    def configure(self, input_args: list[str]) -> None:
        self._input_args = input_args

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        with self._lock:
            if self.active:
                return
            if not self._input_args:
                return
            cmd = [
                "ffmpeg",
                *self._input_args,
                "-an",
                "-c:v", "copy",
                "-f", "mpjpeg",
                "pipe:1",
            ]
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            self._running = True
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()

    def stop(self) -> None:
        with self._lock:
            self._running = False
            proc = self._proc
            self._proc = None
        if proc and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2)
        if self._reader and self._reader.is_alive():
            self._reader.join(timeout=2)
        self._reader = None
        self._notify(None)

    def _read_loop(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            while self._running and proc.poll() is None:
                chunk = proc.stdout.read(65536)
                if not chunk:
                    break
                with self._lock:
                    self._latest.append(chunk)
                    self._latest_event.set()
                self._notify(chunk)
        finally:
            self._running = False

    def _notify(self, chunk: bytes | None) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(chunk)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    pass

    async def subscribe(self):
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=32)
        self._subscribers.add(queue)

        with self._lock:
            for chunk in self._latest:
                try:
                    queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    break

        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            self._subscribers.discard(queue)


class StreamManager:
    def __init__(self, config: StreamConfig | None = None) -> None:
        self.config = config or StreamConfig()
        self._preview = PreviewBroadcaster()
        self._rtsp_proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    @property
    def preview_active(self) -> bool:
        return self._preview.active

    @property
    def rtsp_active(self) -> bool:
        return self._rtsp_proc is not None and self._rtsp_proc.poll() is None

    def _input_args(self, *, preview: bool = False) -> list[str]:
        cfg = self.config
        if preview:
            w, h, fps = cfg.preview_width, cfg.preview_height, cfg.preview_fps
        else:
            w, h, fps = cfg.width, cfg.height, cfg.fps
        return [
            "-hide_banner",
            "-loglevel", "error",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-f", "v4l2",
            "-input_format", ffmpeg_input_format(cfg.pixel_format),
            "-video_size", f"{w}x{h}",
            "-framerate", str(fps),
            "-i", cfg.device,
        ]

    def _stop_rtsp(self) -> None:
        proc = self._rtsp_proc
        self._rtsp_proc = None
        if proc is None or proc.poll() is not None:
            return
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

    def ensure_preview(self) -> None:
        if self.rtsp_active:
            return
        self._preview.configure(self._input_args(preview=True))
        self._preview.start()

    def stop_preview(self) -> None:
        self._preview.stop()

    def stop_rtsp(self) -> None:
        with self._lock:
            self._stop_rtsp()

    def stop_all(self) -> None:
        with self._lock:
            self.stop_preview()
            self._stop_rtsp()

    def start_rtsp(self) -> subprocess.Popen[bytes]:
        with self._lock:
            if self._rtsp_proc and self._rtsp_proc.poll() is None:
                return self._rtsp_proc
            self.stop_preview()
            cmd = [
                "ffmpeg",
                *self._input_args(preview=False),
                "-an",
                "-c:v", "copy",
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                self.config.rtsp_url,
            ]
            self._rtsp_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return self._rtsp_proc

    def update_config(self, **kwargs: object) -> None:
        with self._lock:
            restart_preview = False
            for key, value in kwargs.items():
                if hasattr(self.config, key) and value is not None:
                    setattr(self.config, key, value)
                    if key.startswith("preview_"):
                        restart_preview = True
            if self.rtsp_active:
                self.stop_all()
            elif restart_preview and self.preview_active:
                self.stop_preview()

    async def mjpeg_generator(self):
        """Clients hängen an dauerhaft laufendem ffmpeg."""
        self.ensure_preview()
        async for chunk in self._preview.subscribe():
            yield chunk

    def status(self) -> dict:
        cfg = self.config
        return {
            "preview_active": self.preview_active,
            "rtsp_active": self.rtsp_active,
            "device": cfg.device,
            "width": cfg.width,
            "height": cfg.height,
            "pixel_format": cfg.pixel_format,
            "fps": cfg.fps,
            "preview_width": cfg.preview_width,
            "preview_height": cfg.preview_height,
            "preview_fps": cfg.preview_fps,
            "rtsp_url": cfg.rtsp_url,
            "rtsp_public_url": cfg.rtsp_url.replace(
                "127.0.0.1", os.environ.get("RASZERO_HOST", "raszero")
            ),
        }
