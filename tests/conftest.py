from pathlib import Path

import pytest

from tests.trial_builder import TrialBuilder


@pytest.fixture
def make_trial(tmp_path: Path):
    """A factory for fake trial folders: make_trial(language="go") -> TrialBuilder."""
    count = 0

    def make(language: str = "go", **kwargs) -> TrialBuilder:
        nonlocal count
        count += 1
        return TrialBuilder(tmp_path / f"t{count}", language=language, **kwargs)

    return make
