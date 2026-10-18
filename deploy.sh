#!/bin/bash
# Build a release on this machine and install it on a printer with the on-device installer.
#
#   ./deploy.sh workshop.local               # build, copy, `elyir-bench apply <release>` there
#   ./deploy.sh workshop.local plan          # just show what apply would change there
#   ./deploy.sh workshop.local doctor        # check the printer without changing anything
#
# The printer runs exactly what the bootstrap would run; this script only builds and copies.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
HOST="${1:?usage: $0 <host> [apply|plan|doctor]}"
CMD="${2:-apply}"
DEST="${SSH_USER:-pi}@${HOST}"
# ConnectTimeout: without it, ssh to a .local name from this Mac sometimes hangs before connecting (15 October 2026)
OPTS=(-4 -o BatchMode=yes -o ConnectTimeout=15)
SSH=(ssh "${OPTS[@]}" "$DEST")
# a terminal lets the installer ask for the sudo password on printers that need one
[ -t 0 ] && SSH=(ssh "${OPTS[@]}" -t "$DEST")

if [ "$CMD" != "apply" ]; then
  # use the installer from the release being built, so new checks show up before deploying
  scp "${OPTS[@]}" -q "$ROOT/installer/elyir_bench.py" "$DEST:/tmp/elyir-bench-installer.py"
  exec "${SSH[@]}" "python3 /tmp/elyir-bench-installer.py $CMD"
fi

echo "== build"
TARBALL="$("$ROOT/scripts/build-release.sh" | tail -1)"
echo "   $(basename "$TARBALL")"

echo "== copy to $DEST"
"${SSH[@]}" 'mkdir -p ~/elyir-bench/incoming'
scp "${OPTS[@]}" -q "$TARBALL" "$DEST:elyir-bench/incoming/"

echo "== apply"
NAME="$(basename "$TARBALL")"
"${SSH[@]}" "cd ~/elyir-bench/incoming &&
  rm -rf .installer && mkdir .installer && tar -xzf '$NAME' -C .installer installer/elyir_bench.py &&
  { python3 .installer/installer/elyir_bench.py apply '$NAME'; rc=\$?
    ls -t elyir-bench-*.tar.gz | tail -n +4 | xargs -r rm -f; exit \$rc; }"
