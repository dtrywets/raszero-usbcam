"""V4L2 camera control via v4l2-ctl."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass


CTRL_LINE = re.compile(
    r"^\s*(?P<name>\S+)\s+0x[0-9a-f]+\s+\((?P<type>\w+)\)\s+:"
    r"(?: min=(?P<min>-?\d+) max=(?P<max>-?\d+) step=(?P<step>\d+))?"
    r"(?: default=(?P<default>-?\d+))?"
    r" value=(?P<value>[^\s]+(?:\s+\([^)]+\))?)"
    r"(?: flags=(?P<flags>[^\s]+))?"
)

FORMAT_SIZE = re.compile(
    r"^\s+Size: Discrete (\d+)x(\d+)\s*$"
)
FORMAT_INTERVAL = re.compile(
    r"^\s+Interval: Discrete ([\d.]+)s \(([\d.]+) fps\)\s*$"
)
FORMAT_PIXEL = re.compile(
    r"^\s+\[(\d+)\]: '(\w+)' \(([^)]+)\)\s*$"
)


@dataclass
class MenuOption:
    value: int
    label: str


@dataclass
class Control:
    name: str
    type: str
    value: str
    minimum: int | None = None
    maximum: int | None = None
    step: int | None = None
    default: int | None = None
    flags: str = ""
    inactive: bool = False
    menu_options: list[MenuOption] | None = None

    def to_dict(self) -> dict:
        raw = self.value.split()[0]
        parsed: str | int | bool = raw
        if self.type == "bool":
            parsed = raw == "1"
        elif self.type in ("int", "menu"):
            try:
                parsed = int(raw)
            except ValueError:
                parsed = raw
        return {
            "name": self.name,
            "type": self.type,
            "value": parsed,
            "display": self.value,
            "min": self.minimum,
            "max": self.maximum,
            "step": self.step,
            "default": self.default,
            "inactive": self.inactive,
            "flags": self.flags,
            "menu_options": [
                {"value": o.value, "label": o.label}
                for o in (self.menu_options or [])
            ],
        }


@dataclass
class FormatOption:
    pixel_format: str
    description: str
    width: int
    height: int
    fps: float

    def to_dict(self) -> dict:
        return {
            "pixel_format": self.pixel_format,
            "description": self.description,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "label": f"{self.width}x{self.height} {self.pixel_format} @ {self.fps:.0f}fps",
        }


def run_v4l2(device: str, *args: str) -> str:
    result = subprocess.run(
        ["v4l2-ctl", "-d", device, *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "v4l2-ctl failed")
    return result.stdout


def list_devices() -> list[dict]:
    output = subprocess.run(
        ["v4l2-ctl", "--list-devices"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    devices: list[dict] = []
    video0: dict | None = None
    current_name = ""
    for line in output.splitlines():
        if not line.strip():
            continue
        if not line.startswith("\t"):
            current_name = line.rstrip(":")
            continue
        path = line.strip()
        if not path.startswith("/dev/video"):
            continue
        if "bcm2835" in current_name.lower():
            continue
        entry = {"name": current_name, "device": path}
        if path == "/dev/video0":
            video0 = entry
        else:
            devices.append(entry)
    if video0 is not None:
        devices.insert(0, video0)
    return devices


def pick_capture_device(preferred: str | None = None) -> str:
    if preferred:
        return preferred
    devices = list_devices()
    if not devices:
        raise RuntimeError("Keine V4L2-Kamera gefunden")
    return devices[0]["device"]


def get_device_info(device: str) -> dict:
    output = run_v4l2(device, "--all")
    card = re.search(r"Card type\s+:\s+(.+)", output)
    driver = re.search(r"Driver name\s+:\s+(.+)", output)
    bus = re.search(r"Bus info\s+:\s+(.+)", output)
    width = re.search(r"Width/Height\s+:\s+(\d+)/(\d+)", output)
    fmt = re.search(r"Pixel Format\s+:\s+'(\w+)'", output)
    return {
        "device": device,
        "card": card.group(1).strip() if card else "",
        "driver": driver.group(1).strip() if driver else "",
        "bus_info": bus.group(1).strip() if bus else "",
        "width": int(width.group(1)) if width else None,
        "height": int(width.group(2)) if width else None,
        "pixel_format": fmt.group(1) if fmt else "",
    }


MENU_OPTION = re.compile(r"^\s+(\d+):\s+(.+)$")


def list_controls(device: str) -> list[Control]:
    output = run_v4l2(device, "--list-ctrls")
    controls: list[Control] = []
    current: Control | None = None

    for line in output.splitlines():
        menu_match = MENU_OPTION.match(line)
        if menu_match and current and current.type == "menu":
            if current.menu_options is None:
                current.menu_options = []
            current.menu_options.append(
                MenuOption(int(menu_match.group(1)), menu_match.group(2).strip())
            )
            continue

        match = CTRL_LINE.match(line)
        if not match:
            continue
        groups = match.groupdict()
        flags = groups.get("flags") or ""
        current = Control(
            name=groups["name"],
            type=groups["type"],
            value=groups["value"].strip(),
            minimum=int(groups["min"]) if groups.get("min") else None,
            maximum=int(groups["max"]) if groups.get("max") else None,
            step=int(groups["step"]) if groups.get("step") else None,
            default=int(groups["default"]) if groups.get("default") else None,
            flags=flags,
            inactive="inactive" in flags,
        )
        controls.append(current)
    return controls


def set_control(device: str, name: str, value: str | int | bool) -> None:
    if isinstance(value, bool):
        value = "1" if value else "0"
    run_v4l2(device, f"--set-ctrl={name}={value}")


def list_formats(device: str) -> list[FormatOption]:
    output = run_v4l2(device, "--list-formats-ext")
    formats: list[FormatOption] = []
    current_fmt = ""
    current_desc = ""
    current_w = 0
    current_h = 0

    for line in output.splitlines():
        fmt_match = FORMAT_PIXEL.match(line)
        if fmt_match:
            current_fmt = fmt_match.group(2)
            current_desc = fmt_match.group(3)
            continue
        size_match = FORMAT_SIZE.match(line)
        if size_match:
            current_w = int(size_match.group(1))
            current_h = int(size_match.group(2))
            continue
        interval_match = FORMAT_INTERVAL.match(line)
        if interval_match and current_fmt:
            fps = float(interval_match.group(2))
            formats.append(
                FormatOption(current_fmt, current_desc, current_w, current_h, fps)
            )
    return formats


def get_current_format(device: str) -> dict:
    info = get_device_info(device)
    return {
        "width": info["width"],
        "height": info["height"],
        "pixel_format": info["pixel_format"],
    }


def set_format(device: str, width: int, height: int, pixel_format: str) -> None:
    run_v4l2(
        device,
        f"--set-fmt-video=width={width},height={height},pixelformat={pixel_format}",
    )
