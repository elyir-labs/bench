# A start macro for someone else's printer

On a printer someone else set up, Elyir Bench can't lean on our shared PRINT_START. Five features read
it today: the getting-ready steps, Cancel while warming up, keeping the first layer (squish more or less),
the chamber part of warm-up, and the color change (M600). `design/getting-started/` decided how the
person gets them: one optional `[include elyir-bench.cfg]` line, shown in full before it's added, removed
with one tap. It left open how Elyir Bench's start macro meets theirs. This is the spike that answers it.

**The answer: neither replace theirs nor wrap it. Run before it.** `ELYIR_BENCH_PRINT_START` goes above
their start G-code, heats the bed while the file is paused (so Cancel works), then lets their own start
G-code run exactly as before. `ELYIR_BENCH_PRINT_START_DONE` goes below it and puts back the kept first
layer. Their PRINT_START keeps every step it has: homing, leveling, mesh, purge, probe docking, lights.
The draft is `printer/klipper/elyir-bench.cfg`, and it was run in a real Klipper.

## What the app reads today

From `printer/elyir_bench_intent.py`. Every name below is in Moonraker's subscription list
(`"gcode_macro _PRINT_START": ["stage"]`, `"gcode_macro _PRINT_START_SETTINGS": ["chamber_max", "tap"]`).

| Feature | What it reads | On a printer without our macros |
|---|---|---|
| Getting-ready steps | `gcode_macro _PRINT_START.stage`, mapped by `PRINT_START_STAGES` to the four steps and by `ART_STAGES` to the ring's drawing. Without a stage: `display_status.message` (M117) against `PREP_STEPS` and `ART_FROM_MESSAGE`, else the heater temperatures. | Steps from M117 if their macro sends any (stock Voron and Ellis' template send none), else from the heaters. |
| Getting ready vs printing | A stage set = getting ready. Printing starts at an M117 with `printing...` or `printing, good luck` (`PRINT_STARTED_MARKERS`), or `print_stats.info.current_layer` 1 or more. | **A gap:** with neither (stock Orca Voron profile: no `SET_PRINT_STATS_INFO`; a macro without "Printing..."), Now says Getting ready for the whole print. |
| Cancel while warming | Nothing. Cancel sends `CANCEL_PRINT`, which waits behind any running M190/M109/TEMPERATURE_WAIT. Getting ready means paused with a stage. | Cancel waits until the heat-up ends, up to 20 minutes. Stop now still works. |
| Squish more / less | Nudges are `SET_GCODE_OFFSET Z_ADJUST` on layers 1 to 3, not paused, no stage. Keep needs `[save_variables]` (`first_layer_z`, `first_layer_against`, `first_layer_history`, `first_layer_at`) and a start macro that applies `first_layer_z` when `first_layer_against` matches `z_by()` (`"tap"` when `_PRINT_START_SETTINGS.tap` is true, else `"scan"`) and it's 0.5 mm or less (`SQUISH_LIMIT`). | Nudging works. Keeping does nothing next time: nothing applies it. |
| Warm-up | Sends `M140`/`M104` itself. The chamber target is `_PRINT_START_SETTINGS.chamber_max`, and only with a `temperature_sensor` named chamber or enclosure. | Works, bed and nozzle only. (The board's "What works" table says No; it's the chamber part that's missing.) |
| Color change | `M600` lines in the file (`colour_plan`), and console lines with `m600`, `color change` or `load new filament` to call a pause a color change. | Klipper answers `Unknown command:"M600"` and **prints on in the same color**. It's a note, not an error (`klippy/gcode.py`). |

## Five common setups

Read on 5 October 2026. Sources are at the end.

| Setup | Name and parameters | What it does | Says what it's doing | Its own PAUSE / M600 |
|---|---|---|---|---|
| Voron 2.4 sample config | `PRINT_START`, no parameters | `G32` (home, QGL, home, park). Orca's stock Voron start G-code heats first with `M190` and `M109`, before the macro. | Nothing | No / No (Mainsail's `mainsail.cfg` renames PAUSE to `PAUSE_BASE`) |
| Ellis' print tuning guide | `PRINT_START BED= HOTEND= CHAMBER=` | A template: home, `M190`, `TEMPERATURE_WAIT` for the chamber, `M109`, home Z; the person adds QGL and mesh. Tells PrusaSlicer users to add `M104 S0` and `M140 S0` so the slicer doesn't heat first. | Nothing | No / No |
| RatOS (v2.x macros) | `START_PRINT EXTRUDER_TEMP= BED_TEMP= CHAMBER_TEMP= X0= Y0= X1= Y1=` | `CLEAR_PAUSE`, home if needed, chamber heat-up, `M190`, preheat nozzle to 150 with `TEMPERATURE_WAIT`, adaptive mesh, park, `M109`, prime line. User hooks around each step. | M117 and RESPOND: "Heating bed...", "Heating Extruder...", "Printing..." | Yes, `PAUSE_BASE` / Yes (pause, unload, "Please load new filament and resume") |
| jschuh/klipper-macros | `PRINT_START BED= EXTRUDER= CHAMBER= MESH_MIN= MESH_MAX= LAYERS=` (also takes `BED_TEMP`/`EXTRUDER_TEMP`), or five `_PRINT_START_PHASE_*` lines | `CLEAR_PAUSE`, bed overshoot and settle (skipped when the bed is already at target), `M191`, home, QGL or Z tilt, mesh, nozzle, purge. **Sections are lower case** (`[gcode_macro print_start]`, `[gcode_macro m600]`). | Its own status macros, no M117 | Yes, `_KM_PAUSE_BASE` / Yes (pause, unload) |
| KAMP (adaptive mesh and purge) | Whatever the person's macro is called | Overrides `BED_MESH_CALIBRATE` (rename to `_BED_MESH_CALIBRATE`) and adds `LINE_PURGE`/`VORON_PURGE`, called from inside their PRINT_START. Klipper now has `BED_MESH_CALIBRATE ADAPTIVE=1` itself. | Nothing | No / No |
| Sovol SV08 (stock) | `START_PRINT`, no parameters | Reads the heater targets the slicer set, `CLEAR_PAUSE`, home if needed, `M190`/`M109` (redefined as `TEMPERATURE_WAIT` within 1 °C), QGL if not applied, adaptive mesh. Orca's SV08 start G-code homes before it and heats and purges after it. | M117 "Bed heating...", "Printing now!!!" | Yes, `PAUSE_BASE` / Yes (`PAUSE STATE=filament_change`) |
| Creality K1 (stock, rooted) | `START_PRINT EXTRUDER_TEMP= BED_TEMP=` | `CLEAR_PAUSE`, then Creality's own closed `CX_*` commands: rough home with heating, nozzle wipe, leveling, purge line. | Little | Yes / No |

What they share: almost everyone heats with blocking waits, so Cancel waits everywhere. Four of the
seven call `CLEAR_PAUSE` at the start. Most redefine PAUSE, RESUME and CANCEL_PRINT, under at least two different
base names. Many define M600, in either case. Their steps are what make their first layer theirs:
probing temperature, docking, wiping, which mesh, which purge.

## What Klipper does with a second macro of the same name

Tested, not guessed: Klipper master `461c4e3` (30 September 2026), batch mode in Docker, with Mainsail's
`client.cfg`. The test configs are in the spike's scratchpad, not in this repo.

- **Same section name, same case** (`[gcode_macro M600]` twice): no error. Klipper's config parser runs
  with `strict=False`, so the two sections merge and the file read later wins, option by option. Ours
  after theirs replaced their M600 without a word; theirs after ours replaced ours.
- **Same name, different case** (jschuh's `[gcode_macro m600]` and our `[gcode_macro M600]`): Klipper
  refuses to start, `gcode command M600 already registered`. Section names are case-sensitive; command
  names are not.
- **Wrapping a macro with `rename_existing`** (`[gcode_macro PRINT_START]` with `rename_existing:
  _THEIR_PRINT_START`): Klipper refuses to start, `Existing command 'PRINT_START' not found in
  gcode_macro rename`. The two sections merged into one, so there was nothing left to rename.
  `rename_existing` only renames commands that aren't the same section: built-ins, or a macro whose
  section name is written in another case. Writing ours as `[gcode_macro print_start]` did wrap theirs,
  in either order, but that leans on undocumented case handling.
- **An unknown command in a file** is a note, `Unknown command:"X"`, and the print carries on.

## Three ways to meet their start macro

**A. A separate macro that replaces theirs** (as drawn). The slicer line calls `ELYIR_BENCH_PRINT_START`
instead of their PRINT_START, and ours does everything: heat, home, level, mesh, purge.

**B. Wrap theirs.** The include takes over `PRINT_START` and calls theirs under another name. No slicer
change.

**C. Run before theirs** (recommended). `ELYIR_BENCH_PRINT_START` above their start G-code heats while
paused; `ELYIR_BENCH_PRINT_START_DONE` below it finishes. Theirs runs untouched in between.

| | A. Replace | B. Wrap | C. Before theirs |
|---|---|---|---|
| Their own steps (docking, Tap temperature, wipe, adaptive mesh, purge, lights) | **Lost.** Ours can't know them. Prints differ from their usual ones, silently. | Kept | Kept |
| Getting-ready steps | All of ours | Ours while heating, then theirs as one block | Ours while heating (`warming`, `soaking`), then theirs as one block (`own`), steps from their M117s |
| Cancel while warming | Yes | Only if the slicer doesn't heat before the macro. Orca's stock Voron and PrusaSlicer's automatic heat-up both do. | Yes; ours is the first line |
| Keep the first layer | Yes | Yes | Yes, applied after their start, so their homing and offsets come first |
| Slicer change | Their start line rewritten | None | Two lines added; nothing of theirs changes |
| Their files without the change | Print as before | **All changed**, including every file they already have | Print as before |
| Klipper loads it | Yes | Only by the case trick, chosen per printer | Yes; no shared names |
| Double homing, double mesh | Yes, if they keep their line too | No | No |
| Their `CLEAR_PAUSE` at the start (RatOS, jschuh, SV08, K1) | No issue | **Breaks it**: their macro runs while the file is paused, clears the pause, and the file never resumes | No issue; the file has already resumed |
| Parameter names | Ours must cover every slicer | Must accept all of theirs and pass them on | Ours only; theirs keep theirs |
| Removing it | Their slicer line must go back | One tap | One tap; files with the two lines still print (Klipper skips them) |

## Recommendation

C. It keeps the one thing a stranger cares about most, their own first layer, because their whole start
sequence still runs. It gives the two things only we can add: Cancel during the long wait, and the kept
first layer, applied after their start so it lands on top of whatever they found. It never shares a name
with their config, so it can't merge into or clash with their macros, and their existing files are never
changed. B touches every print they have, can't be made cancellable when the slicer heats first, needs
an undocumented case trick to even load, and breaks on the common `CLEAR_PAUSE`. A loses their steps.

What C gives up: the steps inside their start G-code are one block (`own`), shown from their M117s if
they send any. Most say little; the step reads "Leveling" until DONE. That's the same as today without
anything added, and better at both ends.

## What the draft does

`printer/klipper/elyir-bench.cfg`, written for a stranger reading it in Mainsail's editor.

- **`ELYIR_BENCH_PRINT_START BED= EXTRUDER= [CHAMBER=]`.** Also takes `BED_TEMP`, `BEDTEMP`,
  `EXTRUDER_TEMP`, `HOTEND`, `HOTEND_TEMP`, `NOZZLE`, `CHAMBER_TEMP`, so a copied line works. Without a
  bed temperature it uses the bed's target. Sets the bed, the nozzle to a warm 150 (`nozzle_warm`, or
  the print temperature if lower), pauses the file and starts a 1-second timer. Their start G-code takes
  the nozzle the rest of the way, at the temperature and moment they chose (Tap users probe at 150).
- **The pause** uses the command their PAUSE macro renamed, read from
  `configfile.settings['gcode_macro pause'].rename_existing` (`PAUSE_BASE` with Mainsail, Fluidd, RatOS
  and Sovol; `_KM_PAUSE_BASE` with jschuh; plain `PAUSE` with none), so nothing parks an unhomed head.
  RESUME the same way.
- **The timer** (`_ELYIR_BENCH_PRINT_START_TICK`): `warming` until the bed is within 1 °C and the nozzle
  within 2 °C; `soaking` while waiting for the chamber (capped by `chamber_max`, given up after
  `chamber_timeout`) or a timed soak; then it resumes the file and sets `own`. Cancelled, finished or
  failed: it stops, and if that happened while the heaters were still ours it turns them off (a
  CANCEL_PRINT macro that stops partway leaves them on; see the risks). Resumed by hand: it hands over
  (their start G-code heats the rest). A heater switched off, or longer than `max_minutes`: it cancels.
- **`home_first`** (off unless set) homes before heating, for configs whose CANCEL_PRINT moves the
  head without checking it's homed.
- **`ELYIR_BENCH_PRINT_START_DONE`** applies the kept `first_layer_z` with `SET_GCODE_OFFSET Z_ADJUST`
  (only when `first_layer_against` is `"scan"`, only up to 0.5 mm), remembers it as `applied_z`, clears
  the stage and says `M117 Printing...` (a marker today's app already reads). The next
  `ELYIR_BENCH_PRINT_START` takes `applied_z` back off before their start G-code runs. A Klipper restart
  zeroes both the offset and the variable, so they stay in step. Missing DONE line: the stage ends at
  layer 1 when the slicer reports layers, else when the print ends.
- **State** is `gcode_macro _ELYIR_BENCH_PRINT_START` (`stage`, `bed`, `warm`, `chamber`, `applied_z`, ...),
  not `_PRINT_START`, so it can't merge with anyone's own `_PRINT_START`, our printers' included.
- **Settings** are `[gcode_macro _ELYIR_BENCH_PRINT_START_SETTINGS]`: `nozzle_warm`, `chamber_max`,
  `chamber_sensor` (empty finds one named chamber or enclosure), `chamber_timeout`, `soak_minutes`,
  `max_minutes`, `home_first`. To change one, the person repeats the heading and that line in printer.cfg below the
  include; Klipper's merge makes theirs win. No tap: that stays with our own PRINT_START.
- **M600** is a marked section at the end: a console line naming the color change, then their `PAUSE`
  (which parks). The installer leaves it out when the printer has any M600.
- It uses `action_respond_info`, never `RESPOND`, so it doesn't need `[respond]`. It needs only what
  Moonraker already requires: `[virtual_sdcard]`, `[pause_resume]`, `[display_status]`.
- No `_CLIENT_VARIABLE` resume guard (ours sets one): it would merge with theirs. Resuming early just
  hands over instead.

Run in Klipper `461c4e3` (batch mode, a real config parser and macro engine, no hardware): loads beside
Mainsail's `client.cfg`, beside a jschuh-style lower-case `pause`/`resume`, and on bare Klipper; a file
pauses at `warming`, resumes, runs their PRINT_START, applies a kept -0.050 mm, clears the stage;
`CANCEL_PRINT` while warming cancels at once and puts the idle timeout back; `RESUME` by hand hands
over; the chamber wait finds `temperature_sensor Chamber` and caps 60 at a `chamber_max` of 45 set by
an override below the include. Not tested: the timed parts (soak, chamber give-up, `max_minutes`),
because batch mode's print clock doesn't move. Our own PRINT_START uses the same clock live.

## What the app needs

- Read `gcode_macro _ELYIR_BENCH_PRINT_START` (`stage`, `applied_z`) and
  `gcode_macro _ELYIR_BENCH_PRINT_START_SETTINGS` (`chamber_max`) beside today's `_PRINT_START` names,
  ours first. One helper instead of the direct reads of both names spread through the file.
- Map `own` to the leveling step in `PRINT_START_STAGES`, and let `_art_stage()` fall back to the
  M117 drawing when a stage has no picture of its own (it returns `None` today).
- Count the stage clearing from `own` as the print starting, not only the M117 marker.
- The stranger gap above: without layer numbers or a "Printing" message, decide printing some other way
  (the first layer's height from the file's metadata, or the head reaching it after the start).
- Decide whether the kept first layer comes off when the print ends (`SET_GCODE_OFFSET Z_ADJUST=-applied_z`
  and zero `applied_z`, in the same step that takes the nudges back out). Today it stays until the next
  Elyir Bench start, so a print from their own slicer in between gets it too.
- The slicer service: once the include is in, wrap the printer's start G-code with the two lines,
  instead of renaming their PRINT_START (the board's "switch to ELYIR_BENCH_PRINT_START"). `TOOL=`
  still goes on their own PRINT_START line.

## What the installer must do before offering it

1. Read the config Klipper loaded, not printer.cfg's text: Moonraker's `configfile.config` covers every
   included file and glob.
2. Check our names are free, in any case: `gcode_macro elyir_bench_print_start`,
   `elyir_bench_print_start_done`, `_elyir_bench_print_start`, `_elyir_bench_print_start_settings`,
   `_elyir_bench_print_start_step`, `_elyir_bench_print_start_go`, `_elyir_bench_print_start_stage`,
   `_elyir_bench_print_start_end`, `delayed_gcode _elyir_bench_print_start_tick`. A clash means no offer.
3. M600: if any `gcode_macro m600` exists (any case), write the file without the M600 section. The
   person's M600 stays theirs; the app still recognizes "load new filament" and "color change".
4. `[save_variables]`: never add a second one (it would merge and move their file). Without one, Keep
   isn't offered; a later version could offer a variables file as its own question.
5. Turn on `home_first` (in the generated file) when their CANCEL_PRINT moves the head without a
   homing check; set `nozzle_warm` from a probing temperature it recognizes.
6. Show the include line and the whole file, add the line above the `#*#` SAVE_CONFIG block, restart
   Klipper only when it's idle, and check `ELYIR_BENCH_PRINT_START` is in `gcode.commands` afterwards. If
   Klipper doesn't come back ready, take the line out and restart again, then say what happened.
7. Show the slicer change, below, with their own start G-code filled in when their recent files carry it
   (Orca writes `machine_start_gcode` in each file's config block; PrusaSlicer and SuperSlicer write
   `start_gcode`; Cura writes nothing usable).

## The slicer start G-code to show

The lines go above and below what's there. Nothing in between changes.

**OrcaSlicer** (Printer settings, Machine G-code, Machine start G-code). With the Klipper G-code flavor,
Orca adds no heat-up of its own before the start G-code (checked in Orca's `GCode.cpp`).

```gcode
ELYIR_BENCH_PRINT_START BED=[bed_temperature_initial_layer_single] EXTRUDER=[nozzle_temperature_initial_layer] CHAMBER=[chamber_temperature]
; ... your start G-code, as it is ...
ELYIR_BENCH_PRINT_START_DONE
```

**PrusaSlicer** (Printer settings, Custom G-code, Start G-code). PrusaSlicer heats and waits before the
start G-code unless the start G-code sets the temperatures itself; the two `S0` lines stop that, before
ours turns the heaters on. If your start G-code already begins with `M104 S0` and `M140 S0`, move them
up here instead of repeating them.

```gcode
M104 S0
M140 S0
ELYIR_BENCH_PRINT_START BED=[first_layer_bed_temperature] EXTRUDER=[first_layer_temperature[initial_extruder]]
; ... your start G-code, as it is ...
ELYIR_BENCH_PRINT_START_DONE
```

**SuperSlicer** (same place as PrusaSlicer):

```gcode
M104 S0
M140 S0
ELYIR_BENCH_PRINT_START BED=[first_layer_bed_temperature] EXTRUDER={first_layer_temperature[initial_extruder]+extruder_temperature_offset[initial_extruder]} CHAMBER=[chamber_temperature]
; ... your start G-code, as it is ...
ELYIR_BENCH_PRINT_START_DONE
```

**Cura** (Preferences, Printers, Machine Settings, Start G-code). Cura skips its own heat-up when the
start G-code names these settings, as this line does. Cura's build volume temperature is usually set
even without a chamber; `chamber_max` (0 unless changed) caps it.

```gcode
ELYIR_BENCH_PRINT_START BED={material_bed_temperature_layer_0} EXTRUDER={material_print_temperature_layer_0} CHAMBER={build_volume_temperature}
; ... your start G-code, as it is ...
ELYIR_BENCH_PRINT_START_DONE
```

## Open risks

- **Conditional soaks in their macro.** Some only soak when the bed starts cold (jschuh skips its
  overshoot and settle when the bed is at target). With the bed already hot, that soak is skipped.
  `soak_minutes` covers it, but nobody will know to set it. The installer could read known settings
  (jschuh's `start_bed_heat_delay`, RatOS's `start_print_heat_chamber_bed_temp`) and suggest one.
- **The warm nozzle.** If their probing temperature is below 150 (`nozzle_warm`), their `M109` waits
  for it to cool, a minute or so. RatOS uses 150; Tap macros 150; jschuh and K1 can differ.
  The installer could set `nozzle_warm` from what it finds.
- **Their CANCEL_PRINT during our pause, on an unhomed printer.** Mainsail's and Fluidd's check homing
  first; others don't. Sovol's cancels, then lifts Z: on an unhomed head Klipper stops it with "Must
  home axis first" before its TURN_OFF_HEATERS (seen in the batch run with a copy of it). The timer then
  turns the heaters off. RatOS's runs END_PRINT first, which turns the heaters off and then retracts and
  lifts: it fails before the actual cancel, so the print stays paused. jschuh's restores a pause state
  only its own PAUSE saves, so it errors after cancelling (the print is cancelled; the error is
  noise). The fix for RatOS and Sovol is `home_first`, which the installer should turn on when it finds
  their macros, or any CANCEL_PRINT that moves without checking `homed_axes`. With it on, Cancel in the batch run
  worked against the Sovol copy. The heaters-off path itself can't be shown in batch mode (any error
  ends the run).
- **Not on a real printer yet.** Next: a KIAUH-only card with Mainsail, then one friendly tester. The
  timed branches especially.
- **The kept first layer stays on between prints** (see the app list).
- **Prints that never say they've started** (the stranger gap) make Now wrong for the whole print,
  include or not. Worth fixing before any tester.
- **The public name.** The export turns `elyir-bench.cfg` into `{name}.cfg` by its path rule, while the
  board says `[include elyir_bench.cfg]`. Add a rule like the `.py` one if the underscore is wanted.
- **Multi-tool printers** (IDEX, toolchangers) weren't looked at; `EXTRUDER` is the first tool only.

## Sources

- `printer/elyir_bench_intent.py`; our shared PRINT_START (`common/print_start.cfg` in the printer config).
- Voron 2.4 sample config: https://raw.githubusercontent.com/VoronDesign/Voron-2/Voron2.4/firmware/klipper_configurations/Octopus/Voron2_Octopus_Config.cfg
- Ellis' guide, passing slicer variables: https://raw.githubusercontent.com/AndrewEllis93/Print-Tuning-Guide/main/articles/passing_slicer_variables.md
- RatOS macros: https://raw.githubusercontent.com/Rat-OS/RatOS-configuration/v2.x/macros.cfg
- jschuh/klipper-macros: https://raw.githubusercontent.com/jschuh/klipper-macros/main/start_end.cfg and `pause_resume_cancel.cfg`, `filament.cfg` beside it
- KAMP: https://raw.githubusercontent.com/kyleisah/Klipper-Adaptive-Meshing-Purging/main/Configuration/Adaptive_Meshing.cfg
- Sovol SV08: https://raw.githubusercontent.com/Sovol3d/SV08/main/home/sovol/printer_data/config/Macro.cfg
- Creality K1: https://raw.githubusercontent.com/CrealityOfficial/K1_Series_Klipper/main/config/K1_CR4CU220812S12/gcode_macro.cfg
- Mainsail and Fluidd client macros: https://raw.githubusercontent.com/mainsail-crew/mainsail-config/master/client.cfg, https://raw.githubusercontent.com/fluidd-core/fluidd-config/master/client.cfg
- Orca's stock start G-code: `resources/profiles/Voron/machine/fdm_klipper_common.json`, `Sovol/machine/Sovol SV08 0.4 nozzle.json`, `Creality/machine/Creality K1 (0.4 nozzle).json`, and `src/libslic3r/GCode.cpp` in https://github.com/SoftFever/OrcaSlicer
- Klipper `461c4e3`: `klippy/configfile.py`, `klippy/extras/gcode_macro.py`, `klippy/gcode.py`, `klippy/extras/pause_resume.py`
