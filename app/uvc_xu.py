"""UVC Extension Unit discovery and control."""

from __future__ import annotations

import ctypes
import fcntl
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

UVCIOC_CTRL_QUERY = 0xC00C7521
UVC_GET_CUR = 0x81
UVC_GET_LEN = 0x85
UVC_GET_INFO = 0x86
UVC_SET_CUR = 0x01


class _XUQuery(ctypes.Structure):
    _fields_ = [
        ("unit", ctypes.c_uint8),
        ("selector", ctypes.c_uint8),
        ("query", ctypes.c_uint8),
        ("size", ctypes.c_uint16),
        ("data", ctypes.c_void_p),
    ]


@dataclass
class XUControl:
    unit: int
    selector: int
    size: int
    info: int
    value: bytes = field(default_factory=bytes)

    @property
    def control_id(self) -> str:
        return f"u{self.unit}_s{self.selector}"

    @property
    def readable(self) -> bool:
        return bool(self.info & 0x01)

    @property
    def writable(self) -> bool:
        return bool(self.info & 0x02)

    def to_dict(self) -> dict:
        return {
            "id": self.control_id,
            "unit": self.unit,
            "selector": self.selector,
            "size": self.size,
            "info": self.info,
            "readable": self.readable,
            "writable": self.writable,
            "value_bytes": list(self.value),
            "value_hex": self.value.hex(),
        }


def _device_sysfs(device: str) -> Path:
    name = Path(device).name
    return Path(f"/sys/class/video4linux/{name}/device").resolve()


def usb_ids_for_device(device: str) -> tuple[str, str] | None:
    path = _device_sysfs(device)
    for _ in range(6):
        try:
            vid = (path / "idVendor").read_text().strip()
            pid = (path / "idProduct").read_text().strip()
            return vid, pid
        except OSError:
            if path.parent == path:
                break
            path = path.parent
    return None


def discover_extension_units(device: str) -> list[tuple[int, int]]:
    """Return [(unit_id, num_controls), ...] from USB descriptors."""
    ids = usb_ids_for_device(device)
    if not ids:
        return _fallback_units(device)

    vid, pid = ids
    try:
        out = subprocess.check_output(
            ["lsusb", "-v", "-d", f"{vid}:{pid}"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return _fallback_units(device)

    units: list[tuple[int, int]] = []
    for match in re.finditer(
        r"bDescriptorSubtype\s+6 \(EXTENSION_UNIT\)\s+"
        r"bUnitID\s+(\d+)\s+"
        r"guidExtensionCode\s+\{[^}]+\}\s+"
        r"bNumControls\s+(\d+)",
        out,
    ):
        units.append((int(match.group(1)), int(match.group(2))))
    return units or _fallback_units(device)


def _fallback_units(device: str) -> list[tuple[int, int]]:
    """Probe common unit IDs if lsusb parsing fails."""
    found: list[tuple[int, int]] = []
    for unit in range(1, 16):
        try:
            _ioctl(device, unit, 1, UVC_GET_LEN, 2)
            found.append((unit, 32))
        except OSError:
            continue
    return found


def _ioctl(device: str, unit: int, selector: int, query: int, size: int, data: bytes = b"") -> bytes:
    fd = os.open(device, os.O_RDWR)
    try:
        buf = (ctypes.c_uint8 * 64)()
        if data:
            buf[: len(data)] = data
        req = _XUQuery(
            unit=unit,
            selector=selector,
            query=query,
            size=size,
            data=ctypes.cast(buf, ctypes.c_void_p),
        )
        fcntl.ioctl(fd, UVCIOC_CTRL_QUERY, req)
        return bytes(buf[:size])
    finally:
        os.close(fd)


def scan_controls(device: str) -> list[XUControl]:
    """Scan all UVC extension unit controls for a device."""
    controls: list[XUControl] = []
    units = discover_extension_units(device)

    for unit_id, num_controls in units:
        max_sel = max(num_controls + 4, 32)
        for selector in range(1, max_sel + 1):
            try:
                length = int.from_bytes(_ioctl(device, unit_id, selector, UVC_GET_LEN, 2)[:2], "little")
                if length <= 0 or length > 64:
                    continue
                info = _ioctl(device, unit_id, selector, UVC_GET_INFO, 1)[0]
                value = _ioctl(device, unit_id, selector, UVC_GET_CUR, length)
                controls.append(
                    XUControl(
                        unit=unit_id,
                        selector=selector,
                        size=length,
                        info=info,
                        value=value,
                    )
                )
            except OSError:
                continue
    return controls


def get_control(device: str, unit: int, selector: int, size: int) -> bytes:
    return _ioctl(device, unit, selector, UVC_GET_CUR, size)


def set_control(device: str, unit: int, selector: int, data: bytes) -> bytes:
    _ioctl(device, unit, selector, UVC_SET_CUR, len(data), data)
    return _ioctl(device, unit, selector, UVC_GET_CUR, len(data))


def set_control_bytes(device: str, unit: int, selector: int, value_bytes: list[int]) -> dict:
    controls = {c.control_id: c for c in scan_controls(device)}
    ctrl_id = f"u{unit}_s{selector}"
    meta = controls.get(ctrl_id)
    if meta is None:
        raise ValueError(f"Control {ctrl_id} nicht gefunden")
    if not meta.writable:
        raise ValueError(f"Control {ctrl_id} ist schreibgeschützt")
    if len(value_bytes) != meta.size:
        raise ValueError(f"Control {ctrl_id} erwartet {meta.size} Bytes")
    data = bytes(v & 0xFF for v in value_bytes)
    after = set_control(device, unit, selector, data)
    return {
        "id": ctrl_id,
        "unit": unit,
        "selector": selector,
        "value_bytes": list(after),
        "value_hex": after.hex(),
    }
