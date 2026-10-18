#!/bin/bash
# Launch Chromium full-screen on the panel inside cage (a single-window
# Wayland compositor), or on a bare X server where the OS has no cage
# (ELYIR_BENCH_BACKEND=x11: Debian 11, BTT CB1). Shows the app's own boot
# screen within seconds of power, before Moonraker is ready; the app
# reconnects on its own.

URL="${ELYIR_BENCH_URL:-http://localhost/}"
PROFILE="${HOME}/.elyir-bench-chromium"
BACKEND="${ELYIR_BENCH_BACKEND:-cage}"
# cpu: a board whose GPU this OS can't drive (BTT Pi on Debian 11). Chromium's own software
# renderer beats emulating a GPU on the CPU, and the app drops motion and blur (?lite=1).
RENDER="${ELYIR_BENCH_RENDER:-gpu}"
if [ "$RENDER" = "cpu" ]; then
  case "$URL" in *\?*) URL="$URL&lite=1" ;; *) URL="$URL?lite=1" ;; esac
fi

# Chromium refuses to start if the previous run died uncleanly
rm -f "$PROFILE/SingletonLock" "$PROFILE/SingletonSocket" "$PROFILE/SingletonCookie" 2>/dev/null
mkdir -p "$PROFILE"
# Don't show "restore pages?" after a power cut
sed -i 's/"exit_type":"Crashed"/"exit_type":"Normal"/; s/"exited_cleanly":false/"exited_cleanly":true/' "$PROFILE/Default/Preferences" 2>/dev/null

CHROME="$(command -v chromium-browser || command -v chromium)"
[ -n "$CHROME" ] || { echo "chromium not installed: run elyir-bench apply"; exit 1; }

# shellcheck disable=SC2054  # the commas are inside --enable-features, not separators
FLAGS=(
  --kiosk "$URL"
  --user-data-dir="$PROFILE"
  --enable-features=OverlayScrollbar,TouchpadOverscrollHistoryNavigation
  --disable-features=TranslateUI
  --noerrdialogs --disable-infobars --disable-session-crashed-bubble
  --no-first-run --disable-pinch --overscroll-history-navigation=0
  --touch-events=enabled --autoplay-policy=no-user-gesture-required
  --check-for-update-interval=31536000
  --password-store=basic
  --disable-background-networking
  # Chromium's own window paints white before the page's first frame; dark, it matches the boot eye.
  # The panel's theme is its own setting (src/theme.ts), so the page doesn't follow this.
  --force-dark-mode
)
if [ "$RENDER" = "cpu" ]; then
  FLAGS+=(--disable-gpu --disable-gpu-compositing --force-prefers-reduced-motion)
else
  FLAGS+=(--enable-gpu-rasterization --enable-zero-copy --ignore-gpu-blocklist)
fi

if [ "$BACKEND" = "x11" ]; then
  # xinit runs this script a second time as the X server's one client.
  # No window manager: Chromium is told the screen's size itself.
  if [ "${1:-}" != "--in-x" ]; then
    exec xinit "$0" --in-x -- :0 -nocursor -nolisten tcp -s 0 -dpms
  fi
  xset s off -dpms s noblank
  if [ -n "${ELYIR_BENCH_OUTPUT:-}" ]; then
    # DRM calls it HDMI-A-1, X's modesetting driver HDMI-1
    want="$ELYIR_BENCH_OUTPUT"; xwant="${ELYIR_BENCH_OUTPUT/HDMI-A-/HDMI-}"
    for o in $(xrandr | awk '/ connected/ {print $1}'); do
      [ "$o" = "$want" ] || [ "$o" = "$xwant" ] || xrandr --output "$o" --off
    done
    case "${ELYIR_BENCH_ROTATION:-0}" in
      90) xrandr --output "$xwant" --rotate left ;;
      180) xrandr --output "$xwant" --rotate inverted ;;
      270) xrandr --output "$xwant" --rotate right ;;
    esac
  fi
  size="$(xrandr | sed -n 's/.*current \([0-9]*\) x \([0-9]*\).*/\1,\2/p' | head -1)"
  exec "$CHROME" "${FLAGS[@]}" --ozone-platform=x11 --window-position=0,0 ${size:+--window-size=$size}
fi

# cage runs this script a second time as its one client: switch off any output that
# isn't the panel (a stray dtoverlay can add a phantom DSI that cage would extend onto)
if [ "${1:-}" != "--in-cage" ]; then
  exec cage -- "$0" --in-cage
fi
if [ -n "${ELYIR_BENCH_OUTPUT:-}" ] && command -v wlr-randr >/dev/null; then
  for o in $(wlr-randr | awk '/^[^ ]/ {print $1}'); do
    [ "$o" = "$ELYIR_BENCH_OUTPUT" ] || wlr-randr --output "$o" --off
  done
  # panels mounted upside down or sideways; touch is flipped by the panel's dtoverlay
  # (invx/invy), since wlroots doesn't rotate touch along with the picture
  case "${ELYIR_BENCH_ROTATION:-0}" in
    90|180|270) wlr-randr --output "$ELYIR_BENCH_OUTPUT" --transform "$ELYIR_BENCH_ROTATION" ;;
  esac
fi

# cage shows black until its first window has a picture, which takes a cold Chromium seconds. The
# boot eye's handoff frame goes up first (kiosk/boot/cover.py): the picture Plymouth just
# left on the panel and the app's first frame, so the three meet without a gap.
# After wlr-randr: until then cage spans any phantom output too, and the eye would sit off-center.
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$HERE/boot/plymouth/cover.json" ] && command -v python3 >/dev/null; then
  python3 "$HERE/boot/cover.py" "$HERE/boot/plymouth" &
fi

exec "$CHROME" "${FLAGS[@]}" --ozone-platform=wayland
