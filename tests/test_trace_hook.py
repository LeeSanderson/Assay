"""Seam 3: the trace hook (`instruments/trace.sh`) as a black box.

Each test runs the real script with real bash, git, and the bundled jq against
temp folders. On Windows the script runs under WSL.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TRACE_SH = REPO_ROOT / "instruments" / "trace.sh"


def _posix(path: Path) -> str:
    if sys.platform != "win32":
        return str(path)
    p = PureWindowsPath(path)
    drive = p.drive.rstrip(":").lower()
    return "/mnt/" + drive + "/" + "/".join(p.parts[1:])


def _shell_prefix() -> list[str]:
    if sys.platform == "win32":
        if shutil.which("wsl.exe") is None:
            pytest.skip("the trace hook needs WSL on Windows")
        return ["wsl.exe", "-e"]
    if shutil.which("bash") is None or shutil.which("git") is None:
        pytest.skip("the trace hook needs bash and git")
    return []


class Trial:
    """An app folder (the seed repository) and a trace folder for one trial."""

    def __init__(self, root: Path):
        self.app = root / "app"
        self.trace = root / "trace"
        self.app.mkdir()

    def write(self, rel: str, content: str = "x\n") -> None:
        path = self.app / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")

    def fire(self, event: str = "PostToolUse", tool_name: str = "Write",
             tool_use_id: str = "toolu_1", stdin: str | None = None,
             app: Path | None = None,
             home: Path | None = None) -> subprocess.CompletedProcess:
        env = [*([f"HOME={_posix(home)}"] if home else []),
            f"ASSAY_TRACE_APP_DIR={_posix(app or self.app)}",
            f"ASSAY_TRACE_DIR={_posix(self.trace)}",
        ]
        if event == "seed":
            args, data = ["seed"], ""
        else:
            args = []
            data = stdin if stdin is not None else json.dumps({
                "hook_event_name": event,
                "tool_name": tool_name,
                "tool_use_id": tool_use_id,
                "tool_input": {},
            })
        return subprocess.run(
            [*_shell_prefix(), "env", *env, "bash", _posix(TRACE_SH), *args],
            input=data.encode(), capture_output=True, timeout=60,
        )

    def lines(self) -> list[dict]:
        text = (self.trace / "trace.jsonl").read_text(encoding="utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def last(self) -> dict:
        return self.lines()[-1]

    def snapshot_files(self, commit: str) -> list[str]:
        result = subprocess.run(
            [*_shell_prefix(), "git", f"--git-dir={_posix(self.trace / 'trace.git')}",
             "-c", "safe.directory=*", "ls-tree", "-r", "--name-only", commit],
            capture_output=True, text=True, check=True,
        )
        return result.stdout.splitlines()


@pytest.fixture
def trial(tmp_path: Path) -> Trial:
    return Trial(tmp_path)


def test_seed_fire_makes_the_first_snapshot(trial):
    trial.write("src/stopwatch.ts", "export {}\n")

    trial.fire("seed")

    line = trial.last()
    assert line["seq"] == 0
    assert line["event"] == "seed"
    assert line["changed"] is True
    assert trial.snapshot_files(line["commit"]) == ["src/stopwatch.ts"]
    assert line["paths"] == [{"status": "A", "path": "src/stopwatch.ts"}]


def test_a_fire_with_no_change_records_changed_false_and_no_commit(trial):
    trial.write("src/stopwatch.ts")
    trial.fire("seed")

    trial.fire("PostToolUse", tool_name="Read", tool_use_id="toolu_read")

    line = trial.last()
    assert line["seq"] == 1
    assert line["changed"] is False
    assert "commit" not in line
    assert line["paths"] == []


def test_each_line_holds_the_record_fields(trial):
    trial.fire("seed")
    trial.write("src/stopwatch.ts")

    trial.fire("PostToolUseFailure", tool_name="Bash", tool_use_id="toolu_bash")

    line = trial.last()
    assert set(line) == {"seq", "ts", "event", "tool_name", "tool_use_id",
                         "changed", "commit", "paths"}
    assert line["seq"] == 1
    assert line["event"] == "PostToolUseFailure"
    assert line["tool_name"] == "Bash"
    assert line["tool_use_id"] == "toolu_bash"
    assert line["changed"] is True
    assert line["ts"].startswith("20") and line["ts"].endswith("Z")
    assert line["paths"] == [{"status": "A", "path": "src/stopwatch.ts"}]


def test_paths_give_added_modified_and_deleted_files(trial):
    trial.write("keep.ts", "one\n")
    trial.write("gone.ts")
    trial.fire("seed")

    trial.write("keep.ts", "two\n")
    (trial.app / "gone.ts").unlink()
    trial.write("new.ts")
    trial.fire()

    assert trial.last()["paths"] == [
        {"status": "D", "path": "gone.ts"},
        {"status": "M", "path": "keep.ts"},
        {"status": "A", "path": "new.ts"},
    ]


def test_a_rename_gives_deleted_old_path_and_added_new_path(trial):
    trial.write("src/old_name.ts", "the same content in both places\n")
    trial.fire("seed")

    (trial.app / "src/old_name.ts").rename(trial.app / "src/new_name.ts")
    trial.fire()

    assert trial.last()["paths"] == [
        {"status": "A", "path": "src/new_name.ts"},
        {"status": "D", "path": "src/old_name.ts"},
    ]


def test_snapshot_leaves_out_git_and_node_modules_and_ignores_gitignore(trial):
    trial.write(".git/HEAD", "ref: refs/heads/main\n")
    trial.write("node_modules/dep/index.js")
    trial.write("pkg/node_modules/dep/index.js")
    trial.write(".gitignore", "hidden.test.ts\n")
    trial.write("hidden.test.ts")
    trial.write("sub/.gitignore", "*\n")
    trial.write("sub/also_hidden.ts")

    trial.fire("seed")

    assert trial.snapshot_files(trial.last()["commit"]) == [
        ".gitignore", "hidden.test.ts", "sub/.gitignore", "sub/also_hidden.ts",
    ]


def test_the_agents_git_folder_is_never_written(trial):
    trial.write("src/stopwatch.ts")
    subprocess.run([*_shell_prefix(), "git", "-C", _posix(trial.app), "init", "-q"],
                   check=True)
    before = {p: p.read_bytes() for p in (trial.app / ".git").rglob("*") if p.is_file()}

    trial.fire("seed")
    trial.write("src/stopwatch.ts", "changed\n")
    trial.fire()

    after = {p: p.read_bytes() for p in (trial.app / ".git").rglob("*") if p.is_file()}
    assert after == before
    assert trial.last()["changed"] is True


def test_the_hook_is_silent_and_exits_0(trial):
    trial.write("src/stopwatch.ts")

    results = [trial.fire("seed"), trial.fire(), trial.fire(stdin="not json")]

    for result in results:
        assert result.returncode == 0
        assert result.stdout == b""


def test_a_failed_fire_logs_the_error_and_still_appends_a_line(trial):
    trial.fire("seed")

    result = trial.fire(tool_name="Bash", tool_use_id="toolu_bash",
                        app=trial.app / "missing")

    assert result.returncode == 0
    assert result.stdout == b""
    line = trial.last()
    assert line["seq"] == 1
    assert line["tool_use_id"] == "toolu_bash"
    assert line["changed"] is None
    assert "commit" not in line
    assert line["error"]
    assert (trial.trace / "errors.log").read_text(encoding="utf-8").strip()


def test_bad_hook_input_gives_an_error_line(trial):
    trial.fire(stdin="not json")

    line = trial.last()
    assert line["changed"] is None
    assert line["error"]


def test_commits_ignore_global_git_config_and_use_a_fixed_name_and_date(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        "[user]\n\tname = Someone Else\n[i18n]\n\tcommitEncoding = ISO-8859-1\n", encoding="utf-8")
    trials = []
    for name in ("one", "two"):
        root = tmp_path / name
        root.mkdir()
        t = Trial(root)
        t.write("src/stopwatch.ts", "export {}\n")
        trials.append(t)

    trials[0].fire("seed")
    trials[1].fire("seed", home=home)

    one, two = (t.last() for t in trials)
    assert one["changed"] is True
    assert one["commit"] == two["commit"]
    author = subprocess.run(
        [*_shell_prefix(), "git", f"--git-dir={_posix(trials[0].trace / 'trace.git')}",
         "-c", "safe.directory=*", "log", "-1", "--format=%an|%aI"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert author == "assay-trace|2000-01-01T00:00:00+00:00"