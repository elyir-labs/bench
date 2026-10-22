# Filament units: the Anycubic ACE Pro

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
- **Watches what it can't move.** A unit run by Happy Hare, or inside a Kobra's own firmware, shows on the
  screen the same way; Elyir Bench only sends commands to units it drives.

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
hardware yet: two units on one printer. Other units can follow the same way (a driver for a unit with its own
controller, or an adapter to Happy Hare or AFC); see `units/README.md` for how the service is put together.
