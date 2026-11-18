#!/bin/bash
# Two units on one printer: feed assist on the head's slot while a slot on the other unit feeds 30 mm and retracts
# 30 mm, through the running service (no Klipper restart). Refuses unless the printer is idle and cold.
# usage: units/tools/two-unit-session.sh <user@host> <slot 1-8 on the other unit> [--same-unit <slot on the head's unit>]
# The timeline lands in units/captures/<date>-two-unit.jsonl.
set -euo pipefail

target=${1:-}
slot=${2:-}
[[ -n $target && $slot =~ ^[1-8]$ ]] || { echo "usage: $0 <user@host> <slot 1-8> [--same-unit <slot 1-8>]"; exit 2; }
extra=()
if [[ ${3:-} == --same-unit ]]; then
    [[ ${4:-} =~ ^[1-8]$ ]] || { echo "--same-unit takes a slot 1-8"; exit 2; }
    extra=(--same-unit $(($4 - 1)))
fi

here=$(cd "$(dirname "$0")" && pwd)
out="$here/../captures/$(date +%F)-two-unit.jsonl"
ssh_() { ssh -4 -o ConnectTimeout=8 -o ServerAliveInterval=5 "$target" "$@"; }

ssh_ 'cat > /tmp/two_unit_probe.py' < "$here/two_unit_probe.py"
status=0
ssh_ bash -s -- $((slot - 1)) "${extra[@]}" <<'REMOTE' || status=$?
set -uo pipefail
q() { curl -4 -s --max-time 5 "localhost:7125/printer/objects/query?$1"; }
field() { python3 -I -c 'import json, sys; d = json.load(sys.stdin)["result"]["status"]; print(eval(sys.argv[1], {}, d))' "$1"; }

st=$(q "print_stats=state&idle_timeout=state&extruder=target&heater_bed=target")
[ "$(echo "$st" | field 'print_stats["state"] in ("printing", "paused")')" = False ] || { echo "REFUSED: printing or paused"; exit 3; }
[ "$(echo "$st" | field 'idle_timeout["state"]')" != Printing ] || { echo "REFUSED: busy"; exit 3; }
[ "$(echo "$st" | field 'extruder["target"] == 0 and heater_bed["target"] == 0')" = True ] || { echo "REFUSED: heaters on"; exit 3; }
systemctl is-active --quiet elyir-units || { echo "REFUSED: the filament-unit service isn't running"; exit 3; }

python3 -I /tmp/two_unit_probe.py "$1" /tmp/two-unit.jsonl "${@:2}"
REMOTE
ssh_ 'cat /tmp/two-unit.jsonl 2>/dev/null; rm -f /tmp/two_unit_probe.py /tmp/two-unit.jsonl' > "$out" || true
[ -s "$out" ] && echo "timeline: $out" || rm -f "$out"
exit $status
