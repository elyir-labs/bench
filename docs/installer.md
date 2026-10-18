# Installer

Goal: installing Elyir Bench should feel like setting up an appliance, not like administering a
Linux box. KIAUH proved people want one tool for the Klipper stack; this is the version where
the tool works things out for itself and the person only answers questions a machine can't.

## Direction

**Now (phase 1):** add Elyir Bench to a printer that already runs Klipper and Moonraker, e.g. one
set up with KIAUH. Klipper, Moonraker and Mainsail are adopted as they are; Mainsail stays as
the Advanced door.

**North star** (see [vision.md](vision.md); OS slots and trial updates: [os-slots.md](os-slots.md)): the same seamless install on a printer with no Klipper at all: a bare Pi OS
install, and later a flashable image (flash, boot, scan the QR code on the screen, done).
Nothing in phase 1 may assume Klipper was installed by hand; every component the installer
adopts today is one it will be able to install later.

## Principles

1. **One command, then a web page.** A short bootstrap runs on the Pi. Everything after that
   happens in a browser: on the printer's own touchscreen, or on a phone via a QR code. No
   text menus.
2. **Detect, don't ask.** The installer finds the Pi model, the real display (and ignores
   phantom outputs), touch, MCUs on USB and CAN, ACE units, cameras, and what is already
   installed. It only asks what it cannot know, such as the printer's name.
3. **Show the plan, then do it.** The person sees what will change before anything changes.
4. **Converge, don't script.** One settings file describes what should be true. `apply` makes
   it true and is safe to run any number of times. `doctor` reports anything that drifted.
5. **Never leave a printer worse off.** Each version installs into its own directory and is
   switched in atomically. A failed health check switches back. KlipperScreen stays installed
   and comes back with one command. Nothing runs while a print is in progress.
6. **One code path.** Deploying from a laptop builds a release and runs the same on-device
   installer that the bootstrap uses.

## On the printer

```
~/elyir-bench/
  releases/<version>/      app/ (built UI)  printer/ (Moonraker component)  kiosk/  installer/
  current -> releases/<version>
  state.json               installed version, previous version, last apply result, expectations()
~/printer_data/config/elyir-bench.conf   the settings file (visible in Mainsail's editor)
```

`elyir-bench.conf`:

```ini
[elyir-bench]
printer_name: Workshop
# elyir-bench | klipperscreen | none
panel: elyir-bench
# auto, or a connector name such as DSI-1
panel_output: auto
port: 8088
```

What `apply` converges, in order:

| Step | Converges to |
|---|---|
| release | `current` points at the requested release; the last three are kept |
| component | Moonraker's components dir has symlinks to `current/printer/*.py` |
| moonraker.conf | a `[printer_intent]` section with name and Advanced URL |
| start macro | with `start_macro: on`, `elyir-bench.cfg` and its include line in printer.cfg (below); off, neither |
| web | an nginx site on `port` serving `current/app` and proxying Moonraker |
| panel | kiosk service rendered for this user, display and URL; enabled or not per `panel` |
| power button | where there is one (the Pi 5): logind leaves a short press to `elyir-bench-power-key.service` (`printer/power_key.py`), which sends Turn off so the nozzle cools first (design/power/); a long press still halts at once; on a Bench Box a press powers off |
| turning off | Moonraker may turn the Pi off and restart it: no "The shutdown API will be disabled" in its warnings; if there is, Moonraker's own `scripts/set-policykit-rules.sh` (needs full sudo, else it says to run it once) |
| network wait | with `network_wait: off` (the default), `NetworkManager-wait-online` is disabled, so Klipper, Moonraker, nginx and the panel start without waiting for the Wi-Fi (about 6 s of every boot on a Pi 5); `on` turns back on only a wait this step turned off |
| health | the app answers, `/printer/intent` returns a valid state, the kiosk is running if enabled |

## Commands

```
elyir-bench detect            facts about this machine, as JSON
elyir-bench plan              what apply would change
elyir-bench apply [release]   converge (optionally to a new release tarball)
elyir-bench doctor            check every step without changing anything
elyir-bench rollback          switch back to the previous release
elyir-bench panel elyir-bench|klipperscreen
elyir-bench startmacro on|off [--force]   the start macro's include, and only that (below)
elyir-bench check             what the install command says first: the board, what it adds, what it leaves alone
elyir-bench pair              a QR code for a phone (a one-time pairing code when remote is on)
elyir-bench remove [--yes]    take it off again: KlipperScreen back, Mainsail and printer.cfg untouched
elyir-bench bring scan|plan <id>|apply <id> [--gcodes]|address <address>
                            bring an old printer's setup to a fresh card (docs/bring-it-over.md)
```

`elyir-bench --json bring …` is what the component runs for Bring it over: one JSON line per step, the last one the
answer (`sources`, `plan`, `result` or `failed`). An old card is mounted read-only under `/run/elyir-bench-bring/sdXN`
(ext4 with `noload`, so not even its journal is replayed) and unmounted after; the sudo rule allows that mount, its
`mkdir -p` and `umount` for `sd[a-z]`, `sd[a-z][0-9]` and `sd[a-z][0-9][0-9]` and nothing else, never read-write.
Apply keeps the config folder that was there as `config-before-bring-<date>/` beside the new one, and Moonraker's
backup of the database from before as `backup/database/elyir-bench-before-bring-<date>.db`.

From a laptop: `./deploy.sh workshop.local` builds a release, copies it over and runs
`elyir-bench apply` there.

## On someone else's printer (design/getting-started, C)

```
curl -fsSL https://bench.elyir.dev/install | sh
```

`install/install.sh` fetches `bench/latest.json` from Elyir's release bucket (`scripts/release/`), downloads the
release once, checks its sha256 and its ECDSA signature against the key written into the script
(`install/release-key.pem`; a test keeps the two the same), and unpacks only the installer. Then:

1. `elyir-bench check` says what this printer is and what to expect, before anything changes. Exit 0 goes
   on; 3 is "not now" (a print is running); 4 is "can't" (no Moonraker, no sudo, a 32-bit system, a board
   it doesn't know). Nothing is changed in either case.
2. One question, "Go ahead?", read from `/dev/tty` because the script itself arrives on standard input.
   `ELYIR_BENCH_YES=1` answers it ahead of time.
3. `elyir-bench apply <release>`, with the terminal attached so sudo can ask for a password. The screen is
   left as it is (KlipperScreen stays on); the phone's setup card offers the switch later.
4. `elyir-bench pair`: a QR code (`qrencode`, installed if sudo allows) and the printer's address.

**What each board gets** lives in one place, `expectations()`: everything; everything with named
differences (the screen's animations without a graphics driver, slicing where Orca can't run: glibc older
than 2.39 or under 1.5 GB of memory, and who slices instead); or not yet. `elyir-bench --json check` gives
the same list for the app's What works sheet. Boards: Raspberry Pi 4, 400, 5, CM4, CM5, and BTT's H616
image (BTT Pi or CB1, which can't be told apart). `ELYIR_BENCH_ANY_BOARD=1` lets another 64-bit board through.

**The start macro** (`elyir-bench startmacro on|off`, docs/start-macro.md; the setup card's What works sheet runs it
through the intent layer, docs/setup-card.md). `start_macro: on` in elyir-bench.conf, then only the `start macro`
step (and the printer's own slicer, so it hears about it):

- `printer/klipper/elyir-bench.cfg` from the current release goes into the config folder as `elyir-bench.cfg`. When any
  other `.cfg` in the config folder (linked folders too) has `[gcode_macro m600]` in any letter case, the file's M600
  section is left out; theirs stays theirs.
- `[include elyir-bench.cfg]` goes into printer.cfg after its last `[include ...]` line, or at the top when it has
  none; never into the `#*#` SAVE_CONFIG block.
- `elyir-bench-slicer/printer.json`, when there is one, gets `"start_macro": true`: the slicer then puts
  `ELYIR_BENCH_PRINT_START ...` and `ELYIR_BENCH_PRINT_START_DONE` around the machine's start G-code.
- Klipper restarts through Moonraker (`POST /printer/firmware_restart`) only when elyir-bench.cfg or printer.cfg
  changed, and the step checks `ELYIR_BENCH_PRINT_START` is there afterwards. Klipper not coming back puts all three
  back and restarts it again. While printing or paused it refuses; `--force` writes the files and leaves the
  restart for later.

`off` takes the file, the line and the flag out the same way. `remove` turns it off first. A release update
rewrites elyir-bench.cfg when it changed (and restarts Klipper, when nothing is printing).

**Remove** turns off what knows how to turn itself off (the screen goes back to KlipperScreen, the boot
screen to the Pi's own text, the door and the slicer stop), then deletes what's left of ours: services,
the nginx site, the avahi files, the Moonraker component and its `[printer_intent]` section (backup in
`moonraker.conf.elyir-bench-bak`), the sudoers rule and `~/elyir-bench`, paired phones included.
`elyir-bench.conf` and `elyir-bench-slicer/` stay in the config folder, so installing again picks up where
it left off. Packages it installed (Chromium, cage) stay; the Plymouth theme files stay but aren't used.

## Phases

1. **Installer core** (this): detect, plan, apply, doctor, rollback, panel; laptop deploy uses it.
2. **Browser setup**: the bootstrap installs only the non-disruptive parts, then shows a
   setup page on the panel and a QR code: confirm the screen ("tap the screen that lit up"),
   name the printer, switch the panel. Backed by Moonraker endpoints in the component.
3. **Updates**: release tarballs on GitHub, Moonraker `update_manager` entry, "Update
   available" on the Care tab, automatic rollback on a failed health check. Needs a public
   repo or a deploy token.
4. **Bare printer**: install Klipper, Moonraker and Mainsail when they are missing, detect MCUs,
   start from known printer profiles.
5. **Image**: a flashable Pi image with first-boot setup.

## Field notes: install and remove on desk.local (2026-10-05)

A Pi 4 (4 GB, Debian 13) with a DSI touchscreen and no printer board, made into a stranger's printer: the Elyir Bench
card's own install removed, KlipperScreen installed with its own installer (X11, defaults), Klipper's host MCU
(`klipper-mcu.service`; the user needs the `tty` group) and a stand-in printer.cfg whose bed and extruder read the Pi's
own temperature. Then the public release from releases.elyir.dev, through `install.sh`, with a real terminal.

- Install: check, "Go ahead?", 85–100 s, QR code in the terminal; printer.cfg, Mainsail and KlipperScreen untouched.
- The setup card from the real component; the start macro added from the card (include after Mainsail's, Klipper
  ready with it, M600 added since Mainsail's has none).
- A print through it: paused while warming (Getting ready), their PRINT_START, the kept +0.05 mm applied after it and
  taken off 2 s after the print ended. Cancel while warming: answered in 0.03 s, heaters off, "Print stopped."
- The screen trial on the real panel: left unanswered it went back to KlipperScreen by itself; Keep kept it.
- Remove, three times: Wi-Fi kept every time.

Found and fixed: install.sh ended silently under dash without a terminal (a failed redirect on `:`); remove left the
card's first-boot install enabled; a settings copy below the include (as elyir-bench.cfg said) stopped Klipper once the
include was gone (now commented out with a note, and the file says to copy a `gcode:` line); a remove step that
failed halfway wasn't put back; KlipperScreen's stop showed as a failed service; a stranger's printer was named DESK.

## Field notes: rebuilding Studio by hand (2026-10-01)

Studio went from Raspbian 11 to a fresh Raspberry Pi OS (Debian 13) card with two OS slots. Each
manual step below is something the bare-printer installer and the image have to do on their own.

| Step | Done by hand | To automate |
|---|---|---|
| Inventory | Listed repos, pinned commits, extension links, MCU firmware versions, CAN ids, boot config | `elyir-bench detect` on the old system, saved with the backup |
| Backup | rsync of printer_data (2.4 GB), dotfiles, system files; Moonraker DB snapshot via `/server/database/backup` | One "Back up this printer" action |
| Card | Imager with hostname, user, Wi-Fi, key; then edited the card on the Mac: removed `resize` from cmdline.txt, `growpart: off` in user-data, explicit DSI overlay with `invx,invy` instead of auto-detect | Image ships with this layout; setup page asks about the panel |
| Partitions | Grew rootfs to 12 GB online, added slot B (12 GB) and data (33.8 GB); fstab mounts `LABEL=astro-data` at /data and bind-mounts /data/printer_data | First boot does it |
| CAN | systemd-networkd `80-can0.network` with only `BitRate`; the gs_usb adapter rejects `BusErrorReporting` and `RestartSec` | Detect the adapter, write only what it supports |
| Stack | `installer/stack/install-stack.sh` with Klipper and Moonraker pinned to the old card's commits so MCU firmware still matches | Pinned versions come from the release bundle |
| Extensions | KlipperACE (its own install.sh), led_effect, KAMP, katapult; commented out update_manager entries for tools not reinstalled | Extensions listed in the backup are reinstalled; missing ones are reported, not left as warnings |
| Elyir Bench | `deploy.sh`; rotation 180 inferred from `invx,invy` | Already automatic |

Surprises worth remembering: the restored config folder included an `elyir-bench.conf` written by
an earlier failed install (`panel: klipperscreen`); workshop's networkd CAN file had never actually
been used (a `can0.service` brings CAN up there), so its options were untested.
