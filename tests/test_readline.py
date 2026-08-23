"""Readline plugin: tty gate, guarded import, explicit word-jump binds."""

import sys
import types

from scout.builtin import MANIFEST
from scout.builtin import readline as readline_plugin


class FakeReadline(types.ModuleType):
    def __init__(self, doc="GNU readline library"):
        super().__init__("readline", doc)
        self.binds = []

    def parse_and_bind(self, line):
        self.binds.append(line)


def test_manifest_includes_readline():
    assert "readline" in MANIFEST


def test_binds_word_jumps_on_tty(monkeypatch):
    fake = FakeReadline()
    monkeypatch.setitem(sys.modules, "readline", fake)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    readline_plugin.scout(None)
    assert '"\\e[1;5D": backward-word' in fake.binds
    assert '"\\e[1;5C": forward-word' in fake.binds
    assert '"\\e[5D": backward-word' in fake.binds
    assert '"\\e[5C": forward-word' in fake.binds


def test_noop_when_stdin_not_a_tty(monkeypatch):
    fake = FakeReadline()
    monkeypatch.setitem(sys.modules, "readline", fake)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False)
    readline_plugin.scout(None)
    assert fake.binds == []


def test_libedit_uses_bind_syntax(monkeypatch):
    fake = FakeReadline("libedit line editing emulation")
    monkeypatch.setitem(sys.modules, "readline", fake)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    readline_plugin.scout(None)
    assert "bind ^[[1;5D backward-word" in fake.binds
    assert "bind ^[OC forward-word" in fake.binds


def test_missing_readline_is_silent(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setitem(sys.modules, "readline", None)
    assert readline_plugin.scout(None) is None
