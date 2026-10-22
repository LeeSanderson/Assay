import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_lock_file_pins_harbor_0_24_0():
    lock = tomllib.loads((REPO_ROOT / "uv.lock").read_text(encoding="utf-8"))
    versions = {p["name"]: p["version"] for p in lock["package"]}
    assert versions["harbor"] == "0.24.0"


@pytest.mark.slow
def test_harbor_runs_the_pinned_version():
    result = subprocess.run(
        ["uv", "run", "harbor", "--version"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "0.24.0" in result.stdout
