# raszero-usbcam

USB-Webcam-Verwaltung und RTSP-Streaming für einen **Raspberry Pi Zero** mit angeschlossener UVC-Kamera.

Das Projekt liefert eine schlanke Web-Oberfläche zur **Analyse und Steuerung** aller V4L2-Parameter (Helligkeit, Belichtung, Auflösung, …) mit **flinker MJPEG-Livevorschau** sowie einen **RTSP-Stream** für Integration in NVRs, Home Assistant oder VLC.

## Sinn & Ziel

| Aufgabe | Lösung |
|---------|--------|
| Kamera erkennen & analysieren | `v4l2-ctl` via REST-API — Formate, Controls, Geräteinfos; **mehrere USB-Cams**, Umschalten in der Web-UI |
| Parameter live anpassen | Web-UI mit Slidern, Checkboxen und Menüs |
| Schnelle Vorschau im Browser | MJPEG-Stream direkt aus der Kamera (`ffmpeg -c copy`, kein Re-Encode) |
| Dauerhafter Netzwerk-Stream | `ffmpeg` → **MediaMTX** → `rtsp://<host>:8554/cam` |

Der Pi Zero hat wenig RAM (~512 MB). Deshalb: MJPEG passthrough statt Software-Encoding, schlanke Python-App (FastAPI), RTSP nur on-demand.

## Architektur

```
USB-Kamera (/dev/video0)
    │
    ├── v4l2-ctl ──► FastAPI REST-API ──► Web-UI (:8080)
    │
    ├── ffmpeg (copy) ──► MJPEG Preview (/preview.mjpg)
    │
    └── ffmpeg (copy) ──► MediaMTX (:8554) ──► RTSP /cam
```

## Hardware

- Raspberry Pi Zero (W/WH), Raspbian/Debian armhf
- Beliebige **UVC**-Webcam (getestet: Microdia USB Live camera)
- USB-Ethernet-Adapter empfohlen (RTL8152) — WLAN auf dem Zero ist möglich, aber langsamer

## Installation

Repo auf den Pi kopieren (oder klonen), dann:

```bash
sudo bash deploy/install.sh
```

Das Skript installiert `ffmpeg`, `v4l2-utils`, MediaMTX (armv6-Binary), legt ein Python-venv an und aktiviert zwei systemd-Dienste:

| Dienst | Beschreibung |
|--------|--------------|
| `mediamtx.service` | RTSP-Server auf Port 8554 |
| `raszero-cam.service` | Web-UI & Kamera-Steuerung auf Port 8080 |

Der ausführende Benutzer wird automatisch erkannt (`SUDO_USER` oder Repo-Besitzer) und der `video`-Gruppe hinzugefügt.

### Update nach Code-Änderung

```bash
rsync -az --exclude venv --exclude __pycache__ ./ raszero:~/raszero-usbcam/
ssh raszero 'sudo bash ~/raszero-usbcam/deploy/install.sh'
```

## Nutzung

| Endpoint | URL |
|----------|-----|
| Web-UI | `http://raszero:8080/` |
| MJPEG-Vorschau | `http://raszero:8080/preview.mjpg` |
| Kamera-API | `http://raszero:8080/api/camera` |
| RTSP-Stream | `rtsp://raszero:8554/cam` (erst in UI starten) |

RTSP in VLC öffnen: *Medien → Netzwerkstream öffnen* → URL einfügen.

## Projektstruktur

```
raszero-usbcam/
├── app/
│   ├── main.py          # FastAPI — REST-API & Web-UI
│   ├── v4l2.py          # V4L2-Steuerung via v4l2-ctl
│   ├── stream.py        # ffmpeg MJPEG-Preview & RTSP
│   ├── requirements.txt
│   └── static/          # Web-Frontend
├── config/
│   └── mediamtx.yml     # MediaMTX-Konfiguration
├── deploy/
│   ├── install.sh       # Installation auf dem Pi
│   ├── mediamtx.service
│   └── raszero-cam.service
└── raszero-usbcam.code-workspace
```

## Konfiguration

Umgebungsvariablen (in `raszero-cam.service`):

| Variable | Default | Bedeutung |
|----------|---------|-----------|
| `RASZERO_DEVICE` | `/dev/video0` | Start-Kamera (Capture-Device); weitere Cams in der Web-UI wählbar |
| `RASZERO_PORT` | `8080` | Web-UI-Port |
| `RASZERO_HOST` | `raszero` | Hostname in RTSP-URLs |
| `RASZERO_OSD_TIMESTAMP` | `1` | Datum/Uhrzeit links oben (`0` zum Abschalten) |
| `RASZERO_OSD_TIMESTAMP_FORMAT` | `%Y-%m-%d %H:%M:%S` | strftime-Format für ffmpeg drawtext |

Keine Secrets nötig — alles läuft im lokalen Netzwerk ohne Authentifizierung.

## Lizenz

MIT — frei verwendbar, ohne Garantie.
