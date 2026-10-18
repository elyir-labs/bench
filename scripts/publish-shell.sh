#!/bin/bash
# Publish the printer app (the shell) to https://printers.elyir.app. docs/door.md, *One app for every printer*.
#
#   scripts/publish-shell.sh                 build HEAD from a clean checkout and publish it
#   REF=<commit> scripts/publish-shell.sh    publish another commit
#   RELAY=root@relay.example scripts/...     another relay box
#   STAGE=staging scripts/publish-shell.sh   staging's Printers app: talks to cloud-staging.elyir.app, served at
#                                            printers-staging.elyir.app from the staging Bench Cloud box
#
# Every phone that opens the shell trusts this code with its printers' tokens, so it is only ever
# published from a commit, built in a clean checkout, and unpacked into a new versioned directory on the
# relay's volume; `current` then switches to it in one rename. Nothing on the box is edited by hand, and
# the last few versions stay so a bad one can be switched back with `ROLLBACK=<version>`.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAGE="${STAGE:-production}"
if [ "$STAGE" = staging ]; then
  RELAY="${RELAY:-root@cloud-staging.elyir.dev}" DIR=/var/lib/bench-cloud/printers SITE=https://printers-staging.elyir.app
  export VITE_CLOUD_URL=https://cloud-staging.elyir.app VITE_ACCOUNT_URL=https://account-staging.elyir.com
else
  RELAY="${RELAY:-root@relay.elyir.app}" DIR=/var/lib/relay/printers SITE=https://printers.elyir.app
fi
KEEP=5
SSH=(ssh -o BatchMode=yes "$RELAY")

if [ -n "${ROLLBACK:-}" ]; then
  "${SSH[@]}" "cd $DIR && test -d '$ROLLBACK' && ln -sfn '$ROLLBACK' current.tmp && mv -T current.tmp current && readlink current"
  exit 0
fi

REF="${REF:-HEAD}"
VERSION="$(git -C "$ROOT" log -1 --format=%cd --date=format:%Y.%m.%d "$REF")-$(git -C "$ROOT" rev-parse --short "$REF")"
WT="$(mktemp -d)"
trap 'git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true' EXIT
git -C "$ROOT" worktree add -q --detach "$WT" "$REF"
ln -s "$ROOT/app/node_modules" "$WT/app/node_modules"

echo "== build $VERSION"
(cd "$WT/app" && npm run build:shell --silent >/dev/null)
OUT="$WT/app/dist-shell"
[ -f "$OUT/index.html" ] || { echo "no $OUT/index.html: is build:shell set up?" >&2; exit 1; }
# The shell runs under a CSP that allows no inline script; catch it here rather than on a phone.
if grep -l -E '<script(\s[^>]*)?>[^<[:space:]]' "$OUT/index.html" >/dev/null; then
  echo "index.html has an inline <script>; the relay's CSP would block it" >&2; exit 1
fi

# Built from the private tree, not the scrubbed public copy, so nothing renames a real name or printer here:
# the same check the public copy passes, on what phones would download.
PUBLIC_NAME="Elyir Bench" PUBLIC_DOMAIN=elyir.app "$ROOT/scripts/public/check.sh" "$OUT" >&2 \
  || { echo "refused: the build names a person, a real printer or the home network (above)" >&2; exit 1; }

echo "== publish to $RELAY:$DIR/$VERSION"
COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -czf - -C "$OUT" . |
  "${SSH[@]}" "set -e; mkdir -p $DIR/.incoming; rm -rf $DIR/.incoming/$VERSION; mkdir $DIR/.incoming/$VERSION
    tar -xzf - -C $DIR/.incoming/$VERSION
    chmod -R a+rX $DIR/.incoming/$VERSION
    rm -rf $DIR/$VERSION; mv $DIR/.incoming/$VERSION $DIR/$VERSION
    cd $DIR && ln -sfn $VERSION current.tmp && mv -T current.tmp current
    ls -1dt 20*/ 2>/dev/null | tail -n +$((KEEP + 1)) | xargs -r rm -rf
    readlink current"

echo "== check"
curl -fsS -o /dev/null -w "$SITE/ -> %{http_code}\n" "$SITE/"
