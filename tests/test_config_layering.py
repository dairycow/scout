"""Config precedence via boot: plugin defaults < user toml < project toml < env < CLI."""

import os

import pytest

from scout.errors import ScoutError
from scout.host import boot

FAKE = '''
class FakeClient:
    def __init__(self, cfg):
        self.cfg = cfg
    def complete(self, system, messages, tools, on_text=None, on_usage=None):
        return {"role": "assistant", "content": [{"type": "text", "text": "ok"}]}

def scout(api):
    api.provider("fake", lambda cfg: FakeClient(cfg))
    api.config({"provider": "fake", "flavor": "from-plugin"})
'''


def write_plugin(directory, name, source):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(source)


@pytest.fixture
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    home.mkdir()
    proj.mkdir()
    monkeypatch.setenv("HOME", str(home))
    for key in [k for k in os.environ if k.startswith("SCOUT_") or k.endswith("_API_KEY")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(proj)
    write_plugin(home / ".agents" / "plugins", "fake.py", FAKE)
    return home, proj


def user_toml(home, text):
    path = home / ".config" / "scout"
    path.mkdir(parents=True)
    (path / "scout.toml").write_text(text)


def test_defaults(env):
    home, proj = env
    rt = boot(proj, {})
    assert rt.config["provider"] == "fake"
    assert rt.config["model"] == "claude-sonnet-4-5"
    assert rt.config["max_tokens"] == 16384
    assert rt.config["max_turns"] == 40
    assert rt.config["timeout"] == 300
    assert rt.config["flavor"] == "from-plugin"
    assert rt.config["api_key"] == ""
    assert rt.config["base_url"] == ""


def test_user_toml_overrides_defaults(env):
    home, proj = env
    user_toml(home, 'model = "from-user"\nmax_tokens = 100\nflavor = "from-user"\n')
    rt = boot(proj, {})
    assert rt.config["model"] == "from-user"
    assert rt.config["max_tokens"] == 100
    assert rt.config["flavor"] == "from-user"
    assert rt.config["provider"] == "fake"


def test_project_toml_overrides_user(env):
    home, proj = env
    user_toml(home, 'model = "from-user"\nmax_tokens = 100\nflavor = "from-user"\n')
    (proj / "scout.toml").write_text('model = "from-project"\nflavor = "from-project"\n')
    rt = boot(proj, {})
    assert rt.config["model"] == "from-project"
    assert rt.config["max_tokens"] == 100
    assert rt.config["flavor"] == "from-project"


def test_env_overrides_toml(env, monkeypatch):
    home, proj = env
    user_toml(home, 'model = "from-user"\n')
    (proj / "scout.toml").write_text('model = "from-project"\nflavor = "from-project"\n')
    monkeypatch.setenv("SCOUT_MODEL", "from-env")
    monkeypatch.setenv("SCOUT_FLAVOR", "from-env")
    rt = boot(proj, {})
    assert rt.config["model"] == "from-env"
    assert rt.config["flavor"] == "from-env"


def test_cli_overrides_env(env, monkeypatch):
    home, proj = env
    (proj / "scout.toml").write_text('model = "from-project"\n')
    monkeypatch.setenv("SCOUT_MODEL", "from-env")
    monkeypatch.setenv("SCOUT_FLAVOR", "from-env")
    rt = boot(proj, {"model": "from-cli", "flavor": "from-cli"})
    assert rt.config["model"] == "from-cli"
    assert rt.config["flavor"] == "from-cli"


def test_env_int_coercion_max_tokens(env, monkeypatch):
    home, proj = env
    monkeypatch.setenv("SCOUT_MAX_TOKENS", "999")
    rt = boot(proj, {})
    assert rt.config["max_tokens"] == 999
    assert type(rt.config["max_tokens"]) is int

    monkeypatch.setenv("SCOUT_MAX_TOKENS", "nope")
    with pytest.raises(ScoutError, match="integer"):
        boot(proj, {})


def test_cli_int_overrides_env(env, monkeypatch):
    home, proj = env
    monkeypatch.setenv("SCOUT_MAX_TOKENS", "999")
    rt = boot(proj, {"max_tokens": 12})
    assert rt.config["max_tokens"] == 12


def test_unknown_toml_keys_ignored(env):
    home, proj = env
    user_toml(home, 'model = "from-user"\nunknown_key = "nope"\n')
    (proj / "scout.toml").write_text('also_unknown = 1\nflavor = "from-project"\n')
    rt = boot(proj, {})
    assert "unknown_key" not in rt.config
    assert "also_unknown" not in rt.config
    assert rt.config["model"] == "from-user"
    assert rt.config["flavor"] == "from-project"
