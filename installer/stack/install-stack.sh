#!/bin/bash
# Install the Klipper stack on a bare Raspberry Pi OS: Klipper, Moonraker, Mainsail and nginx,
# laid out the way KIAUH does it (~/klipper, ~/klippy-env, ~/moonraker, ~/moonraker-env,
# ~/mainsail, ~/printer_data) so existing configs, tools and docs keep working.
#
#   KLIPPER_REF=867d73f0b MOONRAKER_REF=5b92e52 ./install-stack.sh
#
# Refs pin the exact versions to install; the branch is reset to them, so Moonraker's update
# manager still offers newer versions. Safe to run again. Runs as the printer user and uses
# sudo. This is the seed of the "bare printer" phase in docs/installer.md.

set -euo pipefail
KLIPPER_REF="${KLIPPER_REF:-origin/master}"
MOONRAKER_REF="${MOONRAKER_REF:-origin/master}"
PD="$HOME/printer_data"
say() { printf '\n== %s\n' "$*"; }

# clone_at <url> <dir> <branch> <ref>: clone if missing, then put <branch> at <ref>
clone_at() {
  local url="$1" dir="$2" branch="$3" ref="$4"
  [ -d "$dir/.git" ] || git clone -q "$url" "$dir"
  git -C "$dir" fetch -q origin
  git -C "$dir" checkout -q -B "$branch" "origin/$branch"
  git -C "$dir" reset -q --hard "$ref"
  echo "   $(basename "$dir") at $(git -C "$dir" describe --always --tags)"
}

say "printer_data layout"
mkdir -p "$PD"/{config,logs,gcodes,systemd,comms,database,backup}

say "Klipper ($KLIPPER_REF)"
clone_at https://github.com/Klipper3d/klipper "$HOME/klipper" master "$KLIPPER_REF"
[ -x "$HOME/klippy-env/bin/python" ] || python3 -m venv "$HOME/klippy-env"
"$HOME/klippy-env/bin/pip" install -q --upgrade pip
"$HOME/klippy-env/bin/pip" install -q -r "$HOME/klipper/scripts/klippy-requirements.txt"
[ -f "$PD/systemd/klipper.env" ] || cat > "$PD/systemd/klipper.env" <<EOF
KLIPPER_ARGS="$HOME/klipper/klippy/klippy.py $PD/config/printer.cfg -I $PD/comms/klippy.serial -l $PD/logs/klippy.log -a $PD/comms/klippy.sock"
EOF
sudo tee /etc/systemd/system/klipper.service >/dev/null <<EOF
[Unit]
Description=Klipper 3D Printer Firmware SV1
Documentation=https://www.klipper3d.org/
After=network-online.target
Wants=udev.target

[Install]
WantedBy=multi-user.target

[Service]
Type=simple
User=$USER
RemainAfterExit=yes
WorkingDirectory=$HOME/klipper
EnvironmentFile=$PD/systemd/klipper.env
ExecStart=$HOME/klippy-env/bin/python \$KLIPPER_ARGS
Restart=always
RestartSec=10
EOF

say "Moonraker ($MOONRAKER_REF)"
clone_at https://github.com/Arksine/moonraker "$HOME/moonraker" master "$MOONRAKER_REF"
# Moonraker's own installer handles its system packages, venv, service and PolicyKit rules
"$HOME/moonraker/scripts/install-moonraker.sh" -f -d "$PD" -c "$PD/config/moonraker.conf" -l "$PD/logs/moonraker.log" -z

say "Mainsail"
if [ ! -f "$HOME/mainsail/index.html" ]; then
  tmp="$(mktemp -d)"
  curl -fsSL -o "$tmp/mainsail.zip" https://github.com/mainsail-crew/mainsail/releases/latest/download/mainsail.zip
  mkdir -p "$HOME/mainsail" && unzip -q -o "$tmp/mainsail.zip" -d "$HOME/mainsail" && rm -rf "$tmp"
fi
clone_at https://github.com/mainsail-crew/mainsail-config "$HOME/mainsail-config" master origin/master
chmod o+x "$HOME"

say "nginx"
sudo tee /etc/nginx/conf.d/common_vars.conf >/dev/null <<'EOF'
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}
EOF
sudo tee /etc/nginx/conf.d/upstreams.conf >/dev/null <<'EOF'
upstream apiserver { ip_hash; server 127.0.0.1:7125; }
upstream mjpgstreamer1 { ip_hash; server 127.0.0.1:8080; }
upstream mjpgstreamer2 { ip_hash; server 127.0.0.1:8081; }
upstream mjpgstreamer3 { ip_hash; server 127.0.0.1:8082; }
upstream mjpgstreamer4 { ip_hash; server 127.0.0.1:8083; }
EOF
sudo tee /etc/nginx/sites-available/mainsail >/dev/null <<EOF
server {
    listen 80;
    access_log /var/log/nginx/mainsail-access.log;
    error_log /var/log/nginx/mainsail-error.log;
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 4;
    gzip_types text/plain text/css text/xml text/javascript application/javascript application/x-javascript application/json application/xml;
    root $HOME/mainsail;
    index index.html;
    server_name _;
    client_max_body_size 0;
    proxy_request_buffering off;

    location / { try_files \$uri \$uri/ /index.html; }
    location = /index.html { add_header Cache-Control "no-store, no-cache, must-revalidate"; }
    location /websocket {
        proxy_pass http://apiserver/websocket;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_read_timeout 86400;
    }
    location ~ ^/(printer|api|access|machine|server)/ {
        proxy_pass http://apiserver\$request_uri;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Host \$http_host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Scheme \$scheme;
    }
    location /webcam/  { postpone_output 0; proxy_buffering off; proxy_ignore_headers X-Accel-Buffering; access_log off; error_log off; proxy_pass http://mjpgstreamer1/; }
    location /webcam2/ { postpone_output 0; proxy_buffering off; proxy_ignore_headers X-Accel-Buffering; access_log off; error_log off; proxy_pass http://mjpgstreamer2/; }
    location /webcam3/ { postpone_output 0; proxy_buffering off; proxy_ignore_headers X-Accel-Buffering; access_log off; error_log off; proxy_pass http://mjpgstreamer3/; }
    location /webcam4/ { postpone_output 0; proxy_buffering off; proxy_ignore_headers X-Accel-Buffering; access_log off; error_log off; proxy_pass http://mjpgstreamer4/; }
}
EOF
sudo ln -sf /etc/nginx/sites-available/mainsail /etc/nginx/sites-enabled/mainsail
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t -q && sudo systemctl reload nginx

say "services"
sudo systemctl daemon-reload
sudo systemctl enable -q klipper moonraker
echo "   installed; start with: sudo systemctl start klipper moonraker"
