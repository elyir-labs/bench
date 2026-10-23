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
step is read from those lines and the status (`printer/unit_check.py`). The simulator shows it all with
`--units happy_hare` or `--units afc` and the `unit_check` scenario.

#### Check and measure: the gear (Happy Hare)

Happy Hare scales every move by its gear's rotation distance, and a fresh unit only has the design value. When
Klipper's saved variables say slot 1's gear or the unit's encoder isn't measured (`mmu_gear_rotation_distances`, or
`mmu_<unit>_gear_rotation_distances` on Happy Hare 4, -1 for a gate not measured; `…encoder_resolution` once the
encoder is calibrated; the `mmu` status has no calibration field), Check and measure adds a step between the slots
and the tube (design/unit-setup/, "Gear calibration", C with B's mark). Care's **Measure the gear (again)** runs Check
and measure with it even when it's measured.

1. The plan, with **No ruler? Skip it** (the gear keeps its design value, and Ready says so).
2. Take the tube off the outlet; Bench selects slot 1 and pushes 20 mm out (`MMU_SELECT GATE=…`, `MMU_TEST_MOVE MOVE=20`,
   with `GRIP=1` on Happy Hare 4 so an ERCF's servo stays down; **Push a bit more** pushes 20 more). Draw a line at the
   outlet's edge.
3. Bench pushes exactly 100 mm. Measure from the outlet's edge to the mark and type it on the number pad: 90 to 110 is
   taken, 80 to 90 and 110 to 120 ask **Measure again** (back 100, out 100) or **Use**, past that it can't be the gear.
4. Bench pulls back everything it pushed, then `MMU_CALIBRATE_GEAR LENGTH=100 MEASURED=<mm>` (it only does arithmetic,
   on the selected gate). Put the tube back on.
5. With an encoder: `MMU_CALIBRATE_ENCODER` (3 x 400 mm, slot 1 selected), which learns its scale from slot 1's gear;
   then on a unit with a gear per gate (an ERCF) each other slot that passed its check by the encoder, one at a time:
   `MMU_CALIBRATE_GATE GATE=n` (Happy Hare 3: `MMU_CALIBRATE_GATES GATE=n`). One thrown out (more than 20% from slot 1)
   or stopped partway can be tried again or kept at its design value.
6. Then the tube to the head, as before.

A Tradrack (one gear for every gate, `variable_rotation_distances` off in `mmu_machine`) needs only the ruler step;
with its encoder mod, the encoder learns from slot 1 too, with no per-slot runs. Whether there's an encoder comes from
`mmu.encoder`. Stop with filament out of the outlet pulls it back first. Never for AFC or an ACE Pro, never while
printing.

Happy Hare checks its essential calibration before `MMU_CHECK_GATE` as well as before `MMU_CALIBRATE_BOWDEN`, so a
fresh unit can refuse at slot 1. Either refusal says what's actually missing, from the `Required:` list in Happy
Hare's "Calibration steps are not complete" (or, when it names nothing Bench knows, from the saved variables): slot
1's gear, the encoder, the selector. When measuring the gear clears it, the failure offers **Measure the gear** and
the slots or the tube carry on after; the selector is still done from Advanced. The simulator plays the gear with the
`unit_check_gear` scenario (an ERCF whose gear isn't measured; slot 3's encoder run is thrown out once) and
`unit_check_tradrack`.

### Setting one up from the screen

On a printer with no filament unit, Materials says **No filament unit found · Set one up** under the one spool, and
Care has a Filament unit row with **Set one up** (design/unit-setup/, B, stage 2). Never beside an ACE Pro (it needs no
setup), on a printer that already has a unit or one Bench only watches, or while printing. Five steps:

1. **Which unit**, by its picture: Box Turtle, Night Owl, ERCF v2, Tradrack, or Something else (the two projects'
   own guides).
2. **Which board** it's wired to. Bench looks for a board on USB or CAN that no `[mcu]` section names; when its chip
   matches only one of the unit's boards, that one is marked *Probably*. Then the board's version (a BTT MMB's v1.0,
   v1.1 and v2 have the same chip and different pins) and the slot count. Another board leads to the guides.
3. **Installing.** `elyir-bench unit install` (docs/installer.md) fetches Happy Hare or AFC at the commit Bench tested,
   keeps a copy of the config folder, runs their own installer with Bench's answers, and restarts Klipper once. If
   Klipper doesn't start with it, the copy goes back by itself and the screen says what Klipper said, with Try again.
4. and 5. **Check and measure** (above) carries on as the last two steps; its Ready adds the version and **Your old
   settings · kept**.

A phone at home follows along and, while it installs, says what's next at the printer: **Carry on here**, or
**Use Workshop's screen**, which leaves the rest to the panel.

**Put it back** (Care › Filament unit › Your old settings, or after a failure while a copy is kept) runs
`elyir-bench unit putback`: the config folder's files back as they were in the copy (files the install added go), their
code taken out of Klipper's and Moonraker's folders, and Klipper restarted once. The copy itself stays in
`printer_data/config-before-unit-<date>/`.

The pairs Bench sets up (`UNIT_PAIRS` in `installer/elyir_bench.py`; none tried on a real unit yet, each marked
`tested_on_hardware: false`):

| Unit | Software | Boards | Slots |
| --- | --- | --- | --- |
| ERCF v2 | Happy Hare 4.1 | BTT MMB v1.0, v1.1, v2; Mellow EASY-BRD v1, v2; Fysetc ERB v1, v2 | 6, 8, 9, 12 |
| Tradrack | Happy Hare 4.1 | BTT MMB v1.0, v1.1, v2; Mellow EASY-BRD v1, v2 | 6, 8, 10, 12 |
| Box Turtle | AFC 1.2 | AFC-Lite; AFC-Pro | 4; 8 |
| Night Owl | AFC 1.2 | Fysetc ERB v2 | 2 |

Their code is never copied here (docs/licensing.md): the installer downloads it onto the printer at one pinned commit
each (`UNIT_PROGRAMS`: Happy Hare `70aa90fb9aa1…` on main, AFC `5ea84ea6fab7…` on main; Happy Hare 3 `883a01198a3f…`
was read too, but its installer only asks interactively, so Bench never installs it). Mainsail's update entry for
either is taken out of `moonraker.conf`, so neither moves past the version Bench tested. Removing Bench gives it
back: the unit stays set up, its update entry returns to `moonraker.conf` and its copy goes back on its branch, so
Mainsail updates it again. (Put it back takes the unit itself out instead.)

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
commands, tried in the simulator), including Check and measure, measuring Happy Hare's gear, and setting one up from the screen (the simulator's
`unit_check_gear`, `unit_setup` and `unit_setup_fails` scenarios). See `units/README.md` for how the service is put together.
