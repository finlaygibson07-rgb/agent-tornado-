#!/usr/bin/env python3
"""agent tornado -- hands.

Gives the tornado something to work with. The app on its own is a simulation: it
schedules and it learns, but nothing it does touches the world. This is the part
that touches the world, and it is deliberately narrow.

How it stays narrow
-------------------
* It binds to loopback and refuses browser requests that did not come from this
  app. Binding to 127.0.0.1 keeps other machines out; it does not keep other web
  pages out, because browsers do not apply same-origin policy to a *simple* POST
  the way they do to a WebSocket handshake. Only the Origin header does that.
* It can only run tools that exist as manifests on disk. There is no endpoint
  that takes a command. `argv` comes from the manifest, not from the request --
  the request supplies named arguments that are substituted into placeholders
  the manifest already declared, then passed as argv with no shell involved.
* File tools cannot leave the `roots` their own manifest declares, and the check
  is done after symlink resolution. A shell argument typed `path` is held to the
  same roots, so `git -C {repo}` cannot be pointed outside them either.
* A value substituted into argv may not start with `-` unless the manifest put a
  literal `--` before it. Otherwise `node --test {file}` would take
  `--eval=...` as an option, and an argument would become a program.
* Destructive tools must declare `"confirm": true`, and then every call has to
  carry an explicit confirmation. The app surfaces that as an approval prompt.
* Everything is append-only logged to tools/.audit.jsonl, including refusals.
* A token bucket caps invocations per window so a runaway loop cannot hammer the
  machine while you are asleep.

Run it:

    python3 hands.py --start         # start it in the background and open the app
    python3 hands.py --status        # is it up, and on which pid
    python3 hands.py --stop          # stop it
    python3 hands.py --check         # validate every manifest and exit
    python3 hands.py --port 8799     # pick a port
    python3 hands.py --dry-run       # validate and plan, never execute

Without a verb it serves in the foreground, which is what you want when you are
watching the log. `--start` is the same server in its own session, so the window
that launched it can close; the record it leaves in `.run/` is what `--stop`
reads, and a record that points at a process which is gone is cleaned up rather
than trusted.
"""

from __future__ import annotations

import argparse
import hmac
import html.parser
import importlib.util
import ipaddress
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

VERSION = "4.0"

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}
KINDS = {"shell", "file-read", "file-write", "http", "web-read", "copy-tree"}
ARG_TYPES = {"string", "int", "number", "bool", "path"}

MAX_BODY = 256 * 1024
MAX_OUTPUT = 64 * 1024
DEFAULT_TIMEOUT = 20.0
DEFAULT_HTTP_TIMEOUT = 20.0

# A page, not a download: enough for docs and articles, small enough that a
# runaway response cannot eat the bridge.
MAX_WEB_BYTES = 2 * 1024 * 1024
MAX_WEB_CHARS = 32000
DEFAULT_WEB_CHARS = 12000
WEB_USER_AGENT = "agent-tornado/1.0 (local; one page at a time)"
LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
# 'auto' reads with Scrapin (the Scrapin/Scrapling fork) when it is installed and
# with the standard library when it is not. The result always names the engine
# that actually ran, so 'auto' cannot pass one off as the other.
WEB_ENGINES = {"auto", "stdlib", "scrapin"}
MAX_WEB_HOPS = 5

RATE_TOKENS = 30
RATE_WINDOW = 10.0

# What a shell hand inherits from the bridge's environment, and nothing more.
# A test suite is code from the repo being repaired -- and, in the loop, code
# the model just wrote -- so API keys, tokens and agent sockets in the bridge's
# own environment are not handed to it. A manifest that needs another variable
# names it in "passEnv".
SAFE_ENV = ("PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL",
            "LC_CTYPE", "TMPDIR", "TERM", "TZ")
ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,63}")

# Every /api call except the launcher's health probe carries this header. The
# token is made fresh each time the bridge starts, written only to its 0600
# record, and handed to the app window in the url's fragment -- which a browser
# never sends to a server -- so another user on this machine, or a page in some
# other tab, cannot learn it by asking the bridge.
TOKEN_HEADER = "X-Tornado-Token"

STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".map": "application/json; charset=utf-8",
}

PLACEHOLDER = re.compile(r"\{([a-zA-Z0-9_]+)\}")


class ToolError(Exception):
    """A tool call that was refused. Always safe to show the operator."""


# --------------------------------------------------------------------------- #
# tools
# --------------------------------------------------------------------------- #


class Tool:
    def __init__(self, raw: dict, source: str):
        if not isinstance(raw, dict):
            raise ToolError("a manifest must be a JSON object")
        self.id = str(raw.get("id") or "").strip()
        if not self.id or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", self.id):
            raise ToolError(f"bad or missing id: {self.id!r} (lowercase, dashes, 2-64 chars)")

        self.name = str(raw.get("name") or self.id)
        self.description = str(raw.get("description") or "").strip()
        self.kind = str(raw.get("kind") or "").strip()
        if self.kind not in KINDS:
            raise ToolError(f"{self.id}: kind must be one of {sorted(KINDS)}, got {self.kind!r}")

        self.matches = [str(m).lower() for m in raw.get("matches") or []]
        self.source = source
        self.args = self._parse_args(raw.get("args") or {})

        # declarations that only make sense for a given kind
        self.argv = [str(part) for part in raw.get("argv") or []]
        self.cwd = raw.get("cwd")
        self.url = raw.get("url")
        self.method = str(raw.get("method") or "GET").upper()
        self.headers = {str(k): str(v) for k, v in (raw.get("headers") or {}).items()}
        self.roots = [str(r) for r in raw.get("roots") or []]
        for root in self.roots + [r for spec in self.args.values() for r in spec["roots"]]:
            # fail at manifest time, not at call time: an unset $VAR leaves the
            # literal '$VAR' behind, which would silently resolve against cwd
            if not expand(root).is_absolute():
                raise ToolError(f"{self.id}: root {root!r} is not absolute (is the env var set?)")
            # a root of / is no root at all: it would make every path "inside"
            if expand(root).resolve() == Path("/").resolve():
                raise ToolError(f"{self.id}: refusing root {root!r} -- it holds the whole disk")
        self.pass_env = [str(name) for name in raw.get("passEnv") or []]
        for name in self.pass_env:
            if not ENV_NAME.fullmatch(name):
                raise ToolError(f"{self.id}: passEnv entry {name!r} is not an environment variable name")
        self.timeout = float(raw.get("timeout") or DEFAULT_TIMEOUT)
        self.engine = "auto"

        if self.kind == "shell":
            if not self.argv:
                raise ToolError(f"{self.id}: kind 'shell' needs a non-empty 'argv'")
            if isinstance(self.cwd, str) and self.cwd.strip() in ("", "/"):
                raise ToolError(f"{self.id}: refusing cwd '/'")
            for part in self.argv:
                for name in PLACEHOLDER.findall(part):
                    if name not in self.args:
                        raise ToolError(f"{self.id}: argv uses undeclared argument {{{name}}}")
        if self.kind in ("file-read", "file-write") and not self.roots:
            raise ToolError(f"{self.id}: kind '{self.kind}' needs at least one 'roots' entry")
        if any(spec["type"] == "path" and not (spec["roots"] or self.roots) for spec in self.args.values()):
            raise ToolError(f"{self.id}: a 'path' argument needs at least one 'roots' entry to be held to")
        if self.kind == "copy-tree":
            for needed in ("src", "dst"):
                if self.args.get(needed, {}).get("type") != "path":
                    raise ToolError(f"{self.id}: kind 'copy-tree' needs a 'path' argument called {needed!r}")
        # A hand that reaches past this machine has to say so. Without the flag,
        # a dropped manifest cannot quietly post your arguments to a host you
        # never read the name of.
        self.allow_remote = bool(raw.get("allowRemote"))

        if self.kind == "web-read":
            # Unlike 'http', the host comes from the caller -- that is the whole
            # point of reading the web -- so the flag matters more here, not less.
            if not self.allow_remote:
                raise ToolError(f"{self.id}: kind 'web-read' reaches the internet -- "
                                "set \"allowRemote\": true to say that is intended")
            if "url" not in self.args:
                raise ToolError(f"{self.id}: kind 'web-read' needs a 'url' argument")
            # Which engine reads the page. 'auto' uses Scrapin when it is
            # installed and the standard library when it is not, and either way
            # the result says which one ran -- a hand never quietly swaps its
            # fetch for another one.
            self.engine = str(raw.get("engine") or "auto").strip().lower()
            if self.engine not in WEB_ENGINES:
                raise ToolError(f"{self.id}: unknown engine {self.engine!r} -- one of "
                                + ", ".join(sorted(WEB_ENGINES)))

        if self.kind == "http":
            if not self.url:
                raise ToolError(f"{self.id}: kind 'http' needs a 'url'")
            try:
                target = (urlparse(str(self.url)).hostname or "").lower()
            except ValueError:
                raise ToolError(f"{self.id}: url {self.url!r} does not parse")
            if PLACEHOLDER.search(urlparse(str(self.url)).netloc or ""):
                raise ToolError(f"{self.id}: the url's host cannot come from an argument")
            if target not in LOOPBACK_HOSTS and not self.allow_remote:
                raise ToolError(f"{self.id}: {target or 'that host'} is not this machine -- "
                                "set \"allowRemote\": true to let a hand reach it")

        # writing is always destructive; never let a manifest opt out
        self.confirm = bool(raw.get("confirm")) or self.kind == "file-write"

        if self.timeout <= 0 or self.timeout > 600:
            raise ToolError(f"{self.id}: timeout must be between 0 and 600 seconds")

    @staticmethod
    def _parse_args(raw: dict) -> dict:
        schema = {}
        for name, spec in raw.items():
            if not isinstance(spec, dict):
                raise ToolError(f"argument {name!r} must be an object")
            kind = str(spec.get("type") or "string")
            if kind not in ARG_TYPES:
                raise ToolError(f"argument {name!r}: type must be one of {sorted(ARG_TYPES)}")
            roots = [str(r) for r in spec.get("roots") or []]
            if roots and kind != "path":
                raise ToolError(f"argument {name!r}: only a 'path' argument can declare its own roots")
            schema[name] = {
                "type": kind,
                "required": bool(spec.get("required")),
                "description": str(spec.get("description") or ""),
                "default": spec.get("default"),
                "enum": spec.get("enum"),
                # an argument's own roots narrow it further than the tool's: a
                # copy reads from anywhere in $HOME but lands only in work/
                "roots": roots,
            }
        return schema

    def public(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "description": self.description,
            "matches": self.matches,
            "confirm": self.confirm,
            "timeout": self.timeout,
            "source": self.source,
            "args": self.args,
            "requires": (
                "argv" if self.kind == "shell"
                else "roots" if self.kind in ("file-read", "file-write")
                else "the internet" if self.kind == "web-read"
                else "roots" if self.kind == "copy-tree"
                else "url"
            ),
        }


def load_tools(tools_dir: Path) -> tuple[dict, list]:
    """Read every *.json in the folder. Returns (tools by id, problems).

    The folder is the interface: drop a manifest in, it appears. A file may hold
    one tool or {"tools": [...]}, so you can keep related hands together.
    """
    tools: dict = {}
    problems: list = []
    if not tools_dir.is_dir():
        return tools, problems

    for path in sorted(tools_dir.glob("*.json")):
        if path.name.startswith("."):
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - a bad manifest must not kill startup
            problems.append({"file": path.name, "error": f"invalid JSON: {exc}"})
            continue

        for entry in raw.get("tools", []) if isinstance(raw, dict) and "tools" in raw else [raw]:
            try:
                tool = Tool(entry, path.name)
                if tool.id in tools:
                    problems.append({"file": path.name, "error": f"duplicate id: {tool.id}"})
                    continue
                tools[tool.id] = tool
            except ToolError as exc:
                problems.append({"file": path.name, "error": str(exc)})
    return tools, problems


# --------------------------------------------------------------------------- #
# validation and planning (pure, so it can be tested without a server)
# --------------------------------------------------------------------------- #


def coerce_args(tool: Tool, given: dict) -> dict:
    """Validate a request's arguments against the manifest's schema."""
    if not isinstance(given, dict):
        raise ToolError("args must be an object")
    unknown = set(given) - set(tool.args)
    if unknown:
        raise ToolError(f"unknown arguments: {', '.join(sorted(unknown))}")

    out = {}
    for name, spec in tool.args.items():
        if name in given and given[name] is not None:
            value = given[name]
        elif spec["default"] is not None:
            value = spec["default"]
        elif spec["required"]:
            raise ToolError(f"missing required argument: {name}")
        else:
            continue

        kind = spec["type"]
        try:
            if kind == "int":
                value = int(value)
            elif kind == "number":
                value = float(value)
            elif kind == "bool":
                if isinstance(value, str):
                    value = value.strip().lower() in ("1", "true", "yes", "on")
                value = bool(value)
            else:
                value = str(value)
        except (TypeError, ValueError):
            raise ToolError(f"argument {name!r} is not a valid {kind}")

        if spec["enum"] and value not in spec["enum"]:
            raise ToolError(f"argument {name!r} must be one of {spec['enum']}")
        out[name] = value
    return out


def substitute(template: str, args: dict) -> str:
    """Replace {name} placeholders. No shell, no evaluation, no escapes."""

    def repl(match):
        name = match.group(1)
        if name not in args:
            raise ToolError(f"no value for {{{name}}}")
        return str(args[name])

    return PLACEHOLDER.sub(repl, template)


def expand(value: str) -> Path:
    """$VARS and ~ both work in manifests, so paths survive a machine move."""
    return Path(os.path.expandvars(value)).expanduser()


def resolve_within_roots(candidate: str, roots: list) -> Path:
    """Resolve a path and prove it sits inside one of the declared roots.

    Symlinks are resolved first, so a link inside a root cannot be used to step
    outside it.
    """
    path = expand(candidate)
    if not path.is_absolute():
        raise ToolError("path must be absolute")
    resolved = path.resolve()
    for root in roots:
        base = expand(root).resolve()
        if resolved == base or base in resolved.parents:
            return resolved
    raise ToolError(f"path is outside every declared root: {resolved}")


def contained_args(tool: Tool, args: dict) -> dict:
    """Every `path` argument, resolved and proven to sit inside its roots: the
    argument's own when it declares them, the tool's otherwise."""
    out = dict(args)
    for name, spec in tool.args.items():
        if spec["type"] == "path" and name in out:
            out[name] = str(resolve_within_roots(str(out[name]), spec["roots"] or tool.roots))
    return out


def shell_argv(tool: Tool, args: dict) -> list:
    """Substitute argv, refusing any argument that would be read as an option.

    A literal `--` in the manifest ends option parsing for the program, so a
    placeholder after it may start with a dash (a grep pattern like `-x`).
    """
    argv, options_ended = [], False
    for part in tool.argv:
        value = substitute(part, args)
        if PLACEHOLDER.search(part) and not options_ended and not part.startswith("-") and value.startswith("-"):
            raise ToolError(f"argument value {value[:40]!r} starts with '-' and would be read as an option")
        if part == "--":
            options_ended = True
        argv.append(value)
    return argv


def plan(tool: Tool, args: dict) -> dict:
    """What this call would do. Safe to show before anything happens."""
    args = contained_args(tool, args)
    if tool.kind == "shell":
        argv = shell_argv(tool, args)
        cwd = substitute(str(tool.cwd), args) if tool.cwd else None
        if cwd:
            # A literal cwd is written by the manifest author, not by the caller,
            # so it stands on its own; a cwd containing {args} must prove itself
            # against the declared roots.
            cwd = str(resolve_within_roots(cwd, tool.roots)) if tool.roots else cwd
        return {"kind": "shell", "argv": argv, "cwd": cwd, "timeout": tool.timeout}
    if tool.kind in ("file-read", "file-write"):
        path = resolve_within_roots(str(args.get("path", "")), tool.roots)
        return {"kind": tool.kind, "path": str(path), "timeout": tool.timeout}
    if tool.kind == "http":
        return {"kind": "http", "method": tool.method, "url": substitute(tool.url, args), "timeout": tool.timeout}
    if tool.kind == "web-read":
        return {"kind": "web-read", "url": web_url(str(args.get("url", ""))),
                "maxChars": web_chars(args.get("max_chars")), "timeout": tool.timeout,
                "engine": resolve_engine(tool.engine)}
    if tool.kind == "copy-tree":
        return {"kind": "copy-tree", "src": args["src"], "dst": args["dst"], "timeout": tool.timeout}
    raise ToolError(f"unsupported kind {tool.kind!r}")


def safe_manifest_name(name: str) -> str:
    """Force a dropped name into a plain *.json sitting directly in tools/."""
    stem = Path(str(name or "")).name
    stem = re.sub(r"[^A-Za-z0-9._-]", "-", stem).strip("-.")
    if stem.lower().endswith(".json"):
        stem = stem[: -len(".json")]
    stem = stem[:48]
    if not stem:
        raise ToolError("a manifest needs a name")
    return stem + ".json"


def validate_manifest_text(text: str) -> list:
    """Parse dropped JSON and prove every tool in it loads, before it is written."""
    try:
        raw = json.loads(text)
    except ValueError as exc:
        raise ToolError(f"invalid JSON: {exc}")
    entries = raw.get("tools", []) if isinstance(raw, dict) and "tools" in raw else [raw]
    if not entries:
        raise ToolError("no tools in that manifest")
    needed = []
    for entry in entries:
        needed.append(Tool(entry, "(pending)"))  # raises ToolError with the reason
    return needed


def execute(tool: Tool, args: dict, confirmed: bool, dry_run: bool = False) -> dict:
    """Run a tool. Everything dangerous was already narrowed by `plan`."""
    if tool.confirm and not confirmed:
        raise ToolError(f"{tool.id} is destructive and needs an explicit confirmation")

    steps = plan(tool, args)
    if dry_run:
        return {"dryRun": True, "plan": steps, "output": "(dry run -- nothing was executed)"}

    if tool.kind == "shell":
        code, output = run_shell(steps["argv"], steps["cwd"], steps["timeout"], shell_env(tool))
        return {"exit": code, "output": clip(output), "plan": steps}

    if tool.kind == "copy-tree":
        copied = copy_tree(Path(steps["src"]), Path(steps["dst"]))
        return {"exit": 0, "output": copied, "plan": steps}

    if tool.kind == "file-read":
        path = Path(steps["path"])
        if not path.is_file():
            raise ToolError(f"not a file: {path}")
        if path.stat().st_size > MAX_OUTPUT:
            raise ToolError(f"file is larger than {MAX_OUTPUT} bytes: {path}")
        return {"output": clip(path.read_text(encoding="utf-8", errors="replace")), "plan": steps}

    if tool.kind == "file-write":
        path = Path(steps["path"])
        body = str(args.get("content", ""))
        if len(body) > MAX_OUTPUT:
            raise ToolError(f"refusing to write more than {MAX_OUTPUT} bytes")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return {"output": f"wrote {len(body)} bytes to {path}", "plan": steps}

    if tool.kind == "web-read":
        body = fetch_web(steps["url"], steps["maxChars"], steps["timeout"], steps.get("engine", "auto"))
        body["plan"] = steps
        return body

    if tool.kind == "http":
        import urllib.request

        request = urllib.request.Request(steps["url"], headers=tool.headers, method=steps["method"])
        data = None
        if tool.method in ("POST", "PUT", "PATCH"):
            data = json.dumps(args.get("body", {})).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, data=data, timeout=steps["timeout"]) as response:  # noqa: S310
            return {"status": response.status, "output": clip(response.read().decode("utf-8", "replace")), "plan": steps}

    raise ToolError(f"unsupported kind {tool.kind!r}")


def shell_env(tool: Tool) -> dict:
    """The bridge's environment, cut down to what a command needs to run."""
    names = set(SAFE_ENV) | set(tool.pass_env)
    return {name: value for name, value in os.environ.items() if name in names}


def run_shell(argv: list, cwd, timeout: float, env: dict) -> tuple:
    """Run argv in its own process group, so a timeout takes the whole tree down.

    A test runner starts workers of its own; killing only the direct child would
    leave them running, and holding the output pipe open, long after the call
    was given up on.
    """
    proc = subprocess.Popen(  # noqa: S603 - argv comes from the manifest, never the request
        argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", start_new_session=True,
    )
    try:
        output, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass  # it finished between the timeout and the kill
        proc.communicate()
        raise
    return proc.returncode, output or ""


def copy_tree(src: Path, dst: Path) -> str:
    """Copy a repository into an empty scratch folder, and nothing that leads out of it.

    A symlink is kept only when it is relative and lands inside the repo. Any
    other link -- to ~/.ssh, to /etc, or an absolute one back into the original
    repo -- is left behind and named in the result: a copy the loop can read and
    write must not have doors in it to files the loop was never given.
    """
    if not src.is_dir():
        raise ToolError(f"not a folder: {src}")
    if dst == src or src in dst.parents or dst in src.parents:
        raise ToolError("the copy and the repo cannot sit inside one another")
    if dst.exists() and (not dst.is_dir() or any(dst.iterdir())):
        raise ToolError(f"{dst} already has files in it -- a copy only lands in an empty folder")

    skipped = []

    def ignore(folder, names):
        dropped = set()
        for name in names:
            entry = Path(folder) / name
            if not entry.is_symlink():
                continue
            target = os.readlink(entry)
            landed = (entry.parent / target).resolve()
            if os.path.isabs(target) or not (landed == src or src in landed.parents):
                dropped.add(name)
                skipped.append(str(entry.relative_to(src)))
        return dropped

    shutil.copytree(src, dst, symlinks=True, ignore=ignore, dirs_exist_ok=True)
    note = f"copied {src} to {dst}"
    if skipped:
        note += (f"\nleft out {len(skipped)} link(s) that point outside the repo: "
                 + ", ".join(sorted(skipped)[:20]))
    return note


def clip(text: str) -> str:
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + f"\n... truncated {len(text) - MAX_OUTPUT} more bytes"


# --------------------------------------------------------------------------- #
# the web
#
# One page at a time, as text. This is the only part of the bridge that leaves
# the machine on a caller's say-so, so the checks are the point: http(s) only,
# no credentials in the url, no name that points back here, and every redirect
# re-checked rather than trusted.
# --------------------------------------------------------------------------- #


SKIP_TAGS = {"script", "style", "noscript", "template", "head", "svg", "canvas",
             "iframe", "object", "embed", "video", "audio"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "header", "footer", "nav",
              "blockquote", "pre", "table", "tr", "ul", "ol", "dl", "figure", "aside",
              "h1", "h2", "h3", "h4", "h5", "h6", "br", "hr", "form", "fieldset"}


class _PageText(html.parser.HTMLParser):
    """HTML in, readable text out. Not a renderer: it keeps the words, drops the
    furniture, and puts a line break where a browser would have drawn one."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.title = ""
        self._skipping = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skipping += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in ("td", "th"):
            self.parts.append(" | ")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skipping = max(0, self._skipping - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skipping:
            return
        self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(markup: str) -> tuple:
    """(title, text). Idempotent, no network, so it can be tested on a string."""
    parser = _PageText()
    try:
        parser.feed(markup)
        parser.close()
    except Exception:  # a malformed page is still worth what it did give us
        pass
    lines = []
    for line in "".join(parser.parts).splitlines():
        line = line.rstrip()
        if line.strip() or (lines and lines[-1]):
            lines.append(line)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    title = re.sub(r"\s+", " ", parser.title).strip()
    return title, text


def web_url(value: str) -> str:
    """A url a hand may read. Refused here rather than fetched and regretted."""
    text = str(value or "").strip()
    if not text:
        raise ToolError("missing required argument: url")
    if len(text) > 2048:
        raise ToolError("that url is longer than any real one")
    if any(ord(ch) < 32 for ch in text):
        raise ToolError("that url has a control character in it")
    try:
        parts = urlparse(text)
    except ValueError:
        raise ToolError(f"that is not a url: {text[:80]!r}")
    if parts.scheme not in ("http", "https"):
        raise ToolError(f"only http and https can be read, not {parts.scheme or 'that'!r}")
    if parts.username or parts.password:
        raise ToolError("a url carrying a username or password is refused")
    host = (parts.hostname or "").lower()
    if not host:
        raise ToolError("that url has no host")
    if host in LOCAL_NAMES or host.endswith(".localhost") or host.endswith(".local"):
        raise ToolError(f"{host} is this machine, not the web")
    # A literal address needs no lookup to be judged, so it is judged here rather
    # than waiting for the check at call time.
    try:
        literal = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ToolError(f"{host} is a private address, not the web")
    return parts.geturl()


def web_chars(value) -> int:
    try:
        wanted = int(value) if value is not None else DEFAULT_WEB_CHARS
    except (TypeError, ValueError):
        raise ToolError("max_chars must be a whole number")
    if wanted <= 0:
        wanted = DEFAULT_WEB_CHARS
    return min(wanted, MAX_WEB_CHARS)


def public_host(host: str) -> str:
    """Resolve, and refuse anything that is not a public address.

    Done at call time, so a dry run never touches the network, and done by name
    because that is how the request will connect. A name that resolves to a
    router, a metadata endpoint or this machine is the obvious way to turn a web
    tool into a way in, and it is refused by address rather than by spelling.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as exc:
        raise ToolError(f"could not resolve {host}: {exc}")
    for info in infos:
        address = str(info[4][0]).split("%")[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            raise ToolError(f"{host} resolved to something that is not an address")
        # not is_global, rather than a list of what is private: shared address
        # space (100.64/10, where tailnets live), site-local v6 and whatever is
        # reserved next are all "not the public web" without being named here
        # (site-local v6 is deprecated, and ipaddress still calls it global)
        if (not ip.is_global or ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified
                or getattr(ip, "is_site_local", False)):
            raise ToolError(f"{host} resolves to {address}, which is not the public web")
    return host


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Every hop is checked, not only the url that was asked for."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parts = urlparse(newurl)
        if parts.scheme not in ("http", "https"):
            raise ToolError(f"a redirect to {parts.scheme or 'that'} is refused")
        if parts.username or parts.password:
            raise ToolError("a redirect carrying credentials is refused")
        host = (parts.hostname or "").lower()
        if not host or host in LOCAL_NAMES or host.endswith(".localhost"):
            raise ToolError(f"a redirect to {host or 'nowhere'} is refused")
        public_host(host)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def scrapin_installed() -> bool:
    """Whether Scrapin/Scrapling can be imported here, without importing it.

    Asked at plan time as well as call time so a dry run can say which engine
    would read the page before anything touches the network.
    """
    try:
        return importlib.util.find_spec("scrapling") is not None
    except (ImportError, ValueError):
        return False


def resolve_engine(preference: str) -> str:
    wanted = str(preference or "auto").strip().lower()
    if wanted in WEB_ENGINES and wanted != "auto":
        return wanted
    return "scrapin" if scrapin_installed() else "stdlib"


def _scrapin_fetcher():
    """The Fetcher class from Scrapin, or a refusal that says how to get it."""
    try:
        from scrapling.fetchers import Fetcher  # noqa: PLC0415 -- optional dependency
    except Exception as exc:  # a broken optional install must not crash the hand
        raise ToolError("read-web is set to use Scrapin, but `scrapling` did not import "
                        f"({exc}). Install it with: pip install \"scrapling[fetchers]\", "
                        "or set \"engine\": \"stdlib\" in the manifest")
    return Fetcher


def _header_text(headers, name: str) -> str:
    wanted = name.lower()
    for key, value in dict(headers or {}).items():
        if str(key).lower() == wanted:
            return str(value or "")
    return ""


def _charset_of(header: str) -> str:
    for part in str(header or "").split(";")[1:]:
        key, _, value = part.partition("=")
        if key.strip().lower() == "charset" and value.strip():
            return value.strip().strip('"').strip("'")
    return "utf-8"


def fetch_web_scrapin(url: str, max_chars: int, timeout: float) -> dict:
    """One page as text, read by Scrapin.

    Scrapin does the fetching and the parsing. **Redirects stay ours**: the
    fetcher is told not to follow them, and each `Location` is run back through
    `web_url` and `public_host` before the next hop exists at all. That is the
    one part of a scraper this bridge cannot delegate, because a fetcher that
    follows a redirect on its own decides where the request goes next.
    """
    Fetcher = _scrapin_fetcher()
    current = url
    hops = 0
    while True:
        public_host((urlparse(current).hostname or "").lower())
        try:
            page = Fetcher.get(
                current,
                follow_redirects=False,
                stealthy_headers=False,
                headers={
                    "User-Agent": WEB_USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,application/json;q=0.8",
                },
                timeout=timeout,
            )
        except ToolError:
            raise
        except Exception as exc:  # curl_cffi raises its own errors on the wire
            raise ToolError(f"could not reach {current}: {exc}")

        status = int(getattr(page, "status", 0) or 0)
        headers = getattr(page, "headers", {}) or {}
        location = _header_text(headers, "location")
        if status in (301, 302, 303, 307, 308) and location:
            hops += 1
            if hops > MAX_WEB_HOPS:
                raise ToolError(f"{url} redirected more than {MAX_WEB_HOPS} times")
            # web_url applies every refusal again, including to a redirect the
            # page chose -- this is the hop that would otherwise walk home.
            current = web_url(urljoin(current, location))
            continue
        break

    if status >= 400:
        raise ToolError(f"{current} answered {status}")

    ctype_header = _header_text(headers, "content-type")
    ctype = ctype_header.split(";")[0].strip().lower()
    charset = _charset_of(ctype_header)
    body = bytes(getattr(page, "body", b"") or b"")[:MAX_WEB_BYTES]

    if ctype in ("", "text/html", "application/xhtml+xml"):
        try:
            heading = page.css("title::text").get()
        except Exception:
            heading = ""
        title = re.sub(r"\s+", " ", str(heading or "")).strip()
        try:
            # Scrapin's own extraction: scripts and styles dropped, one line per
            # block. If a page defeats it, the text parser takes over.
            text = str(page.get_all_text(separator="\n"))
        except Exception:
            text = ""
        if not text.strip():
            fallback_title, text = html_to_text(body.decode(charset, "replace"))
            title = title or fallback_title
    elif ctype.startswith("text/") or ctype in ("application/json", "application/xml", "text/xml"):
        title, text = "", body.decode(charset, "replace")
    else:
        raise ToolError(f"{current} is {ctype or 'not text'}, which is not something to read")

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    # Scrapin's text pass includes the <title> node, which is already the heading.
    if title and text.startswith(title):
        text = text[len(title):].lstrip("\n").strip()
    clipped = text[:max_chars]
    note = "" if len(text) <= max_chars else f"\n... {len(text) - max_chars} more characters"
    head = f"# {title}\n\n" if title else ""
    return {
        "status": status,
        "url": current,
        "title": title,
        "engine": "scrapin",
        "output": (head + clipped + note).strip(),
    }


def fetch_web(url: str, max_chars: int, timeout: float, engine: str = "auto") -> dict:
    """One page as text. No cookies, no credentials, nothing followed off http(s)."""
    chosen = resolve_engine(engine)
    if chosen == "scrapin":
        return fetch_web_scrapin(url, max_chars, timeout)
    public_host((urlparse(url).hostname or "").lower())
    request = urllib.request.Request(url, headers={
        "User-Agent": WEB_USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,application/json;q=0.8",
    })
    opener = urllib.request.build_opener(_CheckedRedirects())
    try:
        with opener.open(request, timeout=timeout) as response:  # noqa: S310
            status = getattr(response, "status", 200)
            final = response.geturl()
            ctype = response.headers.get_content_type() or ""
            charset = response.headers.get_content_charset() or "utf-8"
            body = response.read(MAX_WEB_BYTES)
    except ToolError:
        raise
    except urllib.error.HTTPError as exc:
        raise ToolError(f"{url} answered {exc.code} {exc.reason}")
    except urllib.error.URLError as exc:
        raise ToolError(f"could not reach {url}: {exc.reason}")
    except (socket.timeout, TimeoutError):
        raise ToolError(f"{url} took longer than {timeout:g}s to answer")

    try:
        page = body.decode(charset, "replace")
    except LookupError:
        page = body.decode("utf-8", "replace")

    if ctype in ("text/html", "application/xhtml+xml"):
        title, text = html_to_text(page)
    elif ctype.startswith("text/") or ctype in ("application/json", "application/xml", "text/xml"):
        title, text = "", page
    else:
        raise ToolError(f"{final} is {ctype or 'not text'}, which is not something to read")

    text = text.strip()
    clipped = text[:max_chars]
    note = "" if len(text) <= max_chars else f"\n... {len(text) - max_chars} more characters"
    head = f"# {title}\n\n" if title else ""
    return {
        "status": status,
        "url": final,
        "title": title,
        "engine": "stdlib",
        "output": (head + clipped + note).strip(),
    }


# --------------------------------------------------------------------------- #
# rate limiting and audit
# --------------------------------------------------------------------------- #


class RateLimiter:
    def __init__(self, tokens: int = RATE_TOKENS, window: float = RATE_WINDOW):
        self.tokens = tokens
        self.window = window
        self.calls: deque = deque()
        self.lock = threading.Lock()

    def take(self) -> float:
        """Return seconds to wait, or 0.0 if the call may proceed."""
        now = time.monotonic()
        with self.lock:
            while self.calls and now - self.calls[0] > self.window:
                self.calls.popleft()
            if len(self.calls) >= self.tokens:
                return round(self.window - (now - self.calls[0]), 2)
            self.calls.append(now)
            return 0.0


class Audit:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def write(self, entry: dict) -> None:
        entry = {"ts": datetime.now().astimezone().isoformat(timespec="seconds"), **entry}
        line = json.dumps(entry, ensure_ascii=False)
        with self.lock:
            try:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                pass  # an unwritable log must never take the bridge down

    def tail(self, limit: int = 50) -> list:
        if not self.path.is_file():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines[-max(1, min(limit, 500)):]:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out


# --------------------------------------------------------------------------- #
# the saved run
#
# The app keeps each step's state here as it goes, so a window that is closed or
# killed mid-run comes back where it was instead of losing the task. It is plain
# JSON in the app folder, because the record *is* the run's report: the same
# bytes you would export, readable with less(1) when the app is not open.
# --------------------------------------------------------------------------- #

RUNS_DIR = "runs"
RUN_KIND = "agent-tornado-run"

# How many runs are kept. Each run writes its own file, so without a bound the
# folder would grow with every task you have ever sent -- and this folder lives in
# a synced one, where quiet growth is the thing you notice last. Newest wins.
RUN_KEEP = 20


def safe_run_id(value) -> str:
    """Force a run's id into a filename that cannot leave runs/.

    The id arrives in the request, so this is the same guard the manifest
    installer uses: letters, digits, dot, dash, underscore, and it must start with
    a letter or a digit -- which is what rules out `..`, a path, and an empty id.
    """
    run_id = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id):
        raise ToolError("a run record needs an id of letters, digits, dot, dash or underscore")
    return run_id


class RunStore:
    """The runs: one file each, newest wins, bounded.

    The app saves a run's state as it goes, so a window that is closed or killed
    mid-run comes back where it was. Each run saves to its own file and never to
    another run's, so the run you finished is still there whatever you build next.
    They are plain JSON on purpose: the record *is* the run's report, readable with
    less(1) when the app is not open.

    Three failures are reasoned about here rather than assumed:

    * **An interrupted save** leaves a `.tmp` beside the real file. The write is a
      rename, so the real file is either the old record or the new one and never
      half of either; a `.tmp` is not a record at all, and `_prune` sweeps it by
      the same ordering as the files.
    * **A torn or unreadable record** is skipped by `newest`, which walks back to
      the newest file that does read. The worst case is therefore resuming the run
      before it rather than being unable to resume at all -- which is what you
      want, because the newest file is exactly the one a killed save was writing.
    * **Ordering is by id, not by mtime**, because the id carries the run's own
      clock: a folder copied between machines, or synced by iCloud, keeps its
      order, where mtimes do not survive it.

    A record with nothing in it is still a record. Clearing a run writes one, and
    it has to win -- otherwise a reload would resurrect the run you just cleared.
    """

    def __init__(self, root: Path):
        self.dir = root / RUNS_DIR

    def path_for(self, run_id) -> Path:
        return self.dir / (safe_run_id(run_id) + ".json")

    def write(self, record: dict) -> Path:
        path = self.path_for(record.get("id"))
        temp = path.with_name(path.name + ".tmp")
        self.dir.mkdir(parents=True, exist_ok=True)
        temp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temp, path)
        self._prune(keep=path)
        return path

    def get(self, run_id) -> dict | None:
        """One run by id, or None when it is not there or does not read."""
        record = _load_record(self.path_for(run_id))
        return record if record is not None and record.get("kind") == RUN_KIND else None

    def summaries(self) -> list:
        """Every readable run, newest first, as the few fields a list needs.

        A torn or foreign file is left out rather than failing the list: the list
        is for finding a run, and one bad file must not hide the other nineteen.
        """
        out = []
        for run_id in self._ids():
            record = _load_record(self.dir / (run_id + ".json"))
            if record is None or record.get("kind") != RUN_KIND:
                continue
            plan = [step for step in record.get("plan") or [] if isinstance(step, dict)]
            out.append({
                "id": run_id,
                "at": record.get("at"),
                "brief": str(record.get("brief") or "")[:160],
                "done": bool(record.get("done")),
                "steps": len(plan),
                "settled": sum(1 for step in plan if step.get("state") in ("ok", "skipped")),
            })
        return out

    def newest(self) -> dict | None:
        """The newest record worth resuming, or None when there is not one."""
        for run_id in self._ids():
            record = _load_record(self.dir / (run_id + ".json"))
            if record is not None and record.get("kind") == RUN_KIND:
                return record
        return None

    def _ids(self) -> list:
        """Every run's id, newest first. A `.tmp` is not a run."""
        try:
            names = [path.name for path in self.dir.glob("*.json")]
        except OSError:
            return []
        return sorted((name[: -len(".json")] for name in names), reverse=True)

    def _prune(self, keep: Path) -> int:
        """Keep the newest RUN_KEEP runs, plus the one just written.

        `keep` is load-bearing. A resumed run is old by id, so without it the run
        you are working on would be deleted the moment it saved -- silently, while
        the app reported it saved. The bound is therefore "the newest twenty, and
        whatever you are doing now", which is one file over at worst.
        """
        entries = []
        try:
            for path in self.dir.glob("*.json*"):
                name = path.name[: -len(".tmp")] if path.name.endswith(".tmp") else path.name
                # `<id>.json` and `<id>.json.tmp` are the same run, so they sort
                # together and a `.tmp` left by a killed save is swept too.
                entries.append((name, path))
        except OSError:
            return 0
        entries.sort(key=lambda entry: entry[0], reverse=True)
        ordered = [path for _, path in entries]
        rows = ordered[:RUN_KEEP]
        if keep not in rows:
            # it takes the last slot rather than being an extra one, which is only
            # reachable for a resumed run: old by id, and the one you are on
            rows = ordered[: max(0, RUN_KEEP - 1)] + [keep]
        removed = 0
        for path in ordered:
            if path in rows:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed


def _load_record(path: Path):
    """A record, or None if that file is missing, torn, or not an object."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return record if isinstance(record, dict) else None


# --------------------------------------------------------------------------- #
# http surface
# --------------------------------------------------------------------------- #


def origin_allowed(origin, allow_file_origin: bool = False, port: int | None = None) -> bool:
    """Only this app, or a non-browser caller, may drive the bridge.

    A browser always sends Origin on a cross-origin request, so a missing header
    means a local script -- which already had the right to run commands anyway.
    Given `port`, the origin must be this bridge's own port: any other dev server
    on localhost is a different site, and must not be able to fire the hands.
    """
    if origin is None:
        return True
    if origin == "null":
        return allow_file_origin
    try:
        parsed = urlparse(origin)
        host = (parsed.hostname or "").lower()
        origin_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return False
    if host not in LOOPBACK_HOSTS:
        return False
    return port is None or origin_port == port


def host_allowed(host_header, port: int) -> bool:
    """The Host header must name this bridge on loopback.

    A same-origin GET carries no Origin, so without this a DNS-rebinding page
    (evil.example resolving to 127.0.0.1) could read the run record and the tool
    list. Its Host would still say evil.example, which is what this refuses.
    """
    if host_header is None:
        return True  # HTTP/1.0 scripts; a browser always sends Host
    try:
        parsed = urlparse("//" + host_header)
        host = (parsed.hostname or "").lower()
        host_port = parsed.port or 80
    except ValueError:
        return False
    return host in LOOPBACK_HOSTS and host_port == port


class Bridge:
    """Holds the mutable things: the tool folder, the audit log, the runs."""

    def __init__(self, root: Path, dry_run: bool = False, token: str | None = None):
        self.root = root
        # The secret every /api call but health must carry. One per process, so
        # a stopped bridge's token is worth nothing to the next one.
        self.token = token or secrets.token_urlsafe(32)
        self.tools_dir = root / "tools"
        self.dry_run = dry_run
        self.limiter = RateLimiter()
        self.audit = Audit(self.tools_dir / ".audit.jsonl")
        self.runs = RunStore(root)
        self.lock = threading.Lock()
        self.tools: dict = {}
        self.problems: list = []
        # When a browser last spoke to us, so the launcher can tell a live app
        # window from one that has been closed. The launcher's own probe is
        # urllib, not Mozilla, so it does not count as a window.
        self.last_browser = 0.0
        self.reload()

    def note_browser(self, user_agent: str = "") -> None:
        if "Mozilla/" in (user_agent or ""):
            self.last_browser = time.monotonic()

    def window_idle(self):
        """Seconds since the app window last spoke, or None if it never has."""
        if not self.last_browser:
            return None
        return round(time.monotonic() - self.last_browser, 1)

    def reload(self) -> None:
        tools, problems = load_tools(self.tools_dir)
        with self.lock:
            self.tools, self.problems = tools, problems

    def get(self, tool_id: str) -> Tool:
        with self.lock:
            tool = self.tools.get(tool_id)
        if tool is None:
            raise ToolError(f"no such tool: {tool_id}")
        return tool


def make_handler(bridge: Bridge, allow_file_origin: bool, verbose: bool = False):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"agent-tornado-hands/{VERSION}"
        protocol_version = "HTTP/1.1"

        # ---- helpers ---------------------------------------------------- #

        def log_message(self, fmt, *args):
            if verbose:
                sys.stderr.write(f"[hands] {self.address_string()} {fmt % args}\n")

        def _cors(self):
            if allow_file_origin:
                self.send_header("Access-Control-Allow-Origin", "null")
                self.send_header("Access-Control-Allow-Headers", f"Content-Type, {TOKEN_HEADER}")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _send(self, status: int, body, content_type="application/json; charset=utf-8"):
            bridge.note_browser(self.headers.get("User-Agent", ""))
            if not isinstance(body, (bytes, bytearray)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _fail(self, status: int, message: str):
            self._send(status, {"error": message})

        def _authorised(self) -> bool:
            origin = self.headers.get("Origin")
            host = self.headers.get("Host")
            port = self.server.server_address[1]
            if not (origin_allowed(origin, allow_file_origin, port) and host_allowed(host, port)):
                bridge.audit.write({"event": "denied", "origin": str(origin)[:200],
                                    "host": str(host)[:200], "path": self.path[:200]})
                self._fail(403, "This bridge only answers the app it is serving.")
                return False
            route = urlparse(self.path).path
            # Health is the launcher's probe, and says nothing a caller could use.
            # Static files are the app's own code, and hold no secret. Everything
            # else under /api is the hands, and needs the token.
            if route == "/api/health" or not route.startswith("/api/"):
                return True
            given = self.headers.get(TOKEN_HEADER) or ""
            if hmac.compare_digest(given.encode(), bridge.token.encode()):
                return True
            bridge.audit.write({"event": "denied", "reason": "token", "path": self.path[:200]})
            self._fail(401, "This bridge needs the token it was started with -- open the app "
                            "with ./launch.command (or python3 hands.py --start --open).")
            return False

        def _body(self) -> dict:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                raise ToolError("bad Content-Length")
            if length <= 0:
                return {}
            if length > MAX_BODY:
                raise ToolError("request body too large")
            raw = self.rfile.read(length)
            try:
                parsed = json.loads(raw.decode("utf-8"))
            except ValueError as exc:
                raise ToolError(f"invalid JSON body: {exc}")
            if not isinstance(parsed, dict):
                raise ToolError("body must be a JSON object")
            return parsed

        # ---- routes ----------------------------------------------------- #

        def do_OPTIONS(self):  # noqa: N802
            self.send_response(204)
            self._cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):  # noqa: N802
            if not self._authorised():
                return
            route = urlparse(self.path).path
            if route == "/api/health":
                with bridge.lock:
                    count = len(bridge.tools)
                return self._send(200, {
                    "ok": True,
                    "version": VERSION,
                    "root": str(bridge.root),
                    "tools": count,
                    "dryRun": bridge.dry_run,
                    "toolsDir": str(bridge.tools_dir),
                    # seconds since the app window last polled, or null if none ever has
                    "appWindowIdle": bridge.window_idle(),
                })
            if route == "/api/tools":
                with bridge.lock:
                    published = [t.public() for t in bridge.tools.values()]
                    problems = list(bridge.problems)
                published.sort(key=lambda t: t["id"])
                return self._send(200, {"tools": published, "problems": problems, "dryRun": bridge.dry_run})
            if route == "/api/log":
                return self._send(200, {"entries": bridge.audit.tail(60)})
            if route == "/api/run":
                wanted = parse_qs(urlparse(self.path).query).get("id")
                if not wanted:
                    return self._send(200, {"ok": True, "record": bridge.runs.newest()})
                try:
                    record = bridge.runs.get(wanted[0])
                except ToolError as exc:
                    return self._fail(400, str(exc))
                if record is None:
                    return self._fail(404, "no saved run with that id")
                return self._send(200, {"ok": True, "record": record})
            if route == "/api/runs":
                return self._send(200, {"ok": True, "runs": bridge.runs.summaries()})
            if route.startswith("/api/"):
                return self._fail(404, "no such endpoint")
            return self._static(route)

        def do_POST(self):  # noqa: N802
            if not self._authorised():
                return
            route = urlparse(self.path).path
            try:
                payload = self._body()
            except ToolError as exc:
                return self._fail(400, str(exc))

            if route == "/api/reload":
                bridge.reload()
                with bridge.lock:
                    count = len(bridge.tools)
                return self._send(200, {"ok": True, "tools": count})

            if route == "/api/install":
                try:
                    name = safe_manifest_name(payload.get("filename", ""))
                    contents = payload.get("content")
                    if not isinstance(contents, str) or not contents.strip():
                        raise ToolError("nothing to install")
                    loaded = validate_manifest_text(contents)
                    target = bridge.tools_dir / name
                    if target.exists() and not payload.get("overwrite"):
                        raise ToolError(f"{name} already exists -- pass overwrite to replace it")
                    bridge.tools_dir.mkdir(parents=True, exist_ok=True)
                    target.write_text(contents, encoding="utf-8")
                except ToolError as exc:
                    bridge.audit.write({"event": "install", "ok": False, "error": str(exc)})
                    return self._fail(400, str(exc))
                bridge.reload()
                bridge.audit.write({"event": "install", "file": name,
                                    "tools": [t.id for t in loaded], "ok": True})
                return self._send(200, {"ok": True, "file": name, "tools": [t.id for t in loaded]})

            if route == "/api/uninstall":
                try:
                    if not payload.get("confirm"):
                        raise ToolError("removing a tool needs confirm: true")
                    name = safe_manifest_name(payload.get("filename", ""))
                    target = bridge.tools_dir / name
                    if not target.is_file():
                        raise ToolError(f"no manifest called {name}")
                    target.unlink()
                except ToolError as exc:
                    bridge.audit.write({"event": "uninstall", "ok": False, "error": str(exc)})
                    return self._fail(400, str(exc))
                bridge.reload()
                bridge.audit.write({"event": "uninstall", "file": name, "ok": True})
                return self._send(200, {"ok": True, "file": name})

            if route == "/api/run":
                record = payload.get("record")
                if not isinstance(record, dict) or record.get("kind") != RUN_KIND:
                    return self._fail(400, f"a run record must be an object with kind {RUN_KIND!r}")
                try:
                    path = bridge.runs.write(record)
                except ToolError as exc:
                    return self._fail(400, str(exc))
                # Only a finished run is worth a line: this route is called on every
                # step transition, and the audit log is the record of what the
                # machine did, not of how often the page said hello.
                if record.get("done"):
                    bridge.audit.write({"event": "run", "steps": len(record.get("plan") or []),
                                        "brief": str(record.get("brief") or "")[:120], "ok": True})
                return self._send(200, {"ok": True, "path": str(path)})

            if route != "/api/invoke":
                return self._fail(404, "no such endpoint")

            tool_id = str(payload.get("id") or "")
            try:
                tool = bridge.get(tool_id)
            except ToolError as exc:
                bridge.audit.write({"event": "invoke", "tool": tool_id, "ok": False, "error": str(exc)})
                return self._fail(404, str(exc))

            wait = bridge.limiter.take()
            if wait > 0:
                bridge.audit.write({"event": "ratelimited", "tool": tool_id, "wait": wait})
                return self._fail(429, f"rate limit: try again in {wait}s")

            started = time.monotonic()
            dry = bridge.dry_run or bool(payload.get("dryRun"))
            try:
                args = coerce_args(tool, payload.get("args") or {})
                result = execute(tool, args, bool(payload.get("confirm")), dry)
            except ToolError as exc:
                bridge.audit.write({"event": "invoke", "tool": tool_id, "ok": False, "error": str(exc)})
                return self._fail(400, str(exc))
            except subprocess.TimeoutExpired:
                bridge.audit.write({"event": "invoke", "tool": tool_id, "ok": False, "error": "timeout"})
                return self._fail(504, f"{tool.id} timed out after {tool.timeout}s")
            except Exception as exc:  # noqa: BLE001 - report, never crash the bridge
                bridge.audit.write({"event": "invoke", "tool": tool_id, "ok": False, "error": repr(exc)})
                return self._fail(500, f"{type(exc).__name__}: {exc}")

            duration = round((time.monotonic() - started) * 1000)
            bridge.audit.write({
                "event": "invoke", "tool": tool_id, "ok": True,
                "args": args, "ms": duration, "confirm": bool(payload.get("confirm")),
                # the audit is the record of what the machine did: a per-request
                # dry run did nothing, and must not read as an execution
                "dryRun": dry,
            })
            return self._send(200, {"ok": True, "tool": tool_id, "ms": duration, "result": result})

        def _static(self, route: str):
            if route in ("/", ""):
                route = "/index.html"
            relative = route.lstrip("/")
            if relative.startswith(".") or ".." in Path(relative).parts:
                return self._fail(400, "bad path")
            target = (bridge.root / relative)
            try:
                resolved = target.resolve()
                if bridge.root.resolve() not in resolved.parents and resolved != bridge.root.resolve():
                    return self._fail(403, "outside the app folder")
            except OSError:
                return self._fail(400, "bad path")
            if not resolved.is_file():
                return self._fail(404, "not found")
            kind = STATIC_TYPES.get(resolved.suffix.lower())
            if kind is None:
                return self._fail(403, "that file type is not served")
            return self._send(200, resolved.read_bytes(), kind)

    return Handler


# --------------------------------------------------------------------------- #
# lifecycle -- start, stop, status
#
# This process *is* the app's only moving part, so it has to outlive the window
# that started it. `--start` therefore hands the server to a child in its own
# session: closing a Terminal signals the session it belongs to, and the bridge
# is no longer in it. What makes that safe rather than a leak is the record file
# in .run/ -- one obvious way back out, and the pid in it is never trusted on
# its own: the port is asked first, and the command line is checked before any
# signal is sent, because a pid gets recycled.
# --------------------------------------------------------------------------- #

RUN_DIR = ".run"
START_TIMEOUT = 15.0

# How long a window may stay quiet and still count as open. The app polls
# /api/health every 15s, so a live window is never near this; a window closed
# more than this ago is gone, and asking for the app should open a new one.
WINDOW_IDLE = 40.0

# Chromium-family browsers are the only ones that will give us a window with no
# browser in it. Safari has no equivalent flag, so it is not on this list.
APP_MODE_BROWSERS = (
    "Google Chrome", "Chromium", "Brave Browser", "Microsoft Edge",
    "Vivaldi", "Google Chrome Canary",
)


def run_dir(root: Path) -> Path:
    return root / RUN_DIR


def record_path(root: Path, port: int) -> Path:
    return run_dir(root) / f"bridge-{port}.pid"


def log_path(root: Path, port: int) -> Path:
    return run_dir(root) / f"bridge-{port}.log"


def read_record(path: Path) -> dict:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def write_record(path: Path, **fields) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # The record holds the bridge's token, so it is created private: opened
        # 0600 rather than written and then narrowed, which would leave a moment
        # when another user could read it.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(fields, indent=2) + "\n")
    except OSError:
        pass  # losing the record costs you --stop; it must never cost you the bridge


def clear_record(path: Path) -> bool:
    try:
        path.unlink()
        return True
    except OSError:
        return False


def health(port: int, timeout: float = 0.8) -> dict:
    """The bridge's own health route.

    This is also how *our* listener is told apart from some other program that
    happens to be holding the port -- a bound socket alone cannot say.
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as reply:
            body = json.loads(reply.read().decode("utf-8"))
    except Exception:
        return {}
    return body if isinstance(body, dict) and body.get("ok") else {}


def alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OverflowError):
        return True
    return True


# This file, resolved once. The launcher starts the bridge by absolute path, a
# direct run may name it relatively, and --root defaults to its folder -- so the
# identity check, the spawn, and the CLI default must all agree on one answer.
SELF_SCRIPT = Path(__file__).resolve()


def command_line(pid: int) -> str:
    """The target's full command line, exactly as `ps` reports it.

    Full, not tokenised: this app's own folder has spaces in its path, so
    splitting on whitespace would corrupt the very path the check depends on.
    """
    ps = shutil.which("ps") or "/bin/ps"
    try:
        result = subprocess.run([ps, "-p", str(pid), "-o", "command="],
                                capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip()


def process_cwd(pid: int) -> str:
    """Where the target is working, so a relative script path can be resolved."""
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    try:
        result = subprocess.run([lsof, "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
                                capture_output=True, text=True, timeout=6)
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            return line[1:]
    return ""


def _leading_path(rest: str) -> str:
    """The script token from the front of a command line.

    An absolute script path is taken whole -- a path with spaces cannot be
    recovered by splitting -- and any other path is the first token, then checked
    by resolution like any other candidate.
    """
    self_path = str(SELF_SCRIPT)
    if rest == self_path or rest.startswith(self_path + " "):
        return self_path
    return rest.split()[0]


def runs_this_script(command: str, pid: int) -> bool:
    """True when the command *runs* this script, not merely mentions its name.

    An editor, a grep, and a file that happens to be called test_hands.py all
    contain "hands.py"; none of them is the bridge. Identity is the interpreter,
    then the script it runs, resolved (against the target's own cwd when the path
    is relative) and compared to this file.
    """
    match = re.match(r"^\S*python[\d.]*\s+(.*)$", command, re.IGNORECASE)
    if not match:
        return False                     # vim, grep, bash: not an interpreter at all
    rest = match.group(1).strip()
    if re.match(r"^-[mc](?:\s|$)", rest):
        return False                     # a module or literal code, not a script file
    # strip leading single-token interpreter flags (`-u`, `-O`, `-B`, ...). The
    # script must survive this step, so a flag never consumes the next token.
    rest = re.sub(r"^(?:-\S+\s+)*", "", rest)
    if not rest:
        return False
    candidate = Path(_leading_path(rest))
    if not candidate.is_absolute():
        cwd = process_cwd(pid)
        if not cwd:
            return False                 # cannot resolve it, so cannot vouch for it
        candidate = Path(cwd) / candidate
    try:
        return candidate.resolve() == SELF_SCRIPT
    except OSError:
        return False


def is_this_bridge(pid: int) -> bool:
    """The guard on the kill: a recycled pid, a grep, or an editor must never cost."""
    if not alive(pid):
        return False
    command = command_line(pid)
    if not command:
        return False
    # A `--stop` invocation is the CLI telling a bridge to die; it is not one.
    if re.search(r"(?:^|\s)--stop(?:\s|$)", command):
        return False
    return runs_this_script(command, pid)


def port_owner(port: int) -> str:
    """Who holds the port, for the one error that needs to name a culprit."""
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    try:
        result = subprocess.run([lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fcp"],
                                capture_output=True, text=True, timeout=6)
    except (OSError, subprocess.SubprocessError):
        return ""
    pid, command = "", ""
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            pid = line[1:].strip()
        elif line.startswith("c") and not command:
            command = line[1:].strip()
    if command and pid:
        return f"{command}, pid {pid}"
    return command


def listener_pid(port: int) -> int:
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    try:
        result = subprocess.run([lsof, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
                                capture_output=True, text=True, timeout=6)
    except (OSError, subprocess.SubprocessError):
        return 0
    for line in result.stdout.split():
        if line.isdigit():
            return int(line)
    return 0


def activate_browser() -> str:
    """Bring the window you already have forward.

    `open -a` with no file is just "activate this app" -- it raises Chrome and
    its app window without asking it to open anything, which is the difference
    between a second double-click bringing the app forward and a second window
    appearing beside the first one.
    """
    if sys.platform != "darwin":
        return ""
    app = browser_app()
    if not app:
        return ""
    try:
        subprocess.run(["open", "-a", app], capture_output=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return f"{Path(app).stem}, the window you already had"


def browser_app() -> str:
    for name in APP_MODE_BROWSERS:
        for base in ("/Applications", str(Path.home() / "Applications")):
            candidate = Path(base) / f"{name}.app"
            if candidate.is_dir():
                return str(candidate)
    return ""


def app_url(url: str, token: str) -> str:
    """The app's address with its token in the fragment: the window reads it, and
    a browser never sends a fragment to any server, so it is not in a log."""
    return f"{url}#token={token}" if token else url


def open_app(url: str) -> str:
    """Open the app in a window with no browser around it. Returns how it went.

    `-n` is load-bearing: `open -a` drops --args when the app is already running,
    so without it there is no app window at all on the second launch. Chrome is a
    singleton per profile, so this command line is forwarded to the running copy
    rather than starting a rival instance beside it.
    """
    if sys.platform != "darwin":
        webbrowser.open(url)
        return "the default browser"
    app = browser_app()
    if app:
        try:
            subprocess.run(["open", "-na", app, "--args", f"--app={url}"],
                           capture_output=True, timeout=20, check=False)
            return f"{Path(app).stem}, no browser chrome"
        except (OSError, subprocess.SubprocessError):
            pass
    webbrowser.open(url)
    return "the default browser, as an ordinary window (no Chromium-family browser found)"


def log_tail(path: Path, lines: int = 8) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def wait_for_health(port: int, timeout: float, on_tick=None) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        served = health(port)
        if served:
            return served
        if on_tick is not None and on_tick():
            return {}
        time.sleep(0.15)
    return {}


def start(root: Path, port: int, open_window: bool, timeout: float = START_TIMEOUT) -> int:
    url = f"http://127.0.0.1:{port}/"
    record_file = record_path(root, port)
    record = read_record(record_file)

    served = health(port)
    if not served and record and alive(int(record.get("pid") or 0)) and is_this_bridge(int(record["pid"])):
        # A bridge that is up but not yet answering is not a reason to start a
        # second one: they would fight over the port and one would die.
        served = wait_for_health(port, 3.0)

    if served:
        print(f"agent tornado is already running on port {port} — bringing the app forward.")
        print(f"  app        {url}")
        if record.get("pid"):
            print(f"  pid        {record['pid']}")
        print(f"  serving    {served.get('root', '?')}")
        print(f"  tools      {served.get('tools', '?')} loaded")
        if open_window:
            # A window that is still polling does not need another one opened
            # beside it; a window that has gone quiet does.
            idle = served.get("appWindowIdle")
            keyed = app_url(url, str(record.get("token") or ""))
            if isinstance(idle, (int, float)) and idle <= WINDOW_IDLE:
                print(f"  window     {activate_browser() or open_app(keyed)}")
            else:
                print(f"  window     {open_app(keyed)}")
        print(f"\n  to stop it: ./stop.command")
        return 0

    if record:
        print(f"  clearing a stale record for pid {record.get('pid', '?')} (that process is gone)")
        clear_record(record_file)

    owner = port_owner(port)
    if owner:
        print(f"port {port} is held by {owner}, and that is not agent tornado.", file=sys.stderr)
        print("  quit that program, or start this one somewhere else:", file=sys.stderr)
        print("      TORNADO_PORT=8801 ./launch.command", file=sys.stderr)
        return 2

    log = log_path(root, port)
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        handle = log.open("ab", buffering=0)
    except OSError as exc:
        print(f"could not open the log file {log}: {exc}", file=sys.stderr)
        return 3

    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        child = subprocess.Popen(
            [sys.executable, str(SELF_SCRIPT),
             "--port", str(port), "--root", str(root)],
            stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT,
            start_new_session=True,   # its own session: a closing Terminal cannot reach it
            cwd=str(root),
        )
    except OSError as exc:
        print(f"could not start the bridge: {exc}", file=sys.stderr)
        return 3
    finally:
        handle.close()

    served = wait_for_health(port, timeout, on_tick=lambda: child.poll() is not None)
    if not served:
        print(f"the bridge did not come up on port {port} within {int(timeout)}s.", file=sys.stderr)
        tail = log_tail(log)
        if tail:
            print(f"  last lines of {log}:", file=sys.stderr)
            for line in tail.splitlines():
                print(f"    {line}", file=sys.stderr)
        if child.poll() is None:
            child.terminate()
        return 3

    # The serving process records itself, so the record and the listener cannot
    # disagree; this is only the backstop for the moment before it writes one.
    if not read_record(record_file):
        write_record(record_file, pid=child.pid, port=port, url=url, root=str(root), started=started_at)

    print(f"agent tornado is running on port {port}.")
    print(f"  app        {url}")
    print(f"  pid        {child.pid}")
    print(f"  tools      {served.get('tools', '?')} loaded")
    print(f"  log        {log}")
    print(f"  survives   closing this window — the bridge runs in its own session")
    if open_window:
        keyed = app_url(url, str(read_record(record_file).get("token") or ""))
        print(f"  window     {open_app(keyed)}")
    print(f"\n  to stop it: ./stop.command")
    return 0


def stop(root: Path, port: int, timeout: float = 8.0) -> int:
    record_file = record_path(root, port)
    record = read_record(record_file)
    recorded = int(record.get("pid") or 0)
    served = health(port)

    if not served and not recorded:
        print(f"agent tornado is not running on port {port}.")
        return 1

    target = recorded if (recorded and alive(recorded) and is_this_bridge(recorded)) else 0
    if not target:
        # No usable record -- ask the port instead, and still check before killing.
        candidate = listener_pid(port)
        target = candidate if is_this_bridge(candidate) else 0

    if not target:
        print(f"nothing was stopped: port {port} is either free or held by something that is not agent tornado.", file=sys.stderr)
        if recorded and not alive(recorded):
            clear_record(record_file)
            print(f"  (a stale record for pid {recorded} was removed)", file=sys.stderr)
        return 1

    try:
        os.kill(target, signal.SIGTERM)
    except OSError as exc:
        print(f"could not signal pid {target}: {exc}", file=sys.stderr)
        return 1

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and health(port):
        time.sleep(0.15)
    if health(port):
        print(f"pid {target} did not stop after {int(timeout)}s — forcing it.", file=sys.stderr)
        try:
            os.kill(target, signal.SIGKILL)
        except OSError:
            pass
        wait_for_health(port, 3.0)

    clear_record(record_file)
    print(f"agent tornado stopped (pid {target}).")
    return 0


def status(root: Path, port: int) -> int:
    served = health(port)
    record = read_record(record_path(root, port))
    if not served:
        print(f"agent tornado is not running on port {port}.")
        if record:
            print(f"  a stale record for pid {record.get('pid', '?')} is still in .run/ — ./stop.command clears it")
        return 1
    print(f"agent tornado is running on port {port}.")
    print(f"  app        http://127.0.0.1:{port}/")
    print(f"  pid        {record.get('pid', '?')}")
    print(f"  serving    {served.get('root', '?')}")
    print(f"  tools      {served.get('tools', '?')} loaded")
    print(f"  dry run    {'on' if served.get('dryRun') else 'off'}")
    if record.get("started"):
        print(f"  started    {record['started']}")
    return 0


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #


def check(root: Path) -> int:
    tools, problems = load_tools(root / "tools")
    for tool_id, tool in sorted(tools.items()):
        print(f"  ok   {tool_id:24} {tool.kind:10} from {tool.source}")
    for problem in problems:
        print(f"  FAIL {problem['file']:24} {problem['error']}")
    print(f"\n{len(tools)} tool(s) valid, {len(problems)} problem(s)")
    return 1 if problems else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="hands.py", description="agent tornado local bridge")
    parser.add_argument("--host", default="127.0.0.1", help="loopback only unless you know why")
    parser.add_argument("--port", type=int, default=8800)
    parser.add_argument("--root", default=str(SELF_SCRIPT.parent), help="the app folder to serve")
    parser.add_argument("--start", action="store_true",
                        help="start in the background (idempotent), then exit")
    parser.add_argument("--stop", action="store_true", help="stop a running bridge")
    parser.add_argument("--status", action="store_true", help="report whether it is running")
    parser.add_argument("--open", action="store_true",
                        help="open the app in its own window (a plain browser elsewhere)")
    parser.add_argument("--check", action="store_true", help="validate manifests and exit")
    parser.add_argument("--dry-run", action="store_true", help="plan tool calls but never execute them")
    parser.add_argument("--allow-file-origin", action="store_true",
                        help="also accept Origin: null, so a file:// page can call the bridge")
    parser.add_argument("--verbose", action="store_true", help="log every request (off by default)")
    args = parser.parse_args(argv)

    root = Path(args.root).expanduser().resolve()
    if args.check:
        return check(root)
    if args.status:
        return status(root, args.port)
    if args.stop:
        return stop(root, args.port)
    if args.start:
        return start(root, args.port, args.open)

    if Path(args.host).name not in ("127.0.0.1", "localhost", "::1"):
        print(f"refusing to bind {args.host}: this bridge executes commands.", file=sys.stderr)
        return 2

    bridge = Bridge(root, dry_run=args.dry_run)
    handler = make_handler(bridge, args.allow_file_origin, verbose=args.verbose)
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    except OSError as exc:
        owner = port_owner(args.port)
        print(f"port {args.port} is not usable: {exc}", file=sys.stderr)
        if owner:
            print(f"  it is already held by {owner}", file=sys.stderr)
        print("  quit that program, or pick another port:  TORNADO_PORT=8801 ./launch.command", file=sys.stderr)
        return 2

    url = f"http://127.0.0.1:{args.port}/"
    record_file = record_path(root, args.port)
    # The process that serves is the process that records, so the record and the
    # listener can never disagree about who is on this port.
    write_record(record_file, pid=os.getpid(), port=args.port, url=url, root=str(root),
                 started=datetime.now().astimezone().isoformat(timespec="seconds"),
                 token=bridge.token)

    with bridge.lock:
        count = len(bridge.tools)
    print(f"agent tornado hands {VERSION}")
    print(f"  app        {url}")
    print(f"  tools      {count} loaded from {bridge.tools_dir}")
    for problem in bridge.problems:
        print(f"  manifest   FAIL {problem['file']}: {problem['error']}")
    if args.dry_run:
        print("  dry run    ON -- tool calls are planned, never executed")
    print("  ctrl-c to stop\n")

    if args.open:
        threading.Timer(0.4, lambda: open_app(app_url(url, bridge.token))).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
        clear_record(record_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
