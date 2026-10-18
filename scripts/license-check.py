#!/usr/bin/env python3
"""Fail when a library Elyir Bench ships has a license that would tie Elyir LLC's hands (scripts/licenses.json).

    scripts/license-check.py                     # npm from the lockfile; Python in a fresh venv
    scripts/license-check.py --python ~/.venvs/elyir-bench-door/bin/python   # an env that already has them

npm licenses come from package-lock.json (production packages only). Python licenses come from the installed
packages' metadata, so the requirements are installed into a throwaway venv unless --python names one.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "scripts" / "licenses.json"

ALIASES = {
    "apache 2.0": "Apache-2.0",
    "apache license 2.0": "Apache-2.0",
    "apache license, version 2.0": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "mit license": "MIT",
    "mozilla public license 2.0 (mpl 2.0)": "MPL-2.0",
    "python software foundation license": "PSF-2.0",
    "isc license (iscl)": "ISC",
}

INSPECT = r"""
import importlib.metadata as m, json
out = []
for d in m.distributions():
    md = d.metadata
    if md['Name'] in ('pip', 'setuptools', 'wheel'):
        continue
    out.append({'name': md['Name'], 'expression': md.get('License-Expression'), 'license': md.get('License'),
                'classifiers': [c for c in (md.get_all('Classifier') or []) if c.startswith('License ::')]})
print(json.dumps(out))
"""


def allowed_by(expression: str, allowed: set[str]) -> bool:
    tokens = re.findall(r"\(|\)|[^\s()]+", expression)
    pos = 0

    def peek():
        return tokens[pos] if pos < len(tokens) else None

    def take():
        nonlocal pos
        pos += 1
        return tokens[pos - 1]

    def factor() -> bool:
        if peek() == "(":
            take()
            ok = either()
            if peek() == ")":
                take()
            return ok
        ident = take()
        if peek() == "WITH":
            take()
            ident = f"{ident} WITH {take()}"
        return ident in allowed

    def both() -> bool:
        ok = factor()
        while peek() == "AND":
            take()
            ok = factor() and ok
        return ok

    def either() -> bool:
        ok = both()
        while peek() == "OR":
            take()
            ok = both() or ok
        return ok

    return bool(tokens) and either()


def python_license(pkg: dict) -> str | None:
    if pkg.get("expression"):
        return pkg["expression"]
    text = (pkg.get("license") or "").strip()
    if text and "\n" not in text and len(text) < 100 and text.upper() != "UNKNOWN":
        return ALIASES.get(text.lower(), text)
    for c in pkg.get("classifiers", []):
        name = c.split("::")[-1].strip()
        if name.lower() in ALIASES:
            return ALIASES[name.lower()]
    return None


def npm_packages(lockfile: Path) -> list[tuple[str, str | None]]:
    lock = json.loads(lockfile.read_text())
    found = {}
    for path, meta in lock.get("packages", {}).items():
        if not path or meta.get("dev") or meta.get("link"):
            continue
        name = meta.get("name") or path.split("node_modules/")[-1]
        lic = meta.get("license")
        found[name] = lic if isinstance(lic, str) else None
    return sorted(found.items())


def python_packages(requirements: list[Path], python: str | None) -> list[tuple[str, str | None]]:
    if python is None:
        env = Path(tempfile.mkdtemp(prefix="license-check-"))
        venv.create(env, with_pip=True)
        python = str(env / "bin" / "python")
        args = [python, "-m", "pip", "install", "-q", "--disable-pip-version-check"]
        for r in requirements:
            args += ["-r", str(r)]
        subprocess.run(args, check=True)
    out = subprocess.run([python, "-c", INSPECT], check=True, capture_output=True, text=True).stdout
    return sorted((p["name"], python_license(p)) for p in json.loads(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--python", help="an interpreter that already has the Python requirements installed")
    args = ap.parse_args()

    policy = json.loads(POLICY.read_text())
    allowed = set(policy["allowed"])
    exceptions = policy.get("exceptions", {})

    checked = []
    for lockfile in policy.get("npm", []):
        checked += [("npm", n, lic) for n, lic in npm_packages(ROOT / lockfile)]
    if policy.get("python"):
        reqs = [ROOT / r for r in policy["python"]]
        checked += [("python", n, lic) for n, lic in python_packages(reqs, args.python)]

    problems = []
    for kind, name, lic in checked:
        if name in exceptions:
            if lic != exceptions[name]["license"]:
                problems.append(f"{kind} {name}: now {lic or 'no license'}, the exception was granted for "
                                f"{exceptions[name]['license']}; check it again")
            continue
        if lic is None:
            problems.append(f"{kind} {name}: no license found")
        elif not allowed_by(lic, allowed):
            problems.append(f"{kind} {name}: {lic}")

    print(f"{len(checked)} libraries checked against {POLICY.relative_to(ROOT)}")
    if problems:
        print("\nNot allowed (see docs/licensing.md before adding an exception):")
        for p in problems:
            print(f"  {p}")
        return 1
    print("All allowed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
