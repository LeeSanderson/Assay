#!/bin/bash
# Probe (wayfinder ticket 57): a content digest of a directory tree.
# One line per entry: type, mode and path for every entry, the link target for
# a symlink, and sha256sum's line for every regular file. The lines are sorted
# bytewise and hashed. Times, owners and the image digest play no part.
# Usage: tree-hash.sh <dir>   (prints the digest and the entry count)
set -euo pipefail
cd "$1"
lines=$({
    find . -mindepth 1 -printf '%y %m %p %l\n'
    find . -type f -print0 | xargs -0 -r sha256sum
} | LC_ALL=C sort)
echo "$(printf '%s\n' "$lines" | sha256sum | cut -d' ' -f1) $(find . -mindepth 1 | wc -l)"
