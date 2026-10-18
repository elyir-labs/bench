#!/bin/bash
# Build a release tarball: the built app, the Moonraker component, the kiosk launcher, the boot
# screen's Plymouth theme, the first Wi-Fi's service and the installer. Prints the tarball path on the last line.
#
#   scripts/build-release.sh              -> dist/elyir-bench-<date>-<sha>.tar.gz, from a clean
#                                            checkout of HEAD (uncommitted work never ships)
#   REF=<commit> scripts/build-release.sh -> same, from another commit
#   DIRTY=1 scripts/build-release.sh      -> from the working tree as it is, for quick iteration

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
WT=""; STAGE=""
cleanup() {
  [ -n "$STAGE" ] && rm -rf "$STAGE"
  [ -n "$WT" ] && git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
}
trap cleanup EXIT

if [ "${DIRTY:-}" = "1" ]; then
  SRC="$ROOT"
  VERSION="$(date +%Y.%m.%d)-$(git rev-parse --short HEAD)"
  # uncommitted builds get a unique name so the printer never reuses a stale unpack
  git diff --quiet HEAD -- app printer kiosk installer door slicer bench setup || VERSION="$VERSION-dirty.$(date +%H%M%S)"
else
  REF="${REF:-HEAD}"
  WT="$(mktemp -d)"
  git worktree add -q --detach "$WT" "$REF"
  ln -s "$ROOT/app/node_modules" "$WT/app/node_modules"
  SRC="$WT"
  VERSION="$(git log -1 --format=%cd --date=format:%Y.%m.%d "$REF")-$(git rev-parse --short "$REF")"
fi

# a release built from the public copy keeps the private commit's name (scripts/release/publish.sh)
VERSION="${RELEASE_VERSION:-$VERSION}"

(cd "$SRC/app" && npm run build --silent >/dev/null && npm run build:bench --silent >/dev/null)

STAGE="$(mktemp -d)"
mkdir -p "$STAGE/app" "$STAGE/printer" "$STAGE/kiosk" "$STAGE/installer" "$STAGE/door" "$STAGE/slicer" "$STAGE/bench-app" "$STAGE/bench" "$STAGE/setup"
cp -R "$SRC/app/dist/." "$STAGE/app/"
cp "$SRC/printer/elyir_bench_intent.py" "$SRC/printer/filament_units.py" "$SRC/printer/elyir_bench_care.py" "$SRC/printer/printer_intent.py" "$SRC/printer/orca_profile.py" "$SRC/printer/power_key.py" "$STAGE/printer/"
# the start macro the installer writes into the config folder (elyir-bench startmacro on, docs/start-macro.md)
mkdir -p "$STAGE/printer/klipper"
cp "$SRC/printer/klipper/elyir-bench.cfg" "$STAGE/printer/klipper/"
cp "$SRC/kiosk/start.sh" "$STAGE/kiosk/"
# the boot eye's Plymouth theme, drawn from the same geometry as the app's boot screen
python3 "$SRC/kiosk/boot/make-plymouth.py" "$STAGE/kiosk/boot/plymouth"
cp "$SRC/kiosk/boot/cover.py" "$STAGE/kiosk/boot/"    # that frame under cage until Chromium has a window
cp "$SRC/installer/elyir_bench.py" "$SRC/installer/elyir_bench_os.py" "$STAGE/installer/"   # the OS slots tool too (docs/os-slots.md)
cp "$SRC/door/door.py" "$SRC/door/requirements.txt" "$STAGE/door/"
# orca_keys.json: which Orca preset each setting goes in, for printer/orca_profile.py (docs/slicer-profile.md)
cp "$SRC/slicer/elyir_bench_slice.py" "$SRC/slicer/slice_service.py" "$SRC/slicer/orca_keys.json" "$STAGE/slicer/"
cp -R "$SRC/app/dist-bench/." "$STAGE/bench-app/"          # a Bench Box's screen (docs/bench.md)
cp "$SRC/bench/"*.py "$STAGE/bench/"                         # the service and its shelf
cp -R "$SRC/bench/profiles" "$STAGE/bench/"                  # slicing profiles for printers the box speaks for (design/bench-kobra/)
cp "$SRC/setup/wifi_setup.py" "$SRC/setup/phone.html" "$STAGE/setup/"   # a new printer's first Wi-Fi (docs/setup.md)
echo "$VERSION" > "$STAGE/VERSION"

# The built app talks to whatever host served it (nginx proxies Moonraker), never a fixed printer.
python3 - "$STAGE/app" <<'EOF'
import json, os, re, sys
d = sys.argv[1]
p = os.path.join(d, "config.json")
if os.path.exists(p):
    c = json.load(open(p))
    c.setdefault("moonraker", {})["host"] = ""
    json.dump(c, open(p, "w"), indent=2)
# elyir-bench.yaml wins over config.json; blank its first moonraker host too
y = os.path.join(d, "elyir-bench.yaml")
if os.path.exists(y):
    open(y, "w").write(re.sub(r"(?m)^(  host:).*$", r"\1 ''", open(y).read(), count=1))
EOF

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/elyir-bench-$VERSION.tar.gz"
COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -czf "$OUT" -C "$STAGE" VERSION app printer kiosk installer door slicer bench-app bench setup
echo "$OUT"
