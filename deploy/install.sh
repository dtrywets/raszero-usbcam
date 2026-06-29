#!/usr/bin/env bash
set -euo pipefail

# Install RasZero USB cam stack on the Pi Zero.
# Run on raszero as root or with sudo.

APP_DIR="/opt/raszero-usbcam"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
MEDIAMTX_VERSION="1.15.3"
PI_USER="${SUDO_USER:-$(stat -c '%U' "$REPO_DIR")}"
PI_GROUP="$(id -gn "$PI_USER" 2>/dev/null || echo "$PI_USER")"
PI_HOST="$(hostname -s 2>/dev/null || echo raszero)"

if [[ -z "$PI_USER" || "$PI_USER" == "root" ]]; then
  PI_USER="$(logname 2>/dev/null || whoami)"
fi
echo "==> Zielbenutzer: ${PI_USER}"

echo "==> Pakete installieren"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends \
  ffmpeg \
  v4l-utils \
  python3-venv \
  python3-pip \
  curl \
  ca-certificates

echo "==> MediaMTX ${MEDIAMTX_VERSION} (armv6) installieren"
if [[ -x /usr/local/bin/mediamtx ]]; then
  echo "    bereits installiert: $(/usr/local/bin/mediamtx --version 2>&1 | head -1 || true)"
else
  ARCHIVE="mediamtx_v${MEDIAMTX_VERSION}_linux_armv6.tar.gz"
  URL="https://github.com/bluenviron/mediamtx/releases/download/v${MEDIAMTX_VERSION}/${ARCHIVE}"
  WORK="/var/tmp/mediamtx-install"
  rm -rf "$WORK"
  install -d -m 755 "$WORK"
  curl -fsSL "$URL" -o "$WORK/${ARCHIVE}"
  tar -xzf "$WORK/${ARCHIVE}" -C "$WORK" mediamtx
  install -m 755 "$WORK/mediamtx" /usr/local/bin/mediamtx
  rm -rf "$WORK"
fi

echo "==> App nach ${APP_DIR} deployen"
install -d -m 755 "$APP_DIR"
rsync -a --delete \
  --exclude venv \
  --exclude __pycache__ \
  "$REPO_DIR/app/" "$APP_DIR/app/"
install -d -m 755 /etc/raszero-usbcam
install -m 644 "$REPO_DIR/config/mediamtx.yml" /etc/raszero-usbcam/mediamtx.yml

echo "==> Python venv"
rm -rf "$APP_DIR/venv"
python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip wheel
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/app/requirements.txt"

echo "==> User ${PI_USER} in video-Gruppe"
usermod -aG video "$PI_USER" || true

echo "==> systemd Units (User=${PI_USER})"
sed "s/^User=.*/User=${PI_USER}/" "$REPO_DIR/deploy/mediamtx.service" \
  > /etc/systemd/system/mediamtx.service
sed "s/^User=.*/User=${PI_USER}/" "$REPO_DIR/deploy/raszero-cam.service" \
  > /etc/systemd/system/raszero-cam.service
chmod 644 /etc/systemd/system/mediamtx.service /etc/systemd/system/raszero-cam.service
systemctl daemon-reload
systemctl enable mediamtx.service raszero-cam.service
systemctl restart mediamtx.service
systemctl restart raszero-cam.service

echo "==> Fertig"
echo "Web-UI:  http://${PI_HOST}:8080/"
echo "RTSP:    rtsp://${PI_HOST}:8554/cam"
systemctl --no-pager --full status mediamtx.service raszero-cam.service | sed -n '1,12p'
