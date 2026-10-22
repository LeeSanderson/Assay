"""The instruments digest (PRD section 5, "How the hook gets into the container").

A content hash over the files of `instruments/`, in sorted path order.
`InstrumentedClaudeCode` writes it to `instruments.json`; the trace check
computes it again over the committed `instruments/` and compares the two.

This module uses only the standard library, so the analyzer can import it
without Harbor.
"""

import hashlib
from pathlib import Path

# Python writes these when it imports the agent class; they are not instruments.
EXCLUDED_DIRS = frozenset({"__pycache__"})


def instrument_files(folder: Path | str) -> list[str]:
    """The files of the instruments folder, as sorted POSIX paths relative to it."""
    root = Path(folder)
    return sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and not EXCLUDED_DIRS.intersection(path.relative_to(root).parts[:-1])
    )


def instruments_digest(folder: Path | str) -> str:
    """`sha256:<hex>` over each file's relative path and content hash.

    The digest changes when any file is added, removed, renamed, or changed.
    It does not depend on where the folder is, on file modes, or on times.
    """
    root = Path(folder)
    outer = hashlib.sha256()
    for rel in instrument_files(root):
        content = hashlib.sha256((root / rel).read_bytes()).hexdigest()
        outer.update(f"{rel}\0{content}\n".encode("utf-8"))
    return f"sha256:{outer.hexdigest()}"
