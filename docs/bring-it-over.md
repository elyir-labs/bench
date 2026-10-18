# Bring it over: the contract

`design/printer-setup/` (A, agreed 5 October 2026), the first of its three ways to a config. A card flashed with the
Elyir Bench image starts with Klipper and no `printer.cfg`. Most people flashing one are moving a printer that worked
yesterday, so the first thing offered is to bring that printer's setup over: its config, its history and spools, its
Mainsail settings. This file is the contract between the printer's side (the installer, the Moonraker component, the
intent layer) and the app. Private names (`elyir-bench`); the public copy renames them.

## When it shows

The intent layer says `setup` (a new state, beside ready/printing/…) when Klipper can't start because there is no
`printer.cfg` ("Unable to open config file …printer.cfg"). The panel and phone then show **Now the printer itself**
(board `a-start`) instead of Problem. The image's Wi-Fi setup ends on Connected, which links here too
(its "Bring things over from another printer"). For now the first screen offers two of the three ways: **Bring it over**
and **Write my own** (Mainsail's editor, the Advanced door). A printer it knows comes later.

## Where a setup can come from

| kind | found by | what's read |
|---|---|---|
| `card` | a USB card reader with an old card in it: `lsblk`, partitions on a USB device, mounted **read-only** under `/run/elyir-bench-bring/` | `home/*/printer_data` (any `*_data` with `config/printer.cfg`), its `database/`, `gcodes/` |
| `printer` | another printer on the Wi-Fi: Elyir Bench printers by mDNS (`_elyir-printer._tcp`), or any Moonraker by address typed in | its Moonraker: the config files (file API, root `config`), a database backup (`POST /server/database/backup`, then the file), optionally its gcodes |
| `file` | a backup sent from the phone or computer: a `.zip` or `.tar.gz` of a `printer_data` folder or of a `config` folder (KIAUH's backups look like this) | the same, from inside it |
| `cloud` | a Bench Cloud backup of a printer last seen on this internet connection (`docs/cloud.md`), once the house's owner allows it | the backup, as a `file` once it's here |

An old card is never written to: mounted read-only, and unmounted after.

## The installer: `elyir-bench bring …` (`--json`)

- `bring scan`: the sources it can see now, each `{id, kind, name, detail, when, files, gcodes, history, boards}`:
  name from the setup's own `printer_intent` name, else its hostname; `when` the newest config file's time;
  `boards` the MCUs its config names (`[mcu*] serial:` and `canbus_uuid:`).
- `bring plan <id>`: what would come over (`config` file count, `history` yes/no and how many prints, `spools`,
  `mainsail` settings, `gcodes` count and size, offered not default) and **whether the boards match**: each MCU in the
  copied config against what this Pi sees (`/dev/serial/by-id`, Klipper's CAN query). Match, or "the main board's
  serial differs: it will be set to <the one plugged in>" when exactly one board of that chip is plugged in, or "not
  found: plug it in, or it can be changed after".
- `bring apply <id> [--gcodes]`: the current config folder is kept as `config-before-bring-<date>/` (even when empty),
  the config files are copied in (never `elyir-bench.conf`'s secrets or another printer's relay state), a serial that
  differs is set as the plan said, the database is restored through Moonraker (`POST /server/database/restore`, the
  backup placed in its backup folder first), gcodes when asked, then Klipper and Moonraker restart. It reports Klipper's
  state after the restart in words. Refused while printing (a fresh card isn't).

Sources are cached for the plan and apply; `bring scan` refreshes.

## What the app is told (`GET /printer/intent/bring`, from the component)

```jsonc
{
  "state": "idle",                 // idle | scanning | planning | bringing | done | failed
  "sources": [ { "id": "card-sda2", "kind": "card", "name": "Voron", "detail": "In a USB reader", "when": 1791100000,
                 "files": 19, "gcodes": 46, "history": 212, "boards": ["stm32f446xx", "can 6cc850bbec73"] } ],
  "plan": { "id": "card-sda2", "config": 19, "history": 212, "spools": true, "mainsail": true,
            "gcodes": { "count": 46, "bytes": 812000000 },
            "boards": [ { "name": "Main board", "chip": "stm32f446xx", "match": "same" },     // same | changed | missing
                        { "name": "Toolhead board", "can": "6cc850bbec73", "match": "same" } ] },
  "progress": null,                // while bringing: { "step": "Copying the config", "done": 2, "of": 5 }
  "result": null,                  // done: { "klipper": "ready" | "error", "message": "…in words" }
  "why": null                      // failed: in words; nothing half-done (the kept config is put back)
}
```

## Actions (`POST /printer/intent/action`)

| action | does |
|---|---|
| `bring_scan` | looks again (a card plugged in now) |
| `bring_plan` `{id}` | what comes over from that source, and whether the boards match |
| `bring_address` `{address}` | adds a printer typed in by address (any Moonraker), then plans it |
| `bring_apply` `{id, gcodes}` | brings it over; the screens follow `progress`, then `result` |

A backup file sent from the phone is uploaded to Moonraker's `config` root as `elyir-bench-bring/<name>`; the next scan
lists it as `kind: file`.

## The screens

Boards `a-start`, `a-bring`, `a-bring-what` (and `a-done` for the end, without the check list until Check the printer
is built). Panel first (a fresh card's screen), phone too. Words as drawn; "Elyir Bench" for the product name.
After `done` with Klipper ready: the printer's normal Now. With Klipper in error: its message, and the Advanced door.

## The simulator

Scenarios `setup_printer` (no printer.cfg; a card in a reader and Studio on the Wi-Fi), `bring_progress` (half way),
`bring_done`, with the actions above.

## As built on the printer's side

Built 5 October 2026 on branch `bo-api`: `elyir-bench bring` (installer/elyir_bench.py, "Bring it over"), the component's
endpoint and actions (printer/printer_intent.py), the `setup` state (printer/elyir_bench_intent.py). Pinned by
`installer/tests/test_bring_it_over.py`, `printer/tests/test_bring_component.py` and the setup tests in
`printer/tests/test_intent.py`. What differs from the contract above, or adds to it:

**Moonraker, read from its source** (Workshop's, commit 058517b, read-only):

- `POST /server/database/backup` writes `<data_path>/backup/database/<filename>` (database.py `get_backup_dir`,
  `_handle_backup_request`), and `<data_path>/backup` is a *reserved path without read access* in the file manager
  (file_manager.py: `add_reserved_path("backup", …, False)`), not a root. **A backup can't be downloaded through the
  file API.** So another printer's database comes from Elyir Bench's component there instead:
  `GET /printer/intent/bring/export` makes the backup with Moonraker's own `backup_database`, deletes its logins, API key
  and phone count, sends it as base64 in JSON, and deletes the copy. A Moonraker without Elyir Bench (typed in by address)
  can't send its database: its namespaces are read with `/server/database/item` and written here one key at a time
  (Mainsail's settings, Spoolman's, its cameras), and its **history stays there**; the plan says so in `notes`.
- `POST /server/database/restore {filename}` takes a name inside that same backup folder, validates the file, restores
  it and restarts Moonraker *in its own process* (`server.restart`). Apply places the file there first.
- Moonraker's history is the `job_history` table; the count read from a card is `SELECT COUNT(*)` on a copy of its
  `moonraker-sql.db` (copied with its `-wal`, never opened on the card). A card with only an older LMDB database
  (`data.mdb`) can't be restored: its history and Mainsail settings stay on the old card, said in `notes`.

**The installer** (`elyir-bench --json bring …`): `scan`, `plan <id>` and `apply <id> [--gcodes]` as the contract, plus
`address <address>` (reads it, remembers it for later scans, and answers `{source, plan}`). Every run's first line is
`{"started": <kind>, "pid": …}`, then `{"progress": {step, done, of}}` lines (`done` counts the steps finished), and its
last line is the answer: `{sources, found}`, `{plan}`, `{source, plan}`, `{result}` or `{failed: "…in words"}`.

- Sources: `card-sda2` (`card-sda2-<folder>` when a card has more than one `*_data`), `printer-<host>[-<port>]`,
  `file-<name>`. A card is also looked for at the top of a partition (a stick, or Elyir Bench's own data partition). A
  partition someone else mounted (under `/media`, `/mnt`) is read where it is and left mounted; a USB disk the Pi runs
  from is never a source. Links in an old config read as that card's own (`/home/pi/klipper-macros` means the card's),
  and are copied as files; links that lead off the card are left out. `name`: `printer_name` from the old
  `moonraker.conf` `[printer_intent]`, then its `elyir-bench.conf`, then Mainsail's `general.printername`, then the card's
  `/etc/hostname` (a file: its name). `files` and `gcodes` count visible files (`.theme/`, `.thumbs/` still come);
  `history` is `null` when it can't come.
- Plan: `history` is a count or `null`; `boards` rows carry `words` (the drawn words: "STM32F446, same serial", "Same
  CAN ID", "Found", "The main board's serial differs: it will be set to the one plugged in", "Not found: plug it in, or it
  can be changed after") and `to` for `changed`. **`match` has a fourth value, `unchecked`** ("Not checked: CAN isn't set
  up on this card yet", or "Not checked" when Klipper is running and holds its CAN boards). CAN is checked with Klipper's
  own `scripts/canbus_query.py`, which needs no config: on a fresh card nothing has claimed the boards, so they answer.
  Boards are the `[mcu …]` sections of the files Klipper reads (printer.cfg and its includes), plus other sections with a
  `/dev/serial/` serial (an ACE Pro, a probe). `changed` is any one unclaimed device of the same kind (the by-id name
  with its serial number taken out), so it never guesses between two. Plan adds `notes`: words for what won't come, and
  sections this card's Klipper has no module for ("[ace] needs an add-on this card doesn't have yet. Klipper will say so
  after.").
- Apply: steps "Reading <name>'s setup", "Copying your files" (gcodes, only with `--gcodes`, first, and never over a
  file already here), "Keeping your current config", "Matching the boards", "Bringing history and settings", "Starting
  Klipper". Never brought: `elyir-bench.conf` (this printer's own name and door settings stay), `elyir-bench-bring/`, an
  earlier `config-before-bring-*`. The brought `moonraker.conf` gets this printer's `[printer_intent]` instead of its
  own, so the component and the name survive. A printer.cfg that includes `elyir-bench.cfg` sets `start_macro: on`, so the
  next apply keeps it. Before the restore, Moonraker backs up this card's database
  (`backup/database/elyir-bench-before-bring-<date>.db`). Moonraker is only ever restarted in its own process (the restore,
  or `POST /server/restart`), never through systemd, so the run survives it. Klipper restarts through
  `/machine/services/restart?service=klipper`. `result.message` is "Klipper started with it." or Klipper's own first
  lines. A failure answers `failed` ending "Nothing was changed: the config that was here is back."
- A restored database is cleaned first: no `authorized_users` (logins, API key; Moonraker makes a new key) and no
  `elyir-bench/phones`.

**The component**: `GET /printer/intent/bring` as the contract, plus **`found`**: what this Pi sees plugged in, in
words, for a-start's chips ("Main board · STM32F446 on USB", "Toolhead board · on CAN", "ACE Pro", "Camera"). Changes
are also pushed as **`notify_bring_update`** with the same object. Scan and plan answers go back to `idle` (with the new
`sources` or `plan`); a scan or plan that fails is `idle` with `why`, and only `bring_apply` ends in `failed`. Actions
answer `{ok, action, ran, intent, bring}`; refused in words: while bringing ("It's bringing a setup over now."), while
looking, an id it didn't find ("That isn't one it found. Look again first."), while printing. A fresh card is scanned
once by itself. The run's lines go to `~/elyir-bench/state/bring-run.jsonl` and are read every second; after the
restore's Moonraker restart the component reads the same file and carries on (or says the answer, for half an hour).

**The intent layer**: `state: "setup"`, `phase: "no_config"`, headline "Now the printer itself.", detail "It found
these. It can't see how they're wired, so it needs a config, once." (with `found`) or "It can't see how the printer is
wired, so it needs a config, once." (nothing found), and actions `bring_open` "Bring it over" (primary) and `write_own`
"Write my own", both opened by the screens (they send nothing to the printer). Only Klipper's "Unable to open config
file …printer.cfg"; any other config error is still a problem.

**Not done here**: CAN set up on the old card's system (`/etc/network/interfaces.d/can0`, systemd-networkd) isn't part
of `printer_data` and doesn't come; the toolhead then reads "Not checked". Klipper add-ons (KlipperACE, led_effect, a
probe's) aren't installed; Klipper's error says which. An ext4 card whose home folder belongs to another user number
than this Pi's can't be read. Not yet tried with a real fresh card and a real old card or printer.

## As built in the app

Branch `bo-app` (5 October 2026), against the simulator only. `app/src/intent/bring.ts` holds which screen shows when
and every word (pinned by `app/tests/bring.test.ts`); `app/src/intent/useBring.ts` follows `printer.intent.bring`
(once on connecting and on each change of the intent's state, every second while `scanning`, `planning` or
`bringing`, every 3 s while the screens show); `app/src/components/bring/BringScreen.vue` draws them, on the panel and
the phone. `App.vue` shows it instead of the app (after pairing) while the intent says `setup`, while bringing, and
until a `done` result has been seen on that screen (kept in the browser as `elyir-bench.bring.seen`).

- **What it found plugged in:** a-start's chips come from an optional `found: ["Main board · STM32F446 on USB", …]`
  in `GET /printer/intent/bring` (words, one chip each). Not in the contract above yet: without it the chips are left
  out and the line says "It can't see how the printer is wired, so it needs a config, once."
- **A printer it knows** is shown muted with a "Later" pill and does nothing. **Write my own** opens the Advanced
  door (Mainsail), as holding the printer's name does; its line says "When Klipper starts, it's ready" (no checks yet).
- **Sources:** an old card first, then the rest newest first, then "Another printer's address" (sends
  `bring_address`) and "A backup file". `when` is shown as "from Oct 3" for a card or file and "changed 2 hours ago"
  for a printer (the board's "backed up" isn't what `when` means). On a phone the backup is picked there and uploaded
  (`POST /server/files/upload`, `root=config`, `path=elyir-bench-bring`), then `bring_scan`; when the scan lists a
  `kind: file` source of that name, its plan opens. The panel can't pick a file, so it says to send it from the phone.
- **What comes over:** from `plan` (config count, macros and calibration, history, spools and/or Mainsail settings);
  the G-code files are a box that starts unticked and sends `gcodes: true`. Boards: `same` (a tick: "STM32F446, same
  serial" / "Same CAN ID"), `changed` ("another serial: it will be set to the one plugged in", no serial shown),
  `missing` (amber: "Not found: plug it in, or it can be changed after"). The board's "ACE Pro · Found" line isn't an
  MCU, so it isn't there. Under the button: "Then Klipper restarts with it, in about a minute."
- **Progress:** `step` as the big line, "Step done+1 of of" under it, the ring at `done / of`.
- **The end:** `done` with Klipper ready: "<name> is set up." with `result.message`, the Came over list where the
  board has the check list, and Done (then the normal Now). With Klipper in error: "It came over, but Klipper
  stopped.", the message, Open Mainsail and Done. `failed`: `why` (plus "Nothing was changed." after Bring it over),
  and Back to the sources.
- **Step bar:** Wi-Fi, Printer. Check joins it when Check the printer is built.
- **Wi-Fi setup's Connected** has the link "Bring things over from another printer": `POST /wifi/done` first, then
  this screen at the sources.

## Printer or Bench Box (`design/role/`, B, picked 5 October 2026)

Every fresh card reaches this screen, on Wi-Fi or a cable, and a Bench Box has no `printer.cfg` either, so the choice
is made here: with a printer board found, the three ways and a last line, "Not a printer? Make this a Bench Box" (it
asks once); with nothing plugged in, **Nothing's plugged in.** with A Bench Box first and It's a printer beside it.

**What the app is told** (the same `GET /printer/intent/bring`, two more fields):

- `boards`: how many printer boards are plugged in, from the scan (`elyir-bench bring scan` answers it next to `found`):
  Klipper serials, USB-serial chips a board without Klipper answers on (CH340, CP210x, FTDI), CAN boards, or a CAN
  adapter with none answering. Not a camera or a filament unit. `null` until it has looked; the app shows Nothing's
  plugged in only for `0`.
- `role`: `null`, or `{state: "switching" | "failed", progress: {step, done, of} | null, why, url}`. `url` is where the
  box will be (`http://<hostname>.local:8088/`), for a phone once Moonraker is gone.

**Actions:** `role_box` starts the switch (refused while printing or bringing a setup over); `role_back` clears a
failure.

**The installer (the OS image session builds it): `elyir-bench --json role controller`**, and `role printer` for the way
back. Run by the component like a bring run (`/bin/sh -c 'exec … &'`, its lines to `state/role-run.jsonl`, stderr to
`state/role-run.log`):

1. First line `{"started": "role", "pid": …}`.
2. `{"progress": {"step", "done", "of": 3}}` before each step, `done` counting the steps finished, in this order:
   **"The Bench app"** (`role: controller` saved, then apply: the Bench app's site, its service, the slicer service),
   **"Its screen"** (the kiosk on the Bench app; the panel switching over may be left to the last step),
   **"Klipper and Moonraker off"** (`systemctl disable --now klipper moonraker`, left installed).
3. `{"failed": "…in words"}` if anything before the last step fails, with what was done put back (still a printer card).
4. The last step stops Moonraker, which ends the component (and the app's connection) too, so **the run must not be
   in Moonraker's cgroup by then**: re-run itself detached (e.g. `systemd-run`) before stopping it. A `{"result": …}`
   line may be written but no one reads it; the panel's kiosk restarting onto the Bench app is the end the person sees.

Also for the OS image session: `elyir-bench-os update --auto` only updates when Moonraker answers `print_stats`; on a
controller with Moonraker off on purpose, it should count as idle.

Built on the app's side 5 October 2026 (branch `design-role`): `app/src/intent/bring.ts` (`headerFor`, `screenFor`'s
`none` and `box`, the words), `BringScreen.vue`, pinned by `app/tests/role.test.ts`; the component's `role_*` actions and
`boards` (`printer/printer_intent.py`), pinned by `printer/tests/test_role_component.py`; the installer's
`printer_boards`, pinned by `installer/tests/test_role_boards.py`; the simulator's `setup_box` scenario and a role run
that goes dark like Moonraker stopping.

The installer's side built the same day (branch `role-switch`): `role_main` in `installer/elyir_bench.py`. For a
box it saves `role: controller` and applies (the put-back on failure: the role it had, applied again), removes the
printer's mDNS announcement, restarts the kiosk onto the Bench app, writes its `result` line, then stops Klipper and
Moonraker from a transient unit (`systemd-run --unit=elyir-bench-role-off`), outside Moonraker's cgroup. The way back
starts Klipper and Moonraker first, then applies `role: printer`. Pinned by `installer/tests/test_role_switch.py`.
`elyir-bench-os update --auto` counts a box with Moonraker off as idle (`box_without_moonraker`).
