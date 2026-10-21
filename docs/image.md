# The Elyir Bench card image

Step 2 of the [vision](vision.md)'s order of work: a card you flash, put in the printer and power on. The
printer then opens its own setup Wi-Fi ([setup.md](setup.md)) with no computer involved. This is the first cut,
for a Raspberry Pi 4.

```bash
image/build.sh --dev      # dist/elyir-bench-<release>-pi4-dev.img.xz, with this Mac's SSH key for user pi
image/build.sh            # the same with no key: nobody can log in
```

Flash it with Raspberry Pi Imager (Use custom), and choose **No** when Imager offers to apply OS customization:
the card has its own user, name and Wi-Fi setup.

## What's on the card

Raspberry Pi OS's own pieces (the Raspberry Pi kernel, firmware and archive), Debian Trixie arm64, built by
Raspberry Pi's [rpi-image-gen](https://github.com/raspberrypi/rpi-image-gen) in Docker (`image/Dockerfile`:
native on an Apple Silicon Mac or a Pi). Layers in `image/layer/`:

- **elyir-bench-base**: what rpi-image-gen's `trixie-minbase` has, with NetworkManager (and wpa_supplicant, which can be a
  hotspot) in place of systemd-networkd and iwd, since the first Wi-Fi drives NetworkManager.
- **elyir-bench-printer**: Klipper, Moonraker and Mainsail laid out as KIAUH does it on our printers, pinned to what Workshop
  runs (`klipper`, `moonraker`, `mainsail` variables); the packages the installer would otherwise download (cage,
  chromium, plymouth, dnsmasq-base, nginx, avahi); and the Elyir Bench release in `~/elyir-bench/incoming`.

`image/config/elyir-bench-pi4.yaml`: user `pi` with no password (locked) and sudo without one (the installer runs
`sudo -n`), the name `elyir-bench` on the network until setup names it, the Wi-Fi country US, SSH by key only.

## First boot

1. **elyir-bench-layout** makes the card's two OS slots and data partition ([os-slots.md](os-slots.md)), once, before
   Klipper and Moonraker start. The image holds only `bootfs` and `rootfs` (slot A, by PARTUUID), so it downloads
   and flashes quickly; on the card, slot A grows to the slot size, and `rootfs-b` (slot B) and `astro-data`
   (`/data`) follow it. `printer_data` moves to `/data` and comes back at `~/printer_data` as a bind mount, as on
   Studio. Slots are a third of the card after 4 GB, between 6 and 12 GB: a 32 GB card gets 9 + 9 GB and 13 GB of
   data, a 16 GB card 6 + 6 and 3.5. A card too small for two slots (8 GB) gets one OS on all of it.
   `image/test-layout.sh` runs it on pretend 32, 16 and 8 GB cards in Docker. The slots tool (`elyir-bench-os`),
   its two boot units and the watchdog setting are on the card from the start.
2. **elyir-bench-firstboot** runs `elyir-bench apply <release>` as `pi`, on the printer's own hardware and with no network:
   it finds the screen and touch, writes the kiosk, the boot screen and the first Wi-Fi, and starts them. Its output
   is on the console and in `journalctl -u elyir-bench-firstboot`.
3. The first Wi-Fi finds no network and opens **Elyir Bench XXXX**; the panel shows the two ways in.

Later boots go straight to the boot screen and the app.

Steps that download (the door's and slicing service's libraries, Orca, the door's binaries) don't run on that
first boot: with no network they say "waits for the network". Renaming during setup applies only the name, then
the setup service runs a full `apply` in the background (`~/elyir-bench/state/apply-after-setup.log`), which
downloads them. The first card sat 55 minutes in pip offline and never reached the Wi-Fi setup, which is why.

## Tried on a Pi 4 (5 October 2026)

First card, a Pi 4 with the 7-inch DSI touchscreen and an iPhone: scanned the setup code, joined, picked the home
Wi-Fi on the phone page, named it on the panel (Desk), scanned the phone code and opened it on the phone. The
panel then showed the Problem screen (no `printer.cfg` yet). Found on the way, fixed since: the offline first boot
above, and the panel giving up on the setup state when it loaded before the service. Touch didn't respond on the
very first boot and did after a reboot; not seen again yet, to watch on the next fresh card.

Second card (0084726), flashed fresh and powered on with no cable: the first boot went straight to the setup
Wi-Fi and the panel's two ways in, and setup worked from there. The first card's problems didn't come back.

## Not yet

- Signed updates written into the idle slot from releases.elyir.dev instead of a copy. (The two slots themselves
  are proven on a flashed card: [os-slots.md](os-slots.md).)
- Klipper has no `printer.cfg`, so after setup the printer shows its Problem screen. Printer profiles (or bringing a
  config over) are phase 4 of [installer.md](installer.md).
- A Pi 5 image, and listing it in Raspberry Pi Imager. (The Pi 4 card is built by the public repository's OS
  image workflow in GitHub Actions; a maintainer signs it before it goes live.)
- The first boot shows the console until `apply` has started the kiosk (a minute or two); the boot screen from the
  first frame needs the theme baked in at build time.
