"""The real `Containers` (assay/evaluation.py): Docker on the host.

Harbor deletes each trial's task image, so `pack_image` builds it again from
the pack's Dockerfile (whose base image is pinned by digest) and adds the
pack's tests/ at /tests, where Harbor uploads them for the verifier. A built
image is kept and reused, tagged by a hash of the pack's environment/ and
tests/ folders.
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path

from assay.digests import image_tag_hash
from assay.evaluation import ContainerError, Network, RunResult

INTERNAL_NETWORK = "assay-internal"  # a Docker network with no route out
DOCKER_NETWORKS = {"none": "none", "internal": INTERNAL_NETWORK, "online": "bridge"}


class DockerContainers:
    def pack_image(self, task_pack: Path) -> str:
        pack = Path(task_pack)
        name = f"{pack.parent.name}-{pack.name}:{image_tag_hash(pack, ('environment', 'tests'))}"
        tag = f"assay-replay-{name}"
        found = _docker("image", "inspect", "--format", "{{.Id}}", tag)
        if found.returncode == 0:
            return found.stdout.strip()
        task_tag = f"assay-task-{name}"
        task = _docker("build", "-q", "-t", task_tag, str(pack / "environment"), timeout=3600)
        if task.returncode != 0:
            raise ContainerError(f"docker build of {pack / 'environment'} failed: {task.stderr}")
        dockerfile = f"FROM {task_tag}\nCOPY tests/ /tests/\n"
        image = _docker("build", "-q", "-t", tag, "-f", "-", str(pack),
                        input=dockerfile, timeout=600)
        if image.returncode != 0:
            raise ContainerError(f"docker build of the pack image failed: {image.stderr}")
        return image.stdout.strip()

    def run(self, image: str, command: Sequence[str], *, mounts: Mapping[Path, str] = {},
            network: Network = "none", timeout: float | None = None) -> RunResult:
        if network == "internal":
            _internal_network()
        name = f"assay-eval-{uuid.uuid4().hex[:12]}"
        volumes = [arg for host, target in mounts.items()
                   for arg in ("-v", f"{Path(host).resolve()}:{target}")]
        try:
            done = _docker("run", "--rm", "--name", name, "--network", DOCKER_NETWORKS[network],
                           *volumes, image, *command, timeout=timeout)
        except subprocess.TimeoutExpired:
            _docker("rm", "-f", name)
            return RunResult(None, "", "")
        return RunResult(done.returncode, done.stdout, done.stderr)


def _internal_network() -> None:
    if _docker("network", "inspect", INTERNAL_NETWORK).returncode != 0:
        _docker("network", "create", "--internal", INTERNAL_NETWORK)


def _docker(*args: str, input: str | None = None, timeout: float | None = 120):
    return subprocess.run(["docker", *args], capture_output=True, text=True,
                          input=input, timeout=timeout)

