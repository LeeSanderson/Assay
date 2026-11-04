"""The evaluation contract (PRD v3 section 9; issue #64).

An evaluation module exposes one value:

    EVALUATION = Evaluation(name, evaluate, depends_on=(), needs=(), pins=..., online=False)

`evaluate(TrialInput)` gets one trial and returns a JSON value; a raised
exception gives an error result. `depends_on` names the evaluations whose
values it reads from `deps` (hard dependencies only). `needs` names the
optional parts of the trial record it needs (OPTIONAL_PARTS); the plan
refuses it when the reader of some harness in the experiment does not give
one. `pins` gives the pinned external inputs that are not files of this
repository. `online=True` exists, and Assay refuses it in this slice.

An evaluation starts containers only through `TrialInput.containers`. The
network of `run` is `none` (the default), `internal` or `online`; `online`
is refused for an evaluation that does not declare `online=True`.
`Containers.service` is deferred.

This module imports nothing of the repository at load time: it is in the
import closure, and so in the code digest, of every evaluation.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, NamedTuple, Protocol

Json = Any  # a value json.dumps accepts
Network = Literal["none", "internal", "online"]
NETWORKS = ("none", "internal", "online")

# The optional parts of the trial record (PRD v3 section 8, "The record"):
# a reader gives each one or marks it absent.
OPTIONAL_PARTS = ("result", "error_flag", "exit_code", "call_duration", "step_cost")


class RunResult(NamedTuple):
    exit_code: int | None  # None on a timeout
    stdout: str
    stderr: str


class ContainerError(Exception):
    """A container could not be built or started."""


class Containers(Protocol):
    """The one way an evaluation starts containers."""

    def pack_image(self, task_pack: Path) -> str:
        """The task pack's image, built from its Dockerfile, ready to run."""
        ...

    def run(self, image: str, command: Sequence[str], *, mounts: Mapping[Path, str] = {},
            network: Network = "none", timeout: float | None = None) -> RunResult:
        """Runs the command in a fresh container from the image and removes it.

        `mounts` maps a host folder to its path in the container; a path that
        ends in `:ro` is read-only. On a timeout the container is removed and
        the exit code is None."""
        ...


class OnlineRefused(Exception):
    """An evaluation that is not declared online asked for the online network."""


@dataclass(frozen=True)
class GuardedContainers:
    """The containers an evaluation gets: `network="online"` only when it is
    declared online."""

    inner: Containers
    evaluation: str
    online: bool = False

    def pack_image(self, task_pack: Path) -> str:
        return self.inner.pack_image(task_pack)

    def run(self, image: str, command: Sequence[str], *, mounts: Mapping[Path, str] = {},
            network: Network = "none", timeout: float | None = None) -> RunResult:
        if network not in NETWORKS:
            raise ValueError(f"network {network!r} is not one of {', '.join(NETWORKS)}")
        if network == "online" and not self.online:
            raise OnlineRefused(f"evaluation {self.evaluation} is not declared online=True, "
                                f"so it cannot run a container with the online network")
        return self.inner.run(image, command, mounts=mounts, network=network, timeout=timeout)


@dataclass(frozen=True)
class TrialInput:
    """Everything an evaluation gets for one trial. Read-only except `out`."""

    job: str
    trial: str
    cell: Any  # assay.experiment.Cell; None outside an experiment
    task_pack: Path  # tasks/<language>/<slug>
    record: Any  # analyze.trial.Trial: the trial record
    deps: Mapping[str, Json]  # the value of each evaluation in depends_on
    options: Mapping[str, Json]  # [evaluation-options.<name>] of experiment.toml
    out: Path  # an empty folder for the evaluation's own files
    containers: Containers
    scratch: Path | None = field(default=None, repr=False)  # where checkouts go

    def checkout(self, commit: str) -> Path:
        """A clone of the trial's repository history, with the commit checked out."""
        root = self.scratch or Path(tempfile.mkdtemp(prefix="assay-checkout-"))
        target = root / f"checkout-{commit[:12]}"
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        git = ["git", "-c", "safe.directory=*", "-c", "core.autocrlf=false"]
        subprocess.run([*git, "clone", "-q", "--no-checkout", str(self.record.trace_git),
                        str(target)], capture_output=True, check=True)
        subprocess.run([*git, "-C", str(target), "checkout", "-q", commit],
                       capture_output=True, check=True)
        return target

    def seed(self) -> Path:
        """The checkout of the seed snapshot."""
        seeds = [line for line in self.record.trace if line.commit]
        if not seeds:
            raise ValueError(f"{self.trial}: the trace has no snapshots")
        return self.checkout(seeds[0].commit)

    def final(self) -> Path:
        """The checkout of the last snapshot."""
        head = self.record.head_commit()
        if not head:
            raise ValueError(f"{self.trial}: the trace has no snapshots")
        return self.checkout(head)


def no_pins(_: TrialInput) -> Mapping[str, str]:
    return {}


@dataclass(frozen=True)
class Evaluation:
    name: str
    evaluate: Callable[[TrialInput], Json]
    depends_on: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    pins: Callable[[TrialInput], Mapping[str, str]] = no_pins
    online: bool = False
