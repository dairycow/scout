"""GNU readline bindings for the interactive prompt.

input() only line-edits if readline is imported first, and terminfo
(notably under tmux) often lacks kLFT5/kRIT5, so Ctrl+Left and
Ctrl+Right are bound explicitly. Skipped when stdin is not a tty.

libedit (uv-managed Pythons, macOS) uses `bind ^[... cmd` syntax and
its own command names — no backward-word/forward-word — so each
sequence carries a GNU and a libedit command.
"""

import sys

ESC = "\\e"
SEQUENCES = [
    ("\\e[1;5D", "backward-word", "ed-prev-word"),
    ("\\e[1;5C", "forward-word", "em-next-word"),
    ("\\e[5D", "backward-word", "ed-prev-word"),
    ("\\e[5C", "forward-word", "em-next-word"),
    ("\\eOD", "backward-word", "ed-prev-word"),
    ("\\eOC", "forward-word", "em-next-word"),
]


def scout(api) -> None:
    if not (sys.stdin and sys.stdin.isatty()):
        return
    try:
        import readline
    except ImportError:
        return
    libedit = "libedit" in (readline.__doc__ or "")
    for seq, gnu, bsd in SEQUENCES:
        if libedit:
            readline.parse_and_bind("bind " + seq.replace(ESC, "^[") + " " + bsd)
        else:
            readline.parse_and_bind('"' + seq + '": ' + gnu)
