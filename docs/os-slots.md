# OS slots and over-the-air OS updates

Step 1 of the [vision](vision.md)'s order of work: two OS slots on the boot device, switched with
Raspberry Pi's `tryboot`, so a new OS can be tried and undone without anyone touching the
printer. The tool is `installer/elyir_bench_os.py`, installed on the printer as
`/usr/local/sbin/elyir-bench-os` (root, standard library only).

## Layout

| Partition | Label | What |
|---|---|---|
| p1 | bootfs | FAT boot partition: firmware, the pointer `config.txt`, one directory per slot |
| p2 | rootfs | slot A |
| p3 | rootfs-b | slot B |
| p4 | astro-data | `/data`: printer_data (bind-mounted to `~/printer_data`) and `/data/elyir-bench-os/state.json` |

On the boot partition:

```
config.txt        the pointer: which slot boots by default
tryboot.txt       the same for a one-off trial boot (`reboot '0 tryboot'`)
slotb/            slot B's own boot files: kernels, initramfs, dtbs, overlays, cmdline.txt, config.txt
elyir-bench/legacy-a.txt   the stock config.txt, kept while slot A still uses the stock layout
start4.elf …      firmware, shared by both slots
```

A pointer is three lines:

```
[all]
os_prefix=slotb/
include slotb/config.txt
```

Inside a slot, `/boot/firmware` is a bind mount of that slot's directory (the whole partition is
at `/boot/bootfs`). Kernel updates, `raspi-config` and the installer therefore read and write that
slot's own files and never touch the other slot's.

A card fresh from Raspberry Pi Imager uses the **stock layout**: slot A's boot files sit at the
partition's root and `config.txt` is the OS's own settings. That keeps working; slot A moves to
`slota/` the first time it is staged.

## Commands

```
elyir-bench-os status             which slot runs, which boots by default, recent trials
elyir-bench-os install            this tool, its two boot units and the watchdog setting, on the running slot
elyir-bench-os stage              copy the running OS into the idle slot
elyir-bench-os try [--deadline S] reboot once into the idle slot, on trial (default 300 s)
elyir-bench-os break <how>        testing only: damage the idle slot so its trial must fail
```

`stage` copies the running OS until the image pipeline exists (step 2 of the vision). A release
will be written into the idle slot in the same place, and everything after it stays the same.

## A trial

1. `try` records what works now (network, ssh, Moonraker, Klipper connected/ready, the Elyir Bench
   app, the panel, connected screens), writes `tryboot.txt` and reboots with `0 tryboot`.
2. The firmware boots the idle slot once. The tryboot flag is one-shot: any later reset or power
   cycle boots the default slot.
3. In the new OS, `elyir-bench-os-confirm.service` waits for everything that worked before to
   work again. Then it rewrites `config.txt` to point at the new slot (atomic replace). That is
   the commit.
4. Otherwise it reboots, and the old slot notes the rollback and the reason in `state.json`.

What brings a bad trial back, from earliest to latest:

| Failure | Caught by |
|---|---|
| Kernel or initramfs panic (root missing, bad init) | `panic=10` in the slot's cmdline: reboot |
| Hang before systemd (no init, stuck initramfs) | `kernel_watchdog_timeout=60` in `tryboot.txt`: the firmware starts the hardware watchdog, and the kernel lets it expire if nothing opens it |
| systemd itself hangs | `RuntimeWatchdogSec=15s` (systemd pings the hardware watchdog) |
| Boot stops in emergency mode, or confirm never starts | `elyir-bench-os-guard.service` (starts early, survives isolate): reboots after deadline + 2 min |
| Services don't come back | confirm's deadline: reboot |
| Anything else | a power cycle (the trial flag doesn't survive one) |

A slot marked broken by `break` is never committed, even if it looks healthy.

## Proven on Studio (2026-10-02)

Pi 4, 64 GB card, Debian 13, kernel 6.18, bootloader EEPROM of 2026-05-17. Every test ran over
SSH with nobody at the printer.

| Test | What happened | Back on A after |
|---|---|---|
| Normal reboot of A with the kit installed | Watchdog armed at 15 s; confirm and guard exit at once | — |
| `break unhealthy` (Moonraker won't start) | B booted on trial, the screen came up; confirm gave up at the deadline and rebooted | ~3 min (deadline 120 s) |
| `break emergency` (fstab needs a missing disk) | B stopped at the emergency prompt; the guard rebooted it. `/data` isn't mounted in emergency mode, so the guard used the default deadline (300 s + 120 s) | ~7 min |
| `break hang` (kernel frozen, no panic reboot) | systemd's watchdog reset the Pi; the tryboot flag did not survive the reset | ~1 min |
| `break no-systemd` (nothing for the kernel to start) | The firmware's watchdog (`watchdog.open_timeout=60` on the cmdline) reset the Pi | ~2 min |
| Clean B | Committed 7 s after confirm started; a plain reboot then boots B | — |
| Back to A from B | A's trial passed and the stock `config.txt` came back byte for byte | — |

Staging the first copy took 5.5 minutes; later copies took seconds (rsync only sends changes).

Things learned:

- systemd 257 takes the reboot argument as `--reboot-argument='0 tryboot'`, not positionally.
- Pi OS keeps the journal in RAM, so each trial saves its boot's journal and cmdline to
  `/data/elyir-bench-os/trial-<slot>.log` (overwritten by the next trial of that slot).
- A unit wanted by `sysinit.target` is started again each time something pulls that target in,
  so both boot units use `RemainAfterExit=yes`.
- The Pi has no clock until NTP syncs, so history entries written early in a boot are marked `~`.
- Cloud-init is disabled in staged slots so it doesn't treat a new slot as a new machine.

## Proven on a flashed card (2026-10-05)

The Elyir Bench card ([image.md](image.md), e669e7a) on a Pi 4 with a 32 GB card (28.8 GB). Its first boot
laid the card out by itself: bootfs 512 MB, rootfs 8.1 GB, rootfs-b 8.1 GB, astro-data 12.1 GB, root by
PARTUUID, printer_data on `/data`. Then, over SSH:

| Step | What happened |
|---|---|
| `stage` | Slot A copied into B in 2 min 50 s; B's boot files in `slotb/` (boot partition 16% used) |
| `try` | B booted on trial and was committed 5 s after confirm started: network, ssh, Moonraker, Klipper, the app, the panel |
| plain reboot | Came back on B (the commit holds) |
| `break unhealthy` on A, `try --deadline 120` | A booted, Moonraker never answered; rolled back to B by itself about 3 minutes after `try` |
| `stage` again | A restored from B; A's boot files moved to `slota/` |

A committed trial boot counts as settled (`settled()`): `stage` and `try` may follow it without a reboot.

## Releases

`elyir-bench-os stage <bundle>` writes a release's OS into the idle slot instead of a copy of the running one.
The bundle (`elyir-bench-os-<version>-pi4.tar`, made with each card by `image/build.sh`) is a tar of:

    manifest.json    {"kind": "elyir-bench-os", "version", "device": "pi4", "root": "root.ext4.zst", "root_bytes", "built"}
    root.ext4.zst    the card's root filesystem
    boot/            its boot files (kernel, initramfs, device trees, overlays, config.txt, cmdline.txt)

and it is signed like the app's releases (`<bundle>.sig`, ECDSA P-256 over SHA-256 with the key in
`scripts/release/`). `stage` refuses it unless it verifies against `/usr/local/share/elyir-bench/release-key.pem`
(the public half, on every card) and names this board. It then writes the root onto the idle partition and
grows it to fill it, and carries the printer over (`CARRY` in `elyir_bench_os.py`): its name and hosts file,
machine id and time zone, Wi-Fi connections, SSH host keys and authorized keys, Elyir Bench's state and slicer
engine, and the layout marker. It also writes that slot's fstab (the running one's, rewritten for the slot,
`/data` included) and its boot files into `slot<x>/` with the slot's `cmdline.txt`. Everything else comes from
the release: on the slot's first boot `elyir-bench-firstboot` runs the installer again with the release's app,
as on a fresh card. Then `try` works as for a copy, and a release that doesn't come up healthy rolls back.

The card carries Orca's libraries and the door's Python environment, so that first boot downloads nothing
inside the trial's deadline.

Proven on desk.local (Pi 4, 5 October 2026): the release bundle of card e66751e (923 MB, signed) went
into slot A in 4 min 25 s; `try` booted it, the installer ran on the new slot's first boot, and it was
committed 64 s after the trial started. Same name, same Wi-Fi, same SSH keys; the new release's app.

`elyir-bench-os update` gets it by itself: it reads `releases.elyir.dev/bench/os/latest-<board>.json`
(`{version, file, sha256, size, signature, board, published}`, the app's release format plus the board),
compares the version with the running slot's release (what it was staged from, or the card's
`/usr/local/share/elyir-bench/os-version`), downloads the bundle into `/data/releases` checked against the
feed's size and sha256 (one release kept at a time), then stages it (signature) and tries it. `--check` only
says, `--no-try` stages, `--feed` points elsewhere. Proven on desk.local with a feed served from a Mac on the
same Wi-Fi: 880 MB downloaded in 1 min 35 s, written into slot B, committed a minute after the trial started.

By itself: `elyir-bench-os-update.timer` (on the card, around 3 am with an hour's spread) runs `update --auto`,
which goes ahead only on a card from the image (`os-version` is there: Studio's hand-built OS is never replaced),
only while the printer is idle (not printing or paused, and Moonraker answering), and never with a release
that already rolled back on this printer (it waits for a newer one). Offline, it says "not now" and tries the
next night.
A Bench Box (`role: controller`, Klipper and Moonraker off on purpose) counts as idle.

## Not yet

- Publishing OS releases to releases.elyir.dev (`bench/os/`).
- "Updated overnight" on the Care tab (a drawing first).
- Firmware files at the partition root are shared and aren't updated per slot.
- Idle-only scheduling and "Updated overnight" on the Care tab.
- Converting a running printer (Workshop) to this layout without opening it (vision step 5).
- A card flashed from the Elyir Bench image ([image.md](image.md)) gets this layout on its first boot
  (`elyir-bench-layout`); not yet tried on a Pi.
