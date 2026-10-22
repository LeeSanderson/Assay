# Assay
Assay measures the value of a context artifact for a coding agent: a skill, a rules file, an instruction file, or a hook.

## Setup

Install [uv](https://docs.astral.sh/uv/), then run `uv sync` at the repository root. `pyproject.toml` pins `harbor==0.24.0` and the repository commits `uv.lock`, so every host gets the same Harbor version.

## Run Harbor

Always run Harbor through uv, so that it uses the locked version:

```sh
uv run harbor --version   # reports 0.24.0
uv run harbor <command>
```

To change the Harbor version, edit the pin in `pyproject.toml`, run `uv lock`, and commit `uv.lock`.

## Run the tests

```sh
uv run pytest             # fast tests; skips tests marked `slow`
uv run pytest -m slow     # only the slow tests
uv run pytest -m ""       # all tests, slow included
```

A test that needs Docker or Harbor gets the `@pytest.mark.slow` marker. The default run skips it.
