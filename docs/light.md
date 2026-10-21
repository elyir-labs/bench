# The chamber light

Design: `design/chamber-light/`, A (picked 21 October 2026). The switch is a bulb on the camera picture on Now; where Now
shows no camera (the printer's own screen, a printer without one) it's a Light pill in the top bar, and inside the
Printers app, whose bar names the printer, it sits at the top of Now. It works from away too.

## Which light

The component looks through Klipper's objects for an `output_pin`, `neopixel`, `dotstar`, `led`, `pca9533` or `pca9632`
whose name says case, chamber, light, lamp or enclosure (`light_candidates` in `printer/elyir_bench_intent.py`). With one,
that's the light. With more than one (an on/off light and a status strip, say), the first tap asks "Which one lights the
bed?": each can be tried, and the one picked is kept in Moonraker's database at `elyir-bench/light`. To name it by hand:

```ini
[printer_intent]
light: output_pin case_light
```

## On and off

- An on/off light: `SET_PIN PIN=<name> VALUE=1`, and `VALUE=0`. Turned on from Mainsail or a macro, it shows as on.
- A strip: `STOP_LED_EFFECTS` on that strip (when the LED effects plugin is there), then `SET_LED` full white. Off sets it
  dark and starts again the effects that were running before (`SET_LED_EFFECT`), so its status colors come back.
- It goes off by itself once the printer has been quiet (not printing, warming up or held by Move and heat) for 30
  minutes, counted from the later of the tap and the end of the print. Never during a print.

On Ready the camera shows a still every 10 seconds, so after a tap it takes a fresh one at once, to show the light.

The simulator has one too: `sim.py --light pin|strip|both|none` (both asks).
