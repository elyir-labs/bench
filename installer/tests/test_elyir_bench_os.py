import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench_os as o  # noqa: E402

DISK = "4d8fd085"
STOCK_FSTAB = """proc            /proc           proc    defaults          0       0
PARTUUID=4d8fd085-01  /boot/firmware  vfat    defaults          0       2
PARTUUID=4d8fd085-02  /               ext4    defaults,noatime  0       1

# Elyir Bench: data partition, shared by both OS slots
LABEL=astro-data  /data  ext4  defaults,noatime,nofail  0  2
"""
CMDLINE = "console=serial0,115200 console=tty1 root=PARTUUID=4d8fd085-02 rootfstype=ext4 fsck.repair=yes rootwait\n"


def test_fstab_for_slot_b_binds_its_own_boot_dir():
    out = o.render_fstab(STOCK_FSTAB, DISK, "b")
    assert "PARTUUID=4d8fd085-03  /               ext4" in out
    assert "PARTUUID=4d8fd085-01  /boot/bootfs  vfat" in out
    assert "/boot/bootfs/slotb  /boot/firmware  none  bind" in out
    assert "/boot/firmware  vfat" not in out and "LABEL=astro-data" in out


def test_fstab_rerender_for_the_other_slot_is_clean():
    out = o.render_fstab(o.render_fstab(STOCK_FSTAB, DISK, "b"), DISK, "a")
    assert out.count(o.FSTAB_NOTE) == 1 and out.count("/boot/bootfs  vfat") == 1
    assert "/boot/bootfs/slota  /boot/firmware" in out and "slotb" not in out
    assert "PARTUUID=4d8fd085-02  /" in out


def test_cmdline_boots_the_slot_and_reboots_on_panic():
    out = o.set_cmdline(CMDLINE + " panic=0", DISK, 3)
    assert o.root_partuuid(out) == (DISK, 3)
    assert out.count("root=") == 1 and "panic=10" in out and "panic=0" not in out
    assert out.startswith("console=serial0") and out.endswith("\n") and "\n" not in out[:-1]


def fat(tmp_path, config="dtparam=audio=on\n"):
    (tmp_path / "config.txt").write_text(config)
    (tmp_path / "cmdline.txt").write_text(CMDLINE)
    return tmp_path


def stage(fat_dir, slot):
    d = fat_dir / f"slot{slot}"
    d.mkdir()
    (d / "cmdline.txt").write_text(o.set_cmdline(CMDLINE, DISK, o.SLOTS[slot]))


def test_stock_card_boots_slot_a(tmp_path):
    f = fat(tmp_path)
    assert o.committed(f) == "a"
    assert o.pointer_for(f, "a") == "dtparam=audio=on\n"
    assert o.pointer_for(f, "b") is None


def test_commit_b_keeps_the_stock_config_for_going_back(tmp_path, monkeypatch):
    f = fat(tmp_path)
    stage(f, "b")
    monkeypatch.setattr(o, "bootfs", lambda disk: f)
    o.commit(DISK, "b")
    assert o.committed(f) == "b" and o.config_prefix((f / "config.txt").read_text()) == "slotb/"
    assert (f / "elyir-bench" / "legacy-a.txt").read_text() == "dtparam=audio=on\n"
    o.commit(DISK, "a")
    assert o.committed(f) == "a" and (f / "config.txt").read_text() == "dtparam=audio=on\n"


def test_trial_pointer_arms_the_firmware_watchdog():
    text = o.trial_pointer(o.render_pointer("b"))
    assert "os_prefix=slotb/" in text and "include slotb/config.txt" in text
    assert text.rstrip().endswith(f"kernel_watchdog_timeout={o.FIRMWARE_WATCHDOG}")


def test_healthy_needs_what_worked_before(monkeypatch):
    seen = {"network": [True, "wlan0"], "moonraker": [True, "answers"], "klipper": [False, "klippy None"],
            "displays": [True, "DSI-1"]}
    monkeypatch.setattr(o, "look", lambda: seen)
    monkeypatch.setattr(o, "displays", lambda: ["DSI-1"])
    assert o.healthy({"required": ["network", "moonraker"], "displays": ["DSI-1"]})[0]
    ok, why = o.healthy({"required": ["network", "klipper"], "displays": ["DSI-1"]})
    assert not ok and "klipper" in why
    monkeypatch.setattr(o, "displays", lambda: [])
    ok, why = o.healthy({"required": ["network"], "displays": ["DSI-1"]})
    assert not ok and "display gone: DSI-1" in why


# ── a release's OS into the idle slot (stage <bundle>) ─────────────────────

import shutil as _shutil
import subprocess as _sp

import pytest


def test_the_board_is_read_from_the_device_tree_model():
    assert o.device_class("Raspberry Pi 4 Model B Rev 1.5\x00") == "pi4"
    assert o.device_class("Raspberry Pi 5 Model B Rev 1.0") == "pi5"
    assert o.device_class("Generic x86") is None


def test_a_release_for_another_board_or_not_an_os_release_is_refused():
    o.check_manifest({"kind": "elyir-bench-os", "device": "pi4"}, "Raspberry Pi 4 Model B Rev 1.5")
    o.check_manifest({"kind": "elyir-bench-os", "devices": ["pi4", "pi5"]}, "Raspberry Pi 5 Model B")
    with pytest.raises(o.Refused, match="for pi5"):
        o.check_manifest({"kind": "elyir-bench-os", "device": "pi5"}, "Raspberry Pi 4 Model B")
    with pytest.raises(o.Refused, match="isn't an Elyir Bench OS"):
        o.check_manifest({"kind": "elyir-bench", "device": "pi4"}, "Raspberry Pi 4 Model B")


@pytest.mark.skipif(not _shutil.which("openssl"), reason="needs openssl")
def test_only_a_release_signed_with_our_key_is_written(tmp_path):
    key, pub, other = tmp_path / "k.pem", tmp_path / "pub.pem", tmp_path / "other.pem"
    _sp.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", key], check=True)
    _sp.run(["openssl", "ec", "-in", key, "-pubout", "-out", pub], check=True, capture_output=True)
    _sp.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", other], check=True)
    bundle = tmp_path / "elyir-bench-os-1-pi4.tar"
    bundle.write_bytes(b"pretend release")
    sig = tmp_path / "elyir-bench-os-1-pi4.tar.sig"
    _sp.run(["openssl", "dgst", "-sha256", "-sign", key, "-out", sig, bundle], check=True)
    o.verify(bundle, sig, pub)                                   # ours: fine
    bundle.write_bytes(b"pretend release, changed")
    with pytest.raises(o.Refused, match="doesn't verify"):
        o.verify(bundle, sig, pub)                               # changed after signing
    _sp.run(["openssl", "dgst", "-sha256", "-sign", other, "-out", sig, bundle], check=True)
    with pytest.raises(o.Refused, match="doesn't verify"):
        o.verify(bundle, sig, pub)                               # someone else's key
    with pytest.raises(o.Refused, match="no signature"):
        o.verify(bundle, tmp_path / "missing.sig", pub)


def test_the_printer_itself_is_carried_and_nothing_else(tmp_path, monkeypatch):
    src = tmp_path / "running"
    for f in ("etc/hostname", "etc/NetworkManager/system-connections/elyir-bench-wifi-hartley-home.nmconnection",
              "etc/ssh/ssh_host_ed25519_key", "home/pi/.ssh/authorized_keys", "home/pi/elyir-bench/state/relay.json",
              "home/pi/elyir-bench/releases/2026.10.05-x/app/index.html", "home/pi/klipper/klippy/klippy.py",
              "var/lib/elyir-bench/laid-out", "var/lib/elyir-bench/firstboot-done"):
        (src / f).parent.mkdir(parents=True, exist_ok=True)
        (src / f).write_text("x")
    calls = []
    monkeypatch.setattr(o, "run", lambda cmd, **kw: calls.append(cmd))
    done = o.carry(tmp_path / "new", src)
    assert "etc/hostname" in done and "etc/NetworkManager/system-connections" in done
    assert "etc/ssh/ssh_host_ed25519_key" in done and "home/pi/.ssh/authorized_keys" in done
    assert "home/pi/elyir-bench/state" in done and "var/lib/elyir-bench/laid-out" in done
    # the release brings its own Klipper and app; first boot runs the installer again on the new slot
    assert not any("releases" in d or "klipper" in d or "firstboot-done" in d for d in done)
    assert all(c[:2] == ["rsync", "-aHAX"] and "/./" in c[-2] for c in calls)


def test_the_running_release_is_what_its_slot_was_staged_from_or_what_the_card_says(tmp_path, monkeypatch):
    st = {"slots": {"a": {"from": "release 2026.10.05-e66751e"}, "b": {"from": "copy of slot a"}}}
    assert o.running_release(st, "a") == "2026.10.05-e66751e"
    monkeypatch.setattr(o, "OS_VERSION", tmp_path / "os-version")
    assert o.running_release(st, "b") is None
    (tmp_path / "os-version").write_text("2026.10.05-24b57cf\n")
    assert o.running_release(st, "b") == "2026.10.05-24b57cf"


def test_a_download_that_isnt_what_the_feed_says_is_thrown_away(tmp_path):
    src = tmp_path / "bundle.tar"
    src.write_bytes(b"x" * 1000)
    import hashlib
    good = hashlib.sha256(b"x" * 1000).hexdigest()
    o.download(src.as_uri(), tmp_path / "a.tar", 1000, good)
    assert (tmp_path / "a.tar").read_bytes() == b"x" * 1000
    with pytest.raises(o.Refused, match="sha256"):
        o.download(src.as_uri(), tmp_path / "b.tar", 1000, "0" * 64)
    with pytest.raises(o.Refused, match="1000 bytes"):
        o.download(src.as_uri(), tmp_path / "c.tar", 999, good)
    assert not (tmp_path / "b.tar").exists() and not list(tmp_path.glob("*.part"))


def test_an_update_may_follow_a_committed_trial_without_a_reboot(monkeypatch):
    monkeypatch.setattr(o, "committed", lambda fat: "a")
    assert o.settled(Path("/"), "a", {"trial": None})                          # committed, nothing pending
    assert not o.settled(Path("/"), "a", {"trial": {"slot": "a"}})             # its trial isn't decided yet
    assert not o.settled(Path("/"), "b", {"trial": None})                      # running the slot that isn't the default


def _idle(monkeypatch, state="standby"):
    monkeypatch.setattr(o, "http_json", lambda url, timeout=3.0: {"result": {"status": {"print_stats": {"state": state}}}})


def test_updates_by_themselves_only_on_an_elyir_bench_card(tmp_path, monkeypatch):
    _idle(monkeypatch)
    monkeypatch.setattr(o, "OS_VERSION", tmp_path / "os-version")
    st = {"slots": {}, "history": []}
    assert "by hand" in o.auto_skip(st, "a", "2")                  # Studio: slots, but its own OS
    (tmp_path / "os-version").write_text("1\n")
    assert o.auto_skip(st, "a", "2") is None


def test_updates_by_themselves_wait_for_an_idle_printer(tmp_path, monkeypatch):
    monkeypatch.setattr(o, "OS_VERSION", tmp_path / "os-version")
    (tmp_path / "os-version").write_text("1\n")
    st = {"slots": {}, "history": []}
    for busy in ("printing", "paused"):
        _idle(monkeypatch, busy)
        assert busy in o.auto_skip(st, "a", "2")
    monkeypatch.setattr(o, "http_json", lambda url, timeout=3.0: (_ for _ in ()).throw(OSError("down")))
    assert "can't tell" in o.auto_skip(st, "a", "2")


def test_a_release_that_rolled_back_isnt_tried_again_by_itself(tmp_path, monkeypatch):
    _idle(monkeypatch)
    monkeypatch.setattr(o, "OS_VERSION", tmp_path / "os-version")
    (tmp_path / "os-version").write_text("1\n")
    st = {"slots": {"b": {"from": "release 2"}},
          "history": [{"slot": "b", "event": "trial"}, {"slot": "b", "event": "rolled-back"}]}
    assert "rolled back" in o.auto_skip(st, "a", "2")
    assert o.auto_skip(st, "a", "3") is None                       # a newer one is fine


def test_a_bench_box_with_moonraker_off_on_purpose_counts_as_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(o, "OS_VERSION", tmp_path / "os-version")
    (tmp_path / "os-version").write_text("1\n")
    monkeypatch.setattr(o, "http_json", lambda url, timeout=3.0: (_ for _ in ()).throw(OSError("off")))
    monkeypatch.setattr(o, "box_without_moonraker", lambda: True)
    assert o.auto_skip({"slots": {}, "history": []}, "a", "2") is None
    monkeypatch.setattr(o, "box_without_moonraker", lambda: False)        # a printer with Moonraker down: not now
    assert "can't tell" in o.auto_skip({"slots": {}, "history": []}, "a", "2")
