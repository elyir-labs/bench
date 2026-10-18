#!/bin/sh
# Elyir Bench, added to a Raspberry Pi printer that already runs Klipper and Moonraker:
#
#   curl -fsSL https://bench.elyir.com/install | sh
#
# It checks the printer first and says what it adds and what it leaves alone (printer.cfg, Mainsail or
# Fluidd, KlipperScreen), asks once, then installs and shows a QR code for your phone. Nothing changes
# before you say yes, and never during a print. design/getting-started, docs/installer.md.
#
#   curl -fsSL https://bench.elyir.com/install | sh -s -- --invite K7QX-M2PD-9HTF
#
# With an invite code, the printer's name on Elyir's relay works at once (notifications, your phone away
# from home); without one it waits for Elyir to approve it, and `elyir-bench remote invite <code>` uses a
# code any time later.
#
#   ELYIR_BENCH_YES=1         answer yes without asking (no terminal needed)
#   ELYIR_BENCH_INVITE=CODE   the same as --invite CODE
#   ELYIR_BENCH_RELEASES=URL  where releases come from (default https://releases.elyir.dev/bench)
#
# Everything is inside main(), run on the last line, so a download cut short runs nothing.

RELEASES="${ELYIR_BENCH_RELEASES:-https://releases.elyir.dev/bench}"

# Elyir Bench releases are signed with this key (ECDSA P-256; scripts/release/). A release whose signature
# doesn't verify against it is never unpacked.
RELEASE_KEY='-----BEGIN PUBLIC KEY-----
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEfaKjjsM3JWh6jJRkzIYYtJK8eQ3w
M4RNEaiHewKV5Ka1a2bVRcxQAXCLcKcW2pkwMty0iQ7zPCJunlr6EtNzOw==
-----END PUBLIC KEY-----'

say() { printf '%s\n' "$*"; }

# After a failed install: send Elyir what it printed and the printer's logs (design/report/, B), asked first.
offer_report() {
  say ""
  if (exec </dev/tty) 2>/dev/null; then
    printf '%s' "Send these lines and the printer's logs to Elyir, so we can fix it? Passwords, keys and Wi-Fi details never go. [Y/n] "
    read -r answer </dev/tty || answer=n
    case "$answer" in [nN]*) say "Nothing was sent. Later, the same: python3 $installer report --kind install"; return ;; esac
    python3 "$installer" report --kind install || true
  else
    say "To send Elyir these lines and the printer's logs: python3 $installer report --kind install"
  fi
}
fail() { say "$*"; say "Nothing was changed."; exit 1; }

# version, file, sha256 and signature come from the manifest, through eval
# shellcheck disable=SC2154
main() {
  set -eu
  if [ "$(id -u)" = 0 ]; then
    fail "Run this as the printer's own user (usually pi), not as root: it uses sudo where it needs to."
  fi
  for tool in python3 curl tar openssl sha256sum; do
    command -v "$tool" >/dev/null 2>&1 || fail "This printer has no $tool, which installing needs."
  done

  invite="${ELYIR_BENCH_INVITE:-}"
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --invite) [ "$#" -ge 2 ] || fail "--invite needs the code after it."; invite="$2"; shift 2 ;;
      --invite=*) invite="${1#--invite=}"; shift ;;
      *) fail "Unknown option $1 (the only one is --invite CODE)." ;;
    esac
  done
  if [ -n "$invite" ] && [ "$(printf '%s' "$invite" | tr -cd 'A-Za-z0-9' | wc -c | tr -d ' ')" != 12 ]; then
    fail "An invite code is twelve letters and numbers, like K7QX-M2PD-9HTF."
  fi

  incoming="$HOME/elyir-bench/incoming"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  mkdir -p "$incoming"

  # which release, from the manifest
  curl -fsSL "$RELEASES/latest.json" -o "$tmp/latest.json" ||
    fail "Couldn't reach $RELEASES. Is the printer on the internet?"
  vars="$(python3 - "$tmp/latest.json" <<'EOF'
import json, re, shlex, sys
m = json.load(open(sys.argv[1]))
for k in ("file", "signature"):
    if not re.fullmatch(r"[A-Za-z0-9._-]+", m[k]):
        sys.exit(f"bad {k} in the manifest")
if not re.fullmatch(r"[0-9a-f]{64}", m["sha256"]):
    sys.exit("bad sha256 in the manifest")
for k in ("version", "file", "sha256", "signature"):
    print(f"{k}={shlex.quote(str(m[k]))}")
EOF
)" || fail "The release list at $RELEASES didn't make sense."
  eval "$vars"   # version, file, sha256, signature
  tarball="$incoming/$file"

  # the release itself: fetched once, then checked every time
  if [ ! -f "$tarball" ] || [ "$(sha256sum "$tarball" | cut -d' ' -f1)" != "$sha256" ]; then
    curl -fsSL "$RELEASES/$file" -o "$tmp/$file" || fail "Couldn't download Elyir Bench $version."
    mv "$tmp/$file" "$tarball"
  fi
  [ "$(sha256sum "$tarball" | cut -d' ' -f1)" = "$sha256" ] ||
    { rm -f "$tarball"; fail "The download of Elyir Bench $version came out damaged. Run the command again."; }
  curl -fsSL "$RELEASES/$signature" -o "$tmp/release.sig" || fail "Couldn't download the release's signature."
  printf '%s\n' "$RELEASE_KEY" > "$tmp/release-key.pem"
  openssl dgst -sha256 -verify "$tmp/release-key.pem" -signature "$tmp/release.sig" "$tarball" >/dev/null 2>&1 ||
    { rm -f "$tarball"; fail "Elyir Bench $version isn't signed by Elyir, so it wasn't installed."; }

  # the installer from that release does the rest: the check, then the install
  rm -rf "$incoming/.installer" && mkdir -p "$incoming/.installer"
  # by folder, not by file name: the public copy renames the installer, and either copy can install either release
  tar -xzf "$tarball" -C "$incoming/.installer" installer
  set -- "$incoming"/.installer/installer/*.py
  [ "$#" = 1 ] && [ -f "$1" ] || fail "Elyir Bench $version has no installer in it."
  installer="$1"

  say ""
  rc=0
  python3 "$installer" check || rc=$?
  [ "$rc" = 0 ] || exit "$rc"

  # the one question; read from the terminal, since this script itself arrives on standard input
  if [ "${ELYIR_BENCH_YES:-}" != 1 ]; then
    if ! (exec </dev/tty) 2>/dev/null; then
      say ""
      say "Run this from a terminal so it can ask first, or with ELYIR_BENCH_YES=1 to say yes ahead of time."
      exit 2
    fi
    printf '\nGo ahead? [Y/n] '
    read -r answer </dev/tty || answer=n
    case "$answer" in
      ""|y|Y|yes|Yes) ;;
      *) say "Nothing was changed."; exit 1 ;;
    esac
  fi

  # the QR code at the end; harmless to go without (the link is printed either way)
  command -v qrencode >/dev/null 2>&1 ||
    sudo -n apt-get install -y -q --no-install-recommends qrencode >/dev/null 2>&1 || true

  say ""
  started="$(date +%s)"
  set -- "$tarball"
  [ -z "$invite" ] || set -- "$tarball" --invite "$invite"
  if (exec </dev/tty) 2>/dev/null; then
    python3 "$installer" apply "$@" </dev/tty || rc=$?   # a terminal, for sudo's password if it asks
  else
    python3 "$installer" apply "$@" || rc=$?
  fi
  if [ "$rc" != 0 ]; then
    say ""
    say "Installing didn't finish; the lines above say why. Anything it had changed was put back."
    offer_report
    exit "$rc"
  fi
  say "  ✓ Installed, release $version ($(( $(date +%s) - started )) s)"
  ls -t "$incoming"/*.tar.gz 2>/dev/null | tail -n +4 | xargs -r rm -f

  say ""
  python3 "$installer" pair
}

main "$@"
