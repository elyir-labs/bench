# Slicing without the settings

A person says what the print is for and which spool to use. The slicer works out the rest from presets
that are already trusted, and keeps a list of every setting it changed and why. That list is the
Advanced door: nothing is hidden, it just isn't asked.

The engine is OrcaSlicer's command line. Elyir Bench never slices anything itself.

## What gets decided, and by whom

| Comes from | Examples | Asked? |
|---|---|---|
| The printer | its Orca machine preset, the plate on the bed, how many slots | Never. Set once in the config. |
| The spool | material, colour, which slot | Known from the filament unit, or picked. |
| The purpose | Quick draft, Everyday, Looks best, Strong | The one question. |
| A short list of settings | layer height, walls, inside and its pattern, solid top and bottom, brim, smooth top, seam, supports from the plate only (`EDITABLE`) | Never asked. Changed on Every setting, for one print or kept for every print of that purpose on the printer (`elyir-bench/slice_usual` `purposes`; `design/edit-settings/`, C). |
| Supports | normal, tree or off | The person's usual kind (kept in Moonraker, `elyir-bench/slice_usual`), else the kind the printer's process preset prints. Picked per print from pictures of each kind's real supports (`design/supports/`, A). |

Each purpose is a handful of process settings on top of the printer's base process
(`0.20mm Standard @Voron` on Workshop, the one its real prints use). They live in `PURPOSES` in
`slicer/elyir_bench_slice.py`, each with the sentence the Advanced door shows.

## Run it

```bash
cd slicer
~/.venvs/elyir-bench-door/bin/python slice_service.py --config slicer.example.json
#   http://127.0.0.1:8095/slice/options
```

`slicer.example.json` describes Workshop and points at the OrcaSlicer on this Mac. Profiles are searched in
order and the first folder that has a name wins, so the person's own presets go before the bundled
ones.

Tests: `~/.venvs/elyir-bench-door/bin/python -m pytest -q slicer/tests`. One of them runs the real Orca
when it is installed.

## API

| Call | What |
|---|---|
| `GET /slice/options` | purposes (id, label, summary), supports (`auto`, `normal`, `tree`, `off`; auto keeps the preset's kind), printers with their materials, slot count, bed size [x, y, z] in mm, base process and `supports` (the kind that process prints, `normal` or `tree`), `unit` (it has a filament unit), `purges` (what Between colors offers, its usual first) and `change_seconds` (one color change by the unit); `editable` [{key, label, kind (`number` or `choice`), min, max, step, unit, default, choices [[value, name]], help}] |
| `POST /slice/models` | multipart: `model` (.stl .obj .step .3mf). Kept for a day. Answers its id, name and size in mm (none for STEP), so four purposes and every change after share one upload. A 3MF is read as its parts (`models`, one each), unless it brings its own colors: then it's kept whole and answers `colors` {colors [{color, material, used}], painted, heights [{z, to}]} (see Several colors). |
| `POST /slice` | JSON: `parts` [{`model` (an id from above), `copies` (1 to 200), `scale` (0.84 = 84%, STL and OBJ only), `lay` (`file` or `flat`), `brim` (`auto`, the default, or `none`, `ears`, `all`)}], `printer`, `purpose`, `supports`, `material`, `color` (#RRGGBB), `slot` (1-based), `thumbnail` (a PNG, base64, put in the G-code the way slicers do), `orient`, `kept` and `settings` ({key: value} from `editable`: the person's own for this purpose, then for this print; applied after the purpose, supports and spool, and refused with a sentence when a key isn't on the list or a value is out of range). Several colors: `spools` [{`material`, `color`, `filament`, `slot` (1-based), `hand` (swapped in by hand)}] in Orca's filament order, each part's `spool` (0-based, which of them it prints in), `purge` (`chute`, `tower`, `both` or `swap`; the printer's usual when left out) and `one_after_other`. One part can still be sent as `model`, `scale`, `lay`. Or multipart with the model itself. Answers 202 with the job, or 400 saying what's wrong. |
| `POST /slice/fit` | JSON: `printer`, `parts`, `part`: how many of that part fit on one plate with the others as they are (`fits`), whether the others still fit (`others_fit`), and `at_least` when every copy tried fitted. With `part: null` the parts as they are: `counts` (each part's copies on plate 1), `plates`, `fits` (all on plate 1), for several shelf models on one bed (docs/bench.md, Several at once). Orca only arranges; nothing is sliced. |
| `GET /slice/{id}/supports` | The first plate's supports as lines to draw: `count`, `width` (mm to draw them, wider when layers were left out to keep it under ~12,000 lines) and `segs` (base64 little-endian int16s, x0 y0 x1 y1 z per line in tenths of a mm on the bed). Read from the G-code the first time it's asked for. |
| `GET /slice/{id}` | `state` queued, slicing, done, failed or cancelled; `parts` (each with `brim_pick` {kind, why, by (`auto`, `you`, `kept`), rule}: the brim it printed with and why); `changes` [{key, label, value, was, why, source}]; `estimate` {seconds, time, grams, layers} for the first plate; `plates` [{plate, seconds, time, grams, counts (per part), gcode}]; `placed` [{part, x, y, turn}] where Orca put each copy on the first plate (the centre of its box in mm, turned anticlockwise in degrees); `supports_added`; `values` and `before` (every editable setting as it prints, and before the person's own changes); with several colors, `colors` {spools [{spool, parts, first, swaps (seconds into the print), changes}], changes [{layer, at, to, hand, purge (mm)}], hand_swaps, unit_changes, changes_seconds, grams (per spool)} and `estimate.changes_seconds` (the changes' own time, which Orca's estimate leaves out); `warnings`; on failure `error` for people and `error_detail` for Advanced |
| `GET /slice/{id}/gcode` | the first plate's file, named the way Orca names them (`bracket_ASA_48m34s.gcode`; `bushing_x25_1of2_PETG_2h26m.gcode` for 25 copies on the first of two plates) |
| `POST /slice/{id}/send` | uploads every plate to the printer's Moonraker. `{"print": true}` starts the first; nothing starts otherwise. With more than one plate, `elyir-bench/next_plates` in Moonraker's database says which file follows which, so Now can offer the rest when a plate is done. |
| `DELETE /slice/{id}` | not wanted any more: dropped from the queue, or stopped mid-slice. The app does this whenever a change makes a slice stale. |

One slice runs at a time, under `nice`. A slice that takes 15 minutes is stopped.

## Several colors

`design/multi-color/` (B, the Colors card). A plate prints with one spool per color (`spools`), each from a slot of
the filament unit or swapped in by hand. Colors come from a spool per part (`spool` on each part) or from a 3MF that
brings its own (an object or part in its own filament, painting, or a change at a height): that 3MF is kept whole,
goes on a plate of its own, and wants a spool for each of its filaments in its order (unused ones too).

Orca gets one filament preset per color (`filament.json`, `filament_2.json`...; `--load-filaments a;b`) and each
model's color (`--load-filament-ids`); a 3MF's own colors and the arranged 3MF of the brim path carry it per object
(`extruder` in `model_settings.config`). Its change G-code is set to

```
ELYIR_PURGE LENGTH=[flush_length] FROM=[previous_extruder] TO=[next_extruder]
T[next_extruder]
```

and because that writes a `T` line itself, Orca leaves out its own. `[flush_length]` is Orca's purge for that pair of
colors, worked out from them (white to black 33 mm, black to white 233 mm). After slicing, `assign_spools` points
each change where its color comes from:

- **A slot:** `T<slot>`, with `ELYIR_PURGE LENGTH=<mm>` before it when the chute takes the purge.
- **By hand**, or any change on a printer without a unit: `;COLOR_CHANGE,T<n>,#RRGGBB`, `; elyir: by hand`, `M600`.
  The printer's color-change sheet reads the color from the marker; the mark says the swap was chosen by hand.
- **The first color** is loaded by `PRINT_START TOOL=<slot>` when the start G-code passes `TOOL=`; otherwise
  Orca's first change stays, as the slot's `T`. On a printer with a unit it needs a slot, whichever color Orca
  prints first.

Purge (`purge`): `chute` (no tower; the printer purges), `tower` (Orca's tower takes the purge), `both` (a tower
with `purge_in_prime_tower` off: Orca still writes the purge length, and the tower only primes) and `swap` (pushed
through at a swap by hand, no tower). Measured on the Mac with Orca 2.3 on the Voron presets: a figure standing on its
base in two colors (one change) 26 min one color, ~28 min with the chute, ~31 min both, ~35 min tower; separate parts
change on every layer they share (62 changes for two covers side by side, one when printed `one_after_other`).

A 3MF with colors also comes back as pieces to draw (`pieces` [{piece, name, filament}], each an STL at
`GET /slice/models/{id}/piece/{k}`): its triangles split by filament, painting read per triangle (`paint_state`,
the first leaf where the brush split one), so the app draws it in its colors. The app's side is the Colors card
(`app/src/slice/colors.ts`, `ModelScreen.vue`).

On the printer: `ELYIR_PURGE` (in `units/klipper/elyir_units.cfg`) keeps the length until the next `ELYIR_TOOL`,
which hands it to the filament-unit service; the service passes it to the after-change macro as `LENGTH=`
(the printer's own macro decides what to do with it: the shared `NOZZLE_POST_TOOL_CHANGE` purges at least 30 mm).
A printer without that file (KlipperACE) answers `Unknown command` to `ELYIR_PURGE` and carries on. The color-change
sheet reads the "by hand" mark (`colour_changes_in`, `hand`): that change is planned as a pause, never onto a
loaded spool, and Print's spool check leaves its color out ("Yellow PLA, swapped in by hand").

Not yet: files that fit together printed as one, PrusaSlicer's 3MF colors, painting and a change at a height chosen
in the app.

## More than one on the plate

`design/plate/` (A). Each part goes to Orca named `p0__`, `p1__`... and repeated once per copy, in one run with
`--arrange 1`. Orca puts what doesn't fit on plate 2, 3 and so on, and every plate is read: its G-code, and from
the 3MF exported in the same run (`--export-3mf`), which part landed on which plate and where. A 3MF transform
is row-vector (`x' = x*m00 + y*m10 + tx`), applied to the part's file as given, so the centre of a part's box
lands at its box centre times the matrix. The 3MF is deleted after reading: it carries every plate's G-code again.
Orca's arrange turns parts to pack them (bushings by 45° steps); `placed` says by how much.

Measured on the Mac with Workshop's presets: the cutting arm, knife holder and blade holder sliced together in 1.4 s
(20 m 42 s of printing against 26 min apart), and 30 bushings in 8.4 s, as 25 (2 h 26 m) and 5 (29 m).

## Pressure advance (3 October 2026)

Found while watching gray PETG string across the vent on Workshop: pressure advance had never been on. It's commented
out in `printer.cfg`, Orca's PETG preset has `enable_pressure_advance = 0`, and `CUT_TIP` set it to 0 and never put it
back (fixed in the printer's Klipper config). PETG also got its own settings here (`MATERIALS`: 235 °C, 1 mm at 40 mm/s, spiral
lift, travel around over the part).

**The test:** `POST /slice/test {"test": "pressure_advance", ...}` slices a 50 mm hollow tower (one wall, no infill,
square corner velocity 1, acceleration 500) with a tick on the front every 4 mm; `TUNING_TOWER` raises pressure
advance by 0.01 per tick (0 to 0.08). Count the ticks up to where the corners are sharpest without a gap: tick n is
0.01 × n. That value goes in `[extruder] pressure_advance` (every print, Orca's too) or, later, per material.

**Next, to make it seamless** (not built): every material starts from a sensible default for the printer's extruder,
applied automatically; "Tune this spool" in Care or the spool's sheet prints the tower and asks which tick looks best
(one tap), stored per material and per RFID spool and applied whenever that spool prints; later the camera suggests the
tick. Fully automatic needs a pressure sensor Workshop doesn't have.

## Next: print a past file in another material (noted 3 October 2026, not built)

Asked: a model sliced in PLA turns out to need ASA or PETG; today that means finding the file and uploading it again,
though a copy is on the printer. A G-code file can't be turned back into a model, but a plate sliced here can: the
slicer already remembers what each sent plate was made of (`elyir-bench/sliced`) and keeps the models a day.

- Keep a plate's models as long as its G-code is on the printer (not a day), and drop them when the file is deleted.
- A file's sheet in the Print tab and the library gets **Print in another material**: Ready opens with the same parts,
  counts, sides and sizes, and the spool picker open; the new material's own settings (`MATERIALS`, its preset, its
  pressure advance once tuned) apply.
- Files sliced in Orca carry no model: their sheet says to send it again from Orca.
- Draw it in `design/` first (the file sheet changes).

## A brim for each part (`design/brim/`, A, built 4 October 2026)

Watching the vent and vent plug print on Workshop: the brim is sometimes needed (small parts), sometimes far too
much (big parts), sometimes not wanted at all. Every slice used to get Orca's `auto_brim` for the whole plate; on the
vent print 70% of the first layer was brim, and on the vent plate it gave the CAN mount, the part most likely to tip,
nothing.

- **Picked per part, said, changeable.** `brim_pick()` decides from the side that's down, measured by `sides()`
  (`down_side()`, at the part's size): **all round** when it's tall for its base (height over 1.5 × the narrow side) or
  touches less than 3 cm²; **corner pads** (`brim_ears`) for long parts (over 60 mm) in ASA or ABS; otherwise **none**.
  Each pick comes back with a sentence (`64 mm tall on a 25 mm base: a rim keeps it standing`) and `rule`, what the
  rule picks, so the sheet can tag it after someone picks another. A part's own `brim` beats a Brim kept from before
  (Every setting had one plate-wide Brim until now; it still counts, as the parts' default), which beats the rule.
- **Per object, from the command line.** Orca's CLI takes one brim for the plate, but a 3MF carries one per object in
  `Metadata/model_settings.config`, and `--slice 0` on that 3MF honors it with the presets loaded on top. When the
  parts agree, their brim goes in the preset and nothing changes. When they differ: one run only arranges
  (`brim_type = outer_only`, so there's room for a brim all round), `set_brims()` writes each object's own, and a
  second run slices the 3MF as arranged (`orca_slice_3mf`). The vent plate on the Mac: 0.5 s to arrange, 4 s to slice.
- **In the app**, each part's line says its brim (`Laid flat · Brim all round`), its sheet has a Brim row, and the
  Brim sheet draws the part's own first layer three ways (`src/slice/footprint.ts`: the triangles on the plate, their
  outline and holes, pads where the edge turns sharper than 125°, Orca's `brim_ears_max_angle`). Measured, not sliced,
  so it opens at once. Every setting lists `Brim · <part>`.
- **Later**: "Did a corner lift?" after a print, to tune the thresholds per material.

## What it does to the G-code

- **Says it's ours.** `; sliced by Elyir Bench` right after Orca's `; generated by` line, so the printer never
  learns how a person slices from a file Elyir Bench sliced (docs/slicer-profile.md).
- **The plate.** Orca chooses the bed temperature by plate type and defaults to Cool Plate. Some
  filament presets give 0 °C for Cool Plate (Workshop's Anycubic ASA does), so the bed never heats. The
  plate is a printer fact (`plate` in the config) and is always set.
- **The slot.** A one-filament slice always uses tool 0. The service rewrites `TOOL=0` in the
  `PRINT_START` line to the chosen slot. That only works when the machine's start G-code passes
  `TOOL=[initial_tool]` (Workshop's does; Orca's stock Voron one doesn't). When it can't, the job says so
  in `warnings`.
- **The colour.** The spool's colour goes in as `filament_colour`, so the printer's own pre-print
  check (`check_print`) matches the file against what's loaded, the same as for a file from Orca.

Tested against Workshop on 2 October 2026: a blue PETG job uploaded, Moonraker read it as an Orca file,
and `check_print` passed; an orange ASA job was refused with "This needs Orange ASA." Both were
deleted afterwards.

## Orca's command line, the hard way

- It won't take a user preset as it is. A preset that isn't `from: system` is looked up by its
  parent's name, and the process must list the printer in `compatible_printers`, or it exits with
  "process not compatible with printer". The service folds each preset's `inherits` chain into one
  file, marks it `system` and makes it compatible with that printer only (`cli_preset`).
- It writes no thumbnails, so a sliced file has no picture yet.
- `--scale` crashes it (exit 139). Scale the model before handing it over.
- Its reason for failing goes to `result.json` on Linux only. On a Mac it's in the log.

## On a printer's own Pi

Timed on Workshop (Pi 5, 4 GB) with Orca 2.4.2's arm64 AppImage: a 50-minute print sliced in 3.0 s and
a 14-hour print in 14.3 s, all four cores, about 0.9 GB at peak. Fast enough. But the AppImage is a
desktop build: on Pi OS Lite it needs about 130 Debian packages of GUI libraries it never uses when
slicing, and its launcher only looks for OpenGL in system folders, so the binary has to be run
directly with `LD_LIBRARY_PATH` set (`orca_env` in the config). A headless build of Orca's slicing
core would avoid all of that. A BTT Pi or a Pi 4 should get its slicing from somewhere else
([Slicing for other printers](#slicing-for-other-printers)).

Never slice at full speed beside a running print: Klipper's host timing comes first.

## The screens

`design/print-a-model/`, direction C, built: `/print/model` in the app (`app/src/pages/ModelScreen.vue`,
`app/src/slice/`). The app reads the model itself (STL, OBJ) to draw it in the spool's colour and to send
that drawing as the thumbnail, and finds the size before slicing, so a model that's too big is made to
fit before Orca sees it. The app reaches the service at `/slice` on its own origin: Vite proxies it in dev
(`SLICER_URL`, default 127.0.0.1:8095).

Try it on the Mac, nothing touched on a printer:

```bash
cd simulator && ~/.venvs/elyir-bench-sim/bin/python sim.py --port 7137 --scenario idle
cd slicer && ~/.venvs/elyir-bench-door/bin/python slice_service.py --config slicer.example.json --moonraker http://127.0.0.1:7137
cd app && VITE_MOONRAKER_URL=http://localhost:7137 npx vite --port 3017
#   http://localhost:3017/print?screen=phone   (localhost counts as the panel, which has no files to pick)
```

The simulator takes uploads like Moonraker (`/server/files/upload`), reads Orca's metadata and the
embedded picture, and plays the print when it's started.

## On a printer

`slicer: on` in `elyir-bench.conf`, then `elyir-bench apply` (or `./deploy.sh <host>`). Two installer steps:

- **slicer engine**: Orca's arm64 build (`ORCA` in `installer/elyir_bench.py`, pinned by checksum) unpacked
  to `~/elyir-bench/slicer/orca-<version>/`, and the desktop libraries it links (`ORCA_PACKAGES`) from apt.
- **slicer service**: `elyir-bench-slicer.service` on 127.0.0.1:8095 at idle CPU and I/O priority, so it
  only gets what Klipper doesn't want; nginx sends `/slice` on the app's port to it.

The printer's side lives next to `elyir-bench.conf`, where Mainsail's editor shows it and the config backup
picks it up:

```
~/printer_data/config/elyir-bench-slicer/
  printer.json    {"machine", "process", "plate", "tools", "materials": {"PLA": "<filament preset>", ...}}
                  with "learned": {"id", "at", "from_files"} when the printer wrote it from its own files,
                  "purge": "chute" when it pushes the old color out off the plate at a change, and
                  "change_seconds" (one change by its filament unit, 105 when left out)
  presets/        the person's Orca presets (Workshop: both of the owner's Orca user folders); they win over Orca's own
    0-learned/    learned from the printer's files (docs/slicer-profile.md); sorts first, so it wins
```

The service reads `printer.json` and the presets from that folder itself (the config names it, `home`), when they
appear and whenever they change, so what the printer learns from its files slices from the next request. Without
`printer.json` the service runs and says so (`/slice/options` answers 404 `{error, settings: false}`), and a
release is never rolled back for it.

**Freeze the presets as the desktop resolves them.** The printer's own Orca fills in any setting a preset
inherits from its bundled defaults, and those differ between Orca versions. On workshop (3 October 2026) Orca
2.4.2's Voron defaults gave `END_PRINT` instead of `PRINT_END` (nothing parked), 5 mm retraction instead of
0.8 and 500 mm/s² instead of 20 000. So export each preset fully resolved on the desktop and put it first:

```bash
slicer/export_presets.py --config slicer/slicer.example.json --printer workshop --out /tmp/workshop-presets
rsync -a /tmp/workshop-presets/ pi@workshop.local:printer_data/config/elyir-bench-slicer/presets/0-resolved/
ssh pi@workshop.local sudo systemctl restart elyir-bench-slicer
```

`0-resolved` sorts before the other preset folders, so it wins. Run it again after changing these presets
in Orca on the desktop.

**A parent is looked up in its child's own vendor** (fixed 5 October 2026). Bases like `fdm_klipper_common` and
`fdm_process_common` are in many vendors' folders with different values, and the first one found (Custom's) used to
win; Orca uses the Voron preset's own Voron base. Found by comparing presets rebuilt from Workshop's own G-code files
with its frozen ones (docs/slicer-profile.md): Workshop's `0-resolved` has Custom's `machine_max_jerk_x/y` 9 where the
desktop prints with 12, and `min_skirt_length` 4 where it prints with 0. Export the printers' presets again.

On a printer someone else set up, nobody freezes anything: the printer learns its presets from the profile at the
end of the person's own Orca files ([docs/slicer-profile.md](slicer-profile.md)), into `presets/0-learned/`.

## Slicing for other printers (4 October 2026)

Slicing is a service a printer uses, not something every printer has to run. Any Linux machine that can
run Orca slices for the printers that join it: a printer's own Pi 5 (Workshop), a NUC, or the house's
controller. A printer that can't run Orca (Desk's BTT Pi: Debian 11, glibc 2.31, 1 GB) still gets
Print a model, by naming a slicer elsewhere. Nothing about it is special to Desk.

```
phone ──/slice──▶ Desk's nginx ──(X-Elyir-Bench-Printer: desk)──▶ Workshop:8095 slicing service
                                                                 │ copies Desk's profile from
                                                                 │ Desk's Moonraker (config/elyir-bench-slicer/)
                                     Desk's Moonraker ◀── G-code ┘
```

What was decided, and why:

- **The printer stays the address.** The app always asks `/slice` on its own printer, and the printer's
  nginx sends it on. Phones, the Printers app and the door never learn where slicing happens, and moving
  the slicer to another box changes one line on the printer.
- **The printer owns its profile.** `elyir-bench-slicer/printer.json` and its frozen presets stay next to
  `elyir-bench.conf` on the printer, backed up with it and editable in Mainsail, wherever it's sliced. The
  slicer copies them from the printer's Moonraker when it joins, and again within a minute of a change
  (it looks when the app next asks for options). A printer that's off still slices with the kept copy.
- **Each printer has its own presets.** Two printers' "PLA @Voron" can differ (frozen from different
  machines in Orca), so presets are looked up per printer: its own folders first, then Orca's bundled
  ones, shared.
- **A request only sees its own printer.** The printer's nginx adds `X-Elyir-Bench-Printer: <id>`. Through
  it, options list only that printer, a slice is for it and is sent to its Moonraker, and nobody else's
  models or slices can be read. The app's old fallback (one printer offered → use it) can't pick Workshop's
  settings for Desk any more. A printer's own slicer gets the same header from its own nginx.
- **The slicer's owner says yes, on its own screen** (`design/slicing-elsewhere/`, A, 4 October 2026). A new
  printer's join is an ask (`PUT` answers 202 `{waiting}`), shown on the slicer's panel as the Allow card a
  phone gets ("Desk wants to slice here", `/slice/asks`). No is kept for a day, so an apply doesn't nag; so is
  Stop on the slicer's Care. A Bench Box (a machine with no printer of its own) has no screen yet, so it lets anyone on the home network join
  (`allow: anyone`), as Moonraker already does.
- **Nothing here ever rolls a release back.** A slicer that's off or refuses a printer is a note in the
  apply, and the app says "The slicer isn't answering. Is workshop.local switched on?" (nginx answers that
  itself, as JSON, when the slicer can't be reached; a name it can't find never stops nginx starting).

Settings, in `elyir-bench.conf`:

| on | setting | does |
|---|---|---|
| any printer (the default) | `slicer: auto` | here when this machine can run Orca; otherwise the best slicer found on the Wi-Fi (a Bench Box, then a Pi 5, then a Pi 4), asked once |
| a printer that slices for itself | `slicer: on` | Orca and the service run here (as before) |
| a printer that slices elsewhere | `slicer: workshop.local` (or `host:port`) | `/slice` goes there; `elyir-bench apply` joins it |
| a slicer that lends | `slice_for_others: on` | listens on the network (`0.0.0.0:8095`), printers may join |
| a box with no printer | `role: auto` | without Moonraker it's a **controller**: only the release, the Python runtime, Orca and the service, always lending |

Setting Desk up (what was done on 4 October 2026):

```bash
# on the Mac: freeze Desk's presets from the desktop Orca, as for Workshop and Studio
slicer/export_presets.py --config <a config with a desk printer> --printer desk --out /tmp/desk-presets
rsync -a /tmp/desk-presets/ biqu@desk.local:printer_data/config/elyir-bench-slicer/presets/0-resolved/
# printer.json beside it: machine Desk, tools 1, the same five materials as Studio
# Workshop's elyir-bench.conf: slice_for_others: on    Desk's: slicer: workshop.local
./deploy.sh workshop.local && SSH_USER=biqu ./deploy.sh desk.local
```

Finding a slicer: a slicer that lends writes `/etc/avahi/services/elyir-slicer.service`
(`_elyir-slicer._tcp`, TXT `name`, `kind`, `machine`), and a printer on `auto` asks for it with one mDNS question
from an ordinary port, which avahi answers straight back (a "legacy unicast" query): no avahi-utils, no Python
packages, Debian 11 included (tried from Desk: Workshop, Studio and the home hub answered). The slicer's name is
remembered (`state.json`), so "Workshop is off" is right while it's off; the printer's nginx answers that as JSON
`{error, slicer, off}`.

What a person sees (A): the Allow card on the slicer; "Asking Workshop to slice for Desk…" on the Print tab while it
waits; "Sliced on Workshop" under Ready's time; "Waiting for Workshop · It's slicing one of its own first." when the
queue is busy (`ahead`, `behind` on a queued slice); "Workshop is off." with Try again; a Slicing row in Care on
both sides, with Stop for each printer on the slicer. Pinned by `app/tests/slicing-elsewhere.test.ts`.

The slicer's side, on the network: `PUT /slice/printers/<id>` {name, moonraker} joins (the installer does
it on every apply), `GET` says whether it has and what it slices with, `DELETE` leaves. Joined printers
are kept in the service's work folder (`printers.json`, `printers/<id>/`), so a restart keeps them.

Orca is pinned for arm64 and amd64 (Ubuntu 24.04 AppImages, glibc 2.39). On an older system the slicer
steps say so and stay off rather than failing.

Not yet: Change on the Slicing row (the printer would have to rewrite its own `elyir-bench.conf` and apply,
which is the Elyir Bench agent's job); the Bench Box's own screen, and so a yes on a Bench Box (`design/` for the Bench Box is
next). The address is resolved when the printer applies, so a slicer that moves to another address is found
again on the next `elyir-bench apply` (with `auto`) or needs a DHCP reservation.

## Not done yet

- From away, the door would have to let `/slice` through for paired phones; until then the card is
  hidden away.
- 3MF input (MakerWorld and Printables files are mostly 3MF), and multi-colour files mapped to filament
  unit slots.
- Editing a setting from Every setting (2 October: maybe later; the rows are shaped for it).
- "How did it come out?": feedback after the print that adjusts the purposes and the filament presets.
