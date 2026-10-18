# Finish setting up: the contract

`design/getting-started/` (C, Ready first). After the install command, a phone lands on Now, already Ready, with one
**Finish setting up** card under Ready. This file is the contract between the printer's side (Moonraker component,
intent layer, installer, slicer) and the app, so both can be built at once. Names here are the private ones
(`elyir-bench`); the public copy renames them.

## What the intent carries (`GET /printer/intent`, and its live updates)

Two small additions, so the panel and the phone know when to show something without fetching more:

```jsonc
"setup": { "open": true },            // the phone shows the card while open; false once every row is done or dismissed
"printer": {
  ...,
  "screen_trial": null                 // or { "seconds_left": 108 } while the printer's screen is on trial
}
```

The **panel** shows the trial bar ("Keep Elyir Bench here?" · Going back in 1:48 · Back to KlipperScreen · Keep)
whenever `screen_trial` is not null. The **phone** shows the card whenever `setup.open` is true; the panel never does.

## `GET /printer/intent/setup`

Everything the card and its sheets need, fetched when the card is shown and after each action.

```jsonc
{
  "name": "Voron", "name_from": "mainsail",          // mainsail | hostname | you
  "secure_link": "waiting",                           // off | waiting (claimed, Elyir hasn't approved it yet) | on
  "rows": [
    { "id": "notify" },                                // the app decides done (this phone has push) or not
    { "id": "screen", "state": "offer" },              // see "The screen row"
    { "id": "works", "now": 3, "with_macro": 3 }       // the counts in the row's second line
  ],
  "dismissed": ["notify"],                             // rows the person closed with ×; the card hides them
  "works": {
    "board": { ... },                                  // `elyir-bench --json check`'s expectations(), as the installer saved it
    "features": [
      { "id": "core",      "group": "now",        "label": "Ready, printing, history, Care" },
      { "id": "runout",    "group": "now",        "label": "Filament runs out", "note": "Your runout sensor" },
      { "id": "camera",    "group": "now",        "label": "Camera" },
      { "id": "steps",     "group": "with_macro", "label": "The steps while it gets ready", "note": "Rough today, from your messages" },
      { "id": "cancel",    "group": "with_macro", "label": "Cancel while it warms up" },
      { "id": "squish",    "group": "with_macro", "label": "Squish the first layer more or less" },
      { "id": "chamber",   "group": "with_macro", "label": "Wait for the chamber to warm" },   // only with a chamber sensor
      { "id": "unit",      "group": "not_here",   "label": "Filament unit slots", "note": "No ACE Pro found" }
    ],
    "include": "off",                                  // off | on | adding | removing | failed
    "include_why": null,                               // with failed: what went wrong, in words
    "include_text": "[include elyir-bench.cfg]",
    "slicer_lines": {
      "before": "ELYIR_BENCH_PRINT_START BED=[bed_temperature_initial_layer_single] EXTRUDER=[nozzle_temperature_initial_layer]",
      "after": "ELYIR_BENCH_PRINT_START_DONE"
    }
  }
}
```

A feature is `now` when it works as things are, `with_macro` when the include would bring it (once the include is on,
these move to `now`), and `not_here` when this printer lacks the hardware. Groups with nothing in them aren't sent.
`works.board.differences` (the screen's animations, slicing) show at the end of the sheet as "On this board".

## Actions (`POST /printer/intent/action`, `{"action": ..., ...}`)

| action | does | refused when |
|---|---|---|
| `setup_name` `{name}` | the name Elyir Bench shows, at once and in elyir-bench.conf and moonraker.conf; never the printer's network name (Mainsail, their slicer and SSH know it by that); the Wi-Fi announcement and the slicer catch up at the next apply | empty or over 32 characters |
| `setup_dismiss` `{row}` | adds the row to `dismissed` (Moonraker DB `elyir-bench/setup`) | never |
| `screen_try` | installs the screen's parts if missing (`elyir-bench --json panel elyir-bench`; KlipperScreen stays on until they're in), switches the screen, starts the trial (120 s) | no screen, or no way to run it here (`works.board`) |
| `screen_keep` | ends the trial; the row is done | no trial running |
| `screen_back` | ends the trial and switches back (`elyir-bench --json panel klipperscreen`) | no trial running |
| `include_add` | `elyir-bench --json startmacro on`: writes `elyir-bench.cfg`, adds the include line, restarts Klipper | printing or paused |
| `include_remove` | `elyir-bench --json startmacro off`: takes both out, restarts Klipper | printing or paused |

A trial nobody answers goes back by itself at 0 s, exactly like `screen_back`.

### The screen row's `state`

| state | the row shows |
|---|---|
| `offer` | "Use it on Voron's screen" · KlipperScreen comes back with a tap · **Try it** |
| `fetching` | "Getting Voron's screen ready" · Fetching what it needs. KlipperScreen stays on until then. (no percentage: apt doesn't give one) |
| `trial` | "Trying it on Voron's screen" · Keep or go back on the printer's screen |
| `done` | ✓ "Voron's screen runs Elyir Bench" · Care › Printer screen to change |
| `kept_klipperscreen` | ✓ "Voron's screen stays on KlipperScreen" · Try again |
| `cant` | "Voron's screen stays on KlipperScreen" · `why` (e.g. "Debian 11 no longer offers the Chromium it needs. Nothing changed.") · OK (dismisses) |

The row isn't sent at all when the printer has no screen, or its screen already runs Elyir Bench from the install.

## The printer's side

- **Installer**: a `start_macro: off|on` setting and a `StartMacro` step. On: render `printer/klipper/elyir-bench.cfg`
  from the release into the config folder, leaving the M600 section out when any other config file defines M600 in
  any letter case; add `[include elyir-bench.cfg]` to printer.cfg after its last `[include ...]` line (or at the top);
  write `"start_macro": true` into `elyir-bench-slicer/printer.json` when it exists; FIRMWARE_RESTART through Moonraker
  when anything changed and nothing is printing. Off: take the line, the file and the flag out again. `elyir-bench
  startmacro on|off` sets it and applies only that step. `remove` turns it off first. The installer saves
  `expectations()` into `state.json` at each apply, for the component's `works.board`. The release carries
  `printer/klipper/elyir-bench.cfg` (scripts/build-release.sh).
- **Intent layer**: subscribe to `gcode_macro _ELYIR_BENCH_PRINT_START` (`stage`, `applied_z`). `warming` and
  `soaking` map like the shared PRINT_START's; `own` maps to leveling ("Your start G-code"); the stage going back to
  '' after `own` (ELYIR_BENCH_PRINT_START_DONE) means the print has started.
- **Slicer**: when printer.json has `"start_macro": true`, the machine start G-code is wrapped: the `before` line
  first, the person's start G-code unchanged, the `after` line last.

## The simulator

`simulator/sim.py` serves `/printer/intent/setup` and the actions above, with scenarios `setup_new` (a stranger's
printer just after the install command: card open, include off, a KlipperScreen screen offered) and `setup_trial`
(the panel on trial, 108 s left), so the app can be built and captured without a printer.

## As built on the printer's side

Where the printer's side (branch `gs-api`) fills in or differs from the above:

- **`fetching`** covers the whole `elyir-bench --json panel elyir-bench` run: the component can't tell the parts
  downloading from the switch itself. The trial (and its 120 s) starts when that run comes back.
- **`cant`** also shows before any try, instead of `offer`, when `works.board.differences` says the screen stays on
  KlipperScreen; `why` is then "This system can't run Elyir Bench on its screen. Nothing changed." After a failed try,
  `why` is the first sentence of the installer's reason, then "Nothing changed."
- **`name_from`** is `you` when the name matches neither Mainsail's `general.printername` nor the host name.
- **`setup.open`**: notify counts as done when any phone listens (`elyir-bench/phones` > 0); works counts as done when
  nothing is `with_macro` (the include is on, or the printer has our shared PRINT_START, whose steps already work).
- **Features** beyond the example: `runout` and `camera` are `not_here` with "No runout sensor found" / "No camera
  found" when absent; `runout` is `now` with "The filament unit" on an ACE printer without a sensor; `unit` is `now`
  with an ACE. The "Rough today" note is only on `steps` while it's `with_macro`.
- **`elyir-bench/setup`** holds `{"dismissed": [...], "screen": "done" | "kept_klipperscreen" | null}`, so a kept or
  declined trial survives a restart.
- **Actions** answer like the others (`ok`, `ran`, `intent`) plus `setup`, the same object as the GET. Refusals are
  Moonraker 400 errors in plain words.
- **Installer**: only a change to elyir-bench.cfg or printer.cfg restarts Klipper (the printer.json flag alone
  doesn't), and `ELYIR_BENCH_PRINT_START` must be in Klipper's objects afterwards, or the change is put back.

## Recorded while building the app

Where the app (branch `gs-app`) and the simulator settled something this file left open, or differ from it:

- **Actions go as the app sends every intent action**: `{"action": "setup_dismiss", "args": {"row": "screen"}}`. A
  refusal comes back as an error whose message the card shows as it is, so it should be words ("Not while it prints.").
- **`setup_name` `{name}`** is one more action: the card's "Change" (the last line, "Called Voron, from Mainsail ·
  Change") edits the name in place and sends it. The printer keeps it as its name and `name_from` becomes `you`. Refused
  when the name is empty. The simulator has it; the printer's side needs it too.
- **The card's ×** sends `setup_dismiss` for each row still on the card, so the card goes for good.
- **The `cant` row carries its words** as `why` in the row itself: `{"id": "screen", "state": "cant", "why": "…"}`.
- **The works row is done once the include is `on`**: the card ticks it off, and the printer should count it as done
  for `setup.open`. The notifications row is done, for `setup.open`, when some phone gets notifications
  (`elyir-bench/phones`), which is what the simulator does; on the card it is this phone's own push that counts.
- **Fetching shows no time left**: the board's "about 2 min left" and its half-full bar are left out, as this file
  says (apt gives no percentage); the bar moves without saying how far.
- **Taking the line out** reuses the include sheet: "Take the line out of printer.cfg", the same two blocks, "Remove and
  restart Klipper". It isn't drawn; the words are the app's.
