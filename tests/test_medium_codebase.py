"""The medium codebase of the codebase ladder, in TypeScript (issue #85) and
in Go (issue #86; PRD section 20, "The domain"): the small codebase of rung
D grown into the order and inventory service in layers (domain, services,
adapters), with the promotions engine (M), the customers and accounts, the
shipping, the invoices, an event log and the reports. It is the seed of rung
E, the pack tasks/<language>/shop-returns-medium (issue #87), which
tests/test_shop_returns_medium_task_packs.py and the shared checks cover.

The feature tests of X (rung D's) must later run unchanged on it, so the root
modules keep the entry points of the small codebase. The design note, which
the Go port follows file for file, is docs/codebase-ladder/medium-codebase.md;
the two languages hold the same seed design and seed-suite case names (ADR
0006).

The fast tests read the seeds. The slow tests build each image and run its
seed suite, the feature tests of M (rung C's) and the feature tests of X
(rung D's) in it, with no network.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.task_packs import (GO_DECLARATION, GO_FUNC, REPO_ROOT, SEED_SIZE_RANGES, TS_EXPORT,
                              TS_TOOLCHAIN, Pack, docker, packs, seed_design,
                              seed_suite_case_names)

TS, GO = packs("shop-returns-medium")["typescript"], packs("shop-returns-medium")["go"]
MEDIUM_CODEBASES = (TS, GO)
RUNG_C = packs("shop-promotions-small")
RUNG_D = packs("shop-returns-small")
DESIGN_NOTE = REPO_ROOT / "docs" / "codebase-ladder" / "medium-codebase.md"
LAYERS = ("domain", "services", "adapters")
# What each layer may import: the domain nothing but itself, the services the
# domain, the adapters the domain (they implement its ports). The root modules
# are the entry points and import any layer.
MAY_IMPORT = {"domain": {"domain"}, "services": {"domain", "services"},
              "adapters": {"domain", "adapters"}}
_IMPORT = re.compile(r"^(?:import|export)\b[^;]*?from '([^']+)'", re.MULTILINE | re.DOTALL)
_GO_IMPORT_BLOCK = re.compile(r"^import (?:\(([^)]*)\)|(.*))$", re.MULTILINE)

each_language = pytest.mark.parametrize("pack", MEDIUM_CODEBASES, ids=str)


def _go_imports(text: str) -> list[str]:
    """The import paths of a Go file."""
    found: list[str] = []
    for block, single in _GO_IMPORT_BLOCK.findall(text):
        found += re.findall(r'"([^"]+)"', block or single)
    return found


def _imports(pack: Pack, name: str) -> list[str]:
    """The layers or seed files that a seed file imports: seed paths in
    TypeScript, package folders in Go."""
    text = (pack.seed / name).read_text(encoding="utf-8")
    if pack.language == "go":
        return [path.removeprefix("shop/") for path in _go_imports(text)
                if path.startswith("shop/")]
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
    """The names that a TypeScript root module exports, by declaration or
    re-export."""
    text = (TS.seed / name).read_text(encoding="utf-8")
    names = {m.group(2) for m in TS_EXPORT.finditer(text)}
    for block in re.findall(r"^export (?:type )?\{([^}]*)\}", text, re.MULTILINE):
        names |= {n.strip().split(" as ")[-1] for n in block.split(",") if n.strip()}
    return names


def _go_declared(path: Path) -> set[str]:
    """The exported names that a Go file declares at its top level, in
    declarations or in grouped `type`, `const` and `var` blocks."""
    text = path.read_text(encoding="utf-8")
    names = {m.group(1) for pattern in (GO_DECLARATION, GO_FUNC) for m in pattern.finditer(text)}
    for block in re.findall(r"^(?:type|const|var) \(\n(.*?)^\)", text, re.MULTILINE | re.DOTALL):
        names |= set(re.findall(r"^\t([A-Z]\w*)", block, re.MULTILINE))
    return names


def _feature_test_imports(pack: Pack) -> dict[str, set[str]]:
    """The names that a TypeScript pack's feature tests import, by module."""
    (text,) = pack.reference_test_texts()
    wanted: dict[str, set[str]] = {}
    for names, source in re.findall(r"^import (?:type )?\{([^}]*)\} from '\./([^']+)'", text,
                                    re.MULTILINE):
        for n in names.split(","):
            if n.strip():
                wanted.setdefault(source, set()).add(n.strip().removeprefix("type ").strip())
    return wanted


# --- The seed's files -----------------------------------------------------------


@each_language
def test_medium_codebase_is_inside_the_size_ranges_of_a_medium_seed(pack):
    # PRD section 20, "The domain": 4,000 to 6,000 lines of production code
    # (non-blank) in 30 to 50 files, and a seed suite of 200 to 400 tests.
    ranges = SEED_SIZE_RANGES["medium"]
    sizes = {"lines": pack.production_lines(), "files": len(pack.production_files()),
             "tests": len(seed_suite_case_names(pack))}
    for key, (least, most) in ranges.items():
        assert least <= sizes[key] <= most, (key, sizes[key])


def test_the_two_languages_hold_the_same_seed_design_and_seed_suite_case_names():
    # Issue #86; ADR 0006: the files and the exported names with the language
    # taken out (but the names that only one language can have), and the
    # same test cases, in the same order.
    assert seed_design(TS) == seed_design(GO)
    assert seed_suite_case_names(TS) == seed_suite_case_names(GO)


def test_toolchain_and_dockerfile_are_rung_ds_but_for_the_package_name():
    for name in TS_TOOLCHAIN:
        want = (RUNG_D["typescript"].seed / name).read_text(encoding="utf-8")
        got = (TS.seed / name).read_text(encoding="utf-8")
        assert got.replace(TS.slug, RUNG_D["typescript"].slug) == want, name
    assert json.loads((TS.seed / "package.json").read_text(encoding="utf-8"))["name"] == TS.slug
    assert (GO.seed / "go.mod").read_bytes() == (RUNG_D["go"].seed / "go.mod").read_bytes()
    for pack in MEDIUM_CODEBASES:
        assert (pack.path / "environment" / "Dockerfile").read_bytes() == (
            RUNG_D[pack.language].path / "environment" / "Dockerfile").read_bytes()


def test_code_imports_nothing_but_its_own_files_and_the_toolchain():
    for name in TS.seed_files():
        if name.endswith(".ts"):
            text = (TS.seed / name).read_text(encoding="utf-8")
            for source in _IMPORT.findall(text):
                assert source.startswith(".") or source == "@jest/globals", (name, source)
    for name in GO.seed_files():
        if name.endswith(".go"):
            for path in _go_imports((GO.seed / name).read_text(encoding="utf-8")):
                # The standard library has no dot in its first element.
                assert path.startswith("shop/") or "." not in path.split("/")[0], (name, path)


@each_language
def test_each_production_file_is_a_root_entry_point_or_in_a_layer(pack):
    for name in pack.production_files():
        assert _layer(name) in ("root", *LAYERS), name
        assert name.count("/") <= 1, name


@each_language
def test_each_layer_imports_only_the_layers_below_it(pack):
    for name in pack.production_files():
        layer = _layer(name)
        if layer == "root":
            continue
        for target in _imports(pack, name):
            assert (pack.seed / target).exists(), (name, target)
            assert _layer(target if pack.language == "typescript" else target + "/")\
                in MAY_IMPORT[layer], (name, target)


@each_language
def test_each_seed_test_sits_beside_the_module_that_it_tests(pack):
    for name in pack.seed_test_files():
        module = name.removesuffix(pack.lang.test_suffix) + pack.lang.source_suffix
        assert (pack.seed / module).is_file(), name


def test_root_modules_export_every_name_that_the_feature_tests_of_m_and_x_import():
    # The feature tests run unchanged in the repository root (rungs C, D, E).
    for pack in (RUNG_C["typescript"], RUNG_D["typescript"]):
        for module, names in _feature_test_imports(pack).items():
            if module == "returns.ts":
                continue  # the file of X, which the seed does not have
            assert names <= _exports(module), (pack, module, names - _exports(module))


def test_go_root_files_declare_every_name_that_rung_ds_files_of_the_same_name_declared():
    # Go has no imports in a package: the feature tests of M and X use the
    # names that rung D's root package declared, so each root file of the same
    # name declares them too (as aliases of the layers).
    small = RUNG_D["go"]
    for name in small.production_files():
        if name.endswith(".go"):
            want = _go_declared(small.seed / name)
            got = _go_declared(GO.seed / name)
            assert want <= got, (name, want - got)


@each_language
def test_seed_has_no_returns_and_no_credit_notes(pack):
    assert pack.feature_file not in pack.seed_files()
    returned = "'returned'" if pack.language == "typescript" else '"returned"'
    for name in pack.production_files():
        text = (pack.seed / name).read_text(encoding="utf-8")
        assert "CreditNote" not in text and returned not in text, name


def test_go_seed_test_files_each_stand_alone():
    # The verifier drops each unchanged seed test file in the agent pass
    # (issue #83), so no seed test file may lean on a helper of another: the
    # top-level names of the test files of one package are all different.
    declared: dict[str, str] = {}
    for name in GO.seed_test_files():
        text = (GO.seed / name).read_text(encoding="utf-8")
        for helper in re.findall(r"^(?:func|type|var|const) (\w+)", text, re.MULTILINE):
            key = f"{_layer(name)}.{helper}"
            assert key not in declared, (name, helper, declared.get(key))
            declared[key] = name


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


def _go_test(image: str, tmp_path: Path, packages: str,
             files: dict[str, str] | None = None) -> dict:
    """go test -json on the packages: {"compiles", "passed", "failed", "names"}
    over the leaf tests (a t.Run with no t.Run inside it), and "cases": each
    test and subtest that passed, by its last name."""
    out = _run(image, f"cd /app && go test -json -count=1 {packages} 2>&1; true",
               tmp_path, files)
    events = [json.loads(line) for line in out.splitlines() if line.startswith("{")]
    status = {(e["Package"], e["Test"]): e["Action"] for e in events
              if e.get("Test") and e["Action"] in ("pass", "fail", "skip")}
    leaves = [key for key in status
              if not any(other[0] == key[0] and other[1].startswith(key[1] + "/")
                         for other in status)]
    return {"compiles": not any(e["Action"] == "build-fail" or "FailedBuild" in e
                                for e in events) and "build failed" not in out,
            "passed": sum(status[k] == "pass" for k in leaves),
            "failed": sum(status[k] != "pass" for k in leaves),
            "subtests": sum(1 for k, v in status.items() if "/" in k[1] and v == "pass"),
            "log": out[-3000:]}


def _its(texts: list[str]) -> int:
    return sum(len(re.findall(r"\bit\(\s*'", text)) for text in texts)


@pytest.fixture(scope="module")
def images(pack_images):
    return lambda pack: pack_images(pack)


@pytest.mark.slow
def test_seed_suite_passes_in_the_pinned_typescript_toolchain_image(images, tmp_path):
    tests = TS.seed_test_files()
    counts = _jest(images(TS), tmp_path, tests)
    want = _its([(TS.seed / t).read_text(encoding="utf-8") for t in tests])
    assert counts["compiles"], counts["log"]
    assert counts["passed"] == counts["total"] == want, counts["log"]


@pytest.mark.slow
def test_seed_suite_passes_in_the_pinned_go_toolchain_image(images, tmp_path):
    # Every t.Run of the seed suite runs and passes: one for each case.
    counts = _go_test(images(GO), tmp_path, "./...")
    assert counts["compiles"], counts["log"]
    assert counts["failed"] == 0, counts["log"]
    assert counts["subtests"] == len(seed_suite_case_names(GO)), counts["log"]


@pytest.mark.slow
def test_feature_tests_of_m_pass_against_the_promotions_engine(images, tmp_path):
    # PRD section 20: the seed of rung E holds the promotions engine, written
    # to the specification of M.
    ts = RUNG_C["typescript"]
    (name,) = ts.reference_tests()
    text = (ts.path / "tests" / name).read_text(encoding="utf-8")
    counts = _jest(images(TS), tmp_path, [name], {name: text})
    assert counts["compiles"], counts["log"]
    assert counts["passed"] == counts["total"] == ts.reference_count, counts["log"]


@pytest.mark.slow
def test_go_feature_tests_of_m_pass_against_the_promotions_engine(images, tmp_path):
    go = RUNG_C["go"]
    (name,) = go.reference_tests()
    text = (go.path / "tests" / "reference" / name).read_text(encoding="utf-8")
    tests = " ".join(re.findall(r"^func (Test\w+)\(", text, re.MULTILINE))
    counts = _go_test(images(GO), tmp_path, f". -run '^({tests.replace(' ', '|')})$'",
                      {name: text})
    assert counts["compiles"], counts["log"]
    assert counts["failed"] == 0, counts["log"]
    assert counts["passed"] == go.reference_count, counts["log"]


@pytest.mark.slow
def test_feature_tests_of_x_fail_because_the_seed_has_no_returns(images, tmp_path):
    ts = RUNG_D["typescript"]
    (name,) = ts.reference_tests()
    text = (ts.path / "tests" / name).read_text(encoding="utf-8")
    counts = _jest(images(TS), tmp_path, [name], {name: text})
    assert not counts["compiles"]
    assert counts["passed"] == 0
    assert counts["failed_suites"] == 1


@pytest.mark.slow
def test_go_feature_tests_of_x_fail_only_on_the_names_of_returns(images, tmp_path):
    # Unchanged, in the root package: they do not compile, and each name that
    # the compiler misses is a name of X (#87 adds them).
    go = RUNG_D["go"]
    (name,) = go.reference_tests()
    text = (go.path / "tests" / "reference" / name).read_text(encoding="utf-8")
    out = _run(images(GO), "cd /app && go vet . 2>&1; go test -gcflags=-e -count=1 . 2>&1; true",
               tmp_path, {name: text})
    missing = set(re.findall(r"undefined: (\w+)", out))
    assert missing, out[-3000:]
    assert missing <= {"Returns", "ReturnsDeps", "NewReturns", "ReturnLine", "CreditNote",
                       "CreditLine"}, out[-3000:]
    assert "--- PASS" not in out and "has no field or method" not in out, out[-3000:]
