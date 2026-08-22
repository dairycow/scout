"""Tests for the open-vocabulary event bus."""

from scout.bus import Bus


def test_subscription_order():
    bus = Bus()
    seen = []
    bus.on("a.b", lambda: seen.append(1))
    bus.on("a.b", lambda: seen.append(2))
    bus.emit("a.b")
    assert seen == [1, 2]


def test_open_names_accepted():
    bus = Bus()
    seen = []
    bus.on("deploy.finished", lambda ok: seen.append(ok))
    bus.emit("deploy.finished", ok=True)
    bus.emit("invented.event")  # no subscribers; must not raise
    assert seen == [True]


def test_wildcard_sees_everything_with_type():
    bus = Bus()
    seen = []
    bus.on("*", lambda type, **data: seen.append((type, data)))
    bus.on("x.y", lambda **data: seen.append(("specific", data)))
    bus.emit("x.y", n=1)
    bus.emit("z.z", n=2)
    assert seen == [
        ("specific", {"n": 1}),
        ("x.y", {"n": 1}),
        ("z.z", {"n": 2}),
    ]


def test_bus_error_isolation(capsys):
    bus = Bus()
    seen = []

    def boom(**_):
        raise RuntimeError("nope")

    bus.on("t", boom)
    bus.on("t", lambda **kw: seen.append("ok"))
    bus.on("*", lambda **kw: seen.append("wild"))
    bus.emit("t", x=1)  # must not raise
    assert seen == ["ok", "wild"]
    assert "scout: t subscriber failed: nope" in capsys.readouterr().err
