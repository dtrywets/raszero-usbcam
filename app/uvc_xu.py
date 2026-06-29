"""UVC Extension Unit discovery and control (inkl. Sonix GPIO/Leuchtring)."""

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

SONIX_SYS_UNIT = 3
SONIX_USR_UNIT = 4
SONIX_SWITCH_TAG = bytes([0x9A, 0x01])

# Sonix Extension Unit Selector-Namen (sonix_xu_ctrls.h)
SONIX_SYS_SELECTORS: dict[int, str] = {
    0x01: "ASIC_RW",
    0x03: "FLASH_CTRL",
    0x06: "FRAME_INFO",
    0x07: "H264_CTRL",
    0x08: "MJPG_CTRL",
    0x09: "OSD_CTRL",
    0x0A: "MOTION_DETECTION",
    0x0B: "IMG_SETTING",
}

SONIX_USR_SELECTORS: dict[int, str] = {
    0x01: "FRAME_INFO",
    0x02: "H264_CTRL",
    0x03: "MJPG_CTRL",
    0x04: "OSD_CTRL",
    0x05: "MOTION_DETECTION",
    0x06: "IMG_SETTING",
    0x07: "MULTI_STREAM",
    0x08: "GPIO_CTRL",
    0x09: "DYNAMIC_FPS",
}

SONIX_GPIO_UNIT = SONIX_USR_UNIT
SONIX_GPIO_SELECTOR = 0x08
SONIX_GPIO_SIZE = 11


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
    protocol: str = "uvc"

    @property
    def control_id(self) -> str:
        return f"u{self.unit}_s{self.selector}"

    @property
    def name(self) -> str:
        if self.unit == SONIX_SYS_UNIT:
            base = SONIX_SYS_SELECTORS.get(self.selector, f"SYS_{self.selector}")
            return f"sonix_sys_{base.lower()}"
        if self.unit == SONIX_USR_UNIT:
            base = SONIX_USR_SELECTORS.get(self.selector, f"USR_{self.selector}")
            return f"sonix_usr_{base.lower()}"
        return self.control_id

    @property
    def label(self) -> str:
        if self.unit == SONIX_SYS_UNIT:
            return SONIX_SYS_SELECTORS.get(self.selector, f"Unit3 Sel{self.selector}")
        if self.unit == SONIX_USR_UNIT:
            return SONIX_USR_SELECTORS.get(self.selector, f"Unit4 Sel{self.selector}")
        return self.control_id

    @property
    def readable(self) -> bool:
        return bool(self.info & 0x01)

    @property
    def writable(self) -> bool:
        return bool(self.info & 0x02)

    def to_dict(self) -> dict:
        return {
            "id": self.control_id,
            "name": self.name,
            "label": self.label,
            "unit": self.unit,
            "selector": self.selector,
            "size": self.size,
            "info": self.info,
            "protocol": self.protocol,
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


def is_sonix_device(device: str) -> bool:
    ids = usb_ids_for_device(device)
    return ids == ("0c45", "6537") if ids else False


def discover_extension_units(device: str) -> list[tuple[int, int]]:
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


def _is_sonix_unit(unit: int) -> bool:
    return unit in (SONIX_SYS_UNIT, SONIX_USR_UNIT)


def sonix_switch(device: str, unit: int, selector: int, size: int) -> None:
    payload = SONIX_SWITCH_TAG + bytes(max(size - 2, 0))
    _ioctl(device, unit, selector, UVC_SET_CUR, size, payload[:size])


def sonix_get(device: str, unit: int, selector: int, size: int) -> bytes:
    sonix_switch(device, unit, selector, size)
    return _ioctl(device, unit, selector, UVC_GET_CUR, size)


def sonix_set(device: str, unit: int, selector: int, data: bytes) -> bytes:
    sonix_switch(device, unit, selector, len(data))
    _ioctl(device, unit, selector, UVC_SET_CUR, len(data), data)
    return sonix_get(device, unit, selector, len(data))


def scan_controls(device: str) -> list[XUControl]:
    controls: list[XUControl] = []
    protocol = "sonix" if is_sonix_device(device) else "uvc"

    for unit_id, num_controls in discover_extension_units(device):
        max_sel = max(num_controls + 4, 32)
        for selector in range(1, max_sel + 1):
            try:
                length = int.from_bytes(_ioctl(device, unit_id, selector, UVC_GET_LEN, 2)[:2], "little")
                if length <= 0 or length > 64:
                    continue
                info = _ioctl(device, unit_id, selector, UVC_GET_INFO, 1)[0]
                if _is_sonix_unit(unit_id):
                    value = sonix_get(device, unit_id, selector, length)
                else:
                    value = _ioctl(device, unit_id, selector, UVC_GET_CUR, length)
                controls.append(
                    XUControl(
                        unit=unit_id,
                        selector=selector,
                        size=length,
                        info=info,
                        value=value,
                        protocol=protocol,
                    )
                )
            except OSError:
                continue
    return controls


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
    if _is_sonix_unit(unit):
        after = sonix_set(device, unit, selector, data)
    else:
        _ioctl(device, unit, selector, UVC_SET_CUR, len(data), data)
        after = _ioctl(device, unit, selector, UVC_GET_CUR, len(data))

    return {
        "id": ctrl_id,
        "label": meta.label,
        "unit": unit,
        "selector": selector,
        "value_bytes": list(after),
        "value_hex": after.hex(),
    }


def get_gpio(device: str) -> dict:
    raw = sonix_get(device, SONIX_GPIO_UNIT, SONIX_GPIO_SELECTOR, SONIX_GPIO_SIZE)
    return {
        "enable": raw[0],
        "output": raw[1],
        "input": raw[2],
        "raw": list(raw),
    }


def set_gpio(device: str, enable: int, output: int) -> dict:
    data = bytes([enable & 0xFF, output & 0xFF]) + bytes(SONIX_GPIO_SIZE - 2)
    sonix_set(device, SONIX_GPIO_UNIT, SONIX_GPIO_SELECTOR, data)
    return get_gpio(device)
