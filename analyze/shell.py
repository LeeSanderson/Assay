"""Reading Bash commands: their simple commands, and the files they write.

written_paths is a heuristic. It finds the targets of > and >> and the files
of tee. Heredoc bodies are dropped first, so the => of an arrow function in a
heredoc is not a redirection. A file written any other way (node -e,
python -c, cp) is missed.
"""

from __future__ import annotations

import re
import shlex

# <<EOF, <<'EOF', <<"EOF" and <<-EOF; the body runs to a line that is the word.
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# > or >> not part of =>, ->, >=, 2>&1 or a process substitution >(...).
_REDIRECT = re.compile(r"(?<![=\->&])>>?(?![&=(])\s*([^\s;&|<>()]+)")
_PUNCTUATION = "();<>|&\n"
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_TEE = re.compile(r"\btee\s+((?:-\S+\s+)*)([^\s;&|<>()]+)")


def without_heredoc_bodies(command: str) -> str:
    """The command with the body lines of each heredoc removed."""
    lines = command.split("\n")
    out: list[str] = []
    ends: list[str] = []  # the words that end the open heredocs, in order
    for line in lines:
        if ends:
            if line.strip() == ends[0]:
                ends.pop(0)
            continue
        out.append(line)
        ends.extend(m[2] for m in _HEREDOC.finditer(line))
    return "\n".join(out)


def written_paths(command: str) -> list[str]:
    """The files a Bash command writes by redirection or tee, in command order."""
    text = without_heredoc_bodies(command)
    found = [(m.start(), m[1]) for m in _REDIRECT.finditer(text)]
    found += [(m.start(), m[2]) for m in _TEE.finditer(text)]
    paths = []
    for _, raw in sorted(found):
        try:
            words = shlex.split(raw)
        except ValueError:
            words = [raw]
        if words and words[0] not in ("/dev/null", "/dev/stdout", "/dev/stderr"):
            paths.append(words[0])
    return paths


def simple_commands(command: str) -> list[list[str]]:
    """The words of each simple command, split at ;, &&, ||, |, & and new lines;
    redirections and their targets are dropped."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:  # unbalanced quotes
        tokens = command.split()
    commands: list[list[str]] = [[]]
    redirect = False
    for token in tokens:
        if redirect:
            redirect = False  # the redirection's target
        elif token and all(c in _PUNCTUATION for c in token):
            if "<" in token or ">" in token:
                redirect = True  # the next word is the target: the file, or the 1 of 2>&1
                if commands[-1] and commands[-1][-1].isdigit():
                    commands[-1].pop()  # the 2 of 2>file
            else:
                commands.append([])
        else:
            commands[-1].append(token)
    return [c for c in commands if c]


def without_prefixes(words: list[str]) -> list[str]:
    """Drops VAR=value assignments and the wrappers time and timeout <duration>."""
    while words:
        if _ASSIGNMENT.match(words[0]) or words[0] == "time":
            words = words[1:]
        elif words[0] == "timeout":
            rest = words[1:]
            while rest and rest[0].startswith("-"):
                rest = rest[1:]
            words = rest[1:]  # the duration
        else:
            break
    return words
