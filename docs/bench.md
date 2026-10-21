# The Bench Box's screen

A Bench Box is a machine with no printer of its own (a Pi 5, a NUC) that runs Elyir Bench for every printer
in the house: it slices for them (`role: controller`, [slicer.md](slicer.md)) and, here, shows them all on
one screen. It never needs the home hub. Every printer keeps its own brain, so with the box off each one
still prints from its own screen and phones. The design is `design/bench-box/`, direction D (agreed 4 October
2026): the sentence across the top, the printers below at any count, a printer opened on the box laid out
for the box.

## The app

A third build beside the printer app and the Printers app: `app/bench/` and `app/src/bench-app/`,
`npm run dev:bench` (localhost:5174) and `npm run build:bench` (`dist-bench/`).

- `bench.ts` (pure, `tests/bench.test.ts`): a tile from each printer's intent (its own words, its one next
  action, never a hold action), the order (needs you, then printing by finish, then ready, then off), the
  size (big tiles up to four, compact up to nine, then rows), the sentence and the line of printers that are off.
- `live.ts`: one intent connection per printer, from the box's list (`GET /bench/printers`:
  `[{id, name, moonraker, app, token?}]`); a printer that doesn't answer for six seconds is off.
- `HomePage.vue`: the bench. A tile's button opens the printer where that action lives; the box never acts
  on a printer behind the person's back.
- `PrinterPage.vue`: a printer, opened. The printer app in a frame in bench chrome
  (`?embed=1&chrome=bench`): it draws no top bar or tab bar and lays itself out as on its own panel
  (`layoutFor`, `tests/layout.test.ts`); the box's row of sections drives it (`elyir-bench:navigate`) and
  follows it (`elyir-bench:path`); the token handshake is the Printers app's, with `''` meaning "no door here".

## The tab bar

Printers, Print, Spools, Care (`BenchTabs.vue`), on every page but `/setup`, an opened printer too. Each tab gathers
what every printer already says about itself (`tabs.ts`, pure, `tests/bench-tabs.test.ts`) and a tap opens that
printer's own screen, where the doing is; a dot on a tab when something there needs a person.

- **Print** (`ShelfPage.vue`, `ModelPage.vue`, design `design/bench-print/`, A): the shelf, below.
- **Spools** (`SpoolsPage.vue`): every printer's spools, the printers with one running short first, and what's loaded
  where by material. Low is short; empty is short only when it's the printer's one spool or the one feeding (an empty
  slot in a unit is room). A printer that reports no spools is named in one line.
- **Care** (`CarePage.vue`): every printer's care items in one list, due first, then the nearest.

## The shelf (Print)

`design/bench-print/`, A (picked 4 October 2026). The box keeps models (STL, 3MF, OBJ, STEP), not G-code, so a model
printed on Workshop can go to Desk next time. The Print tab is the shelf, the last printed first, and Add a model (from the
box's own screen, or a phone or computer at home). A model opens with copies, the filament (every one loaded across the
bench, `filaments()`), and where it can print (`printOn()`): the soonest free printer with that filament loaded first,
then why each other printer can't, or can later. Rules: `src/bench-app/shelf.ts` (`tests/bench-shelf.test.ts`).

- **Print on Desk** (a printer that's free, or free once its bed is cleared): the box sets it up for Desk on its own
  slicer while the sheet asks "Is Desk's bed clear?", with Desk's camera when it has one (`BenchCamera.vue`: live, or a
  still every 2 s); It's clear, print sends the file, runs Desk's own `check_print`
  (spools against the file, as for any file) and `start_file`, then opens Desk. Just before starting, the box looks at
  Desk's live state again: a printer that started something meanwhile is never started on top of.
- **Send to Workshop** (a printer that's printing): the box sets it up and puts it on Workshop, nothing starts; it's on Workshop's
  Print, to start there once it's free. Found in the rig: the first build asked the bed question of a printing Workshop, and the
  simulator started the new file over the running print (a real Moonraker refuses, but the box must never ask).
- A printer the box can't set a model up for says so in the list (no `elyir-bench-slicer/printer.json` on it, as on the Kobras).
- **Lying** (11 October 2026), first under How it prints: which side down, the printer's own "Which side down?"
  (design/orientation/). `GET /bench/shelf/{id}/sides` gives each part's sides as the box's slicer measured them (`lying`
  from its upload, kept on each part) and which is down; `PUT /bench/shelf/{id}/side` `{part, lay: auto | file | side,
  down}` keeps a pick with the model (`sides` in `item.json`, by part), so the model page, the queue, the plan's fit
  checks and every print after lie it so (`plate_parts`). Unpicked, a part goes down its own way: as a printer's plate had
  it (gathered), else laid flat for you when its flattest side isn't down, as on a printer's Print; picking that side
  again is the way back. The plan's move sheet has the same row and sheet (`SideSheet.vue`); away neither shows and the
  away listener refuses `…/side`. Words: `src/bench-app/sides.ts` (`tests/bench-sides.test.ts`).

The service side (`bench/shelf.py`, tests `bench/tests/test_shelf.py` against the real slicer with the slicer tests'
stand-in Orca): models in `state/bench/shelf/<id>/` (the file, `item.json`, `picture.png`). The page draws the picture as it
adds a model (`addModel`, the printer app's `render.ts`; a 3MF from the parts the slicer read in it) and the box keeps it,
and it goes into the G-code as its thumbnail. The box's slicer is asked directly at `--slicer` (default
`http://127.0.0.1:8095`), not through the box's nginx: that stamps `X-Elyir-Bench-Printer` with the box's own name, and the
box isn't a printer. Each printer on the bench is joined to the box's slicer (`PUT /slice/printers/<id>`, with its Moonraker
address) the first time it's asked about and every ten minutes after, which copies its profile from its own config folder.
The slicer forgets a model after a day; the shelf gives it the model again when it has.

**Models printed from a printer's own Print** land on the shelf too (`design/bench-shelf/`, A, picked 4 October 2026):
every three minutes, and when it starts, the service reads each printer's record of what it printed (`elyir-bench/sliced`
in its Moonraker, which the slicer writes when a plate is sent: each part's model id, scale, side down, material, color)
and fetches those models through the printer's own `/slice/models/<id>/file` (its nginx says which printer asks, so its
slicer, here or elsewhere, hands over its models) while they're kept, a day. The picture is the G-code's own (Moonraker's
file metadata, the biggest). The shelf tags them "From Workshop's Print". `gathered.json` keeps every plate looked at, so a
model taken off doesn't come back, and the box's slicer's own model ids, so a print from the box (which the printer records
the same way) isn't added twice. A printer that's off is looked at again next time; a model already let go of is left. A
file sent from a slicer on a computer has no model and stays on its printer. What it can miss: a print made while the box
was off for the whole day the model is kept. Tests: `bench/tests/test_shelf.py` (gathering, against the real slicer).

**Tidying** (`design/bench-queue/`, Tidy A, picked 5 October 2026): the shelf shows what was printed or added in the last
30 days; the rest folds into one row, "Older · 23, not printed since September", which opens to them (`foldShelf`). A
model printed again comes back up. The box never deletes a model; Take it off the shelf does.

**The queue** (`design/bench-queue/`, Queue A; `bench/bench_queue.py`, tests `bench/tests/test_queue.py` against the real
slicer): Add to the queue beside Print on. `GET/POST/PUT /bench/queue`, `DELETE /bench/queue/<id>`,
`POST /bench/queue/<id>/start {anyway?}`, kept in `state/bench/shelf/queue.json`. Every 10 seconds (and at once when the
queue changes) the box reads each printer's intent (`GET /printer/intent`) and gives each waiting print, in order, the
first printer that's free (or done, with its bed to clear), isn't holding another queued print and has the filament
loaded and settings for it; a print nobody can take doesn't hold up the ones behind it. The box sets it up for that
printer; when the copies don't fit one bed (more than one plate), one bed's worth stays with it and the rest waits right
behind it for the next free printer. Then it waits for a person: Up next above the shelf and the printer's tile on the
bench ("Desk is next: clear its bed to start the cap") ask for the bed, with the camera (`QueueStart.vue`). It's clear
sends the file, runs the printer's own `check_print` (a refusal can be overruled once: Print anyway, without sending
twice) and `start_file`; a printer that started something meanwhile is never started on top of, and its queued print
waits again. Rows drag to reorder (the handle) and × takes one out.

Found while building it: two set-ups joining the same printer to the box's slicer at once (the queue's loop and the Print
page asking what's printable) made the slicer's copy of that printer's profile fail ("its presets don't resolve"): it copies
into one folder per printer. The box now joins one printer at a time, looks at the queue one look at a time, and asks
again after a minute (not ten) when a join failed.

A rig with the real Orca (what the Built captures in `design/bench-print/` were taken from):

```bash
# printers with their own profiles: the simulator serves a folder as Moonraker's config root
sim.py --port 7163 --name Workshop --scenario print --config /tmp/cfg-workshop      # /tmp/cfg-workshop/elyir-bench-slicer/ from Workshop/
sim.py --port 7165 --name Desk --scenario idle --no-ace --config /tmp/cfg-desk
# the box's slicer: no printer of its own, lends to anyone; Orca's own presets only (the printers bring theirs)
slice_service.py --config box-slicer.json --port 8195 --work /tmp/slicer-work
#   {"orca": "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer", "lend": true, "allow": "anyone", "printers": {},
#    "profiles": ["~/Library/Application Support/OrcaSlicer/system", "/Applications/OrcaSlicer.app/Contents/Resources/profiles"]}
# the box's service, with the printers already on its bench (state/printers.json: name, host, moonraker_port, home, token)
bench_service.py --state /tmp/b --slicer http://127.0.0.1:8195 --port 8196
BENCH_URL=http://127.0.0.1:8196 npm run dev:bench
```

## Several at once

`design/bench-several/`, C (picked 10 October 2026). **Service side and screens built, not deployed.** Tick models on
the shelf, Print: the box plans a bed per printer, and Print all puts each bed in Up next. `bench/plan.py`, tests
`bench/tests/test_plan.py` (the rules with a given fit; the rest against the real slicer with the stand-in Orca).

**The screens** (`app/src/bench-app/several.ts`, pinned by `app/tests/bench-several.test.ts`): Select beside The shelf,
or holding a model, ticks models instead of opening them (`ShelfPage.vue`); Add a model steps aside and a bar at the
foot says how many, Clear, Print N models. The plan is `/print/plan?m=` (`PlanPage.vue`; the picks, copies and moves are
in the address, so a reload keeps them): a card per bed with its chip, filament, models with − / + and a small picture of
the bed, the time and when it's done as far as known (never invented); a bed waiting for any printer, and a model the box
can't plan, is an amber strip with Take it out. It asks again while `checking` and Print all waits for it. Tapping a model
opens the move sheet at the side (`MoveSheet.vue`): as the box planned it, each printer in `printOn()`'s order with why
for the ones that can't, its own bed, Take it out of this print; each pick plans again. A split bed says what the box
said, with Keep them all on that printer. **How it prints** on each card (11 October 2026) is the model page's words for
how the box planned the bed (`bedHowLine`); tapping it opens the model page's four tiles and sheets (`HowSheets.vue`) for
the whole bed: each change is `PUT /bench/shelf/{id}/how` for every model on it, then the plan asks again. A brim its
models differ on shows Mixed, and picking one sets all. Away the line shows but doesn't open: the model page has no How
away and the away listener refuses `…/how`. A model's move sheet has its **Lying** row (11 October 2026), the model
page's "Which side down?"; a new side plans again, and a rough time from `last.each` is dropped once the side differs
from the one it was printed on. Print all goes back to the shelf, where each bed is one row of Up next (its
models' pictures, `name` as given: rows carry `bed: true`). Phones away plan and Add to the queue; guests get no Select.

**The rules** (the board's, with the owner's six defaults): same filament (one of yours, or a material and a near color) and
the same purpose, supports and settings share a bed when it fits. What doesn't fit goes to another free printer with
that filament loaded, else a second bed on the same printer, after. Another filament goes to the soonest printer with it
loaded (free first, then busy ones in the order they finish), then to one that asks what's loaded (a Kobra), then a
second bed on a printer that has it (two colors on Workshop's unit: another printer first). Nothing has it loaded: the bed
waits in Up next. Each model prints in what it was last printed in (`last`); one never printed takes the filament loaded
on the most printers, as the model page does (on a printer asked for, the most widely loaded one it has), and Change printer
offers it every printer with something loaded. A model's `in` ({material, color, filament?, filament_name?}, picked
with In on the move sheet) wins over both, and its rows carry `chosen`. The box never adds copies.
A printer holding a queued print (or one a queued bed waits for) counts as busy. The order is `printOn()`'s over the
queue's intents; these rules live in `plan.py` only.

**Fits** is the slicer's arrange without slicing (`POST /slice/fit` with `part: null`, docs/slicer.md): one Orca run per
group (0.3 to 1.5 s on the Mac with the real Orca), kept 15 minutes per printer and models-with-copies, so a re-plan
after a move only asks for what changed. Checks run in the background: a plan answers at once with what's known.

**Times** are rough: a model printed alone keeps its time and grams per copy (`last.each`, from that slice), and a bed's
is the sum, `rough: true`; any model never timed leaves the bed's `seconds`, `grams` and `done_at` null. The real time is
the queued bed's own slice (`time`, `grams` on its queue row).

```text
POST /bench/plan   {models: [{shelf, copies (1-200), printer?, bed?: "own", out?: true}], wait?: true}
  printer: move it there ("Keep them all on Workshop" = that printer on each of the bed's models; its overflow stays there)
  bed: "own" never shares; out: left out of the plan (listed in `out`)
→ 200 {checking,                       true while a fit check runs: ask again (same body) until false; wait: true answers
                                         when every check is in (at most 60 s)
       beds: [{id,                     "<printer|waits>:<order>:<first shelf id>", for the screens to keep a card
               printer, printer_name,  null: waits for a printer with it loaded
               order,                  1, 2…: the bed's turn on that printer
               material, color, slot, filament, filament_name, words ("Gray PETG"), asks (it asks what's loaded),
               purpose, supports, settings, brim (the models' brim; "mixed" when they differ: a brim never splits a bed),
               models: [{shelf, name, copies, of (copies asked, when split), picture, first (never printed)}],
               fits,                   true: checked; null: not known yet (checking, or the check failed: said in why)
               split,                  part of a group that didn't fit one bed
               seconds, grams, rough,  the rough guess, or null
               when: {kind: now | clear (once its bed is cleared) | next (busy: clock, at) | after (bed 2+) | queued | waits},
               start_at, done_at,      epoch seconds, or null
               why}],                  its line in words
       cant: [{shelf, name, copies, why}],   gone from the shelf, a printer asked for that can't take it, doesn't fit any bed
       out: [{shelf, name}], said: ["Not all of it fits one bed on Workshop: Cable clips × 8 go on Kobra 3 #2, which has Gray PETG too."],
       free_left: [{id, name}], printers (how many), done_at (all done, or null), ahead (already in Up next)}
POST /bench/plan/print   {beds: plan.beds (as shown)} or {models} (planned again, waiting for the checks)
→ 201 {queued: [queue rows], cant}     each bed one row at the end of Up next; 400 nothing to print, 409 a model left the shelf
```

A bed in the queue (`bench_queue.py`) is one item with `models` [{shelf, name, copies}] (every row now has `models`; a
single model's is one), `name` ready to show ("Phone stand × 2, Cable clips × 4": don't add the copies again), `copies` the
total, and `on`/`on_name`: the printer the plan gave it. It waits for that printer (its line: "Workshop's next, after the bed
before it", "Desk's next, after its print, about 7:40") and goes to whichever is free only once that printer can't take
it (off the bench, or its filament taken off). Its models are sliced together as one plate, the plate printed the way the
first model's how says and each model with its own brim; a bed that doesn't fit where it goes keeps one bed's worth and
the rest waits right behind. It's clear, start is per row, on the box's own service only. When it's sent, each model's
`last` is its own copies on that printer. From away a paired phone may plan and `POST /bench/plan/print` (Print all
becomes Add to the queue, rows `by` and `away`); guests may not; nothing starts from away.

## Trying it

```bash
cd simulator   # five printers, two more listed but off
~/.venvs/elyir-bench-sim/bin/python sim.py --port 7161 --name Studio --scenario runout &
~/.venvs/elyir-bench-sim/bin/python sim.py --port 7162 --name "Kobra Max" --scenario finished --no-ace &
~/.venvs/elyir-bench-sim/bin/python sim.py --port 7163 --name Workshop --scenario print &
cd ../app
npx vite --port 3052 &                                   # draws each printer's own screens, ?printer=host:port
BENCH_PRINTERS=/path/to/bench.json npm run dev:bench     # [{id, name, moonraker: "http://localhost:7161", app: "http://localhost:3052"}]
```

The Bench app keeps its own Vite cache (`node_modules/.vite-bench`): beside the printer app's dev server a
shared one is re-optimized by each in turn, and every load fails with 504 Outdated Optimize Dep.

## The box's own service

`bench/bench_service.py` (tests: `bench/tests/test_bench.py`, against the real door), behind `/bench/` on the box:

- `GET /bench/printers`: the bench, for the page: `[{id, name, moonraker: "/bench/p/<id>", app}]`. No tokens.
- `GET /bench/found`: printers on the Wi-Fi (`_elyir-printer._tcp`, announced by every printer's installer, step
  "on the wi-fi"), whether each is on the bench, and how asking it stands.
- `POST /bench/ask/{id}`: asks at the printer's door home name (from `GET http://<printer>:<port>/door/status`):
  `/door/ask` with `kind: bench` and the box's addresses (`--origin`, repeatable). The answer is followed here;
  a yes hands over a token, kept in `printers.json` (0600) and never sent to a page.
- `DELETE /bench/printers/{id}`.
- `/bench/p/{id}/websocket` and `/bench/p/{id}/server/files/gcodes/...`: the printer's Moonraker, through here.
- `GET /bench/p/{id}/camera`: its first enabled camera (Moonraker's `server.webcams.list`), how it's mounted, and
  `/bench/p/{id}/camera/stream` or `/snapshot`, the picture through here (`null` when it has none). A relative address
  is the printer's own web server's (it serves `/webcam/` as Mainsail does); `localhost` in an absolute one means the
  printer, not the box. A stream only for an MJPEG service, as in the printer app; otherwise stills.
- Every ten minutes it tells each printer's door its addresses again (`PUT /door/me/origins`).
- From away (below): `/bench/phones`, `/bench/invites`, `/bench/watching` and `/bench/box/remote`, and the away
  listener (`--away-port`, 8189, loopback only).
- Your filaments (`bench/filaments.py`, tests `bench/tests/test_filaments.py`; design/bench-material/, B): `GET/POST
  /bench/filaments`, `DELETE /bench/filaments/{id}`, each `{preset, name, brand, material, color}` kept in `filaments.json`;
  `GET /bench/filaments/library?q=` searches Orca's library through the box's slicer (`GET /slice/filaments`). A slice or a queued
  print carries `filament` (the preset) and `filament_name`; the slicer uses that preset instead of the printer's own for the material.
- The box itself (`bench/box.py`, tests `bench/tests/test_box.py`), at the foot of its Care: `GET /bench/box`
  `{power, role}`, `POST /bench/box/power {kind: off|restart}` (no nozzle to wait for: `sudo systemctl poweroff|reboot`
  two seconds later; design/power/) and `POST /bench/box/role`, which runs `elyir-bench --json role printer` and follows its
  lines (design/role/'s way back). A rig (`--found`, `--seed`) only says so.

On the printer's side (`door/door.py`): `kind: bench` asks carry origins; once allowed, the door's CORS,
`frame-ancestors` and page-origin check include them; `GET /door/frames` lists them (not secret, on the house and
home listeners) so the printer's own app, embedded in a box, takes its token from the box (`app/src/auth.ts`,
`learnParents`). Not `/door/me` on the house listener: the printer's own app would think it had to pair.

## The first run

`/setup` (`SetupPage.vue`): the printers found, Ask or Ask all, waiting, said yes; reached from an empty bench
and from + Add. Each printer says yes on its own screen ("Bench Box wants to connect", `AskCard.vue`).

A live rig on a Mac (what `design/bench-box/` Built was captured from):

```bash
sim.py --port 7163 --name Workshop --scenario print
door.py --state /tmp/d --moonraker http://127.0.0.1:7163 --app http://127.0.0.1:3052 --address localhost \
  --home-address http://127.0.0.1:8191 --printer-id workshop --printer-name Workshop \
  --away-port 8189 --local-port 8191 --home-port 8190 --shell-origin http://localhost:5174
# the printer's "nginx": the printer app, IPv4 (the service connects over IPv4), /door to the house listener
DOOR_URL=http://127.0.0.1:8190 VITE_MOONRAKER_URL=http://127.0.0.1:7163 npx vite --host 127.0.0.1 --port 3052
echo '[{"id":"workshop","name":"Workshop","host":"127.0.0.1","port":3052,"door":true,"moonraker":7163}]' > /tmp/found.json
bench_service.py --state /tmp/b --found /tmp/found.json --origin http://localhost:5174 --port 8196
BENCH_URL=http://127.0.0.1:8196 npm run dev:bench
```

## Putting it on a box

Any small Linux computer that stays on: a Raspberry Pi 4 or 5 on Raspberry Pi OS Lite 64-bit (Debian 13), or a
NUC on Ubuntu 24.04 or newer (Orca needs glibc 2.39). Hostname `bench`, user `pi`, SSH by key, on the same
Wi-Fi as the printers; a screen on it is optional.

```bash
./deploy.sh bench.local          # no Klipper there: role auto makes it a controller, called "Bench Box"
```

Its steps: preflight (installs nginx, python3-venv), release, web app (the Bench app on :8088, `/bench/` to the
service), panel (the kiosk on its own screen, if it has one), door runtime, slicer engine and service (it lends to
any printer: `allow: anyone`), bench service. Every printer needs a release from 4 October 2026 or later
(`./deploy.sh <printer>`): that announces it on the Wi-Fi and lets its door take a Bench Box's ask. Then open
`http://bench.local:8088/setup` and ask the printers; each says yes on its own screen.

Note: a printer on `slicer: auto` that can't slice itself (Desk) prefers a Bench Box over another printer, so on
its next apply it moves from Workshop to the box.

## Printers the box speaks for (the Kobras)

`design/bench-kobra/`, A (picked 6 October 2026). An Anycubic Kobra can't run Elyir Bench (one small core, no swap), so the
box runs, for it, what a printer's Pi runs. It reaches the Kobra over Anycubic's own LAN mode (below) whenever that's on,
and through Rinkhals (Moonraker in front of Anycubic's GoKlipper) only with LAN mode off (7 October 2026: on a Kobra,
Rinkhals adds nothing the box can use, and holds its firmware back).

- **Found** (`bench/anycubic.py`): a Kobra announces nothing, so the box looks at its /24 for Anycubic's own ports: 18088
  (every one), 18910 (LAN mode; `/info` names the model and the Wi-Fi MAC) and 7125 (Rinkhals' Moonraker). It shows on
  `/setup` with Add, or why not yet ("On Anycubic's cloud: turn on LAN mode"). `POST /bench/add/{id}` needs LAN mode or
  Rinkhals there; there's no ask, since a Kobra's screen can't show one and either is open on the Wi-Fi anyway.
- **Spoken for** (`bench/standin.py`, tests `bench/tests/test_standin.py` against a fake Rinkhals): one stand-in per Kobra on
  its own port from 8101, started with the service, serving what a printer's nginx serves on 8088: the printer app (the
  release's `app/`, its `config.json` served with no fixed printer), `/websocket` and the Moonraker paths, `/slice` to the
  box's slicer with `X-Elyir-Bench-Printer`, `/webcam/` (the Kobra's port 80), `/door/frames` (the box's addresses; no
  `/door/me`). The intent is the real engine's over the Kobra's status; records (the spool, Care, next plates) stay in the
  Kobra's own Moonraker database, as on a Pi. The printer record is `{host: 127.0.0.1, port, moonraker_port: port,
  standin: {printer, moonraker_port, web_port, model}}`; `/bench/printers` gives its app on whatever address the page used.
- **What GoKlipper can't take** is never offered and refused if asked (`NOT_HERE`): FIRMWARE_RESTART and RESTART deadlock it
  until a power cycle (Rinkhals refuses them), so no Try again, no Stop now (Cancel instead); no squish or our PRINT_START;
  no change filament (our LOAD/UNLOAD macros); no power. Only objects the Kobra lists are subscribed to: asking GoKlipper
  for one it doesn't have can bring it down. Rinkhals allows Moonraker five websockets, so a stand-in keeps one and merges
  every page's subscription into it.
- **Slicing**: `bench/profiles/kobra-3/` and `kobra-3-max/` name Orca's own Anycubic presets (in the box's pinned Orca
  2.4.2; the Mac's 2.3.1 has no Kobra 3 Max), copied into `state/bench/standins/<id>/elyir-bench-slicer/` when added and listed
  as the Kobra's config, so the box's slicer joins it like any printer. Rinkhals starts a sent file through Anycubic's MQTT,
  so its own screen shows the print.
- **A Kobra Combo's ACE Pro**: Rinkhals puts it in every status it sends, as Happy Hare's `mmu` and `mmu_machine`;
  the engine reads that as it is (`printer/filament_units.py`), so its slots, colors, the slot in use and the dryer show
  as on Workshop.
  A Kobra whose `mmu` has no gates is one spool. Nothing on the unit is driven from here: the unit actions are in
  `NOT_HERE`, and an `ACE_…` command is never sent.
- A stand-in whose port is taken is logged and that Kobra is off; the box carries on. A new one gets a port that's free.
- **No fixed address needed**: a Kobra is known by its Wi-Fi MAC (`anycubic-803e82`; from `/info` in LAN mode, else from
  Moonraker's `machine.system_info`), and its model from `/info` or, with LAN mode off, its bed (`toolhead.axis_maximum`). One
  that stops answering is looked for on the Wi-Fi every minute (`_follow_kobras`) and spoken for at its new address.
- **Its door** (`bench/doors.py`, tests `bench/tests/test_doors.py`; docs/door.md, "Printers the box speaks for"): remote
  access and notifications as a printer's own door gives them, run on the box. `POST /bench/p/{id}/remote {name?, invite?}`
  claims its public name on the relay (`kobra-3-max.elyir.app`; the relay's suggestion or `-<tag>` when taken) and opens
  it; `GET` says how it stands (claimed, carried, open, link, home); `DELETE` closes it and keeps the name. It opens by
  itself when a Kobra is added, unless the box's own `remote` is off (`--remote`, from elyir_bench.conf, as a printer's
  door opens at install) or someone turned that Kobra's off; one it couldn't open is tried again every minute. Pairing is
  on the box (the Kobra opened there, Care, Phones, Add a phone) or from a phone at home: its own screen's Finish setting
  up offers notifications from its secure link (the stand-in reports `secure_link` off | waiting | on from the relay,
  asked every 5 minutes), and Change renames it on the bench and in its door's notifications (`setup_name`).
- **Its name at home** spells the box's address (`192-0-2-40.kobra-3-max.home.elyir.app`): lego gets its certificate
  over DNS-01 through the relay with that Kobra's secret, every 15 minutes, and the Kobras' Caddy serves it on
  `--home-port` (443 on a box; the service gets `CAP_NET_BIND_SERVICE` for it) in front of its door's home listener.
- With the box off a Kobra prints from its own screen and Mainsail, but it's gone from the bench, from away and from
  notifications.
- **Over Anycubic's LAN mode, nothing installed** (`design/kobra-lan/`, B; `bench/kobra_lan.py`, tests
  `bench/tests/test_kobra_lan.py` with a real Kobra 3 print's reports in `fixtures/`): a Kobra without Rinkhals but with LAN
  mode on is reached the way Anycubic's slicer reaches it. `GET :18910/info` gives a token; a POST to its `ctrlInfoUrl`
  signed with it (`md5(md5(token[:16]) + ts + nonce)`) answers its MQTT login, AES-CBC with `token[16:32]`; MQTT over TLS on
  9883. `LanUpstream` answers the stand-in's Moonraker calls from its reports: `info` (asked every 3 s; the job's stage is
  pushed by nothing; three unanswered in a row is a lost printer, so a blip on the Wi-Fi isn't) as Klipper-shaped
  status, its stages `preheating → auto_leveling → vibrating → flow_calibrating → printing`, `pausing/paused`,
  `stopping/stoped`. A free printer after a job the box saw run says how it ended (Done or stopped) until the bed is said
  clear or another starts. `last_project` only holds the last print that *finished*, so after a stop it still names an
  older one: it counts only when it's this job's file, and a stop seen on the way out is a stop. Anycubic's `preheating`
  lasts to the first layer, so it names nothing and the engine follows that by temperatures. A file sent to the box is
  read for Moonraker's metadata and pictures and kept on the box (`standins/<id>/gcodes/`, the newest 20) until it
  starts: a Kobra that's sent a file warms up and waits on "Downloading files" for a start, so it goes to the printer as
  the slicer sends it (multipart `filename` + `gcode` to its `fileUploadurl`) right before `print`/`start` (md5, size).
  Move and heat (design/hands-on/) is heat only here: no `toolhead` object, so the engine says `can_move: false` and
  never sends a move; through Rinkhals the whole sheet goes as G-code.
  `pause`, `resume`, `stop`; warm as its `update` settings, and off (an idle Kobra ignores an `update` to 0) as
  `tempature`/`set`, the way the Anycubic Orca plugin sets them (a stopped job stays in `info` until someone touches the screen, and that
  Kobra is idle: off as a print update was ignored and Kobra 3 #2 stayed at 240°, 18 October 2026); other G-code refused. The heaters' targets come from
  its `tempature` query (asked with each `info`): `info` and the `tempature` reports it pushes keep the last `update`'s
  targets after they're off. An idle printer's answer to an `update` is a `print` report, and isn't a job. The spool, Care and history are kept on the box (`standins/<id>/lan.json`).
  LAN mode wins whenever it's on, Rinkhals or not; a Kobra on the bench whose LAN mode is turned off (with Rinkhals on it)
  moves to Rinkhals by itself, and back when it's turned on again (`via`; spool, Care and history don't move along). Setup's
  Set it up opens `KobraGuide.vue`: the switch drawn, and the box adds it once its row says LAN mode is on.
- **On the real Kobras** (6 October 2026, a Kobra 3 on 2.4.6.7 and a Kobra 3 Max on 2.5.2.8, both Rinkhals 20260901_01,
  through the Docker Bench Box): found by MAC, added, Ready on the bench, opened, joined to the box's slicer. What they
  showed that the simulator couldn't: the same 131 objects as `KOBRA_OBJECTS` in the tests; beds 278.5 × 260 and 478 ×
  440 (`toolhead.axis_maximum`); no `filament_hub`, so no ACE on either; a webcam listed but a 503 picture (no camera),
  now not offered (`camera_ok`); and Orca's Kobra 3 preset writes its 2 mm border (`bed_exclude_area`) so that the whole
  bed is excluded, "doesn't fit" for a 20 mm cube, so the box's profile uses its own machine preset
  (`Anycubic Kobra 3 0.4 nozzle (Bench)`, no border; `bench/profiles/kobra-3/presets/`). A profile with `"bench": true`
  follows the box's template. Not yet tried on them: a print through Rinkhals, and a door on the real relay.
- **LAN mode's commands on a real Kobra 3** (7 October 2026, a 20 mm PETG cube, `standin.py --via lan` beside Rinkhals):
  the upload, start, pause, resume and stop all did what they say, each seen on LAN mode within 1 to 3 s. What the
  printer does that the box must allow for: a file sent alone warms the bed and nozzle (60°/140°) and leaves the screen on
  "Downloading files" until a start (so files now wait on the box); a pause while it's getting ready finishes its queued
  start commands first ("completing cache command", heating on to 230°) and only then parks, while LAN mode already says
  paused; a pause mid-print parks and drops the nozzle to 140°, and resume reheats it before carrying on; Rinkhals'
  `print_stats` doesn't show a pause during the start at all. Its `project.pause` says which: 2 pausing, 1 paused,
  3 resuming, 4 stopping. A pause during the start stayed `pausing` for at least 4 minutes, running its start routine
  (heating on to 230°); the bench offers no Pause while getting ready (Cancel only), so from the app a pause is
  mid-print, where `pausing` lasts seconds. The bench shows `pausing` as paused and a `resuming` reheat (about a minute) as printing. Run again
  the same day on the fixed code: a file sent alone stayed on the box, its start sent it and started at once, and the
  stop stayed "Print stopped" (history: cancelled); Warm up and Cool down both reached the heaters. The LAN connection
  never dropped: what looked like drops every 10 minutes was the Mac running the Docker box going to sleep on battery.
  The LAN mode switch is Settings → Network → LAN mode.

Rig (6 October 2026): `sim.py --port 7171 --name "Kobra 3 Max" --scenario idle --no-ace`, the slicer with
`"profiles": [Orca 2.4.2's profiles folder]`, and `bench_service.py --anycubic found.json --printer-app app/dist` with the
sim listed as `{"id", "name", "host": "127.0.0.1", "moonraker_port": 7171, "web_port": 7171, "model": "kobra-3-max", "rinkhals": true}`.

## From away

`design/bench-remote/`, C (picked 9 October 2026; A built as part of it). The box has its own public name on the relay
and its own pairing, as a printer has (docs/door.md): a phone paired at the box sees the whole bench from anywhere, and any
paired phone can invite someone by link to watch, or to watch and step in. `bench/away.py`, tests
`bench/tests/test_away.py` (against the real `door.py`'s phones, codes and away list).

```
phone ──https──▶ relay ──▶ frpc (the box's own, logged in as its name)
                              │ PROXY header + raw TLS
                              ▼
                 Caddy 127.0.0.1:9444  (the Kobras' Caddy; one more site, the box's name)
                              │ http
                              ▼
                 away listener 127.0.0.1:8189 (bench/away.py, in the bench service)
                   │ the Bench app, a printer's app      │ checked calls, the box's own way to each printer
                   ▼                                      ▼
                 release bench-app/, app/               each printer's Moonraker (or its stand-in), as at home
```

The away listener is only ever reached through Caddy for the box's name, so everything on it is from outside; the box's
own service on the Wi-Fi (`/bench/`, no login) is unchanged and never reachable from away. The name is claimed like a
Kobra's (`doors.py`, `BOX`): its own secret in `state/bench/box/relay.json` (0600), its hostname asked for first
(`--remote-name`, the installer's `remote_name`; `bench-box` when it has none), the relay's suggestion or `<name>-<tag>`
when taken, and `<name>-<tag>` at once for a name the relay keeps for itself (`bench`, `bench-box`). It opens by itself
unless the box's `remote` is off, or it was turned off at `DELETE /bench/box/remote`; one that couldn't open is tried
again every minute. The box's tokens for each printer never leave the box: upstream is each printer as the box reaches it
at home.

**Who.** A *phone* is paired at the box: Care, Phones, Add a phone (`POST /bench/phones/code`) shows a code for ten
minutes that works once (`door.py`'s `Codes`, wrong codes counted per address). A *guest* is invited: a link
`https://<box>/join#<code>` (the code in the fragment, so it never reaches a log) made by a paired phone or on the box;
it works once, and unopened it stops working a day after it was made. The guest gives a name and is in. `reach` is
`watch` (the default: the watching calls only, no actions at all) or `step_in` (each printer's away list, as a phone);
`lasts` is `day`, `week` (from when the link was made) or `removed`. Phones and guests are `door.py` `Phones` records
(`state/bench/away/phones.json`, 0600; a guest has `kind: guest`, `reach`, `until`, `invited_by`); a guest past `until`
is a stranger at once and is let go within 30 s with every connection it had open. Removing anyone closes their open
websockets and requests at once.

**What nobody away does**: start a print, heat, move, send G-code, touch files, spools or `machine.*`. Calls on a
printer's websocket go through `door.allowed_call` (a guest who watches: `act=False`, watching only); notifications
only the kinds the app reads (`door.NOTIFY`); an action is logged on the printer as `<name>, away (guest | paired phone,
through the Bench Box)`. Over plain HTTP only reads (below), a job's pictures (`.thumbs/` png, jpg or webp: the door's
rule, so the simulator's .svg pictures don't show away) and the camera. **Paired phones may add to the queue** (not
guests); the item carries `by` and `away: true` and is set up for a free printer like any other, but the queue never
starts anything by itself: `POST /bench/queue/{id}/start` (It's clear) is only on the box's own service, on the Wi-Fi.

### The contract

Who proves themselves how: the cookie `elyir_bench_phone` (HttpOnly, Secure, SameSite=Lax, set by pair and join; the pages
are all on the box's own name, so it goes with every fetch, `<img>` and websocket), or `Authorization: Bearer <token>`,
or the websocket subprotocol `elyir-bench-token.<token>` (the box selects `elyir-bench`). Unpaired, any API path answers 401
`{detail: "phone"}`; a write or a websocket from another site's page 403 `{detail: "origin"}`. Refusals are
`{detail, message, error}` with the words to show.

On the away listener (the box's public name):

| Route | Who | Request | Answer |
|---|---|---|---|
| `GET /door/me` | anyone | | `{paired, role: "away", away: true, kind: phone\|guest\|null, reach: watch\|step_in\|null, until, name, invited_by, phone, actions: [...], may: {queue, invite}, box: {name, address}}`; a phone's `reach` is `step_in` |
| `POST /door/pair` | anyone | `{code, name}` | `{paired, phone, token, box}` and the cookie; 401 `code`, 429 `wait` |
| `POST /door/join/look` | anyone | `{code}` | `{box: {name}, invited_by, reach, until}` (nothing used up); 401 `code` |
| `POST /door/join` | anyone | `{code, name}` | as `/door/me`, plus `token`, and the cookie; 400 `name`, 401 `code`, 429 `wait` |
| `GET /door/invites` | phones | | `{invites: [{id, reach, lasts, invited_by, made, expires, until}]}` (unopened) |
| `POST /door/invites` | phones | `{reach?: watch, lasts?: day}` | 201 `{id, reach, lasts, invited_by, made, expires, until, code, url}`; 409 `off` without a public name |
| `DELETE /door/invites/{id}` | phones | | 204, 404 |
| `GET /bench/printers` | paired | | `[{id, name, moonraker: "/bench/p/<id>", app: "https://<box>/screens/<id>"}]`: no token, address or port |
| `GET /bench/shelf`, `/bench/shelf/{id}/picture`, `/bench/shelf/{id}/parts/{n}`, `/bench/printable`, `/bench/slice-options`, `/bench/usual/{printer}`, `/bench/queue`, `/bench/filaments` | paired | | as at home |
| `GET /bench/p/{id}/camera`, `/bench/p/{id}/camera/{stream\|snapshot}` | paired | | as at home |
| `GET /bench/p/{id}/server/files/gcodes/**/.thumbs/<picture>` | paired | | the picture; anything else under gcodes 403 |
| `GET /bench/p/{id}/websocket` | paired | | the printer's websocket, checked per caller as above |
| `POST /bench/queue` | phones | as at home | 201 the item, with `by` and `away: true` |
| `POST /bench/look` | phones | multipart `model` | 201 the item, `look: true`: set up like any, off the shelf, let go after a day (How would it print? from the Printers app, `design/bench-look/`, C) |
| `PUT /bench/shelf/{id}/keep` | phones | | the item, now on the shelf |
| `POST /bench/shelf/{id}/slice`, `GET`/`DELETE /bench/slice/{job}`, `GET /bench/slice/{job}/layers[/{n}]` | phones | as at home | as at home: a setup and its layers; sending it stays home only |
| `GET /bench/intents` | phones | | `{<printer id>: its intent or null}`, as its Moonraker says (the queue reads the same) |
| any other `/bench/*`, `/door/*` | | | 403 |

The Printers app (`https://printers.elyir.app`, and `http://localhost:5173` for its dev server) may call this listener with
a phone's token: its preflight is answered and its origin passes the origin check (`design/bench-look/`, C). A phone pairs
the box from the Printers app the way it pairs a printer (the code's `https://<box>/pair#CODE`); the app keeps it as a
Bench Box (`kind: "bench"`), reached by its public name only, since the app is https and the box at home isn't.
| `/screens/{id}/...` | | | that printer's own screens (below) |
| anything else | anyone | | the Bench app's files; a path without a file is its `index.html` (`/join`, `/pair` and `/p/<id>` are its pages) |

On the box's own service, on the Wi-Fi (its screen and phones at home, as every `/bench/` route):

| Route | Request | Answer |
|---|---|---|
| `GET /bench/phones` | | `{address, phones: [...], guests: [...], invites: [...], watching: ["Jo"]}`; each phone or guest is `{id, name, joined, last_seen, notifications, kind, watching}` (open connections now), a guest also `reach, until, invited_by` |
| `POST /bench/phones/code` | | `{code, url: "https://<box>/pair#<code>", expires}`: Add a phone (the URL is the QR); 409 `off` without a public name |
| `DELETE /bench/phones/{id}` | | 204: a phone or a guest, gone now with their connections; 404 |
| `POST /bench/invites` | `{reach?, lasts?, by?}` | as `POST /door/invites` (`invited_by` is `by` or the box's name) |
| `DELETE /bench/invites/{id}` | | 204, 404 |
| `GET /bench/watching` | | `{watching: [names]}`: guests with a connection open now, for the box's top line ("Jo is watching"); never the household's phones |
| `GET /bench/box/remote` | | `{on, name, address, open, carried, link: off\|waiting\|on, home: null}` |
| `POST /bench/box/remote` | `{name?, invite?}` | claims (or uses an invite code on) the box's name and opens it: 200, 202 with `why` when it can't open yet, 502 with the relay's words, 409 with no away listener |
| `DELETE /bench/box/remote` | | `{on: false}`: closed, the name kept, every connection from away ended |

### The screens

The same Bench app, served by the away listener, asks `GET /door/me` once at start (`app/src/bench-app/here.ts`; the
rules are `away.ts`, pinned by `app/tests/bench-away.test.ts`). At home that isn't JSON from the away listener and nothing
changes. Away:

- **A paired phone**: an Away chip and + Invite in the header; a tile's button only when its action is on the away list,
  else a word ("Take it off at home"); no Add a model, no start, drag or remove in the queue; a model says Prints start at
  home, with Add to the queue. An opened printer has no Print section.
- **A guest**: Printers and Print only, Watching (or Away for one who steps in, with the away list's buttons), the sentence
  about who invited them ("Two are waiting for Alex"), and until when at the foot. Neither invites nor queues.
- `/join` (`POST /door/join/look`, then a name and `POST /door/join`), `/pair` (the box's code, from its QR or typed), and
  "This bench isn't open from here" for anyone away not let in (or let go: an API path answering 401).
- **Invite someone** (a phone's header, or Care on the box): Watch and A week by default; the phone's share sheet, and
  where there is none (the box) the link as a QR to send on from a phone, and Copy. A share sheet closed without sending
  cancels the invite. Phones are named by their device ("Alex's iPhone"), so the guest reads "Alex".
- **On the box, at home**: Care, Phones (phones, guests with what they can do and until when, invites nobody opened, Invite
  someone, Add a phone with its QR; 409 `off` says so and offers to turn From away on), From away under This box (on, off,
  an invite code the first time), and "Jo is watching" in every page's top line (`GET /bench/watching` every 10 s).

### A printer's screens, through the box

Today the bench frames a printer's own app at the printer's own address and hands it the printer's door token; away
neither exists. So the away listener serves each printer's app (the release's `app/`) at `/screens/<id>/`, and answers
its calls there as a door for that printer would: `/screens/<id>/websocket` (checked as above), `/door/me`
(`{paired, role: "away", printer, actions, kind, reach, frames, ...}`, with this caller's actions, `[]` for a guest who
watches), `/door/frames` (the box's own origin, so a frame takes its parent's handshake), `/door/pair` (the box's
pairing), `.thumbs/` pictures, `/webcam/` (the printer's own web server's, as its door passes it), `config.json` and
`elyir-bench.yaml` with no fixed printer, and 403 for the rest (`/slice` included: printing a model isn't offered away).
Its page carries `window.__ELYIR_BENCH_BASE__ = "/screens/<id>"`, which `app/src/base.ts` reads: the router, the door,
push, asks, the slicer's API, the config and the intent's endpoint all go under it (the camera follows the endpoint's
path); its chunks, fonts and icons load from the root (the two builds' file names don't collide). Push is off there
(the root's service worker would be the box's). `/screens/`, not `/p/`, because `/p/<id>` is the Bench app's own page for
an opened printer.

So `/bench/printers` from away gives `app: "https://<box>/screens/<id>"`, and the Bench app's `PrinterPage.vue` works
unchanged: it frames `<app>/?embed=1&chrome=bench`, same origin, and its `elyir-bench:token` answer (`''`, no token in the
record) leaves the frame on the cookie. The printer app's own away mode (it reads `role` and `actions` from `/door/me`)
does the rest: a guest who watches sees "This is done at the printer." and no buttons. Tried 9 October 2026 on a
simulated Workshop through the away listener in Chromium: the bench, an opened printer with Pause and Hold to stop for a phone,
none for a guest.

Not in it yet: notifications for the box's phones and guests (the box sends none; each printer's own door still does);
the Printers app (`printers.elyir.app`) holding the box; the box's name at home (a phone at home uses
`http://bench.local:8088` as before). While the box runs in Docker on a Mac, the bench away works only while the Mac is on
and awake.

## In containers, before there's a box

`docker/bench-box/` (its README): `./bench-box.sh up` runs the Bench app, the box's service and its slicer (Orca for
Linux) in Docker on any computer on the Wi-Fi, with the real printers, given by address and put on the bench with
`--seed` (no ask: their doors can't take one until their next release). Tried 5 October 2026 on the Mac with Workshop, Studio
and Desk: all three joined the box's slicer with their own profiles, and a model set up for Workshop in the container came
out as on the Mac (23 min 56 s, 2.4 g).

## Not yet

- Tried on a real box: waiting for one (the spare Pi 4, flashed as above).
- The queue: printing several plates of one model on one printer one after another (today each plate is its own queued print).
- At home a phone still pairs nothing: it sees the bench through the box, with no token of any printer, and opens each
  printer's own screen at the printer's own port. From away it pairs with the box (above).
- From away: the screens are built (above), not yet deployed or tried on a phone away through the relay.
- Printers without a Pi: the Kobras are spoken for (below); the resin printers aren't yet.
- A Kobra Combo's ACE Pro is shown, not driven: loading, swapping and drying from the bench need GoKlipper's own commands.
