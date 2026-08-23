"""GNU readline bindings for the interactive prompt.

input() only line-edits if readline is imported first, and terminfo
(notably under tmux) often lacks kLFT5/kRIT5, so Ctrl+Left and
Ctrl+Right are bound explicitly. Skipped when stdin is not a tty.
"""

import sys

SEQUENCES = [
    ("\\e[1;5D", "backward-word"),
    ("\\e[1;5C", "forward-word"),
    ("\\e[5D", "backward-word"),
    ("\\e[5C", "forward-word"),
    ("\\eOD", "backward-word"),
    ("\\eOC", "forward-word"),
]


def scout(api) -> None:
    if not (sys.stdin and sys.stdin.isatty()):
        return
    try:
        import readline
    except ImportError:
        return
    libedit = "libedit" in (readline.__doc__ or "")
    ESC = "\\e"
    for seq, cmd in SEQUENCES:
        if libedit:
            readline.parse_and_bind("bind " + seq.replace(ESC, "^[") + " " + cmd)
        else:
            readline.parse_and_bind('"' + seq + '": ' + cmd)
