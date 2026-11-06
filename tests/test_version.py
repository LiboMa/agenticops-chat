"""MVP-2.7.0 S7: one version string, read by every surface."""
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_release_is_2_7_0():
    from agenticops import __version__
    assert __version__ == "2.7.0"


def test_pyproject_and_the_lock_agree_with_the_package():
    from agenticops import __version__
    assert tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"] == __version__
    lock = (ROOT / "uv.lock").read_text()
    m = re.search(r'\[\[package\]\]\nname = "agenticops"\nversion = "([^"]+)"', lock)
    assert m and m.group(1) == __version__


def test_the_api_reports_the_package_version():
    from agenticops import __version__
    from agenticops.web.app import app
    assert app.version == __version__
