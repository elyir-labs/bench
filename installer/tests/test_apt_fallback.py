"""A package whose security update left the mirror (Debian 11 after its support ended; found on Desk, 7 October 2026):
the next version that's still there is installed instead, and the first Wi-Fi never stops an update."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import elyir_bench as a  # noqa: E402

Desk = """dnsmasq-base:
  Installed: (none)
  Candidate: 2.85-1+deb11u2
  Version table:
     2.85-1+deb11u2 500
        500 http://deb.debian.org/debian-security bullseye-security/main arm64 Packages
     2.85-1 500
        500 http://deb.debian.org/debian bullseye/main arm64 Packages
"""
INSTALLED = """curl:
  Installed: 7.74.0-1.3
  Candidate: 7.74.0-1.3+deb11u14
  Version table:
     7.74.0-1.3+deb11u14 500
        500 http://deb.debian.org/debian-security bullseye-security/main arm64 Packages
 *** 7.74.0-1.3 500
        500 http://deb.debian.org/debian bullseye/main arm64 Packages
        100 /var/lib/dpkg/status
"""


def test_versions_newest_first_with_the_candidate():
    assert a.apt_versions(Desk) == ("2.85-1+deb11u2", ["2.85-1+deb11u2", "2.85-1"])
    assert a.apt_versions(INSTALLED) == ("7.74.0-1.3+deb11u14", ["7.74.0-1.3+deb11u14", "7.74.0-1.3"])


def test_a_404_installs_the_version_still_there(monkeypatch):
    ran = []

    def sudo(*cmd, **kw):
        ran.append(cmd)
        if cmd[:2] == ("apt-get", "install") and "dnsmasq-base" in cmd:
            raise a.StepFailed("sudo -n apt-get install … failed: E: Failed to fetch …deb11u2_arm64.deb  404  Not Found")
    monkeypatch.setattr(a, "sudo", sudo)
    monkeypatch.setattr(a, "run", lambda cmd, check=False, **kw: type("P", (), {"stdout": Desk})())
    a.apt_install("dnsmasq-base")
    assert ran[-1][-1] == "dnsmasq-base=2.85-1"


def test_other_failures_still_fail(monkeypatch):
    def sudo(*cmd, **kw):
        if cmd[:2] == ("apt-get", "install"):
            raise a.StepFailed("E: Unable to locate package nothing-like-it")
    monkeypatch.setattr(a, "sudo", sudo)
    try:
        a.apt_install("nothing-like-it")
    except a.StepFailed:
        pass
    else:
        raise AssertionError("it should still fail")


def test_the_first_wifi_never_stops_an_update(monkeypatch, tmp_path):
    state = {}
    monkeypatch.setattr(a, "load_state", lambda: dict(state))
    monkeypatch.setattr(a, "save_state", lambda st: state.update(st))
    monkeypatch.setattr(a, "missing_packages", lambda pkgs: list(pkgs))

    def broken(*p):
        raise a.StepFailed("E: Failed to fetch …  404  Not Found")
    monkeypatch.setattr(a, "apt_install", broken)
    step = next(s for s in a.STEPS if s.name == "first wi-fi")
    c = type("C", (), {"facts": {"network_manager": True}, "notes": []})()
    step.apply(c)
    assert "dnsmasq-base can't be installed" in state["wifi_setup_unavailable"]
    assert c.notes and "first Wi-Fi isn't available" in c.notes[0]
    ok, words = step.check(c)
    assert ok and words.startswith("not available here")
