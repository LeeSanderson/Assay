"""The medium codebase of the codebase ladder, in TypeScript (issue #85; PRD
section 20, "The domain"): the small codebase of rung D grown into the order
and inventory service in layers (domain, services, adapters), with the
promotions engine (M), the customers and accounts, the shipping, the invoices,
an event log and the reports. It is the seed of rung E (issue #87), built
ahead of that pack, so only its seed and Dockerfile exist yet:
tasks/typescript/shop-returns-medium/environment/.

The feature tests of X (rung D's) must later run unchanged on it, so the root
modules keep the entry points of the small codebase. The design note for the
Go port is docs/codebase-ladder/medium-codebase.md.

The fast tests read the seed. The slow tests build its image and run its seed
suite, the feature tests of M (rung C's) and the feature tests of X (rung D's)
in it, with no network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.task_packs import (MEDIUM_CODEBASES, REPO_ROOT, SEED_SIZE_RANGES, TS_TOOLCHAIN,
                              docker, packs, seed_suite_case_names)

(TS,) = MEDIUM_CODEBASES
RUNG_C = packs("shop-promotions-small")["typescript"]
RUNG_D = packs("shop-returns-small")["typescript"]
DESIGN_NOTE = REPO_ROOT / "docs" / "codebase-ladder" / "medium-codebase.md"
LAYERS = ("domain", "services", "adapters")
# What each layer may import: the domain nothing but itself, the services the
# domain, the adapters the domain (they implement its ports). The root modules
# are the entry points and import any layer.
MAY_IMPORT = {"domain": {"domain"}, "services": {"domain", "services"},
              "adapters": {"domain", "adapters"}}
_IMPORT = re.compile(r"^(?:import|export)\b[^;]*?from '([^']+)'", re.MULTILINE | re.DOTALL)


def _imports(name: str) -> list[str]:
    """The seed files that a seed file imports, as seed paths."""
    text = (TS.seed / name).read_text(encoding="utf-8")
    folder = Path(name).parent
    return [_normalise((folder / source).as_posix())
            for source in _IMPORT.findall(text) if source.startswith(".")]


def _normalise(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if part == "..":
            parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    return "/".join(parts)


def _layer(name: str) -> str:
    return name.split("/")[0] if "/" in name else "root"


def _exports(name: str) -> set[str]:
    """The names that a root module exports, by declaration or re-export."""
    text = (TS.seed / name).read_text(encoding="utf-8")
    names = set(re.findall(r"^export (?:class|interface|type|function|const) (\w+)", text,
                           re.MULTILINE))
    for block in re.findall(r"^export (?:type )?\{([^}]*)\}", text, re.MULTILINE):
        names |= {n.strip().split(" as ")[-1] for n in block.split(",") if n.strip()}
    return names


def _feature_test_imports(pack) -> dict[str, set[str]]:
    """The names that a pack's feature tests import, by module."""
    (text,) = pack.reference_test_texts()
    wanted: dict[str, set[str]] = {}
    for names, source in re.findall(r"^import (?:type )?\{([^}]*)\} from '\./([^']+)'", text,
                                    re.MULTILINE):
        for n in names.split(","):
            if n.strip():
                wanted.setdefault(source, set()).add(n.strip().removeprefix("type ").strip())
    return wanted


# --- The seed's files -----------------------------------------------------------


def test_medium_codebase_is_inside_the_size_ranges_of_a_medium_seed():
    # PRD section 20, "The domain": 4,000 to 6,000 lines of production code
    # (non-blank) in 30 to 50 files, and a seed suite of 200 to 400 tests.
    ranges = SEED_SIZE_RANGES["medium"]
    sizes = {"lines": TS.production_lines(), "files": len(TS.production_files()),
             "tests": len(seed_suite_case_names(TS))}
    for key, (least, most) in ranges.items():
        assert least <= sizes[key] <= most, (key, sizes[key])


def test_toolchain_and_dockerfile_are_rung_ds_but_for_the_package_name():
    for name in TS_TOOLCHAIN:
        want = (RUNG_D.seed / name).read_text(encoding="utf-8")
        got = (TS.seed / name).read_text(encoding="utf-8")
        assert got.replace(TS.slug, RUNG_D.slug) == want, name
    assert json.loads((TS.seed / "package.json").read_text(encoding="utf-8"))["name"] == TS.slug
    assert (TS.path / "environment" / "Dockerfile").read_bytes() == (
        RUNG_D.path / "environment" / "Dockerfile").read_bytes()


def test_code_imports_nothing_but_its_own_files_and_jest():
    for name in TS.seed_files():
        if name.endswith(".ts"):
            text = (TS.seed / name).read_text(encoding="utf-8")
            for source in _IMPORT.findall(text):
                assert source.startswith(".") or source == "@jest/globals", (name, source)


def test_each_production_file_is_a_root_entry_point_or_in_a_layer():
    for name in TS.production_files():
        assert _layer(name) in ("root", *LAYERS), name
        assert name.count("/") <= 1, name


def test_each_layer_imports_only_the_layers_below_it():
    for name in TS.production_files():
        layer = _layer(name)
        if layer == "root":
            continue
        for target in _imports(name):
            assert (TS.seed / target).is_file(), (name, target)
            assert _layer(target) in MAY_IMPORT[layer], (name, target)


def test_each_seed_test_sits_beside_the_module_that_it_tests():
    for name in TS.seed_test_files():
        assert (TS.seed / name.replace(".test.ts", ".ts")).is_file(), name


def test_root_modules_export_every_name_that_the_feature_tests_of_m_and_x_import():
    # The feature tests run unchanged in the repository root (rungs C, D, E).
    for pack in (RUNG_C, RUNG_D):
        for module, names in _feature_test_imports(pack).items():
            if module == "returns.ts":
                continue  # the file of X, which the seed does not have
            assert names <= _exports(module), (pack, module, names - _exports(module))


def test_seed_has_no_returns_and_no_credit_notes():
    assert "returns.ts" not in TS.seed_files()
    for name in TS.production_files():
        text = (TS.seed / name).read_text(encoding="utf-8")
        assert "CreditNote" not in text and "'returned'" not in text, name


def test_design_note_describes_the_layers_and_the_conventions_for_the_go_port():
    note = DESIGN_NOTE.read_text(encoding="utf-8")
    for heading in ("## Layers", "## Conventions", "### Errors", "### Identifiers",
                    "### Money", "## Files", "## The Go port"):
        assert f"\n{heading}\n" in note, heading
    for name in TS.production_files():
        assert f"`{name}`" in note, name


# --- Slow: the seed's image ------------------------------------------------------


def _run(image: str, script: str, tmp_path: Path, files: dict[str, str] | None = None) -> str:
    """Run a bash script in a fresh container of the image, with no network,
    after writing `files` (paths relative to /app) over /app."""
    mounts: list[str] = []
    prelude = ""
    if files:
        overlay = tmp_path / "overlay"
        for rel, content in files.items():
            target = overlay / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        mounts = ["-v", f"{overlay}:/overlay:ro"]
        prelude = "cp -r /overlay/. /app/ && "
    result = docker("run", "--rm", "--network", "none", *mounts, image, "bash", "-c",
                    prelude + script)
    assert result.returncode == 0, result.stderr
    return result.stdout


def _jest(image: str, tmp_path: Path, tests: list[str],
          files: dict[str, str] | None = None) -> dict:
    """tsc over the given test files (and what they import), then Jest on them:
    {"compiles", "passed", "total", "failed_suites"}."""
    script = (
        "cd /app && node -e 'require(\"fs\").writeFileSync(\"tsconfig.check.json\", "
        "JSON.stringify({extends: \"./tsconfig.json\", files: process.argv.slice(1), "
        "include: []}))' " + " ".join(tests) + " && "
        "(corepack yarn tsc --noEmit -p tsconfig.check.json >/tmp/tsc.log 2>&1 "
        "&& echo COMPILES=1 || echo COMPILES=0) && "
        "corepack yarn jest --ci --json --outputFile=/tmp/jest.json --runTestsByPath "
        + " ".join(f"./{t}" for t in tests) + " >/dev/null 2>&1; "
        "cat /tmp/tsc.log | head -20; echo; cat /tmp/jest.json")
    out = _run(image, script, tmp_path, files)
    compiles = "COMPILES=1" in out
    result = json.loads(out[out.index("{\"num"):])
    return {"compiles": compiles, "passed": result["numPassedTests"],
            "total": result["numTotalTests"],
            "failed_suites": result["numFailedTestSuites"], "log": out[:3000]}


def _its(texts: list[str]) -> int:
    return sum(len(re.findall(r"\bit\(\s*'", text)) for text in texts)


@pytest.fixture(scope="module")
def image(pack_images):
    return pack_images(TS)


@pytest.mark.slow
def test_seed_suite_passes_in_the_pinned_typescript_toolchain_image(image, tmp_path):
    tests = TS.seed_test_files()
    counts = _jest(image, tmp_path, tests)
    want = _its([(TS.seed / t).read_text(encoding="utf-8") for t in tests])
    assert counts["compiles"], counts["log"]
    assert counts["passed"] == counts["total"] == want, counts["log"]


@pytest.mark.slow
def test_feature_tests_of_m_pass_against_the_promotions_engine(image, tmp_path):
    # PRD section 20: the seed of rung E holds the promotions engine, written
    # to the specification of M.
    (name,) = RUNG_C.reference_tests()
    text = (RUNG_C.path / "tests" / name).read_text(encoding="utf-8")
    counts = _jest(image, tmp_path, [name], {name: text})
    assert counts["compiles"], counts["log"]
    assert counts["passed"] == counts["total"] == RUNG_C.reference_count, counts["log"]


@pytest.mark.slow
def test_feature_tests_of_x_fail_because_the_seed_has_no_returns(image, tmp_path):
    (name,) = RUNG_D.reference_tests()
    text = (RUNG_D.path / "tests" / name).read_text(encoding="utf-8")
    counts = _jest(image, tmp_path, [name], {name: text})
    assert not counts["compiles"]
    assert counts["passed"] == 0
    assert counts["failed_suites"] == 1
