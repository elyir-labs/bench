# Vision

Elyir Bench should make a Raspberry Pi 3D printer behave like an appliance: you set it up once
on its own screen or your phone, and after that it keeps itself working. No commands, no SSH,
and no reaching inside the printer for the SD card.

This document records the direction and the decisions behind it. The phase-by-phase plan for
the installer is in [installer.md](installer.md).

## The promise

Whatever the situation, the person never runs a command, opens a terminal, or takes the
printer apart after the first flash:

| Situation | What the person does |
|---|---|
| A new printer, or a fresh build | Flash the Elyir Bench image once, power on, scan the QR code on the screen |
| Replacing an old printer | During setup, choose "Move from another printer" and pick the old one |
| A printer bought already built, with a Pi | Adopt it from the browser; the Pi converts itself without being opened |
| Handing a printer to a friend | Care → "Prepare for a new owner", then the friend powers it on |
| Keeping it up to date | Nothing. Updates install while the printer is idle and undo themselves if anything breaks |

The only scope limit is the hardware: the printer runs on a Raspberry Pi (Pi 4 or newer).

## One end state, three ways in

Every printer ends up in the same known state, however it started:

- **Two OS slots and a data partition** on the boot device. A new OS is written into the idle
  slot while the printer keeps working. Configs, gcode files and history live on the data
  partition, so an OS change never touches them.
- **The Elyir Bench agent**, grown from today's installer. It handles setup, updates, backups,
  moving to another printer, and resetting for a new owner.
- **The Elyir Bench UI** on the touchscreen and phone, with Mainsail behind the Advanced door.

The three ways in:

1. **Flash the image.** "Elyir Bench OS" is Raspberry Pi OS Lite with Klipper, Moonraker,
   Mainsail, Elyir Bench and the kiosk already in it. It can be listed in Raspberry Pi Imager
   through a custom OS list.
2. **Adopt a running Pi.** The agent is installed once (today: one command; later: from a
   browser page). It then reboots once, on trial, into a small RAM-only system that can resize
   the main OS while it isn't running, creates the second slot and the data partition, and
   boots back. If anything goes wrong, the trial boot is not repeated and the Pi starts its
   normal OS. This is how existing printers such as Workshop get converted without being opened.
3. **Already on Elyir Bench.** Nothing to do; it updates itself.

## How the pieces work

**First boot.** If the Pi has no Wi-Fi and no cable, it starts its own setup Wi-Fi (as smart
plugs do), and the panel offers two ways: a QR code that lets a phone pick the network and type
its password, or the same on the panel with a keyboard. While it joins, the panel asks the
printer's name; once it's on, it offers to bring things over from another printer. Everything
else (screen, touch, boards, CAN, ACE units, cameras) is detected. Drawn in `design/setup/`.

**Printer configuration.** The agent detects the boards on USB and CAN, then either matches a
known printer profile or restores the person's own configuration from another printer or a
backup. A one-off custom build still needs its configuration written once; after that it is
backed up and travels with the printer.

**Updates.** A release is a whole, tested image of everything: kernel, Klipper, Moonraker,
Mainsail, Elyir Bench. The printer downloads it, checks its signature, writes it into the idle
slot, and reboots into it once, on trial, using Raspberry Pi's `tryboot` firmware feature. If
the network, Klipper, Moonraker and Elyir Bench all come up healthy, the switch becomes
permanent. If not, the next reboot (forced by the hardware watchdog if the new system hangs)
returns to the previous slot. Updates only start while the printer is idle, never during a
print. The Care tab shows "Updated overnight".

**Board firmware.** When a Klipper release needs the printer's boards reflashed, the agent
does it over USB or CAN with Katapult. Each release pins versions that were tested together,
so firmware changes are deliberate, not accidental.

**Moving and resetting.** "Move from another printer" copies configuration, history, spools
and files from a printer on the network or from a backup. "Prepare for a new owner" wipes
Wi-Fi, accounts and remote access but keeps calibration and configuration.

## Security

- Updates are signed; the printer refuses an image whose signature doesn't verify.
- Printers pull updates; nothing is pushed into the home network, and no ports are opened.
- SSH is off by default (or key-only for developers). Each device has its own credentials.
- Remote access, when added, goes out from the printer; it never needs port forwarding.

## Decisions

**Two OS slots instead of in-place upgrades.** `apt` upgrades stay fine for routine updates,
but a major OS upgrade in place has no undo and can leave the printer offline (the network
stack changes between Debian releases), which then needs physical access anyway. Rewriting
the card remotely from RAM was rejected: a failure mid-write leaves an unreachable printer.

**The core printer stack runs directly on the OS, not in containers.** Considered on
2026-10-01. Containers would give per-service rollback and carry their own runtime, but:

- the OS layer (kernel, bootloader, Wi-Fi, display overlays, the kiosk's graphics stack) stays
  outside any container, so two OS slots would still be needed, and containers would add a
  second update system instead of replacing one;
- Klipper needs serial ports, CAN on the host network, real-time scheduling and USB access for
  firmware flashing, which means privileged host-network containers that give up most of the
  isolation;
- Moonraker manages the host itself (services, reboots, its own git-based updater);
- Klipper extensions such as KlipperACE install by linking files into Klipper, which would
  turn every combination of extensions into a custom image;
- the Docker daemon, image storage and extra SD card writes cost a Pi 4 more than they return.

The two-slot image already gives the main benefit containers would bring: every release is
one tested image of everything, switched and rolled back as a unit, including the OS.

**Where containers are used:**

1. **CI.** Each release's exact Klipper, Moonraker and Elyir Bench run in containers on GitHub
   Actions against a simulated printer board before any printer downloads the release.
2. **Optional add-ons.** Third-party extras (Spoolman, OctoEverywhere, a Home Assistant bridge)
   run as containers, so they stay isolated, optional and easy to remove without being baked
   into the OS image.

balenaOS was noted as the off-the-shelf version of this idea (containers, two OS slots, fleet
updates). It was not adopted: it ties updates to balena's cloud (or a self-hosted openBalena),
is paid beyond 10 devices, and Klipper's hardware needs make it awkward.

## What can't be automated

- The first flash of a blank card (unless cards ship pre-flashed).
- Configuration for a printer nobody has written a profile for.
- Physically fitting a Pi into a printer that doesn't have one.

## Order of work

1. Two OS slots and over-the-air OS updates, proven on Studio, including a deliberately broken
   update that must roll back on its own. Done 2026-10-02, with a copy of the running OS
   standing in for a release image: see [os-slots.md](os-slots.md).
2. An image build pipeline (GitHub Actions with Raspberry Pi's `rpi-image-gen`), producing the
   image and signed update bundles for each release, tested in containers first.
3. First-boot setup: hotspot, QR code, setup on the panel and phone.
4. "Move from another printer" and "Prepare for a new owner".
5. Adopting a running Pi in place, which converts Workshop without opening it.

Open decision: where printers download updates from. A public repository's GitHub Releases
works with no extra infrastructure; a private one needs a token on every printer or a small
update server.
