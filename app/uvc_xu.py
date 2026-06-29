"""UVC Extension Unit controls (vendor-specific, e.g. LED ring light)."""

from __future__ import annotations

import ctypes
import fcntl
import os
from dataclasses import dataclass

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
    name: str
    description: str

    def to_dict(self, value: bytes) -> dict:
        return {
            "unit": self.unit,
            "selector": self.selector,
            "name": self.name,
            "description": self.description,
            "size": self.size,
            "writable": bool(self.info & 0x02),
            "value_hex": value.hex(),
            "value_bytes": list(value),
        }


# Bekannte Controls für Microdia 0c45:6537 (USB Live camera)
KNOWN_CONTROLS = [
    XUControl(3, 1, 4, 0, "led_power", "Leuchtring Ein/Aus (Byte 2: 0=aus, 1=an)"),
    XUControl(4, 5, 24, 0, "device_config", "Geräte-Konfiguration (24 Byte)"),
]


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


def probe_controls(device: str) -> list[XUControl]:
    found: list[XUControl] = []
    for unit in (3, 4):
        for sel in range(1, 25):
            try:
                raw = _ioctl(device, unit, sel, UVC_GET_LEN, 2)
                length = int.from_bytes(raw[:2], "little")
                if length <= 0 or length > 64:
                    continue
                info = _ioctl(device, unit, sel, UVC_GET_INFO, 1)[0]
                known = next(
                    (c for c in KNOWN_CONTROLS if c.unit == unit and c.selector == sel),
                    None,
                )
                found.append(
                    XUControl(
                        unit=unit,
                        selector=sel,
                        size=length,
                        info=info,
                        name=known.name if known else f"xu_{unit}_{sel}",
                        description=known.description if known else f"Extension Unit {unit}, Selector {sel}",
                    )
                )
            except OSError:
                continue
    return found


def get_control(device: str, ctrl: XUControl) -> bytes:
    return _ioctl(device, ctrl.unit, ctrl.selector, UVC_GET_CUR, ctrl.size)


def set_control(device: str, ctrl: XUControl, data: bytes) -> None:
    if len(data) != ctrl.size:
        raise ValueError(f"Erwartet {ctrl.size} Bytes, erhalten {len(data)}")
    _ioctl(device, ctrl.unit, ctrl.selector, UVC_SET_CUR, ctrl.size, data)


def get_led(device: str) -> dict:
    ctrl = XUControl(3, 1, 4, 3, "led_power", "Leuchtring")
    value = get_control(device, ctrl)
    return {
        "on": value[2] != 0,
        "brightness": value[2],
        "raw": list(value),
    }


def set_led(device: str, on: bool, brightness: int | None = None) -> dict:
    ctrl = XUControl(3, 1, 4, 3, "led_power", "Leuchtring")
    current = bytearray(get_control(device, ctrl))
    current[2] = brightness if brightness is not None else (1 if on else 0)
    if not on and brightness is None:
        current[2] = 0
    set_control(device, ctrl, bytes(current))
    return get_led(device)
