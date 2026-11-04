"""The content digests of Assay: one `sha256:<hex>` form for files and JSON
values (the resume digests, the condition digest, the code digest), and the
short hash of a task pack's image tag.

This module uses only the standard library: it is in the import closure, and
so in the code digest, of every built-in evaluation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

PREFIX = "sha256:"


def content_hash(data: bytes) -> str:
    """The hex sha256 of the bytes."""
    return hashlib.sha256(data).hexdigest()


def files_digest(files: Iterable[tuple[str, Path]], extra: Iterable[bytes] = ()) -> str:
    """`sha256:<hex>` over each (name, file): a line of the name and the hash
    of the file's content, in the order given; then each `extra` line."""
    outer = hashlib.sha256()
    for name, file in files:
        outer.update(f"{name}\0{content_hash(file.read_bytes())}\n".encode("utf-8"))
    for line in extra:
        outer.update(line)
    return PREFIX + outer.hexdigest()


def folder_digest(folder: Path) -> str:
    """`sha256:<hex>` over each file of the folder, by its relative path and
    content; the digest of no files when there is no such folder."""
    files = sorted(f for f in folder.rglob("*") if f.is_file()) if folder.is_dir() else []
    return files_digest((f.relative_to(folder).as_posix(), f) for f in files)


def json_digest(value: Any) -> str:
    """`sha256:<hex>` over the compact JSON of the value, with sorted keys."""
    text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return PREFIX + content_hash(text.encode("utf-8"))


def image_tag_hash(root: Path, folders: Iterable[str]) -> str:
    """16 hex digits over each file of the folders of `root`: its path from
    `root` and its content. The tag of a built image holds it, so its form
    stays as it is, or every cached image is built again."""
    digest = hashlib.sha256()
    for folder in folders:
        for path in sorted((root / folder).rglob("*")):
            if path.is_file():
                digest.update(path.relative_to(root).as_posix().encode() + b"\0")
                digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()[:16]
