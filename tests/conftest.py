from pathlib import Path

import pytest

from tests.trial_builder import TrialBuilder

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def local_server_answers(request, monkeypatch):
    """No test reaches a real local model server: the health check of a
    local job answers, except in tests/test_local_server.py, which tests it."""
    if request.node.path.name != "test_local_server.py":
        monkeypatch.setattr("assay.experiment.check_server", lambda url: None)


@pytest.fixture
def make_trial(tmp_path: Path):
    """A factory for fake trial folders: make_trial(language="go") -> TrialBuilder."""
    count = 0

    def make(language: str = "go", **kwargs) -> TrialBuilder:
        nonlocal count
        count += 1
        return TrialBuilder(tmp_path / f"t{count}", language=language, **kwargs)

    return make


@pytest.fixture(scope="session")
def pack_images():
    """pack_images(pack) -> the tag of the pack's image (a tests.task_packs.Pack),
    built once for the session and removed at its end."""
    from tests.task_packs import build_image, docker

    tags = {}

    def image(pack) -> str:
        if pack not in tags:
            tags[pack] = build_image(pack)
        return tags[pack]

    yield image
    for tag in tags.values():
        docker("image", "rm", "-f", tag)


@pytest.fixture
def run_from_repo_root(monkeypatch):
    """Runs the test from the repository root: Harbor resolves task and skill
    paths against the current directory."""
    monkeypatch.chdir(REPO_ROOT)
