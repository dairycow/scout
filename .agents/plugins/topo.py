"""Topo: review agent-written HTML plans in a browser (lavish-axi inspired).

Loop: topo_write -> topo_open (loopback server serves the artifact with an
injected review chrome; annotations and comments POST back) -> topo_feedback
drains the queue. Artifacts live in docs/plans/ (committed, like the repo's
existing architecture-plan.html); feedback state lives in .scout/plans/
(gitignored). Authoring guidance lives in the 'topo' skill, not here.
Stdlib only; works in any modern browser, Firefox included.
"""

import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from scout.tools import Ctx, Tool


# ---------------------------------------------------------------- paths

def _plans_dir(cwd: Path) -> Path:
    return cwd / "docs" / "plans"


def _resolve_artifact(cwd: Path, raw: str) -> Path:
    """docs/plans-relative path -> absolute artifact path. ValueError on escapes."""
    raw = (raw or "").strip().replace("\\", "/")
    if raw.startswith("docs/plans/"):
        raw = raw[len("docs/plans/"):]
    parts = [p for p in PurePosixPath(raw).parts if p not in (".", "")]
    if not parts or any(p == ".." for p in parts) or PurePosixPath(raw).is_absolute():
        raise ValueError(f"bad artifact path {raw!r} — use a docs/plans/-relative name")
    rel = PurePosixPath(*parts)
    if rel.suffix != ".html":
        rel = rel.with_suffix(".html")
    return _plans_dir(cwd) / rel


def _rel_under(plans: Path, abs_path: Path) -> str:
    return abs_path.resolve().relative_to(plans.resolve()).as_posix()


def _store_path(cwd: Path, artifact: Path) -> Path:
    stem = _rel_under(_plans_dir(cwd), artifact).removesuffix(".html").replace("/", "__")
    return cwd / ".scout" / "plans" / f"{stem}.json"


# ---------------------------------------------------------------- store

def _read_store(store: Path) -> list:
    try:
        data = json.loads(store.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _write_store(store: Path, entries: list) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")


def _append_feedback(cwd: Path, artifact: Path, items: list) -> None:
    store = _store_path(cwd, artifact)
    entries = _read_store(store)
    now = time.time()
    for item in items:
        entries.append({"ts": round(now, 3), "target": item.get("target") or {},
                        "text": str(item.get("text", ""))[:4000]})
    _write_store(store, entries)


# ---------------------------------------------------------------- server

CHROME_JS = r"""(function () {
  if (window.__topo) return; window.__topo = true;
  var rel = decodeURIComponent(location.pathname.replace(/^\/plans\//, ""));
  var queue = [], pendingTarget = null, annotate = false;
  var css = document.createElement("style");
  css.textContent = [
    "#__topo{position:fixed;bottom:12px;right:12px;z-index:2147483647;max-width:360px;",
    "font:12px/1.45 ui-monospace,Menlo,monospace;background:#111827;color:#e5e7eb;",
    "border:1px solid #374151;border-radius:8px;padding:10px;box-shadow:0 8px 30px rgba(0,0,0,.35)}",
    "#__topo header{display:flex;justify-content:space-between;align-items:center;gap:8px}",
    "#__topo button{font:inherit;background:#1f2937;color:#e5e7eb;border:1px solid #374151;",
    "border-radius:5px;padding:2px 8px;cursor:pointer}",
    "#__topo button:hover{background:#374151}",
    "#__topo textarea{width:100%;box-sizing:border-box;margin:6px 0;background:#0b1220;",
    "color:#e5e7eb;border:1px solid #374151;border-radius:5px;padding:4px 6px;resize:vertical}",
    "#__topo .chip{display:inline-block;margin:2px 4px 2px 0;padding:1px 6px;max-width:100%;",
    "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;background:#1f2937;",
    "border:1px solid #374151;border-radius:9px;cursor:pointer}",
    "#__topo .status{color:#9ca3af;min-height:14px}",
    "#__topo .on{background:#065f46;border-color:#059669}",
    ".__topo_hover{outline:2px solid #22d3ee !important;outline-offset:2px;cursor:crosshair}"
  ].join("");
  document.head.appendChild(css);
  var panel = document.createElement("div");
  panel.id = "__topo";
  panel.innerHTML = [
    "<header><b>topo</b>",
    "<span><button id=__topo_mode>annotate: off</button> ",
    "<button id=__topo_send>send (0)</button></span></header>",
    "<div id=__topo_chips></div>",
    "<textarea id=__topo_ta rows=2 placeholder='comment on selection…'></textarea>",
    "<div class=status id=__topo_status></div>"
  ].join("");
  document.body.appendChild(panel);
  var ta = document.getElementById("__topo_ta");
  var chips = document.getElementById("__topo_chips");
  var send = document.getElementById("__topo_send");
  var status = document.getElementById("__topo_status");
  var mode = document.getElementById("__topo_mode");

  function describe(el) {
    var t = el.closest('[id],h1,h2,h3,h4,h5,li,p,section,article,table,tr,td,th,pre,blockquote,dt,dd,img,figure');
    if (!t) t = el;
    var d = {tag: t.tagName.toLowerCase(), id: t.id || "",
             text: (t.textContent || "").trim().replace(/\s+/g, " ").slice(0, 80)};
    var s = window.getSelection();
    if (s && !s.isCollapsed && t.contains(s.anchorNode)) d.selection = String(s).trim().slice(0, 200);
    return d;
  }
  function render() {
    chips.innerHTML = "";
    queue.forEach(function (item, i) {
      var c = document.createElement("span");
      c.className = "chip";
      c.title = "remove";
      c.textContent = (i + 1) + ". " + (item.text || "").slice(0, 40);
      c.onclick = function () { queue.splice(i, 1); render(); };
      chips.appendChild(c);
    });
    send.textContent = "send (" + queue.length + ")";
    send.disabled = queue.length === 0;
  }
  function say(msg) { status.textContent = msg; }

  mode.onclick = function () {
    annotate = !annotate;
    mode.textContent = "annotate: " + (annotate ? "on" : "off");
    mode.classList.toggle("on", annotate);
  };
  ta.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); queueComment(); }
  });
  function queueComment() {
    var text = ta.value.trim();
    if (!text) return;
    queue.push({target: pendingTarget || {tag: "page"}, text: text});
    ta.value = ""; pendingTarget = null; render(); say("queued");
  }
  ta.addEventListener("dblclick", queueComment);
  send.onclick = function () {
    if (!queue.length) return;
    say("sending…");
    fetch("/__feedback", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({path: rel, items: queue})}
    ).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      queue = []; pendingTarget = null; render(); say("sent to agent ✓");
    }).catch(function (e) { say("send failed: " + e.message); });
  };

  document.addEventListener("click", function (e) {
    if (!annotate || panel.contains(e.target)) return;
    e.preventDefault(); e.stopPropagation();
    pendingTarget = describe(e.target);
    say("on " + pendingTarget.tag + (pendingTarget.id ? "#" + pendingTarget.id : "") +
        " — type a comment, Enter to queue");
    ta.focus();
  }, true);
  document.addEventListener("mouseover", function (e) {
    if (!annotate) return;
    var t = e.target.closest && e.target.closest("body *");
    if (t && !panel.contains(t)) t.classList.add("__topo_hover");
  });
  document.addEventListener("mouseout", function (e) {
    if (e.target.classList) e.target.classList.remove("__topo_hover");
  });

  var mtime0 = null;
  function stash() {
    try {
      sessionStorage.setItem("__topo_" + rel, JSON.stringify({queue: queue, draft: ta.value}));
    } catch (e) {}
  }
  try {
    var kept = sessionStorage.getItem("__topo_" + rel);
    if (kept) { var d = JSON.parse(kept); queue = d.queue || []; ta.value = d.draft || "";
                sessionStorage.removeItem("__topo_" + rel); }
  } catch (e) {}
  render();
  setInterval(function () {
    fetch("/__poll?path=" + encodeURIComponent(rel))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (mtime0 === null) { mtime0 = d.mtime; return; }
        if (d.mtime > mtime0) { stash(); location.reload(); }
      }).catch(function () {});
  }, 1500);
})();
"""

_servers: dict[str, dict] = {}


def _open_browser(url: str) -> bool:
    return webbrowser.open(url)


def _make_handler(cwd: Path):
    plans = _plans_dir(cwd)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):  # keep the REPL quiet
            pass

        def _host_ok(self) -> bool:
            host = self.headers.get("Host") or ""
            if host.startswith("["):  # [::1]:port
                name = host[1:host.find("]")] if "]" in host else ""
            else:
                name = host.rsplit(":", 1)[0] if ":" in host else host
            return name.lower() in ("127.0.0.1", "localhost", "::1")

        def _send(self, code: int, body: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _artifact_for(self, rel: str) -> Path | None:
            try:
                path = (plans / rel).resolve()
                if not str(path).startswith(str(plans.resolve()) + "/") or path.suffix != ".html":
                    return None
                return path
            except (OSError, ValueError):
                return None

        def do_GET(self):  # noqa: N802 — http.server API
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            url = urlsplit(self.path)
            if url.path == "/__topo.js":
                return self._send(200, CHROME_JS.encode(), "application/javascript; charset=utf-8")
            if url.path == "/__feedback":
                return self._json(405, {"error": "POST only"})
            if url.path == "/__poll":
                rel = unquote((url.query.removeprefix("path=") if url.query.startswith("path=")
                               else "").split("&")[0])
                artifact = self._artifact_for(rel)
                if artifact is None or not artifact.is_file():
                    return self._json(404, {"error": "no such artifact"})
                pending = len(_read_store(_store_path(cwd, artifact)))
                return self._json(200, {"mtime": artifact.stat().st_mtime, "pending": pending})
            if url.path == "/":
                rows = sorted(plans.rglob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True) \
                    if plans.is_dir() else []
                items = "\n".join(
                    f'<li><a href="/plans/{_rel_under(plans, p)}">{_rel_under(plans, p)}</a>'
                    f" — {time.strftime('%Y-%m-%d %H:%M', time.localtime(p.stat().st_mtime))}</li>"
                    for p in rows) or "<li>(no artifacts yet)</li>"
                return self._send(200, f"<!doctype html><title>topo</title>"
                                       f"<h2>docs/plans/</h2><ul>{items}</ul>".encode(),
                                  "text/html; charset=utf-8")
            if url.path.startswith("/plans/"):
                rel = unquote(url.path[len("/plans/"):])
                artifact = self._artifact_for(rel)
                if artifact is None or not artifact.is_file():
                    return self._send(404, b"not found", "text/plain")
                html = artifact.read_text(encoding="utf-8", errors="replace")
                tag = '<script src="/__topo.js" defer></script>'
                lower = html.lower()
                idx = lower.rfind("</body>")
                html = html[:idx] + tag + html[idx:] if idx != -1 else html + tag
                return self._send(200, html.encode(), "text/html; charset=utf-8")
            return self._send(404, b"not found", "text/plain")

        def do_POST(self):  # noqa: N802 — http.server API
            if not self._host_ok():
                return self._send(403, b"forbidden", "text/plain")
            if urlsplit(self.path).path != "/__feedback":
                return self._send(404, b"not found", "text/plain")
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
                body = json.loads(self.rfile.read(length) or b"{}")
                artifact = self._artifact_for(str(body.get("path", "")))
                items = body.get("items")
                if artifact is None or not isinstance(items, list) or not items:
                    return self._json(400, {"error": "bad request"})
                _append_feedback(cwd, artifact, items[:100])
                return self._json(200, {"ok": True})
            except (ValueError, OSError):
                return self._json(400, {"error": "bad request"})

    return Handler


def ensure_server(cwd: Path) -> dict:
    key = str(cwd)
    if key not in _servers:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(cwd))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True,
                                  name=f"topo-{httpd.server_port}")
        thread.start()
        _servers[key] = {"httpd": httpd, "port": httpd.server_port, "thread": thread}
    return _servers[key]


def stop_servers() -> None:
    for s in _servers.values():
        s["httpd"].shutdown()
    _servers.clear()


# ---------------------------------------------------------------- tools

def _url(cwd: Path, artifact: Path) -> str:
    port = ensure_server(cwd)["port"]
    rel = _rel_under(_plans_dir(cwd), artifact)
    return f"http://127.0.0.1:{port}/plans/{quote(rel)}"


def _write_tool(args: dict, ctx: Ctx) -> str:
    html = str(args.get("html", ""))
    if "<" not in html:
        raise ValueError("html must be an HTML document, not plain text")
    artifact = _resolve_artifact(ctx.cwd, str(args.get("path", "")))
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(html, encoding="utf-8")
    rel = _rel_under(_plans_dir(ctx.cwd), artifact)
    extra = " (browser tab will live-reload)" if str(ctx.cwd) in _servers else ""
    return f"wrote docs/plans/{rel} ({len(html)} chars){extra}"


def _open_tool(args: dict, ctx: Ctx) -> str:
    artifact = _resolve_artifact(ctx.cwd, str(args.get("path", "")))
    if not artifact.is_file():
        raise ValueError(f"no artifact at docs/plans/{_rel_under(_plans_dir(ctx.cwd), artifact)}"
                         " — topo_write it first")
    url = _url(ctx.cwd, artifact)
    opened = _open_browser(url)
    how = "opened in browser" if opened else f"open {url} manually (no browser launched)"
    return (f"{how}. Tell the user to review it (annotate mode: click, comment, Enter; "
            "send when done). Then call topo_feedback to collect their comments.")


def _fmt_target(target: dict) -> str:
    head = target.get("tag", "?") + (f"#{target['id']}" if target.get("id") else "")
    if target.get("selection"):
        return f'{head} sel "{str(target["selection"])[:60]}"'
    if target.get("text"):
        return f'{head} "{str(target["text"])[:60]}"'
    return head


def _feedback_tool(args: dict, ctx: Ctx) -> str:
    artifact = _resolve_artifact(ctx.cwd, str(args.get("path", "")))
    rel = _rel_under(_plans_dir(ctx.cwd), artifact)
    store = _store_path(ctx.cwd, artifact)
    entries = _read_store(store)
    if not entries:
        return f"No feedback yet on docs/plans/{rel}. Wait for the user to comment, then call again."
    _write_store(store, [])
    lines = [f"{i}. {_fmt_target(e['target'])} — {e['text']}"
             for i, e in enumerate(entries, 1)]
    return f"{len(entries)} comments on docs/plans/{rel} (queue drained):\n" + "\n".join(lines)


# ---------------------------------------------------------------- plugin

def topo_cmd(agent, rest: str) -> None:
    cwd = agent.ctx.cwd
    plans = _plans_dir(cwd)
    if rest:
        try:
            artifact = _resolve_artifact(cwd, rest)
        except ValueError as e:
            print(f"topo: {e}")
            return
    else:
        if not plans.is_dir():
            print("topo: no artifacts in docs/plans/ — ask the agent to topo_write one")
            return
        found = sorted(plans.rglob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not found:
            print("topo: no artifacts in docs/plans/ — ask the agent to topo_write one")
            return
        artifact = found[0]
    if not artifact.is_file():
        print(f"topo: no artifact at {artifact}")
        return
    url = _url(cwd, artifact)
    print(url if _open_browser(url) else f"open {url} manually (no browser launched)")


def scout(api) -> None:
    api.tool(Tool(
        name="topo_write",
        description="Write an HTML planning artifact under docs/plans/ (path may omit .html). "
                    "Load the 'topo' skill first for authoring guidance.",
        parameters={"type": "object",
                    "properties": {"path": {"type": "string",
                                            "description": "artifact name, e.g. 'auth-rollout'"},
                                   "html": {"type": "string", "description": "full HTML document"}},
                    "required": ["path", "html"]},
        run=_write_tool,
    ))
    api.tool(Tool(
        name="topo_open",
        description="Open a topo artifact in the user's browser for review (live-reloads on "
                    "topo_write). Follow with topo_feedback to collect their comments.",
        parameters={"type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]},
        run=_open_tool,
    ))
    api.tool(Tool(
        name="topo_feedback",
        description="Drain queued review comments for a topo artifact. Empty until the user "
                    "sends from the browser panel.",
        parameters={"type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]},
        run=_feedback_tool,
    ))
    api.command("/topo", topo_cmd)
