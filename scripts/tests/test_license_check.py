import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("license_check", Path(__file__).parent.parent / "license-check.py")
lc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lc)

ALLOWED = {"MIT", "Apache-2.0", "BSD-3-Clause"}


def test_expressions():
    assert lc.allowed_by("MIT", ALLOWED)
    assert not lc.allowed_by("GPL-3.0-only", ALLOWED)
    assert lc.allowed_by("EPL-2.0 OR BSD-3-Clause", ALLOWED)
    assert not lc.allowed_by("Apache-2.0 AND GPL-2.0-or-later", ALLOWED)
    assert lc.allowed_by("(MIT OR GPL-3.0) AND Apache-2.0", ALLOWED)
    assert not lc.allowed_by("GPL-2.0 WITH Classpath-exception-2.0", ALLOWED)
    assert not lc.allowed_by("", ALLOWED)


def test_python_metadata_fallbacks():
    assert lc.python_license({"expression": "MIT"}) == "MIT"
    assert lc.python_license({"license": "Apache 2.0"}) == "Apache-2.0"
    assert lc.python_license({"license": "long text\nof a license", "classifiers":
                              ["License :: OSI Approved :: MIT License"]}) == "MIT"
    assert lc.python_license({"license": "UNKNOWN", "classifiers": ["License :: OSI Approved"]}) is None


def test_npm_skips_dev_packages(tmp_path):
    lock = {"packages": {"": {"name": "app"},
                         "node_modules/vue": {"license": "MIT"},
                         "node_modules/vitest": {"license": "MIT", "dev": True},
                         "node_modules/odd": {"license": {"type": "GPL"}}}}
    path = tmp_path / "package-lock.json"
    path.write_text(json.dumps(lock))
    assert lc.npm_packages(path) == [("odd", None), ("vue", "MIT")]
