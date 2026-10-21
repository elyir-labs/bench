#!/bin/bash
# Build a flashable Elyir Bench card image (docs/image.md).
#
#   image/build.sh                 -> dist/elyir-bench-<release>-pi4.img.xz, from a release of HEAD
#   image/build.sh --dev           -> the same, with this Mac's SSH key for user pi (never for other people)
#   BOARD=pi5 image/build.sh       a Raspberry Pi 5's card (image/config/elyir-bench-<board>.yaml)
#   RELEASE=dist/elyir-bench-….tar.gz image/build.sh    use a release already built
#   DIRTY=1 image/build.sh         the release from the working tree (scripts/build-release.sh)
#
# Builds in Docker (debian:trixie arm64 + rpi-image-gen, image/Dockerfile); the work stays in the
# elyir-imagework volume, so later builds reuse the downloaded packages.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
DEV=0
[ "${1:-}" = "--dev" ] && DEV=1
BOARD="${BOARD:-pi4}"
[ -f "image/config/elyir-bench-$BOARD.yaml" ] || { echo "no image/config/elyir-bench-$BOARD.yaml: no card for $BOARD yet" >&2; exit 2; }
# a developer card is named so (and never published). Not `$([ ] && echo -dev)` inline: in an
# assignment that fails under set -e whenever it isn't one, and ends the script.
SUFFIX=""
[ "$DEV" = 1 ] && SUFFIX=-dev

if [ -z "${RELEASE:-}" ]; then
  echo "== release"
  RELEASE="$(scripts/build-release.sh | tail -1)"
fi
REL_NAME="$(basename "$RELEASE")"
VERSION="${REL_NAME#elyir-bench-}"; VERSION="${VERSION%.tar.gz}"
echo "   $REL_NAME"

echo "== builder"
docker build -q -t elyir-imagegen image >/dev/null

KEY=""
if [ "$DEV" = 1 ]; then
  KEY="$(cat ~/.ssh/id_ed25519.pub 2>/dev/null || cat ~/.ssh/id_rsa.pub)"
  echo "   developer card: SSH as pi with this Mac's key"
fi

echo "== image (a few minutes)"
mkdir -p dist
docker volume create elyir-imagework >/dev/null
docker run --rm --privileged \
  -v elyir-imagework:/work -v "$ROOT/image:/src:ro" -v "$(cd "$(dirname "$RELEASE")" && pwd):/release:ro" -v "$ROOT/dist:/out" -v "$ROOT/install/release-key.pem:/release-key.pem:ro" -e VERSION="$VERSION$SUFFIX" \
  -e DISKSIG="0x$(od -An -N4 -tx1 /dev/urandom | tr -d " \n")" -e ELYIR_RELEASE="/release/$REL_NAME" -e ELYIR_KEY="$KEY" -e BOARD="$BOARD" \
  elyir-imagegen bash -euc '
    mkdir -p "/work/elyir-$BOARD"
    cd /opt/rpi-image-gen
    ./rpi-image-gen build -S /src -c "elyir-bench-$BOARD.yaml" -B "/work/elyir-$BOARD" --"IGconf_bench_release=$ELYIR_RELEASE" "IGconf_bench_release_key=/release-key.pem" "IGconf_bench_os_version=$VERSION" "IGconf_image_disksig=$DISKSIG" "IGconf_ssh_pubkey_user1=$ELYIR_KEY" > /work/elyir.log 2>&1 || { tail -60 /work/elyir.log; exit 1; }
    cp /work/elyir.log /out/elyir-image.log
    img=$(ls "/work/elyir-$BOARD"/image-*/*.img | head -1)
    xz -T0 -6 -c "$img" > /out/elyir-image.img.xz
    # the same OS as an update (docs/os-slots.md, "Releases"): its root filesystem, its boot files, a manifest
    out=$(dirname "$img"); b=$(mktemp -d); mkdir "$b/boot"
    mcopy -s -n -i "$out/boot.vfat" "::*" "$b/boot/"
    zstd -T0 -10 -q "$out/root.ext4" -o "$b/root.ext4.zst"
    printf "{\"kind\": \"elyir-bench-os\", \"version\": \"%s\", \"device\": \"%s\", \"root\": \"root.ext4.zst\", \"root_bytes\": %s, \"built\": \"%s\"}\n" \
      "$VERSION" "$BOARD" "$(stat -c %s "$out/root.ext4")" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$b/manifest.json"
    tar -cf /out/elyir-os.tar -C "$b" manifest.json root.ext4.zst boot'
OUT="dist/elyir-bench-$VERSION-$BOARD$SUFFIX.img.xz"
mv dist/elyir-image.img.xz "$OUT"
OS="dist/elyir-bench-os-$VERSION-$BOARD$SUFFIX.tar"
mv dist/elyir-os.tar "$OS"
# signed with the release key, which only this Mac has (scripts/release/README.md); checked against the public half
KEY_PRIV="$HOME/.config/elyir/bench-release-key.pem"
if [ -f "$KEY_PRIV" ]; then
  openssl dgst -sha256 -sign "$KEY_PRIV" -out "$OS.sig" "$OS"
  openssl dgst -sha256 -verify install/release-key.pem -signature "$OS.sig" "$OS" >/dev/null
  echo "$OS (signed)"
else
  echo "$OS (unsigned: no $KEY_PRIV here)"
fi
echo "$OUT"
