"""The instruments digest: a content hash over the files of `instruments/`.

`instruments.json` records it, and the trace check compares it with the
digest of the committed `instruments/`.
"""

import shutil
from pathlib import Path

from instruments.digest import instruments_digest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _folder(root: Path) -> Path:
    folder = root / "instruments"
    (folder / "sub").mkdir(parents=True)
    (folder / "trace.sh").write_bytes(b"echo trace\n")
    (folder / "jq").write_bytes(b"\x7fELF\x00binary")
    (folder / "sub" / "agent.py").write_bytes(b"class A: pass\n")
    return folder


def test_digest_is_a_sha256_value(tmp_path):
    digest = instruments_digest(_folder(tmp_path))
    assert digest.startswith("sha256:")
    assert len(digest) == len("sha256:") + 64


def test_digest_is_the_same_for_the_same_content(tmp_path):
    a = _folder(tmp_path / "a")
    b = _folder(tmp_path / "b")
    assert instruments_digest(a) == instruments_digest(a)
    assert instruments_digest(a) == instruments_digest(b)


def test_digest_changes_when_a_file_changes(tmp_path):
    folder = _folder(tmp_path)
    before = instruments_digest(folder)
    (folder / "trace.sh").write_bytes(b"echo trace changed\n")
    assert instruments_digest(folder) != before


def test_digest_changes_when_a_file_is_added(tmp_path):
    folder = _folder(tmp_path)
    before = instruments_digest(folder)
    (folder / "new.txt").write_bytes(b"")
    assert instruments_digest(folder) != before


def test_digest_changes_when_a_file_is_renamed(tmp_path):
    folder = _folder(tmp_path)
    before = instruments_digest(folder)
    (folder / "trace.sh").rename(folder / "trace2.sh")
    assert instruments_digest(folder) != before


def test_digest_changes_when_content_moves_between_files(tmp_path):
    folder = tmp_path / "x"
    folder.mkdir()
    (folder / "a").write_bytes(b"ab")
    (folder / "b").write_bytes(b"")
    before = instruments_digest(folder)
    (folder / "a").write_bytes(b"a")
    (folder / "b").write_bytes(b"b")
    assert instruments_digest(folder) != before


def test_digest_leaves_out_pycache(tmp_path):
    folder = _folder(tmp_path)
    before = instruments_digest(folder)
    (folder / "__pycache__").mkdir()
    (folder / "__pycache__" / "agent.cpython-312.pyc").write_bytes(b"\x00")
    (folder / "sub" / "__pycache__").mkdir()
    (folder / "sub" / "__pycache__" / "x.pyc").write_bytes(b"\x00")
    assert instruments_digest(folder) == before


def test_digest_of_the_committed_instruments_ignores_its_location(tmp_path):
    copy = tmp_path / "instruments"
    shutil.copytree(REPO_ROOT / "instruments", copy,
                    ignore=shutil.ignore_patterns("__pycache__"))
    assert instruments_digest(copy) == instruments_digest(REPO_ROOT / "instruments")
