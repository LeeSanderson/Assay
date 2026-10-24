"""The Go `split-second-stopwatch` task pack (PRD §5 "Task packs").

Fast tests read the pack's files. Slow tests build the pack image and run
`tests/test.sh` on prepared repositories, or run the pack through Harbor.
"""

import json
import re
import shutil
import subprocess
import tomllib
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PACK = REPO_ROOT / "tasks" / "go" / "split-second-stopwatch"
SEED = PACK / "environment" / "seed"
STUB = "split_second_stopwatch.go"

REWARD_FIELDS = {
    "reward",
    "reference_compiles",
    "reference_passed",
    "reference_total",
    "agent_tests_compile",
    "agent_tests_passed",
    "agent_tests_total",
}


def _task_toml():
    return tomllib.loads((PACK / "task.toml").read_text(encoding="utf-8"))


def test_seed_repository_holds_the_stub_and_go_mod_only():
    files = sorted(p.relative_to(SEED).as_posix() for p in SEED.rglob("*") if p.is_file())
    assert files == ["go.mod", STUB]


def test_metadata_records_the_provenance():
    meta = _task_toml()["metadata"]
    assert meta["source_repo"] == "https://github.com/exercism/go"
    assert re.fullmatch(r"[0-9a-f]{40}", meta["source_commit"])
    assert meta["seed_files"] == ["go.mod", STUB]
    assert any(p.endswith(".meta/example.go") for p in meta["copied_paths"])
    assert any(p.endswith("cases_test.go") for p in meta["copied_paths"])
    assert meta["mechanical_changes"]
    edits = " ".join(meta["mechanical_changes"])
    assert "Interface section" in edits
    assert "split_second_stopwatch.go" in edits and "not implemented" in edits
    dockerfile = (PACK / "environment" / "Dockerfile").read_text(encoding="utf-8")
    from_image = re.search(r"^FROM (\S+)", dockerfile, re.M).group(1)
    assert re.fullmatch(r"golang:[\d.]+-bookworm@sha256:[0-9a-f]{64}", from_image)
    assert meta["base_image"] == from_image


def test_limits_follow_the_prd():
    cfg = _task_toml()
    assert cfg["agent"]["timeout_sec"] == 1800
    assert cfg["verifier"]["timeout_sec"] == 600
    assert cfg["environment"]["cpus"] == 2
    assert cfg["environment"]["memory_mb"] == 4096


def test_prompt_is_the_exercism_instructions_plus_the_footer():
    prompt = (PACK / "instruction.md").read_text(encoding="utf-8")
    assert prompt.startswith("# Instructions\n")
    assert prompt.rstrip("\n").endswith(
        f"Implement the solution in `{STUB}`. Keep the exported names and signatures "
        "as they are. Tests that you cannot see will check your solution."
    )
    assert "test" not in prompt.split("Implement the solution in")[0].lower()


def test_seed_repository_does_not_identify_its_source():
    for path in SEED.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8").lower()
            assert "exercism" not in text, path.name
            assert "please implement" not in text, path.name


# The exported signatures of the source stub, at `source_commit`.
SOURCE_SIGNATURES = [
    "func (sss *SplitSecondStopwatch) Start() error",
    "func (sss *SplitSecondStopwatch) Stop() error",
    "func (sss *SplitSecondStopwatch) Reset() error",
    "func (sss *SplitSecondStopwatch) Lap() error",
    "func (sss *SplitSecondStopwatch) AdvanceTime(by string)",
    "func (sss *SplitSecondStopwatch) State() string",
    "func (sss *SplitSecondStopwatch) CurrentLap() string",
    "func (sss *SplitSecondStopwatch) Total() string",
    "func (sss *SplitSecondStopwatch) PreviousLaps() []string",
    "func NewSplitSecondStopwatch() *SplitSecondStopwatch",
]


def test_stub_keeps_the_source_signatures_and_module():
    stub = (SEED / STUB).read_text(encoding="utf-8")
    assert stub.startswith("package splitsecondstopwatch\n")
    assert "type SplitSecondStopwatch struct{}" in stub
    signatures = re.findall(r"^(func .*?)\s*\{", stub, re.M)
    assert signatures == SOURCE_SIGNATURES
    go_mod = (SEED / "go.mod").read_text(encoding="utf-8")
    assert go_mod.startswith("module splitsecondstopwatch\n")


def _interface_section():
    prompt = (PACK / "instruction.md").read_text(encoding="utf-8")
    prose, _, rest = prompt.partition("\n## Interface\n")
    assert rest, "instruction.md has no Interface section"
    section, _, footer = rest.partition("Implement the solution in")
    assert footer, "the Interface section must come before the Assay footer"
    assert "| Command | Begin state |" in prose
    return section


def test_interface_section_states_the_getter_and_advance_time_formats():
    section = _interface_section()
    for name in ("CurrentLap", "Total", "PreviousLaps", "AdvanceTime", "State"):
        assert f"`{name}" in section, name
    assert '"HH:MM:SS"' in section
    assert '"00:00:00"' in section
    for state in ('"ready"', '"running"', '"stopped"'):
        assert state in section, state


def test_interface_section_gives_each_error_message_exactly():
    # The messages the reference tests compare with err.Error().
    section = _interface_section()
    for message in (
        "cannot start an already running stopwatch",
        "cannot stop a stopwatch that is not running",
        "cannot lap a stopwatch that is not running",
        "cannot reset a stopwatch that is not stopped",
    ):
        assert f'"{message}"' in section, message


# --- Slow: the pack image and tests/test.sh -------------------------------

GOLD = (PACK / "solution" / "example.go").read_text(encoding="utf-8")
STUB_SOURCE = (SEED / STUB).read_text(encoding="utf-8")

AGENT_TESTS_ONE_FAILING = """package splitsecondstopwatch

import "testing"

func TestNewIsReady(t *testing.T) {
	if got := NewSplitSecondStopwatch().State(); got != "ready" {
		t.Fatalf("got %q", got)
	}
}

func TestStates(t *testing.T) {
	t.Run("ready", func(t *testing.T) {})
	t.Run("wrong", func(t *testing.T) { t.Fatal("deliberately red") })
}
"""

# Redeclares a reference test's name and does not compile on its own.
AGENT_TESTS_NOT_COMPILING = """package splitsecondstopwatch

import "testing"

func TestTime(t *testing.T) {
	undefinedHelper()
}
"""


@pytest.fixture(scope="module")
def image():
    tag = f"assay-test/go-split-second-stopwatch:{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "build", "-q", "-t", tag, str(PACK / "environment")],
        check=True,
        capture_output=True,
    )
    yield tag
    subprocess.run(["docker", "rmi", "-f", tag], capture_output=True)


def _in_image(image, script, mounts=()):
    args = ["docker", "run", "--rm", "--network", "none"]
    for host, container in mounts:
        args += ["-v", f"{host}:{container}"]
    return subprocess.run(
        args + [image, "bash", "-c", script], capture_output=True, text=True
    )


def run_verifier(image, tmp_path, files):
    """Put `files` into /app over the seed repository and run tests/test.sh."""
    prep = tmp_path / "prep"
    prep.mkdir()
    for name, content in files.items():
        (prep / name).write_bytes(content.encode("utf-8"))
    out = tmp_path / "verifier"
    out.mkdir()
    result = _in_image(
        image,
        "cp -a /prep/. /app/ && /tests/test.sh",
        mounts=[
            (PACK / "tests", "/tests:ro"),
            (prep, "/prep:ro"),
            (out, "/logs/verifier"),
        ],
    )
    reward_file = out / "reward.json"
    assert reward_file.exists(), result.stdout + result.stderr
    return json.loads(reward_file.read_text(encoding="utf-8"))


def _assert_shape(reward):
    assert set(reward) == REWARD_FIELDS
    for value in reward.values():
        assert type(value) in (int, float)


@pytest.mark.slow
def test_image_holds_the_seed_repository_and_no_skills(image):
    result = _in_image(
        image,
        "set -e; cd /app; test ! -e ~/.claude/skills; test ! -e .claude;"
        " git log --format=%s; git status --porcelain; ls -A",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ["seed", ".git", "go.mod", STUB]


@pytest.mark.slow
def test_gold_solution_with_no_agent_tests(image, tmp_path):
    reward = run_verifier(image, tmp_path, {STUB: GOLD})
    _assert_shape(reward)
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == 29
    assert reward["agent_tests_passed"] == reward["agent_tests_total"] == 0


@pytest.mark.slow
def test_seed_stub_gives_reward_0(image, tmp_path):
    reward = run_verifier(image, tmp_path, {})
    _assert_shape(reward)
    assert reward["reward"] == 0
    assert reward["reference_compiles"] == 1
    assert reward["agent_tests_total"] == 0


@pytest.mark.slow
def test_agent_tests_are_counted_by_leaf_test(image, tmp_path):
    reward = run_verifier(
        image, tmp_path, {STUB: GOLD, "stopwatch_test.go": AGENT_TESTS_ONE_FAILING}
    )
    assert reward["reward"] == 1
    assert reward["agent_tests_compile"] == 1
    assert reward["agent_tests_passed"] == 2
    assert reward["agent_tests_total"] == 3


@pytest.mark.slow
def test_agent_test_that_does_not_compile_leaves_outcome_pass_unaffected(
    image, tmp_path
):
    reward = run_verifier(
        image, tmp_path, {STUB: GOLD, "stopwatch_test.go": AGENT_TESTS_NOT_COMPILING}
    )
    _assert_shape(reward)
    assert reward["reward"] == 1
    assert reward["reference_compiles"] == 1
    assert reward["reference_passed"] == reward["reference_total"] == 29
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0


@pytest.mark.slow
def test_agent_test_that_does_not_compile_counts_its_files_so_replay_sees_red_compile(
    image, tmp_path
):
    # Replay reads agent_tests_total 0 as `no-tests`; a build failure emits no
    # test events, so the verifier counts the agent test files instead.
    reward = run_verifier(
        image,
        tmp_path,
        {
            STUB: GOLD,
            "stopwatch_test.go": AGENT_TESTS_NOT_COMPILING,
            "more_test.go": AGENT_TESTS_ONE_FAILING.replace("TestNewIsReady", "TestMore")
            .replace("TestStates", "TestMoreStates"),
        },
    )
    assert reward["agent_tests_compile"] == 0
    assert reward["agent_tests_passed"] == 0
    assert reward["agent_tests_total"] == 2


def harbor_reward(agent, tmp_path):
    """Run the pack through Harbor with `agent` and return the trial's rewards."""
    job = f"go-sss-{agent}"
    subprocess.run(
        ["uv", "run", "harbor", "run", "-p", str(PACK), "-a", agent,
         "-o", str(tmp_path), "--job-name", job, "-y", "-q"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        timeout=1200,
    )
    (trial,) = [p for p in (tmp_path / job).iterdir() if p.is_dir()]
    result = json.loads((trial / "result.json").read_text(encoding="utf-8"))
    return result["verifier_result"]["rewards"]


@pytest.mark.slow
def test_harbor_oracle_gives_reward_1(tmp_path):
    rewards = harbor_reward("oracle", tmp_path)
    _assert_shape(rewards)
    assert rewards["reward"] == 1
    assert rewards["reference_passed"] == rewards["reference_total"] == 29


@pytest.mark.slow
def test_harbor_do_nothing_agent_gives_reward_0(tmp_path):
    rewards = harbor_reward("nop", tmp_path)
    _assert_shape(rewards)
    assert rewards["reward"] == 0
    assert rewards["agent_tests_total"] == 0


@pytest.mark.slow
def test_changed_stub_signature_gives_reference_compiles_0(image, tmp_path):
    # Still compiles on its own; only the reference tests' call breaks.
    changed = GOLD.replace("AdvanceTime(by string)", "AdvanceTime(by string, _ int)")
    assert changed != GOLD
    reward = run_verifier(image, tmp_path, {STUB: changed})
    _assert_shape(reward)
    assert reward["reference_compiles"] == 0
    assert reward["reward"] == 0
