# Sourced by start.sh, and by installer/tests/test_kiosk_fit.py with sample output.

# wlr-randr's text on stdin: "<width> <height> <mm wide> <mm high>", the size as turned on screen.
panel_geometry_wlr() {
  awk -v want="$1" '
    /^[^ ]/ { on = ($1 == want) }
    on && /Physical size:/ { split($3, m, "x"); mw = m[1]; mh = m[2] }
    on && /current/ && / px,/ { split($1, p, "x"); w = p[1]; h = p[2] }
    on && /Transform:/ { t = $2 }
    END {
      if (t ~ /90|270/) { x = w; w = h; h = x }
      print w + 0, h + 0, mw + 0, mh + 0
    }'
}

# xrandr's text on stdin, same answer. Its connected line already has the turned size.
panel_geometry_x() {
  awk -v want="$1" '
    $1 == want && $2 == "connected" {
      for (i = 3; i <= NF; i++) {
        if ($i ~ /^[0-9]+x[0-9]+\+/) { split($i, p, /[x+]/); w = p[1]; h = p[2] }
        if ($i ~ /^[0-9]+mm$/ && !mw) mw = $i + 0
        else if ($i ~ /^[0-9]+mm$/) mh = $i + 0
      }
    }
    END { print w + 0, h + 0, mw + 0, mh + 0 }'
}

# width height mm-wide mm-high [inches set by hand] -> "<inches, or 0 if unknown> <device scale>".
# Displays that report nothing say 0x0, and some report a size no panel has, so a report under 40x25 mm is ignored.
# A tall panel gets the phone layout, drawn for 480 across, so wider ones scale up to fill.
panel_fit() {
  awk -v w="$1" -v h="$2" -v mw="$3" -v mh="$4" -v set="${5:-}" 'BEGIN {
    inches = 0
    if (set + 0 > 0) inches = set + 0
    else if (mw >= 40 && mh >= 25 && mw < 2000) inches = sqrt(mw * mw + mh * mh) / 25.4
    scale = (h > w && w > 480) ? w / 480 : 1
    printf "%.1f %.4g\n", inches, scale
  }'
}
