"""`InstrumentedClaudeCode`: Harbor's `claude-code` agent plus the measurement instruments.

PRD section 5, "How the hook gets into the container", and ADR 0001. Every
Assay job runs this class through `import_path:
instruments.agent:InstrumentedClaudeCode`. It overrides `setup()` only.
"""

import copy
import importlib.metadata
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from harbor.agents.installed.claude_code import ClaudeCode
from harbor.environments.base import BaseEnvironment

from instruments.digest import EXCLUDED_DIRS, instruments_digest

INSTRUMENTS_DIR = Path(__file__).resolve().parent
REMOTE_DIR = "/harbor/instruments/"
TRACE_DIR = "/logs/artifacts/trace"
HOOK_COMMAND = "bash /harbor/instruments/trace.sh"
IMPORT_PATH = "instruments.agent:InstrumentedClaudeCode"  # the job files' `import_path`
HOOK_EVENTS = ("PostToolUse", "PostToolUseFailure")
BLOCKING_KEYS = ("disableAllHooks", "allowManagedHooksOnly")
VERSION_PLACEHOLDER = "SET-ON-SMOKE-TRIAL-DAY"


VALID_VERSION = re.compile(r"stable|latest|[0-9]+\.[0-9]+\.[0-9]+")


class VersionNotSetError(RuntimeError):
    """The job's Claude Code version is missing, the placeholder, or not a value
    the Claude Code bootstrap script accepts."""


def check_version_set(version: str | None) -> None:
    """Raise `VersionNotSetError` unless `version` (the agent's `kwargs.version`)
    is `stable`, `latest` or a version number X.Y.Z.

    Harbor passes the version verbatim to the Claude Code bootstrap script,
    which accepts only those values.
    """
    if version and VALID_VERSION.fullmatch(version):
        return
    if not version or version == VERSION_PLACEHOLDER:
        found = "the placeholder" if version else "no version"
        fix = f"Replace `{VERSION_PLACEHOLDER}` with a version"
    else:
        found = repr(version)
        fix = "Use `stable`, `latest` or a version number such as 2.1.308"
    raise VersionNotSetError(
        f"The job's Claude Code version (kwargs.version) is {found}, not a "
        f'version number. {fix}: see README.md, "Set the Claude Code version first".'
    )


class InstrumentBlockedError(RuntimeError):
    """The variant's settings would stop the instrument hooks."""


def check_hooks_not_blocked(variant: dict[str, Any]) -> None:
    """Raise `InstrumentBlockedError` if a key in the variant's settings stops the instrument hooks.

    `disableAllHooks` turns off every hook. `allowManagedHooksOnly` keeps only
    managed-policy hooks, so hooks from `--settings` never fire.
    """
    for key in BLOCKING_KEYS:
        if variant.get(key):
            raise InstrumentBlockedError(
                f"The variant's settings set `{key}`, which stops the instrument "
                "hooks. Remove it from the variant's settings."
            )


def merge_instrument_hooks(variant: dict[str, Any]) -> dict[str, Any]:
    """The variant's settings with the instrument hooks added after its own hooks.

    A pure function: `variant` is not changed. Each instrument hook matches
    every tool (`*`), runs synchronously, and has a 10 s timeout.
    """
    merged = copy.deepcopy(variant)
    hooks = merged.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        hooks.setdefault(event, []).append({
            "matcher": "*",
            "hooks": [{"type": "command", "command": HOOK_COMMAND, "timeout": 10}],
        })
    return merged


class InstrumentedClaudeCode(ClaudeCode):
    def __init__(self, *args, allow_web: bool = False, **kwargs):
        # ADR 0003: the web tools are disallowed unless the job sets
        # `kwargs.allow_web: true`, because the task packs' solutions are on
        # the web. Harbor's `disable_web_search` passes `--disallowedTools`,
        # which removes the tools even under `bypassPermissions`.
        kwargs["disable_web_search"] = not allow_web
        super().__init__(*args, **kwargs)

    async def setup(self, environment: BaseEnvironment) -> None:
        # `self._base_settings` is the job's `kwargs.config` (the variant's
        # settings). `run()` uploads `_base_settings` and passes `--settings`
        # only when `_config` is not None. The trial lock was written from the
        # job config before this, so `kwargs.config` there stays the variant's.
        # The version check is the backstop for a direct `harbor run`; `assay
        # run` makes the same check before Harbor starts.
        check_version_set(self._version)
        check_hooks_not_blocked(self._base_settings)
        merged = merge_instrument_hooks(self._base_settings)
        self._config = merged
        self._base_settings = merged

        await super().setup(environment)
        await self._upload_instruments(environment)
        # The seed fire: the first snapshot, the seed repository, before the
        # agent starts. It runs as the agent user, like the later hook fires.
        await self.exec_as_agent(environment, f"{HOOK_COMMAND} seed")
        await self._write_instruments_json(environment, merged)

    async def _write_instruments_json(
        self, environment: BaseEnvironment, settings: dict[str, Any]
    ) -> None:
        record = {
            "digest": instruments_digest(INSTRUMENTS_DIR),
            "settings": settings,
            "harbor_version": importlib.metadata.version("harbor"),
        }
        await self.exec_as_agent(environment, f"mkdir -p {TRACE_DIR}")
        with tempfile.TemporaryDirectory(prefix="assay-instruments-json-") as temp:
            local = Path(temp) / "instruments.json"
            local.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
            await environment.upload_file(local, f"{TRACE_DIR}/instruments.json")

    async def _upload_instruments(self, environment: BaseEnvironment) -> None:
        await self.exec_as_root(environment, f"rm -rf {REMOTE_DIR} && mkdir -p {REMOTE_DIR}")
        with tempfile.TemporaryDirectory(prefix="assay-instruments-") as temp:
            staged = Path(temp) / "instruments"
            shutil.copytree(INSTRUMENTS_DIR, staged,
                            ignore=shutil.ignore_patterns(*EXCLUDED_DIRS))
            await environment.upload_dir(staged, REMOTE_DIR)
        # File modes after an upload depend on the host, so set them here.
        await self.exec_as_root(
            environment, f"chmod -R a+rX {REMOTE_DIR} && chmod a+x {REMOTE_DIR}jq"
        )
