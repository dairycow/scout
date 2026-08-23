"""Topo plugin: registration, path confinement, server roundtrip, host boot."""

import importlib.util
import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from scout.host import boot
from scout.tools import Ctx

PLUGIN = Path(__file__).resolve().parent.parent / ".agents" / "plugins" / "topo.py"

FAKE = '''
class FakeClient:
    def __init__(self, cfg):
        self.cfg = cfg

    def complete(self, system, messages, tools, on_text=None):
        return {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}

def scout(api):
    api.provider("fake", lambda cfg: FakeClient(cfg))
'''


class FakeApi:
    def __init__(self):
        self.tools, self.commands, self.prompts = {}, {}, []
        self.events, self.handlers = [], {}

    def tool(self, tool): self.tools[tool.name] = tool
    def on(self, event, fn): self.handlers.setdefault(event, []).append(fn)
    def prompt(self, text): self.prompts.append(text)
    def command(self, name, fn): self.commands[name] = fn
    def emit(self, type, **data): self.events.append((type, data))


def load_topo():
    spec = importlib.util.spec_from_file_location("topo_under_test", PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def topo(tmp_path, monkeypatch):
    module = load_topo()
    opened = []
    monkeypatch.setattr(module, "_open_browser", lambda url: opened.append(url) or True)
    yield module, opened
    module.stop_servers()


@pytest.fixture
def ctx(tmp_path):
    return Ctx(cwd=tmp_path, config={}, skills={})


def http(method, url, body=None, headers=None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_registers_tools_command_no_prompt(topo):
    module, _ = topo
    api = FakeApi()
    module.scout(api)
    assert set(api.tools) == {"topo_write", "topo_open", "topo_feedback"}
    assert "/topo" in api.commands
    assert api.prompts == []  # guidance lives in the 'topo' skill, not the prompt
    assert "topo' skill" in api.tools["topo_write"].description
    assert "topo.feedback" in api.handlers


def test_write_resolves_and_confines(topo, ctx, tmp_path):
    module, _ = topo
    out = module._write_tool(
        {"path": "auth-rollout", "html": "<html><body><h1 id=t>x</h1></body></html>"}, ctx)
    assert (tmp_path / "docs" / "plans" / "auth-rollout.html").is_file()
    assert "wrote" in out
    module._write_tool({"path": "docs/plans/auth-rollout.html", "html": "<p>again</p>"}, ctx)
    for bad in ("../../etc/passwd", "..", "/etc/passwd", "a/../../b", ""):
        with pytest.raises(ValueError):
            module._write_tool({"path": bad, "html": "<p>x</p>"}, ctx)
    with pytest.raises(ValueError):
        module._write_tool({"path": "ok", "html": "plain text, no tags"}, ctx)


def test_open_serves_injected_artifact_and_feedback_roundtrip(topo, ctx, tmp_path):
    module, opened = topo
    module._write_tool(
        {"path": "feat", "html": "<html><body><h1 id=t>Title</h1></body></html>"}, ctx)
    out = module._open_tool({"path": "feat"}, ctx)
    assert opened and "topo_feedback" in out

    status, body = http("GET", opened[0])
    assert status == 200
    assert '<script src="/__topo.js" defer></script>' in body
    assert "Title" in body

    base = f"http://127.0.0.1:{module.ensure_server(tmp_path)['port']}"
    status, js = http("GET", f"{base}/__topo.js")
    assert status == 200 and "__feedback" in js

    status, data = http("GET", f"{base}/__poll?path=feat.html")
    assert status == 200 and json.loads(data)["mtime"] > 0

    payload = json.dumps({"path": "feat.html", "items": [
        {"target": {"tag": "h1", "id": "t", "text": "Title"}, "text": "retitle this"},
        {"target": {"tag": "p"}, "text": "unclear"}]}).encode()
    status, data = http("POST", f"{base}/__feedback", payload,
                        {"Content-Type": "application/json"})
    assert status == 200 and json.loads(data) == {"ok": True}

    drained = module._feedback_tool({"path": "feat"}, ctx)
    assert "2 comments" in drained and "retitle this" in drained and "unclear" in drained
    assert "h1#t" in drained
    assert module._feedback_tool({"path": "feat"}, ctx).startswith("No feedback")

    store = tmp_path / ".scout" / "plans" / "feat.json"
    assert json.loads(store.read_text()) == []


def test_server_guards(topo, ctx, tmp_path):
    module, _ = topo
    module._write_tool({"path": "x", "html": "<html><body>x</body></html>"}, ctx)
    module._open_tool({"path": "x"}, ctx)
    base = f"http://127.0.0.1:{module.ensure_server(tmp_path)['port']}"

    assert http("GET", f"{base}/plans/nope.html")[0] == 404
    assert http("GET", f"{base}/plans/../../../etc/passwd")[0] == 404
    assert http("GET", f"{base}/plans/..%2F..%2Fetc%2Fpasswd")[0] == 404
    assert http("GET", base, headers={"Host": "evil.example"})[0] == 403

    status, body = http("GET", f"{base}/")
    assert status == 200 and "x.html" in body

    bad = json.dumps({"path": "../../x", "items": [{"text": "a"}]}).encode()
    assert http("POST", f"{base}/__feedback", bad,
                {"Content-Type": "application/json"})[0] == 400


def test_post_emits_feedback_event_and_nudge_prints(topo, ctx, tmp_path, capsys):
    module, _ = topo
    api = FakeApi()
    module.scout(api)
    module._write_tool({"path": "feat", "html": "<html><body><h1 id=t>T</h1></body></html>"}, ctx)
    module._open_tool({"path": "feat"}, ctx)
    base = f"http://127.0.0.1:{module.ensure_server(tmp_path)['port']}"

    payload = json.dumps({"path": "feat.html", "items": [
        {"target": {"tag": "p"}, "text": "x"}]}).encode()
    status, _ = http("POST", f"{base}/__feedback", payload,
                     {"Content-Type": "application/json"})
    assert status == 200
    assert api.events == [("topo.feedback", {"path": "feat.html", "count": 1})]

    api.handlers["topo.feedback"][0](path="feat.html", count=1)
    out = capsys.readouterr().out
    assert "1 comment ready on feat.html" in out and "topo_feedback" in out
    api.handlers["topo.feedback"][0](path="feat.html", count=2)
    assert "2 comments ready" in capsys.readouterr().out


def test_fixed_port_with_fallback(tmp_path):
    import socket

    module = load_topo()
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # ignore TIME_WAIT, like the server
    try:
        sock.bind(("127.0.0.1", module.DEFAULT_PORT))
    except OSError:
        pytest.skip(f"port {module.DEFAULT_PORT} not free on this host")
    try:
        sock.listen(1)
        a = tmp_path / "a"
        a.mkdir()
        assert module.ensure_server(a)["port"] != module.DEFAULT_PORT
    finally:
        sock.close()
    module.stop_servers()
    b = tmp_path / "b"
    b.mkdir()
    try:
        assert module.ensure_server(b)["port"] == module.DEFAULT_PORT
    finally:
        module.stop_servers()


def test_topo_command(topo, ctx, tmp_path, capsys):
    module, opened = topo

    class Dummy:
        pass
    agent = Dummy()
    agent.ctx = ctx

    module.topo_cmd(agent, "")
    assert "no artifacts" in capsys.readouterr().out
    assert not opened

    module._write_tool({"path": "latest", "html": "<html><body>a</body></html>"}, ctx)
    module.topo_cmd(agent, "")
    assert opened and opened[0].endswith("/plans/latest.html")

    module.topo_cmd(agent, "latest")
    assert opened[-1].endswith("/plans/latest.html")
    module.topo_cmd(agent, "../../escape")
    assert "bad artifact path" in capsys.readouterr().out


def test_plugin_boots_through_host(tmp_path, monkeypatch):
    home = tmp_path / "home"
    cwd = tmp_path / "proj"
    home.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("HOME", str(home))
    import os
    for key in [k for k in os.environ if k.startswith("SCOUT_") or k.endswith("_API_KEY")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(cwd)

    plugins = cwd / ".agents" / "plugins"
    plugins.mkdir(parents=True)
    shutil.copy(PLUGIN, plugins / "topo.py")
    (plugins / "fake.py").write_text(FAKE)

    rt = boot(cwd, {"prompt": None, "resume": False, "provider": "fake"})
    assert {"topo_write", "topo_open", "topo_feedback"} <= set(rt.registry.tools)
    assert "/topo" in rt.commands
    assert rt.prompts == []
    assert "topo" in rt.plugins


def test_skill_shipped_and_discoverable():
    from scout.builtin.skills import load_skills

    skills = load_skills(PLUGIN.parent.parent.parent)  # worktree root
    assert "topo" in skills
    skill = skills["topo"]
    assert skill.description.strip()
    assert "topo_write" in skill.body and "mermaid" in skill.body
