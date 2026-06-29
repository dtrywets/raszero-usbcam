# RasZero USB Cam

Web-Oberfläche zur Analyse und Steuerung einer UVC-Webcam am Raspberry Pi Zero. MJPEG-Livevorschau im Browser, V4L2-Parameter und Formate per API, RTSP-Streaming über MediaMTX und FFmpeg.

## Architektur

```
USB-Webcam (UVC)
       │
       ▼
  /dev/video0  ──►  v4l2-ctl / FFmpeg
       │
       ├─► FastAPI (uvicorn) :8080
       │     ├─ Web-UI (HTML/JS)
       │     ├─ /preview.mjpg (MJPEG)
       │     └─ REST-API (Geräte, Controls, Format, Stream)
       │
       └─► FFmpeg RTSP publish ──► MediaMTX :8554/cam
```

| Komponente | Rolle |
|------------|--------|
| **FastAPI** | Web-UI, REST-API, MJPEG-Preview via FFmpeg-Pipe |
| **FFmpeg** | V4L2-Capture, MJPEG-Stream und RTSP-Publishing |
| **MediaMTX** | RTSP-Server; Pfad `cam` für Publisher (FFmpeg) |
| **v4l2-ctl** | Geräteliste, Controls, Pixelformate |

## Hardware

- Raspberry Pi Zero (getestet: armv6, Pi Zero W)
- UVC-kompatible USB-Webcam (z. B. Logitech C270)
- Stabiles USB-Verkabelung; Pi Zero hat nur einen Micro-USB-Anschluss (OTG-Adapter oder Hub nötig)

Interne Pi-Kameras (`bcm2835-isp`) werden ignoriert; es wird die externe UVC-Kamera bevorzugt (`/dev/video0`).

## Installation

Auf dem Pi (als root oder mit `sudo`):

```bash
git clone git@github.com:dtrywets/raszero-usbcam.git
cd raszero-usbcam
sudo ./deploy/install.sh
```

Das Skript installiert Pakete (`ffmpeg`, `v4l-utils`, Python venv), MediaMTX (armv6), kopiert die App nach `/opt/raszero-usbcam`, legt systemd-Units an und startet die Dienste. Der ausführende Benutzer (`SUDO_USER` oder Repo-Besitzer) wird der `video`-Gruppe hinzugefügt.

Optional: Umgebungsvariablen in `/etc/systemd/system/raszero-cam.service` oder lokal über `.env` (siehe `.env.example`).

## URLs

| Dienst | URL |
|--------|-----|
| Web-UI | `http://<hostname>:8080/` |
| MJPEG-Preview | `http://<hostname>:8080/preview.mjpg` |
| RTSP-Stream | `rtsp://<hostname>:8554/cam` |

Standard-Hostname in der Doku: `raszero`. RTSP nutzt TCP (`rtsp_transport=tcp`).

## Projektstruktur

```
raszero-usbcam/
├── app/
│   ├── main.py          # FastAPI-App, REST-Endpunkte
│   ├── v4l2.py          # v4l2-ctl Wrapper (Geräte, Controls, Formate)
│   ├── stream.py        # FFmpeg MJPEG/RTSP StreamManager
│   ├── requirements.txt
│   └── static/          # Web-UI (HTML, CSS, JS)
├── config/
│   └── mediamtx.yml     # MediaMTX-Konfiguration (RTSP :8554, Pfad cam)
├── deploy/
│   ├── install.sh       # Installation auf dem Pi
│   ├── mediamtx.service
│   └── raszero-cam.service
├── .env.example         # Optionale Umgebungsvariablen (keine Secrets)
└── raszero-usbcam.code-workspace
```

## Lokale Entwicklung

```bash
cd app
python3 -m venv ../venv
../venv/bin/pip install -r requirements.txt
export RASZERO_DEVICE=/dev/video0
../venv/bin/uvicorn main:app --reload --host 0.0.0.0 --port 8080
```

MediaMTX muss für RTSP separat laufen (`mediamtx ../config/mediamtx.yml`).

## Lizenz

Projektcode ohne explizite Lizenz — Nutzung im privaten Kontext.
