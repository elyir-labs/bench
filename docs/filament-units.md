# Filament units: the ACE Pro, Happy Hare and AFC

Elyir Bench drives the ACE Pro itself, with its own driver in [`units/`](../units/). It's free and open source
(AGPL-3.0-only, like the rest of Elyir Bench) and no Klipper add-on: a small service talks to each unit over USB
and to Klipper through Moonraker, so a Klipper update can't break it.

## What it does

- **Load and unload from the screen.** Tap a slot: the unit feeds until the extruder's sensor sees the
  filament, then the extruder takes it to the nozzle. Unloading pulls back until the sensor clears, then parks it.
- **Multi-color prints switch spools by themselves.** A tool change in the file pauses the print quietly, the
  service unloads, loads and purges through your printer's own macros, then resumes where it stopped. A failed
  change leaves the print paused with what went wrong and Try again.
- **Drying and feed assist** from the slot, and the spool's color and material kept per slot, across restarts.
- **Units run by Happy Hare or AFC** (ERCF, Tradrack, Box Turtle, Night Owl and the rest) show and work the
  same way; see below. A unit inside a Kobra's own firmware shows on the screen but takes no commands.

## Written from scratch

The ACE Pro's protocol isn't published. [`units/ace-protocol.md`](../units/ace-protocol.md) was written from
USB captures of a real unit (in [`units/captures/`](../units/captures/), with the tools that took and decoded
them in `units/tools/`), and every fact in it names its capture. No code from another ACE project is in here,
which is what lets the driver carry Elyir Bench's license.

## Nothing to install

The driver comes with Elyir Bench: the install command puts it on the printer with everything else.

- **An ACE Pro that nothing drives yet** (a new printer, or one without KlipperACE): Elyir Bench drives it by
  itself, as long as Klipper knows the extruder's filament sensor. The install command says so before it asks.
- **A printer on KlipperACE** keeps it. The install command asks once whether to switch, and you can switch
  whenever you're ready:

```ini
# ~/printer_data/config/elyir-bench.conf
filament_units: elyir        # auto (the default) | elyir | klipperace
```

Then `elyir-bench apply` on the printer. Switching writes `elyir_units.cfg` next to printer.cfg (the sensor's
push, `ELYIR_TOOL`, `T0`..`T15`) with one include line, comments out KlipperACE's includes with a mark, restarts
Klipper (never during a print) and starts `elyir-units.service`. It carries over KlipperACE's slot in the head
and the spools it knows. `filament_units: klipperace` puts every line back, and `elyir-bench remove` takes the
driver off with the rest.

If the sensor's pin needs a pull-up Klipper doesn't show, name it: `units_sensor_pin: ^PB8`.

## Happy Hare and AFC

A unit that [Happy Hare](https://github.com/moggieuk/Happy-Hare) (v3 or v4) or Armored Turtle's
[AFC](https://github.com/ArmoredTurtle/AFC-Klipper-Add-On) runs needs nothing from Elyir Bench's side: it reads
their status and sends their own commands. They keep doing the tool change themselves, so a multi-color print
uses their `T0`..`Tn` as before.

| From the screen | Happy Hare | AFC |
| --- | --- | --- |
| Load, switch, unload | `MMU_CHANGE_TOOL GATE= STANDALONE=1`, `MMU_UNLOAD` | `CHANGE_TOOL LANE=`, `TOOL_UNLOAD` |
| A spool's color and material | `MMU_GATE_MAP` (with the gate's temperature, which it would otherwise reset) | `SET_COLOR`, `SET_MATERIAL` |
| Already in the head / empty | `MMU_RECOVER` | `SET_LANE_LOADED`, `UNSET_LANE_LOADED` |
| Carry on with a matching spool | `MMU_ENDLESS_SPOOL` | (each lane names its own runout lane) |
| Move filament, swap a spool | (by hand) | `LANE_MOVE` |

The screen only offers what the unit can do: no Dry button where there's no dryer, no "Pull it in" on Happy
Hare. An ACE Pro that AFC or Happy Hare drives stays theirs: `filament_units: auto` never puts Elyir Bench's
own driver in their way, and the install command doesn't ask. Try either without hardware:
`python3 simulator/sim.py --units afc` or `--units happy_hare`.

### Check and measure

Materials (on the unit's line) and Care (Filament unit) offer **Check and measure** for a Happy Hare or AFC unit, when
nothing is printing and no filament is in the head. The screen goes through each slot: if its sensor doesn't see
filament it asks for some to be pushed in (or, on a Happy Hare gate without a sensor, for "It's in"), then the unit
turns its motor a little with its own command. Each slot is passed, skipped, or didn't pass with a sentence saying what
to check and Try again. Then it measures: Happy Hare the tube to the head (`MMU_SELECT` and `MMU_CALIBRATE_BOWDEN`
with the first slot that passed), AFC each slot to its hub (`CALIBRATE_AFC LANE=`) and then the tube
(`CALIBRATE_AFC BOWDEN=`). Ready sums it up: the slots checked and the tube's length. Stop finishes the command
running and then stops. Happy Hare's check is `MMU_CHECK_GATE GATE=n`, after `MMU_HOME` when the selector isn't
homed (Happy Hare 3 needs it); AFC's is `LANE_MOVE` back and forward 10 mm. Both save what they measure in their own
files, as their own commands do.

Neither raises an error for most failures: the command returns and says so on the console, so the result of each
step is read from those lines and the status (`printer/unit_check.py`). Happy Hare's gear, encoder, selector and
per-gate calibration aren't on the screen: Happy Hare refuses the check until its gear and selector are calibrated,
and the screen says to do that from Advanced. The simulator shows it all with `--units happy_hare` or `--units afc`
and the `unit_check` scenario.

## Settings

In the same file, all optional:

| Setting | What |
| --- | --- |
| `units_before_macro`, `units_after_macro` | Your printer's own macros around a change (tip cutting, the purge, the way back). They get `FROM`, `TO`, `TEMP` and `PURGE`. |
| `units_sensor_to_nozzle` | mm from the extruder's sensor to the nozzle (120). |
| `units_backoff` | mm the extruder backs out while the unit pulls. With a cutter between the gears and the sensor, `0`. |
| `units_park` | mm the unit pulls back after the sensor clears (170). |
| `units_temp` | Nozzle temperature for a change when the printer isn't hot already (230). |
| `units_purge_moves` | `x,y x,y`: the way to your purge spot, before anything pushes filament into the nozzle. |
| `units_push_start`, `units_push_end` | G-code around the push into the nozzle, such as a purge belt running. |

## Today

Tested on hardware with one ACE Pro: loads, unloads, changes from the screen and two-color prints. Not tried on
hardware yet: two ACE Pros on one printer, and Happy Hare and AFC (built from their documented status and
commands, tried in the simulator), including Check and measure. Installing Happy Hare or AFC for you comes next. See `units/README.md` for how the service is put together.
