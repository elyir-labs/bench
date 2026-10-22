#!/bin/bash
# Build a release on this machine and install it on a printer with the on-device installer.
#
#   ./deploy.sh workshop.local               # build, copy, `elyir-bench apply <release>` there
#   ./deploy.sh workshop.local plan          # just show what apply would change there
#   ./deploy.sh workshop.local doctor        # check the printer without changing anything
#   ./deploy.sh biqu@desk.local          # another user (or SSH_USER=biqu)
#
# The printer runs exactly what the bootstrap would run; this script only builds and copies.

set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
HOST="${1:?usage: $0 <host> [apply|plan|doctor]}"
CMD="${2:-apply}"
DEST="$HOST"; [[ "$HOST" == *@* ]] || DEST="${SSH_USER:-pi}@${HOST}"
# ConnectTimeout: without it, ssh to a .local name from this Mac sometimes hangs before connecting (15 October 2026)
OPTS=(-4 -o BatchMode=yes -o ConnectTimeout=15)
SSH=(ssh "${OPTS[@]}" "$DEST")
# a terminal lets the installer ask for the sudo password on printers that need one
[ -t 0 ] && SSH=(ssh "${OPTS[@]}" -t "$DEST")

DIR=elyir-bench INSTALLER=installer/elyir_bench.py BUILD="$ROOT/scripts/build-release.sh"
# A printer on Elyir Bench's own names (~/elyir-bench, scripts/move-to-public.py) takes the public build, as testers' do
if [ -x "$ROOT/scripts/release/build-public.sh" ] && ssh "${OPTS[@]}" "$DEST" 'test -d ~/elyir-bench'; then
  DIR=elyir-bench INSTALLER=installer/elyir_bench.py BUILD="$ROOT/scripts/release/build-public.sh"
fi

if [ "$CMD" != "apply" ] && [ "$DIR" = elyir-bench ]; then
  # use the installer from the release being built, so new checks show up before deploying
  scp "${OPTS[@]}" -q "$ROOT/$INSTALLER" "$DEST:/tmp/$DIR-installer.py"
  exec "${SSH[@]}" "python3 /tmp/$DIR-installer.py $CMD"
fi

echo "== build"
TARBALL="$("$BUILD" | tail -1)"
echo "   $(basename "$TARBALL")"

echo "== copy to $DEST"
"${SSH[@]}" "mkdir -p ~/$DIR/incoming"
scp "${OPTS[@]}" -q "$TARBALL" "$DEST:$DIR/incoming/"

echo "== $CMD"
NAME="$(basename "$TARBALL")"
ARGS="$CMD"; [ "$CMD" = apply ] && ARGS="apply '$NAME'"
"${SSH[@]}" "cd ~/$DIR/incoming &&
  rm -rf .installer && mkdir .installer && tar -xzf '$NAME' -C .installer $INSTALLER &&
  { python3 .installer/$INSTALLER $ARGS; rc=\$?
    ls -t $DIR-*.tar.gz | tail -n +4 | xargs -r rm -f; exit \$rc; }"
