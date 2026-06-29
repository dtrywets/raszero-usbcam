"""FFmpeg-based MJPEG preview and RTSP publishing."""

from __future__ import annotations

import asyncio
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


class StreamManager:
    def __init__(self, config: StreamConfig | None = None) -> None:
        self.config = config or StreamConfig()
        self._preview_proc: subprocess.Popen[bytes] | None = None
        self._rtsp_proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()

    @property
    def preview_active(self) -> bool:
        return self._preview_proc is not None and self._preview_proc.poll() is None

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

    def _stop(self, proc: subprocess.Popen[bytes] | None) -> None:
        if proc is None or proc.poll() is not None:
            return
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

    def stop_preview(self) -> None:
        with self._lock:
            self._stop(self._preview_proc)
            self._preview_proc = None

    def stop_rtsp(self) -> None:
        with self._lock:
            self._stop(self._rtsp_proc)
            self._rtsp_proc = None

    def stop_all(self) -> None:
        with self._lock:
            self._stop(self._preview_proc)
            self._preview_proc = None
            self._stop(self._rtsp_proc)
            self._rtsp_proc = None

    def start_preview(self) -> subprocess.Popen[bytes]:
        with self._lock:
            if self._preview_proc and self._preview_proc.poll() is None:
                return self._preview_proc
            self._stop(self._preview_proc)
            self._preview_proc = None
            cmd = [
                "ffmpeg",
                *self._input_args(preview=True),
                "-an",
                "-c:v", "copy",
                "-f", "mpjpeg",
                "pipe:1",
            ]
            self._preview_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return self._preview_proc

    def preview_error(self) -> str:
        proc = self._preview_proc
        if proc is None or proc.stderr is None:
            return ""
        return proc.stderr.read().decode(errors="replace").strip()

    def start_rtsp(self) -> subprocess.Popen[bytes]:
        with self._lock:
            if self._rtsp_proc and self._rtsp_proc.poll() is None:
                return self._rtsp_proc
            # Stop preview if camera may be exclusive
            if self.preview_active:
                self._stop(self._preview_proc)
                self._preview_proc = None

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
            for key, value in kwargs.items():
                if hasattr(self.config, key) and value is not None:
                    setattr(self.config, key, value)
            if self.preview_active or self.rtsp_active:
                self.stop_all()

    async def mjpeg_generator(self):
        """Yield MJPEG chunks for HTTP streaming."""
        proc = self.start_preview()
        assert proc.stdout is not None
        try:
            await asyncio.sleep(0.3)
            while True:
                if proc.poll() is not None:
                    break
                chunk = await asyncio.to_thread(proc.stdout.read, 65536)
                if not chunk:
                    if proc.poll() is not None:
                        break
                    await asyncio.sleep(0.05)
                    continue
                yield chunk
        finally:
            self.stop_preview()

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
            "rtsp_public_url": cfg.rtsp_url.replace("127.0.0.1", os.environ.get("RASZERO_HOST", "raszero")),
        }
