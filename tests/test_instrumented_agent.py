"""Seam 4: `InstrumentedClaudeCode.setup()` with a fake Harbor environment.

The fake follows the `BaseEnvironment` methods that Harbor 0.24.0 agents call
(`exec`, `upload_file`, `upload_dir`, `default_user`) and records each call.
It answers `claude --version` with the pinned version, so the install is
skipped.
"""

import asyncio
import copy
import json
from pathlib import Path

import pytest
from harbor.environments.base import ExecResult
from harbor.models.agent.context import AgentContext

from instruments.agent import (
    InstrumentBlockedError,
    InstrumentedClaudeCode,
    merge_instrument_hooks,
)
from instruments.digest import instruments_digest

REPO_ROOT = Path(__file__).resolve().parent.parent
INSTRUMENTS = REPO_ROOT / "instruments"
CLAUDE_VERSION = "2.1.0"
HOOK_COMMAND = "bash /harbor/instruments/trace.sh"
INSTRUMENT_HOOK = {
    "matcher": "*",
    "hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 10}],
}


class FakeEnvironment:
    def __init__(self):
        self.default_user = None
        self.calls: list[tuple] = []

    async def exec(self, command, cwd=None, env=None, timeout_sec=None, user=None):
        self.calls.append(("exec", command, user))
        return ExecResult(return_code=0, stdout=f"{CLAUDE_VERSION} (Claude Code)\n", stderr="")

    async def upload_file(self, source_path, target_path):
        self.calls.append(("upload_file", target_path, Path(source_path).read_text(encoding="utf-8")))

    async def upload_dir(self, source_dir, target_dir):
        files = sorted(p.relative_to(source_dir).as_posix()
                       for p in Path(source_dir).rglob("*") if p.is_file())
        self.calls.append(("upload_dir", target_dir, files))

    # Views on the recorded calls.
    def index(self, kind, predicate=lambda call: True):
        for i, call in enumerate(self.calls):
            if call[0] == kind and predicate(call):
                return i
        raise AssertionError(f"no {kind} call matched in {self.calls}")

    def uploaded(self, target):
        return self.calls[self.index("upload_file", lambda c: c[1] == target)][2]


def make_agent(tmp_path, config):
    return InstrumentedClaudeCode(
        logs_dir=tmp_path / "agent",
        model_name="anthropic/claude-haiku-4-5",
        version=CLAUDE_VERSION,
        config=config,
        extra_env={"ANTHROPIC_API_KEY": "sk-test"},
    )


def setup(tmp_path, config=None):
    env = FakeEnvironment()
    asyncio.run(make_agent(tmp_path, config).setup(env))
    return env


def test_uploads_the_instruments_folder_to_harbor_instruments(tmp_path):
    env = setup(tmp_path)
    call = env.calls[env.index("upload_dir")]
    assert call[1] == "/harbor/instruments/"
    assert {"trace.sh", "jq", "agent.py", "digest.py"} <= set(call[2])
    assert not any("__pycache__" in f for f in call[2])


def test_jq_is_made_executable_after_the_upload(tmp_path):
    env = setup(tmp_path)
    upload = env.index("upload_dir")
    chmod = env.index("exec", lambda c: "chmod" in c[1] and "/harbor/instruments/jq" in c[1])
    assert chmod > upload
    assert env.calls[chmod][2] == "root"


def test_setup_fires_the_seed_once_after_the_upload(tmp_path):
    env = setup(tmp_path)
    seeds = [c for c in env.calls if c[0] == "exec" and f"{HOOK_COMMAND} seed" in c[1]]
    assert len(seeds) == 1
    assert env.index("exec", lambda c: f"{HOOK_COMMAND} seed" in c[1]) > env.index("upload_dir")


def test_the_seed_fire_comes_before_the_agent_starts(tmp_path):
    env = run_trial(tmp_path, None)
    seed = env.index("exec", lambda c: f"{HOOK_COMMAND} seed" in c[1])
    launch = env.index("exec", lambda c: "claude --verbose" in c[1])
    assert seed < launch


INSTRUMENTS_JSON = "/logs/artifacts/trace/instruments.json"


def test_instruments_json_records_digest_merged_settings_and_harbor_version(tmp_path):
    env = setup(tmp_path, copy.deepcopy(VARIANT))
    record = json.loads(env.uploaded(INSTRUMENTS_JSON))
    assert record == {
        "digest": instruments_digest(INSTRUMENTS),
        "settings": merge_instrument_hooks(VARIANT),
        "harbor_version": "0.24.0",
    }


def test_instruments_json_is_written_after_the_seed_fire(tmp_path):
    env = setup(tmp_path)
    seed = env.index("exec", lambda c: f"{HOOK_COMMAND} seed" in c[1])
    assert env.index("upload_file", lambda c: c[1] == INSTRUMENTS_JSON) > seed


VARIANT = {
    "permissions": {"allow": ["Bash(npm test:*)"]},
    "hooks": {
        "PostToolUse": [
            {"matcher": "Write|Edit", "hooks": [{"type": "command", "command": "echo variant"}]}
        ],
        "Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
    },
}


def test_merge_puts_the_variant_hooks_first_then_the_instrument_hooks():
    merged = merge_instrument_hooks(VARIANT)
    assert merged == {
        "permissions": {"allow": ["Bash(npm test:*)"]},
        "hooks": {
            "PostToolUse": [VARIANT["hooks"]["PostToolUse"][0], INSTRUMENT_HOOK],
            "Stop": VARIANT["hooks"]["Stop"],
            "PostToolUseFailure": [INSTRUMENT_HOOK],
        },
    }


def test_merge_into_empty_settings_adds_only_the_instrument_hooks():
    assert merge_instrument_hooks({}) == {
        "hooks": {"PostToolUse": [INSTRUMENT_HOOK], "PostToolUseFailure": [INSTRUMENT_HOOK]}
    }


def test_merge_leaves_the_variant_settings_unchanged():
    variant = copy.deepcopy(VARIANT)
    merge_instrument_hooks(variant)
    assert variant == VARIANT


def run_trial(tmp_path, config):
    agent = make_agent(tmp_path, config)
    env = FakeEnvironment()
    asyncio.run(agent.setup(env))
    asyncio.run(agent.run("Solve the task.", env, AgentContext()))
    return env


def test_the_run_uses_the_merged_settings_and_kwargs_config_is_unchanged(tmp_path):
    config = copy.deepcopy(VARIANT)
    env = run_trial(tmp_path, config)
    uploaded = json.loads(env.uploaded("/tmp/claude-code-settings/settings.json"))
    assert uploaded == merge_instrument_hooks(VARIANT)
    assert config == VARIANT


@pytest.mark.parametrize("settings", [
    {"disableAllHooks": True},
    {"allowManagedHooksOnly": True},
])
def test_settings_that_stop_the_instrument_hooks_stop_the_trial(tmp_path, settings):
    agent = make_agent(tmp_path, settings)
    env = FakeEnvironment()
    with pytest.raises(InstrumentBlockedError, match=next(iter(settings))):
        asyncio.run(agent.setup(env))
    assert env.calls == []


def test_disable_all_hooks_false_does_not_stop_the_trial(tmp_path):
    env = setup(tmp_path, {"disableAllHooks": False})
    env.index("upload_dir")


def test_a_job_without_kwargs_config_still_gets_the_instrument_hooks(tmp_path):
    env = run_trial(tmp_path, None)
    uploaded = json.loads(env.uploaded("/tmp/claude-code-settings/settings.json"))
    assert uploaded == merge_instrument_hooks({})
