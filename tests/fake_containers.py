"""A fake `Containers` for tests: it starts no container.

Like the real verifier, what `run` gives depends only on the snapshot that
`replay` mounts at /snapshot: it reads `fake-verifier.json` from that tree,
so a test sets the result of a snapshot by writing the file in the trial's
history (`gives`, `fails`, `times_out`). Like the real container, it writes
the verifier's log files into the folder mounted at /logs/verifier, also
when it then fails.
"""

from __future__ import annotations

import json
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

from assay.evaluation import RunResult

FAKE = "fake-verifier.json"


def gives(fields: dict, logs: dict[str, str] | None = None) -> dict[str, str]:
    return {FAKE: json.dumps({"reward": fields, "logs": logs or {}})}


def fails(exit_code: int = 125, stderr: str = "", logs: dict[str, str] | None = None
          ) -> dict[str, str]:
    return {FAKE: json.dumps({"exit_code": exit_code, "stderr": stderr, "logs": logs or {}})}


def times_out(logs: dict[str, str] | None = None) -> dict[str, str]:
    return {FAKE: json.dumps({"timeout": True, "logs": logs or {}})}


class FakeContainers:
    """Builds no image: the image of a pack is its folder's path."""

    def __init__(self, delay: float = 0.0):
        self.packs: list[Path] = []
        self.runs: list[dict] = []
        self.delay = delay  # seconds each run takes

    def pack_image(self, task_pack: Path) -> str:
        self.packs.append(Path(task_pack))
        return f"image-of:{Path(task_pack).as_posix()}"

    def run(self, image: str, command: Sequence[str], *, mounts: Mapping[Path, str] = {},
            network: str = "none", timeout: float | None = None) -> RunResult:
        if self.delay:
            time.sleep(self.delay)
        self.runs.append({"image": image, "command": list(command), "network": network,
                          "timeout": timeout})
        targets = {target.split(":")[0]: Path(host) for host, target in mounts.items()}
        spec = json.loads((targets["/snapshot"] / FAKE).read_text(encoding="utf-8"))
        logs = targets["/logs/verifier"]
        for name, text in spec.get("logs", {}).items():
            (logs / name).parent.mkdir(parents=True, exist_ok=True)
            (logs / name).write_text(text, encoding="utf-8")
        if spec.get("timeout"):
            return RunResult(None, "", "")
        if "exit_code" in spec:
            return RunResult(spec["exit_code"], "", spec.get("stderr", ""))
        return RunResult(0, json.dumps(spec["reward"]), "")
