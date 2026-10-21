#!/usr/bin/env python3
"""elyir-bench-os: two OS slots on one boot device, switched with Raspberry Pi's tryboot.

    elyir-bench-os status             which slot runs, which one boots by default, recent trials
    elyir-bench-os install            put this tool, its boot units and the watchdog setting on this slot
    elyir-bench-os stage [bundle]     the idle slot: a signed release (bundle) or a copy of the running OS
    elyir-bench-os update [--check]   the newest release from releases.elyir.dev: download, stage, try
    elyir-bench-os update --auto      the same, by itself (elyir-bench-os-update.timer): only when it's safe
    elyir-bench-os try [--deadline S] reboot once into the idle slot, on trial
    elyir-bench-os confirm            boot unit: on a trial, wait for health, then commit or go back
    elyir-bench-os guard              boot unit: reboot a trial that never gets as far as confirm
    elyir-bench-os break <how>        testing: damage the idle slot so its trial has to fail

Runs as root. Standard library only. See docs/os-slots.md.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import shutil
import subprocess
import tarfile
import sys
import time
import urllib.request
from pathlib import Path

SLOTS = {"a": 2, "b": 3}          # slot -> partition number on the boot device
BOOT_PART = 1                     # the FAT partition the firmware reads
STATE_DIR = Path(os.environ.get("ELYIR_BENCH_OS_STATE", "/data/elyir-bench-os"))
RUN = Path("/run/elyir-bench-os")
DT_BOOTLOADER = Path("/proc/device-tree/chosen/bootloader")
TOOL = "/usr/local/sbin/elyir-bench-os"
CONFIRM_UNIT = "elyir-bench-os-confirm.service"
GUARD_UNIT = "elyir-bench-os-guard.service"
DEADLINE = 300                    # seconds a trial gets to become healthy
GUARD_GRACE = 120                 # the guard waits this much longer than the deadline
FIRMWARE_WATCHDOG = 60            # seconds the OS gets to take over the firmware's watchdog
MOONRAKER = "http://127.0.0.1:7125"
INTENT_STATES = {"setup", "ready", "preparing", "printing", "needs_you", "finished", "problem"}
# what makes up an OS's own boot files, as opposed to the firmware's or another slot's
BOOT_FILES = re.compile(r"^(kernel.*\.img|initramfs.*|.*\.dtb|cmdline\.txt|config\.txt|issue\.txt)$")

CONFIRM_SERVICE = f"""\
[Unit]
Description=Elyir Bench OS: commit a trial boot once healthy, or go back
After=network-online.target moonraker.service klipper.service
Wants=network-online.target

[Service]
Type=simple
RemainAfterExit=yes
ExecStart={TOOL} confirm

[Install]
WantedBy=multi-user.target
"""

GUARD_SERVICE = f"""\
[Unit]
Description=Elyir Bench OS: undo a trial boot that never finishes starting
DefaultDependencies=no
IgnoreOnIsolate=yes

[Service]
Type=simple
# stays active, so later pulls of sysinit.target don't start it again
RemainAfterExit=yes
ExecStart={TOOL} guard

[Install]
WantedBy=sysinit.target
"""

WATCHDOG_CONF = """\
# Elyir Bench: systemd pings the hardware watchdog, so a hung system resets itself. On a trial
# boot this also takes over the watchdog the firmware started (kernel_watchdog_timeout).
[Manager]
RuntimeWatchdogSec=15s
"""

# A release's OS (docs/os-slots.md, "Releases"): a tar of manifest.json, the root filesystem (root.ext4.zst) and
# boot/, signed like the app's releases (ECDSA P-256, openssl dgst -sha256) with the key in install/
RELEASE_KEY = Path("/usr/local/share/elyir-bench/release-key.pem")
BUNDLE_KIND = "elyir-bench-os"
# Where releases are announced, a file per board (scripts/release/): {version, file, sha256, size, signature, board}
OS_FEED = "https://releases.elyir.dev/bench/os/latest-{board}.json"
OS_VERSION = Path("/usr/local/share/elyir-bench/os-version")    # the card's own release, written when it's built
DOWNLOADS = Path("/data/releases")
# What this printer is, carried from the running slot into a new release's OS. Everything else comes from the
# release, and the installer makes Elyir Bench true again on that slot's first boot (elyir-bench-firstboot).
CARRY = ["etc/hostname", "etc/hosts", "etc/machine-id", "etc/localtime", "etc/timezone", "etc/ssh/ssh_host_*",
         "etc/NetworkManager/system-connections", "etc/sudoers.d/elyir-bench", "home/*/.ssh/authorized_keys",
         "home/*/elyir-bench/state", "home/*/elyir-bench/slicer", "var/lib/elyir-bench/laid-out"]
FSTAB_NOTE = "# Elyir Bench: the boot partition, and this slot's own boot files from it"


# ── small helpers ─────────────────────────────────────────────────────────────

class Refused(Exception):
    pass


def run(cmd: list[str], check: bool = True, timeout: int = 3600) -> subprocess.CompletedProcess:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise Refused(f"{' '.join(cmd)} failed: {(p.stderr or p.stdout).strip()[-400:]}")
    return p


def read(path: Path | str, default: str = "") -> str:
    try:
        return Path(path).read_text(errors="replace")
    except OSError:
        return default


def now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def http_json(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.load(r)


def write_atomic(path: Path, text: str) -> None:
    """Replace a file so a power cut leaves either the old or the new one (FAT included)."""
    tmp = path.with_name(path.name + ".new")
    with open(tmp, "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    os.sync()


def load_state() -> dict:
    try:
        st = json.loads((STATE_DIR / "state.json").read_text())
    except (OSError, ValueError):
        st = {}
    st.setdefault("slots", {})
    st.setdefault("history", [])
    st.setdefault("trial", None)
    return st


def save_state(st: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    st["history"] = st["history"][-30:]
    write_atomic(STATE_DIR / "state.json", json.dumps(st, indent=2))


def clock_synced() -> bool:
    return run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"], check=False).stdout.strip() == "yes"


def note(st: dict, event: str, slot: str, detail: str = "") -> None:
    # early in a boot the Pi has no clock yet (no RTC): such times are marked with "~"
    st["history"].append({"at": now() if clock_synced() else "~" + now(), "event": event, "slot": slot, "detail": detail})
    print(f"{event}: slot {slot}{' — ' + detail if detail else ''}", flush=True)


# ── where things are ──────────────────────────────────────────────────────────

def root_partuuid(cmdline: str) -> tuple[str, int] | None:
    m = re.search(r"(?:^|\s)root=PARTUUID=([0-9a-fA-F]+)-(\d+)(?:\s|$)", cmdline)
    return (m.group(1), int(m.group(2))) if m else None


def set_cmdline(cmdline: str, disk: str, part: int) -> str:
    """The same kernel command line, booting `part` and rebooting itself on a panic."""
    words = [w for w in cmdline.split() if not w.startswith(("root=", "panic="))]
    return " ".join(words + [f"root=PARTUUID={disk}-{part:02d}", "panic=10"]) + "\n"


def config_prefix(text: str) -> str:
    prefix = ""
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("os_prefix="):
            prefix = line.split("=", 1)[1].strip()
    return prefix


def slot_of(part: int | None) -> str | None:
    return next((s for s, p in SLOTS.items() if p == part), None)


def other(slot: str) -> str:
    return "b" if slot == "a" else "a"


def booted() -> tuple[str, str]:
    """(disk id, slot) of the running OS, from the kernel command line."""
    r = root_partuuid(read("/proc/cmdline"))
    if not r or not slot_of(r[1]):
        raise Refused("the running OS isn't booted from a known slot (root=PARTUUID=<disk>-02/03)")
    return r[0], slot_of(r[1])


def tryboot_flag() -> bool:
    raw = DT_BOOTLOADER.joinpath("tryboot").read_bytes() if DT_BOOTLOADER.joinpath("tryboot").exists() else b""
    return int.from_bytes(raw, "big") == 1 if raw else False


def part_device(disk: str, part: int) -> str:
    return os.path.realpath(f"/dev/disk/by-partuuid/{disk}-{part:02d}")


def mountinfo() -> list[dict]:
    out = []
    for line in read("/proc/self/mountinfo").splitlines():
        pre, _, post = line.partition(" - ")
        f, g = pre.split(), post.split()
        un = lambda s: s.encode().decode("unicode_escape")  # \040 for spaces
        out.append({"root": un(f[3]), "target": un(f[4]), "fstype": g[0], "source": g[1]})
    return out


def bootfs(disk: str) -> Path:
    """The whole FAT boot partition: wherever it's mounted, or mounted under /run for us."""
    dev = part_device(disk, BOOT_PART)
    for m in mountinfo():
        if m["source"] == dev and m["root"] == "/":
            return Path(m["target"])
    mnt = RUN / "bootfs"
    mnt.mkdir(parents=True, exist_ok=True)
    run(["mount", dev, str(mnt)])
    return mnt


def own_boot_dir(fat: Path) -> Path:
    """The running OS's boot files: the FAT root (a stock card) or its slot<x>/ directory."""
    for m in mountinfo():
        if m["target"] == "/boot/firmware":
            return fat / m["root"].lstrip("/")
    return fat


def render_pointer(slot: str) -> str:
    return (f"# Elyir Bench: which OS slot boots. Written by elyir-bench-os; don't edit.\n"
            f"# That OS's own settings are in slot{slot}/config.txt (/boot/firmware/config.txt inside it).\n"
            f"[all]\nos_prefix=slot{slot}/\ninclude slot{slot}/config.txt\n")


def trial_pointer(text: str) -> str:
    return (text.rstrip() + "\n\n[all]\n"
            "# Trial boot: the firmware starts the hardware watchdog; if the OS doesn't take it\n"
            "# over in time, the Pi resets and boots the default slot again.\n"
            f"kernel_watchdog_timeout={FIRMWARE_WATCHDOG}\n")


def pointer_for(fat: Path, slot: str) -> str | None:
    """The config.txt that boots `slot`, or None if it has nothing to boot."""
    if (fat / f"slot{slot}" / "cmdline.txt").exists():
        return render_pointer(slot)
    legacy = fat / "elyir-bench" / f"legacy-{slot}.txt"
    if legacy.exists():
        return legacy.read_text()
    cur = read(fat / "config.txt")
    if not config_prefix(cur) and slot_of((root_partuuid(read(fat / "cmdline.txt")) or ("", 0))[1]) == slot:
        return cur
    return None


def settled(fat: Path, cur: str, st: dict) -> bool:
    """The running slot is the one that boots by default and no trial is waiting on it. A trial boot that has
    been committed counts: an update can follow it without a reboot in between (the tryboot flag stays set
    until the next reset, but the firmware would boot this slot anyway)."""
    return committed(fat) == cur and not st.get("trial")


def committed(fat: Path) -> str | None:
    """The slot the firmware boots by default."""
    text = read(fat / "config.txt")
    r = root_partuuid(read(fat / config_prefix(text) / "cmdline.txt"))
    return slot_of(r[1]) if r else None


def render_fstab(text: str, disk: str, slot: str) -> str:
    """The running OS's fstab, rewritten for `slot`: its own root, and /boot/firmware as a bind
    mount of its own directory on the boot partition, so kernel updates land in that slot."""
    out = []
    for line in text.splitlines():
        f = line.split()
        if line.strip() == FSTAB_NOTE:
            continue
        if len(f) >= 2 and not f[0].startswith("#"):
            if f[1] in ("/boot/firmware", "/boot/bootfs"):
                continue
            if f[1] == "/":
                line = re.sub(r"^\S+", f"PARTUUID={disk}-{SLOTS[slot]:02d}", line)
        out.append(line)
    while out and not out[-1].strip():
        out.pop()
    return "\n".join(out + [
        "", FSTAB_NOTE,
        f"PARTUUID={disk}-{BOOT_PART:02d}  /boot/bootfs  vfat  defaults  0  2",
        f"/boot/bootfs/slot{slot}  /boot/firmware  none  bind,x-systemd.requires-mounts-for=/boot/bootfs  0  0",
    ]) + "\n"


# ── health ────────────────────────────────────────────────────────────────────

def elyir_bench_port() -> int:
    for conf in Path("/home").glob("*/printer_data/config/elyir-bench.conf"):
        m = re.search(r"^\s*port\s*[:=]\s*(\d+)", read(conf), re.M)
        if m:
            return int(m.group(1))
    return 8088


def displays() -> list[str]:
    return sorted(p.parent.name.split("-", 1)[1] for p in Path("/sys/class/drm").glob("card*-*/status")
                  if read(p).strip() == "connected")


def active(unit: str) -> bool:
    return run(["systemctl", "is-active", "--quiet", unit], check=False).returncode == 0


def look() -> dict[str, list]:
    """What works right now: name -> [ok, detail]."""
    out: dict[str, list] = {}
    route = run(["ip", "route", "show", "default"], check=False).stdout.strip()
    out["network"] = [bool(route), route.split(" dev ")[-1].split()[0] if route else "no default route"]
    out["ssh"] = [active("ssh.service"), "ssh.service"]
    try:
        info = http_json(f"{MOONRAKER}/server/info")["result"]
        out["moonraker"] = [True, "answers"]
        out["klipper"] = [bool(info.get("klippy_connected")), f"klippy {info.get('klippy_state')}"]
        out["klipper_ready"] = [info.get("klippy_state") == "ready", f"klippy {info.get('klippy_state')}"]
    except Exception as e:
        out["moonraker"] = [False, f"no answer ({e.__class__.__name__})"]
    port = elyir_bench_port()
    try:
        state = http_json(f"http://127.0.0.1:{port}/printer/intent")["result"]["state"]
        out["elyir-bench"] = [state in INTENT_STATES, f"intent {state}"]
    except Exception as e:
        out["elyir-bench"] = [False, f"no answer on :{port} ({e.__class__.__name__})"]
    out["panel"] = [active("elyir-bench-kiosk.service"), "elyir-bench-kiosk.service"]
    shown = displays()
    out["displays"] = [bool(shown), ",".join(shown) or "none connected"]
    return out


def baseline() -> dict:
    """What the trial has to match: everything that works now, and the same screens."""
    seen = look()
    return {"required": [k for k, (ok, _) in seen.items() if ok and k != "displays"], "displays": displays()}


def healthy(base: dict) -> tuple[bool, str]:
    seen = look()
    bad = [f"{k}: {seen.get(k, [False, 'missing'])[1]}" for k in base["required"] if not seen.get(k, [False])[0]]
    lost = sorted(set(base.get("displays", [])) - set(displays()))
    if lost:
        bad.append(f"display gone: {','.join(lost)}")
    return (not bad, "; ".join(bad) or ", ".join(f"{k} ok" for k in base["required"]))


def printing() -> bool:
    try:
        r = http_json(f"{MOONRAKER}/printer/objects/query?print_stats")["result"]
        return r["status"]["print_stats"]["state"] in ("printing", "paused")
    except Exception:
        return False


# ── slot contents ─────────────────────────────────────────────────────────────

def install_kit(root: Path) -> None:
    """This tool, its two boot units and the watchdog setting, into the OS at `root`."""
    tool = root / TOOL.lstrip("/")
    tool.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).resolve(), tool)
    tool.chmod(0o755)
    units = root / "etc/systemd/system"
    for name, text, target in ((CONFIRM_UNIT, CONFIRM_SERVICE, "multi-user.target"),
                               (GUARD_UNIT, GUARD_SERVICE, "sysinit.target")):
        (units / name).write_text(text)
        wants = units / f"{target}.wants"
        wants.mkdir(exist_ok=True)
        link = wants / name
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(f"/etc/systemd/system/{name}")
    conf = root / "etc/systemd/system.conf.d"
    conf.mkdir(parents=True, exist_ok=True)
    (conf / "elyir-bench-watchdog.conf").write_text(WATCHDOG_CONF)


def copy_boot_files(src: Path, dst: Path) -> None:
    for p in sorted(src.iterdir()):
        if p.is_file() and BOOT_FILES.match(p.name):
            shutil.copyfile(p, dst / p.name)   # copyfile: FAT has no permissions to copy
    (dst / "overlays").mkdir()
    for p in sorted((src / "overlays").iterdir()):
        if p.is_file():
            shutil.copyfile(p, dst / "overlays" / p.name)


def size_of(d: Path) -> int:
    return sum(p.stat().st_size for p in d.rglob("*") if p.is_file())


class Mounted:
    """The idle slot's filesystem, mounted for the duration of a `with` block."""

    def __init__(self, disk: str, slot: str, ro: bool = False):
        self.dev = part_device(disk, SLOTS[slot])
        self.path = RUN / f"slot-{slot}"
        self.opts = ["-o", "ro"] if ro else []

    def __enter__(self) -> Path:
        if any(m["source"] == self.dev for m in mountinfo()):
            raise Refused(f"{self.dev} is mounted already; unmount it first")
        self.path.mkdir(parents=True, exist_ok=True)
        run(["mount", *self.opts, self.dev, str(self.path)])
        return self.path

    def __exit__(self, *exc) -> None:
        os.sync()
        run(["umount", str(self.path)], check=False)


def os_name(root: Path) -> str:
    m = re.search(r'^PRETTY_NAME="?([^"\n]*)', read(root / "etc/os-release"), re.M)
    return m.group(1) if m else "?"


# ── commands ──────────────────────────────────────────────────────────────────

def cmd_status(args) -> int:
    disk, cur = booted()
    fat = bootfs(disk)
    st = load_state()
    default = committed(fat)
    info = {
        "running": cur, "default": default, "trial": tryboot_flag(),
        "slots": {s: {"partition": part_device(disk, p),
                      "boots_from": (f"slot{s}/" if (fat / f"slot{s}" / "cmdline.txt").exists()
                                     else "/ (stock layout)" if pointer_for(fat, s) else None),
                      **st["slots"].get(s, {})} for s, p in SLOTS.items()},
        "pending_trial": st["trial"], "history": st["history"][-8:],
    }
    if args.json:
        print(json.dumps(info, indent=2))
        return 0
    print(f"Running slot {cur}{' (on trial)' if info['trial'] else ''}; the firmware boots slot {default} by default.")
    for s, d in info["slots"].items():
        extra = ", ".join(f"{k} {v}" for k, v in d.items() if k not in ("partition", "boots_from"))
        print(f"  slot {s}: {d['partition']}, boot files {d['boots_from'] or 'none'}{'; ' + extra if extra else ''}")
    if st["trial"]:
        print(f"  trial pending: slot {st['trial']['slot']} since {st['trial']['started']}")
    for h in info["history"]:
        print(f"  {h['at']:>20}  {h['event']:<12} slot {h['slot']}  {h['detail']}")
    return 0


def cmd_install(args) -> int:
    install_kit(Path("/"))
    run(["systemctl", "daemon-reload"])
    print(f"installed {TOOL}, {CONFIRM_UNIT}, {GUARD_UNIT} and the watchdog setting (active from the next boot)")
    return 0


def device_class(model: str) -> str | None:
    """pi4, pi5 … from /proc/device-tree/model, as a release's manifest names the boards it's for."""
    m = re.search(r"Raspberry Pi (\d+)", model)
    return f"pi{m.group(1)}" if m else None


def check_manifest(manifest: dict, model: str) -> None:
    if manifest.get("kind") != BUNDLE_KIND:
        raise Refused("that isn't an Elyir Bench OS release")
    want = manifest.get("devices") or [manifest.get("device")]
    have = device_class(model)
    if have not in want:
        raise Refused(f"that release is for {', '.join(str(w) for w in want)}, and this is {model.strip() or 'unknown'}")


def verify(bundle: Path, sig: Path, key: Path) -> None:
    """The release's signature against the key we ship: a release that doesn't verify is never written."""
    if not sig.exists():
        raise Refused(f"no signature next to the release ({sig.name})")
    if not key.exists():
        raise Refused(f"no release key on this printer ({key})")
    p = run(["openssl", "dgst", "-sha256", "-verify", str(key), "-signature", str(sig), str(bundle)], check=False)
    if p.returncode != 0 or "Verified OK" not in p.stdout:
        raise Refused("the release's signature doesn't verify: not writing it")


def carry(dst: Path, src: Path = Path("/")) -> list[str]:
    """This printer's identity and Elyir Bench's state, from the running slot into `dst` (CARRY)."""
    done = []
    for pat in CARRY:
        for path in sorted(src.glob(pat)):
            rel = path.relative_to(src)
            run(["rsync", "-aHAX", "--numeric-ids", "--relative", f"{src}/./{rel}", f"{dst}/"])
            done.append(str(rel))
    return done


def write_release(bundle: Path, disk: str, tgt: str, fat: Path) -> tuple[str, str]:
    """A verified release into slot `tgt`: its root filesystem onto the partition, grown to fill it, this
    printer carried into it, and its boot files into slot<x>/. Returns (version, OS name)."""
    with tarfile.open(bundle) as tf:
        manifest = json.load(tf.extractfile("manifest.json"))
        check_manifest(manifest, read("/proc/device-tree/model"))
        part = part_device(disk, SLOTS[tgt])
        if any(m["source"] == part for m in mountinfo()):
            raise Refused(f"{part} is mounted; unmount it first")
        size = int(run(["blockdev", "--getsize64", part]).stdout.strip())
        if int(manifest["root_bytes"]) > size:
            raise Refused(f"the release's root ({int(manifest['root_bytes']) >> 30} GB) is bigger than slot {tgt} ({size >> 30} GB)")
        print(f"writing release {manifest['version']} into slot {tgt} ({part}) …", flush=True)
        with open(part, "wb") as out:
            z = subprocess.Popen(["zstd", "-dcq"], stdin=subprocess.PIPE, stdout=out)
            shutil.copyfileobj(tf.extractfile(manifest["root"]), z.stdin, 1 << 20)
            z.stdin.close()
            if z.wait() != 0:
                raise Refused("the release's root filesystem didn't unpack")
            os.fsync(out.fileno())
        run(["e2fsck", "-fy", part], check=False)       # 1: fixed something (it shouldn't), 0: clean
        run(["resize2fs", part])
        with Mounted(disk, tgt) as dst:
            (dst / "etc/fstab").write_text(render_fstab(read("/etc/fstab"), disk, tgt))
            (dst / "boot/bootfs").mkdir(exist_ok=True)
            (dst / "etc/cloud").mkdir(exist_ok=True)
            (dst / "etc/cloud/cloud-init.disabled").write_text("a new slot isn't a new machine\n")
            carried = carry(dst)
            name = os_name(dst)
        print(f"carried: {', '.join(carried)}", flush=True)

        boot = [m for m in tf.getmembers() if m.name.startswith("boot/") and m.isfile()]
        need = sum(m.size for m in boot)
        final, new = fat / f"slot{tgt}", fat / f".slot{tgt}.new"
        shutil.rmtree(new, ignore_errors=True)
        if shutil.disk_usage(fat).free + (size_of(final) if final.exists() else 0) < need * 1.2:
            raise Refused(f"not enough room on the boot partition for slot {tgt}'s boot files ({need // 2**20} MB)")
        for m in boot:
            rel = Path(m.name).relative_to("boot")
            if ".." in rel.parts:
                raise Refused(f"a boot file outside boot/: {m.name}")
            (new / rel).parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(m) as f, open(new / rel, "wb") as o:   # FAT: no permissions to keep
                shutil.copyfileobj(f, o)
    (new / "cmdline.txt").write_text(set_cmdline(read(new / "cmdline.txt"), disk, SLOTS[tgt]))
    shutil.rmtree(final, ignore_errors=True)
    new.rename(final)
    (fat / "elyir-bench" / f"legacy-{tgt}.txt").unlink(missing_ok=True)
    os.sync()
    return str(manifest["version"]), name


def cmd_stage(args) -> int:
    if getattr(args, "bundle", None):
        return stage_release(args)
    disk, cur = booted()
    fat = bootfs(disk)
    tgt = other(cur)
    st = load_state()
    if not settled(fat, cur, st):
        raise Refused("this boot isn't committed yet; let the trial finish first")
    st["slots"][tgt] = {"status": "staging", "since": now()}
    save_state(st)

    src = RUN / "running"
    src.mkdir(parents=True, exist_ok=True)
    run(["mount", "--bind", "/", str(src)])          # not recursive: just the root filesystem
    try:
        run(["mount", "-o", "remount,bind,ro", str(src)])
        with Mounted(disk, tgt) as dst:
            print(f"copying slot {cur} into slot {tgt} ({part_device(disk, SLOTS[tgt])}) …", flush=True)
            run(["rsync", "-aHAX", "--numeric-ids", "--delete", f"{src}/", f"{dst}/"])
            (dst / "etc/fstab").write_text(render_fstab(read("/etc/fstab"), disk, tgt))
            (dst / "boot/bootfs").mkdir(exist_ok=True)
            (dst / "etc/cloud").mkdir(exist_ok=True)
            (dst / "etc/cloud/cloud-init.disabled").write_text("first boot is long done; a new slot isn't a new machine\n")
            install_kit(dst)
            name = os_name(dst)
    finally:
        run(["umount", str(src)], check=False)

    own = own_boot_dir(fat)
    need = sum(p.stat().st_size for p in own.iterdir() if p.is_file() and BOOT_FILES.match(p.name)) + size_of(own / "overlays")
    final, new = fat / f"slot{tgt}", fat / f".slot{tgt}.new"
    shutil.rmtree(new, ignore_errors=True)
    if shutil.disk_usage(fat).free + (size_of(final) if final.exists() else 0) < need * 1.2:
        raise Refused(f"not enough room on the boot partition for slot {tgt}'s boot files ({need // 2**20} MB)")
    new.mkdir()
    copy_boot_files(own, new)
    (new / "cmdline.txt").write_text(set_cmdline(read(own / "cmdline.txt"), disk, SLOTS[tgt]))
    shutil.rmtree(final, ignore_errors=True)
    new.rename(final)
    (fat / "elyir-bench" / f"legacy-{tgt}.txt").unlink(missing_ok=True)
    os.sync()

    st = load_state()
    st["slots"][tgt] = {"status": "staged", "since": now(), "from": f"copy of slot {cur}", "os": name}
    note(st, "staged", tgt, f"copy of slot {cur}, {name}")
    save_state(st)
    return 0


def stage_release(args) -> int:
    bundle = Path(args.bundle).resolve()
    verify(bundle, Path(args.sig) if args.sig else bundle.with_name(bundle.name + ".sig"),
           Path(args.key) if args.key else RELEASE_KEY)
    disk, cur = booted()
    fat = bootfs(disk)
    tgt = other(cur)
    st = load_state()
    if not settled(fat, cur, st):
        raise Refused("this boot isn't committed yet; let the trial finish first")
    st["slots"][tgt] = {"status": "staging", "since": now()}
    save_state(st)
    version, name = write_release(bundle, disk, tgt, fat)
    st = load_state()
    st["slots"][tgt] = {"status": "staged", "since": now(), "from": f"release {version}", "os": name}
    note(st, "staged", tgt, f"release {version}, {name}")
    save_state(st)
    return 0


def running_release(st: dict, cur: str) -> str | None:
    """The release this slot runs: what it was staged from, or for a slot as flashed, what the card says."""
    m = re.match(r"release (\S+)", st["slots"].get(cur, {}).get("from", ""))
    return m.group(1) if m else (read(OS_VERSION).strip() or None)


def download(url: str, dest: Path, size: int | None = None, sha256: str | None = None) -> None:
    """`url` into `dest` through a .part file, checked against the size and hash the feed gave."""
    import hashlib
    part = dest.with_name(dest.name + ".part")
    h, n = hashlib.sha256(), 0
    with urllib.request.urlopen(url, timeout=60) as r, open(part, "wb") as f:
        for chunk in iter(lambda: r.read(1 << 20), b""):
            f.write(chunk)
            h.update(chunk)
            n += len(chunk)
    if size is not None and n != size:
        part.unlink(missing_ok=True)
        raise Refused(f"{dest.name}: downloaded {n} bytes, the feed says {size}")
    if sha256 and h.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise Refused(f"{dest.name}: its sha256 doesn't match the feed's")
    part.rename(dest)


def box_without_moonraker() -> bool:
    """A Bench Box (role: controller) has Klipper and Moonraker off on purpose: there's no print to wait for."""
    for conf in Path("/home").glob("*/printer_data/config/elyir-bench.conf"):
        if re.search(r"^\s*role\s*[:=]\s*controller\b", read(conf), re.M):
            return not active("moonraker.service")
    return False


def auto_skip(st: dict, cur: str, latest: str) -> str | None:
    """Why an update by itself shouldn't happen now, or None. A person asking (no --auto) isn't held back by these."""
    if not OS_VERSION.exists():
        return "this OS wasn't flashed from an Elyir Bench card; its updates are done by hand"
    if not box_without_moonraker():
        try:
            state = http_json(f"{MOONRAKER}/printer/objects/query?print_stats")["result"]["status"]["print_stats"]["state"]
        except Exception:
            return "can't tell whether the printer is busy (Moonraker isn't answering)"
        if state in ("printing", "paused"):
            return f"the printer is {state}"
    idle = other(cur)
    tried = [h for h in st["history"] if h["slot"] == idle]
    if (st["slots"].get(idle, {}).get("from") == f"release {latest}" and tried
            and tried[-1]["event"] == "rolled-back"):
        return f"release {latest} rolled back here before; waiting for a newer one"
    return None


def cmd_update(args) -> int:
    board = device_class(read("/proc/device-tree/model"))
    url = args.feed or OS_FEED.format(board=board)
    try:
        latest = http_json(url, timeout=15)
    except Exception as e:
        if args.auto:     # offline tonight: try again tomorrow, without a failed unit to explain
            print(f"not now: can't read {url} ({e.__class__.__name__})")
            return 0
        raise Refused(f"can't read {url} ({e.__class__.__name__})")
    disk, cur = booted()
    st = load_state()
    have = running_release(st, cur)
    if latest.get("board", board) != board:
        raise Refused(f"{url} is for {latest.get('board')}, and this is {board}")
    if latest["version"] == have and not args.force:
        print(f"up to date: slot {cur} runs {have}")
        return 0
    print(f"release {latest['version']} is out; slot {cur} runs {have or 'an unknown release'}")
    if args.check:
        return 0
    if args.auto:
        why = auto_skip(st, cur, latest["version"])
        if why:
            print(f"not now: {why}")
            return 0
    if printing() and not args.force:
        raise Refused("printing; try again when it's done (or --force)")
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    base = url.rsplit("/", 1)[0]
    bundle, sig = DOWNLOADS / latest["file"], DOWNLOADS / latest["signature"]
    for old in DOWNLOADS.glob("elyir-bench-os-*"):                 # one release at a time: they're 900 MB
        if old not in (bundle, sig):
            old.unlink(missing_ok=True)
    if not bundle.exists():
        print(f"downloading {latest['file']} ({int(latest['size']) >> 20} MB) …", flush=True)
        download(f"{base}/{latest['file']}", bundle, int(latest["size"]), latest["sha256"])
    download(f"{base}/{latest['signature']}", sig)
    stage_release(argparse.Namespace(bundle=str(bundle), sig=str(sig), key=None))
    if args.no_try:
        return 0
    return cmd_try(argparse.Namespace(deadline=DEADLINE, force=args.force, no_reboot=False))


def preflight(disk: str, fat: Path, slot: str) -> None:
    d = fat / f"slot{slot}" if (fat / f"slot{slot}").exists() else fat
    missing = [f for f in ("cmdline.txt", "config.txt") if not (d / f).exists()]
    if not any(d.glob("kernel*.img")):          # kernel8.img on a Pi 4, kernel_2712.img on a Pi 5
        missing.insert(0, "kernel*.img")
    if missing:
        raise Refused(f"slot {slot}'s boot files are incomplete: no {', '.join(missing)} in {d}")
    r = root_partuuid(read(d / "cmdline.txt"))
    if r != (disk, SLOTS[slot]):
        raise Refused(f"slot {slot}'s cmdline.txt boots {r}, not partition {SLOTS[slot]}")
    with Mounted(disk, slot, ro=True) as root:
        if not (root / "etc/fstab").exists():
            raise Refused(f"slot {slot} has no OS in it")


def cmd_try(args) -> int:
    disk, cur = booted()
    fat = bootfs(disk)
    slot = other(cur)
    st = load_state()
    if not settled(fat, cur, st):
        raise Refused("this boot is itself a trial; let it finish first")
    if st["slots"].get(slot, {}).get("status") == "staging":
        raise Refused(f"slot {slot} was being written and didn't finish; stage it again")
    pointer = pointer_for(fat, slot)
    if not pointer:
        raise Refused(f"slot {slot} has nothing to boot; stage it first")
    if printing() and not args.force:
        raise Refused("the printer is printing; try again when it's idle")
    preflight(disk, fat, slot)
    base = baseline()
    if "network" not in base["required"]:
        raise Refused("no network right now, so a trial couldn't prove anything")
    st["trial"] = {"slot": slot, "from": cur, "started": now(), "deadline": args.deadline, "baseline": base}
    note(st, "trial", slot, f"must match: {', '.join(base['required'])}; screens {','.join(base['displays']) or 'none'}")
    save_state(st)
    write_atomic(fat / "tryboot.txt", trial_pointer(pointer))
    if args.no_reboot:
        print("tryboot.txt written; reboot with: systemctl reboot --reboot-argument='0 tryboot'")
        return 0
    print(f"rebooting into slot {slot} on trial; if it isn't healthy within {args.deadline}s it comes back here", flush=True)
    run(["systemctl", "reboot", "--reboot-argument=0 tryboot"])
    return 0


def commit(disk: str, slot: str) -> None:
    fat = bootfs(disk)
    cur = read(fat / "config.txt")
    if not config_prefix(cur):   # a stock card's config: keep it so that slot can come back
        was = committed(fat)
        if was and was != slot:
            (fat / "elyir-bench").mkdir(exist_ok=True)
            write_atomic(fat / "elyir-bench" / f"legacy-{was}.txt", cur)
    pointer = pointer_for(fat, slot)
    if not pointer:
        raise Refused(f"slot {slot} has no pointer to commit")
    write_atomic(fat / "config.txt", pointer)
    (fat / "tryboot.txt").unlink(missing_ok=True)
    os.sync()


def keep_log(slot: str, outcome: str) -> None:
    """The journal lives in RAM on Pi OS: keep this trial boot's on /data before it's gone."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        journal = run(["journalctl", "-b", "--no-pager", "-o", "short-monotonic"], check=False).stdout
        write_atomic(STATE_DIR / f"trial-{slot}.log",
                     f"{outcome} at {now()}\ncmdline: {read('/proc/cmdline').strip()}\n\n" + journal[-400_000:])
    except Exception as e:
        print(f"couldn't keep the trial log: {e}", flush=True)


def reboot() -> None:
    os.sync()
    if run(["systemctl", "reboot"], check=False).returncode != 0:
        run(["reboot", "-f"], check=False)


def cmd_confirm(args) -> int:
    disk, cur = booted()
    if tryboot_flag():
        try:
            return trial(disk, cur)
        except Exception as e:  # a trial that can't check itself doesn't get to stay
            print(f"trial check failed: {e}", flush=True)
            try:
                st = load_state()
                if st["trial"]:
                    st["trial"]["failed"] = f"the check itself failed: {e}"
                    save_state(st)
            finally:
                keep_log(cur, f"the check itself failed: {e}")
                reboot()
            return 1
    st = load_state()
    t = st["trial"]
    if t and t["slot"] != cur:
        note(st, "rolled-back", t["slot"], t.get("failed") or
             "it didn't get far enough to report: crashed, hung, or couldn't start")
        st["trial"] = None
        save_state(st)
    elif t:   # running the trial slot outside a trial: it was committed and the record lingered
        st["trial"] = None
        save_state(st)
    return 0


def trial(disk: str, cur: str) -> int:
    st = load_state()
    t = st["trial"] if st["trial"] and st["trial"]["slot"] == cur else None
    if not t:   # a tryboot nobody asked elyir-bench-os for: hold it to the basics
        t = st["trial"] = {"slot": cur, "started": now(), "deadline": DEADLINE,
                           "baseline": {"required": ["network", "moonraker"], "displays": []}}
    end = time.monotonic() + t["deadline"]
    why = ""
    while time.monotonic() < end:
        ok, why = healthy(t["baseline"])
        if ok and st["slots"].get(cur, {}).get("broken"):
            # a test break that didn't take: never make a deliberately damaged slot the default
            why = f"healthy, but marked broken ({st['slots'][cur]['broken']}); not committing a test slot"
            break
        if ok:
            commit(disk, cur)
            note(st, "committed", cur, why)
            keep_log(cur, "committed")
            st["trial"] = None
            st["slots"].setdefault(cur, {})["status"] = "good"
            st["slots"][cur].pop("broken", None)
            save_state(st)
            return 0
        time.sleep(5)
    t["failed"] = why if "marked broken" in why else f"not healthy after {t['deadline']}s: {why}"
    save_state(st)
    print(t["failed"], flush=True)
    keep_log(cur, t["failed"])
    reboot()
    return 1


def cmd_guard(args) -> int:
    if not tryboot_flag():
        return 0
    try:
        deadline = load_state()["trial"]["deadline"]
    except Exception:
        deadline = DEADLINE
    time.sleep(deadline + GUARD_GRACE)
    try:
        disk, cur = booted()
        if committed(bootfs(disk)) == cur:
            return 0
    except Exception as e:
        print(f"guard: can't tell whether the trial was committed ({e})", flush=True)
    print("guard: the trial never finished; going back", flush=True)
    try:
        st = load_state()
        if st["trial"] and not st["trial"].get("failed"):
            st["trial"]["failed"] = "never finished starting (the guard rebooted it)"
            save_state(st)
    except Exception:
        pass
    keep_log(cur if "cur" in locals() else "unknown", "the guard rebooted it")
    reboot()
    return 1


BREAKS = {
    "unhealthy": "Moonraker fails to start",
    "emergency": "fstab needs a disk that isn't there, so boot stops in emergency mode",
    "no-systemd": "systemd is missing, so the kernel falls back to a shell and nothing takes the watchdog",
    "hang": "the kernel freezes after boot and never reboots by itself",
}


def cmd_break(args) -> int:
    disk, cur = booted()
    slot = other(cur)
    if committed(bootfs(disk)) == slot:
        raise Refused(f"slot {slot} is the default; refusing to break it")
    with Mounted(disk, slot) as root:
        if args.how == "unhealthy":
            d = root / "etc/systemd/system/moonraker.service.d"
            d.mkdir(exist_ok=True)
            (d / "elyir-bench-break.conf").write_text("[Service]\nExecStart=\nExecStart=/bin/false\n")
        elif args.how == "emergency":
            with open(root / "etc/fstab", "a") as f:
                f.write("LABEL=astro-missing  /mnt/astro-missing  ext4  defaults,x-systemd.device-timeout=20s  0  2\n")
        elif args.how == "no-systemd":
            bin_ = root / "usr/lib/systemd/systemd"
            bin_.rename(bin_.with_name("systemd.elyir-bench-broken"))
        elif args.how == "hang":
            (root / "etc/systemd/system/elyir-bench-break-hang.service").write_text(
                # Before= the confirm unit, so the trial can't pass before the freeze
                f"[Unit]\nDescription=Elyir Bench OS test: freeze the kernel\nBefore={CONFIRM_UNIT}\n\n"
                "[Service]\nType=oneshot\n"
                "ExecStart=/bin/sh -c 'echo 0 > /proc/sys/kernel/panic; echo c > /proc/sysrq-trigger'\n")
            (root / "etc/systemd/system/multi-user.target.wants/elyir-bench-break-hang.service").symlink_to(
                "/etc/systemd/system/elyir-bench-break-hang.service")
    st = load_state()
    st["slots"].setdefault(slot, {})["broken"] = args.how
    note(st, "broken", slot, BREAKS[args.how])
    save_state(st)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="elyir-bench-os", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status")
    s.add_argument("--json", action="store_true")
    sub.add_parser("install")
    g = sub.add_parser("stage", help="the idle slot: a copy of the running OS, or a signed release")
    g.add_argument("bundle", nargs="?", help="a release's OS (elyir-bench-os-<version>-<board>.tar), signed (.sig beside it)")
    g.add_argument("--sig", help="its signature, if not <bundle>.sig")
    g.add_argument("--key", help=f"the release key to check it with (default {RELEASE_KEY})")
    u = sub.add_parser("update", help="the newest release for this board: download, check, stage, then try it")
    u.add_argument("--check", action="store_true", help="only say whether there's a newer one")
    u.add_argument("--no-try", action="store_true", help="stage it, but don't reboot into it")
    u.add_argument("--force", action="store_true", help="even when it's the same release, or while printing")
    u.add_argument("--feed", help=f"another feed than {OS_FEED}")
    u.add_argument("--auto", action="store_true", help="by itself (the nightly timer): only on an Elyir Bench card, "
                   "idle, and never a release that already rolled back here")
    t = sub.add_parser("try")
    t.add_argument("--deadline", type=int, default=DEADLINE, help="seconds the trial gets to become healthy")
    t.add_argument("--force", action="store_true", help="even while printing")
    t.add_argument("--no-reboot", action="store_true", help="write tryboot.txt but don't reboot")
    sub.add_parser("confirm")
    sub.add_parser("guard")
    b = sub.add_parser("break")
    b.add_argument("how", choices=sorted(BREAKS))
    args = ap.parse_args(argv)
    if os.geteuid() != 0:
        print("elyir-bench-os changes how the Pi boots; run it as root.")
        return 2
    try:
        return globals()[f"cmd_{args.cmd.replace('-', '_')}"](args)
    except Refused as e:
        print(f"elyir-bench-os: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
