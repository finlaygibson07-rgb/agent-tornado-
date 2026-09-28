#!/usr/bin/env python3
"""Tests for hands.py.  Run with:  python3 -m unittest -v test_hands

The bridge executes commands, so the interesting tests are the refusals: what it
will not run, which paths it will not touch, and who it will not answer.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest import mock
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hands  # noqa: E402


def free_port() -> int:
    """A port nothing is on, handed back to the kernel to give to the bridge."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def sleeper(*args: str) -> subprocess.Popen:
    """A live process whose arguments mention whatever is passed, kept simple on
    purpose: it exists to be *looked at* by the identity check, never run."""
    return subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)", *args],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def manifest(**over):
    base = {"id": "probe", "name": "Probe", "kind": "shell", "argv": ["/bin/echo", "{text}"],
            "args": {"text": {"type": "string", "required": True}}}
    base.update(over)
    return base


class ToolManifestTest(unittest.TestCase):
    def test_accepts_a_minimal_shell_tool(self):
        tool = hands.Tool(manifest(), "t.json")
        self.assertEqual(tool.id, "probe")
        self.assertEqual(tool.kind, "shell")
        self.assertFalse(tool.confirm)

    def test_rejects_a_bad_id(self):
        for bad in ("", "Upper", "with space", "-leading", "a"):
            with self.subTest(bad=bad), self.assertRaises(hands.ToolError):
                hands.Tool(manifest(id=bad), "t.json")

    def test_rejects_an_unknown_kind(self):
        with self.assertRaises(hands.ToolError):
            hands.Tool(manifest(kind="rm-rf"), "t.json")

    def test_rejects_shell_without_argv(self):
        with self.assertRaises(hands.ToolError):
            hands.Tool(manifest(argv=[]), "t.json")

    def test_rejects_argv_placeholder_that_was_never_declared(self):
        with self.assertRaises(hands.ToolError):
            hands.Tool(manifest(argv=["/bin/echo", "{sneaky}"]), "t.json")

    def test_rejects_a_file_tool_with_no_roots(self):
        with self.assertRaises(hands.ToolError):
            hands.Tool({"id": "r", "kind": "file-read", "args": {}}, "t.json")

    def test_rejects_a_relative_root(self):
        with self.assertRaises(hands.ToolError):
            hands.Tool({"id": "r", "kind": "file-read", "roots": ["relative/path"], "args": {}}, "t.json")

    def test_file_write_is_always_destructive_even_if_it_says_otherwise(self):
        tool = hands.Tool({"id": "writer", "kind": "file-write", "roots": ["/tmp"], "confirm": False, "args": {}}, "t.json")
        self.assertTrue(tool.confirm, "a write tool must never be able to opt out of confirmation")

    def test_http_needs_a_url(self):
        with self.assertRaises(hands.ToolError):
            hands.Tool({"id": "h", "kind": "http", "args": {}}, "t.json")


class ArgCoercionTest(unittest.TestCase):
    def setUp(self):
        self.tool = hands.Tool(manifest(args={
            "text": {"type": "string", "required": True},
            "count": {"type": "int", "default": 3},
            "loud": {"type": "bool", "default": False},
            "mode": {"type": "string", "enum": ["a", "b"]},
        }), "t.json")

    def test_missing_required_is_refused(self):
        with self.assertRaises(hands.ToolError):
            hands.coerce_args(self.tool, {})

    def test_unknown_argument_is_refused(self):
        with self.assertRaises(hands.ToolError):
            hands.coerce_args(self.tool, {"text": "x", "--danger": "1"})

    def test_types_are_coerced(self):
        got = hands.coerce_args(self.tool, {"text": "hi", "count": "7", "loud": "true"})
        self.assertEqual(got, {"text": "hi", "count": 7, "loud": True})

    def test_defaults_apply_including_false(self):
        got = hands.coerce_args(self.tool, {"text": "hi"})
        self.assertEqual(got["count"], 3)
        self.assertIs(got["loud"], False)

    def test_a_non_numeric_int_is_refused(self):
        with self.assertRaises(hands.ToolError):
            hands.coerce_args(self.tool, {"text": "hi", "count": "many"})

    def test_enum_is_enforced(self):
        with self.assertRaises(hands.ToolError):
            hands.coerce_args(self.tool, {"text": "hi", "mode": "c"})


class SubstituteTest(unittest.TestCase):
    def test_replaces_declared_names(self):
        self.assertEqual(hands.substitute("a {x} b", {"x": 1}), "a 1 b")

    def test_refuses_an_unknown_name(self):
        with self.assertRaises(hands.ToolError):
            hands.substitute("{nope}", {})

    def test_does_not_evaluate_anything(self):
        # no shell, no $(), no backticks -- the value lands as literal argv text
        evil = "$(rm -rf /) `whoami` ; echo"
        self.assertEqual(hands.substitute("/bin/echo {v}", {"v": evil}), "/bin/echo " + evil)


class PathContainmentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "inside").mkdir()
        (self.root / "inside" / "note.txt").write_text("hello", encoding="utf-8")
        self.outside = Path(self.tmp.name + "-outside")
        self.outside.mkdir()

    def tearDown(self):
        self.tmp.cleanup()
        for child in self.outside.iterdir():
            child.unlink()
        self.outside.rmdir()

    def test_allows_a_path_inside_the_root(self):
        got = hands.resolve_within_roots(str(self.root / "inside" / "note.txt"), [str(self.root)])
        self.assertEqual(got.name, "note.txt")

    def test_refuses_the_root_itself_as_traversal(self):
        # the root is allowed, but a sibling of it is not
        with self.assertRaises(hands.ToolError):
            hands.resolve_within_roots(str(self.outside / "x"), [str(self.root)])

    def test_refuses_dot_dot(self):
        with self.assertRaises(hands.ToolError):
            hands.resolve_within_roots(str(self.root / ".." / "elsewhere"), [str(self.root)])

    def test_refuses_a_relative_path(self):
        with self.assertRaises(hands.ToolError):
            hands.resolve_within_roots("inside/note.txt", [str(self.root)])

    def test_refuses_a_symlink_that_escapes_the_root(self):
        link = self.root / "inside" / "escape"
        try:
            link.symlink_to(self.outside)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks unavailable here")
        with self.assertRaises(hands.ToolError):
            hands.resolve_within_roots(str(link / "x"), [str(self.root)])


class ExecuteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_shell_tool_actually_runs(self):
        tool = hands.Tool(manifest(), "t.json")
        result = hands.execute(tool, {"text": "hello"}, confirmed=False)
        self.assertEqual(result["exit"], 0)
        self.assertIn("hello", result["output"])

    def test_arguments_are_never_shell_interpreted(self):
        tool = hands.Tool(manifest(), "t.json")
        result = hands.execute(tool, {"text": "; echo pwned"}, confirmed=False)
        self.assertIn("; echo pwned", result["output"])
        self.assertNotIn("\npwned", result["output"])

    def test_destructive_tool_needs_confirmation(self):
        tool = hands.Tool({"id": "writer", "kind": "file-write", "roots": [str(self.root)],
                           "args": {"path": {"type": "string", "required": True},
                                    "content": {"type": "string", "required": True}}}, "t.json")
        target = self.root / "note.md"
        with self.assertRaises(hands.ToolError):
            hands.execute(tool, {"path": str(target), "content": "x"}, confirmed=False)
        self.assertFalse(target.exists(), "a refused call must not have written anything")

    def test_write_then_read_round_trips(self):
        writer = hands.Tool({"id": "writer", "kind": "file-write", "roots": [str(self.root)],
                             "args": {"path": {"type": "string", "required": True},
                                      "content": {"type": "string", "required": True}}}, "t.json")
        reader = hands.Tool({"id": "reader", "kind": "file-read", "roots": [str(self.root)],
                             "args": {"path": {"type": "string", "required": True}}}, "t.json")
        target = self.root / "out" / "note.md"
        hands.execute(writer, {"path": str(target), "content": "# hi"}, confirmed=True)
        self.assertEqual(hands.execute(reader, {"path": str(target)}, confirmed=False)["output"], "# hi")

    def test_dry_run_executes_nothing(self):
        tool = hands.Tool({"id": "writer", "kind": "file-write", "roots": [str(self.root)],
                           "args": {"path": {"type": "string", "required": True},
                                    "content": {"type": "string", "required": True}}}, "t.json")
        target = self.root / "never.md"
        result = hands.execute(tool, {"path": str(target), "content": "x"}, confirmed=True, dry_run=True)
        self.assertTrue(result["dryRun"])
        self.assertFalse(target.exists())

    def test_reading_a_directory_is_refused(self):
        tool = hands.Tool({"id": "reader", "kind": "file-read", "roots": [str(self.root)],
                           "args": {"path": {"type": "string", "required": True}}}, "t.json")
        with self.assertRaises(hands.ToolError):
            hands.execute(tool, {"path": str(self.root)}, confirmed=False)


class LoadToolsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, payload):
        text = payload if isinstance(payload, str) else json.dumps(payload)
        (self.dir / name).write_text(text, encoding="utf-8")

    def test_reads_both_single_and_grouped_manifests(self):
        self.write("one.json", manifest(id="one"))
        self.write("many.json", {"tools": [manifest(id="two"), manifest(id="three")]})
        tools, problems = hands.load_tools(self.dir)
        self.assertEqual(sorted(tools), ["one", "three", "two"])
        self.assertEqual(problems, [])

    def test_a_broken_manifest_does_not_stop_the_others(self):
        self.write("bad.json", "{ not json")
        self.write("good.json", manifest(id="good"))
        tools, problems = hands.load_tools(self.dir)
        self.assertEqual(list(tools), ["good"])
        self.assertEqual(len(problems), 1)
        self.assertIn("invalid JSON", problems[0]["error"])

    def test_duplicate_ids_are_reported_not_silently_overwritten(self):
        self.write("a.json", manifest(id="same"))
        self.write("b.json", manifest(id="same"))
        tools, problems = hands.load_tools(self.dir)
        self.assertEqual(list(tools), ["same"])
        self.assertEqual(len(problems), 1)
        self.assertIn("duplicate", problems[0]["error"])

    def test_hidden_files_are_skipped(self):
        self.write(".hidden.json", manifest(id="hidden"))
        tools, _ = hands.load_tools(self.dir)
        self.assertEqual(list(tools), [])

    def test_a_missing_folder_is_not_an_error(self):
        tools, problems = hands.load_tools(self.dir / "nope")
        self.assertEqual(tools, {})
        self.assertEqual(problems, [])


class InstallHelpersTest(unittest.TestCase):
    def test_names_are_reduced_to_a_bare_json_file(self):
        for given, want in (
            ("my-tool.json", "my-tool.json"),
            ("my-tool", "my-tool.json"),
            ("../../etc/passwd", "passwd.json"),
            ("/tmp/evil.JSON", "evil.json"),
            ("has spaces.json", "has-spaces.json"),
        ):
            with self.subTest(given=given):
                self.assertEqual(hands.safe_manifest_name(given), want)

    def test_an_empty_name_is_refused(self):
        for bad in ("", "   ", "..", "/"):
            with self.subTest(bad=bad), self.assertRaises(hands.ToolError):
                hands.safe_manifest_name(bad)

    def test_validates_before_writing(self):
        self.assertEqual(len(hands.validate_manifest_text(json.dumps(manifest(id="fine")))), 1)
        self.assertEqual(len(hands.validate_manifest_text(json.dumps({"tools": [manifest(id="a1"), manifest(id="b2")]}))), 2)
        for bad in ("{ not json", "{}", json.dumps({"tools": []}), json.dumps({"id": "x", "kind": "nope"})):
            with self.subTest(bad=bad[:20]), self.assertRaises(hands.ToolError):
                hands.validate_manifest_text(bad)


class ShellArgumentTest(unittest.TestCase):
    """A shell hand's arguments are data. They may not leave the roots, and they
    may not turn into options for the program they are handed to."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "a.test.js").write_text("", encoding="utf-8")
        self.runner = hands.Tool({
            "id": "runner", "kind": "shell", "roots": [str(self.root)],
            "argv": ["/bin/echo", "{file}"],
            "args": {"file": {"type": "path", "required": True}},
        }, "t.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_path_argument_inside_the_roots_runs(self):
        target = str(self.root / "a.test.js")
        self.assertEqual(hands.plan(self.runner, {"file": target})["argv"], ["/bin/echo", target])

    def test_a_path_argument_outside_the_roots_is_refused(self):
        with self.assertRaises(hands.ToolError) as caught:
            hands.plan(self.runner, {"file": "/etc/passwd"})
        self.assertIn("outside every declared root", str(caught.exception))

    def test_a_path_argument_cannot_climb_out(self):
        with self.assertRaises(hands.ToolError):
            hands.plan(self.runner, {"file": str(self.root / ".." / "elsewhere")})

    def test_a_dry_run_is_held_to_the_same_roots(self):
        with self.assertRaises(hands.ToolError):
            hands.execute(self.runner, {"file": "/etc/passwd"}, confirmed=True, dry_run=True)

    def test_a_value_that_looks_like_an_option_is_refused(self):
        tool = hands.Tool(manifest(argv=["/usr/bin/env", "node", "--test", "{text}"]), "t.json")
        for bad in ("--eval=require('child_process').execSync('id')", "-e", "--require=/tmp/x.js"):
            with self.subTest(bad=bad), self.assertRaises(hands.ToolError) as caught:
                hands.execute(tool, {"text": bad}, confirmed=True)
            self.assertIn("would be read as an option", str(caught.exception))

    def test_a_dash_is_fine_after_a_literal_double_dash(self):
        tool = hands.Tool(manifest(argv=["/bin/echo", "--", "{text}"]), "t.json")
        self.assertEqual(hands.plan(tool, {"text": "-x"})["argv"], ["/bin/echo", "--", "-x"])

    def test_a_dash_inside_a_manifest_option_is_the_manifests_own(self):
        tool = hands.Tool(manifest(argv=["/bin/echo", "--label={text}"]), "t.json")
        self.assertEqual(hands.plan(tool, {"text": "-x"})["argv"], ["/bin/echo", "--label=-x"])

    def test_a_path_argument_needs_roots_to_be_held_to(self):
        with self.assertRaises(hands.ToolError) as caught:
            hands.Tool(manifest(argv=["/bin/ls", "{dir}"],
                                args={"dir": {"type": "path", "required": True}}), "t.json")
        self.assertIn("needs at least one 'roots'", str(caught.exception))

    def test_every_shipped_shell_hand_holds_its_paths_to_roots(self):
        tools, problems = hands.load_tools(Path(__file__).resolve().parent / "tools")
        self.assertEqual(problems, [])
        for tool in tools.values():
            if tool.kind != "shell":
                continue
            for name, spec in tool.args.items():
                if "path" in name or name in ("repo", "file", "dir"):
                    with self.subTest(tool=tool.id, arg=name):
                        self.assertEqual(spec["type"], "path", f"{tool.id}.{name} is not held to roots")


class HttpHandTest(unittest.TestCase):
    """An http hand stays on this machine unless its manifest says otherwise."""

    def test_a_loopback_url_loads(self):
        tool = hands.Tool({"id": "local", "kind": "http", "url": "http://127.0.0.1:11434/api/tags"}, "t.json")
        self.assertFalse(tool.allow_remote)

    def test_a_remote_url_needs_the_flag(self):
        with self.assertRaises(hands.ToolError) as caught:
            hands.Tool({"id": "remote", "kind": "http", "url": "https://api.example.com/x"}, "t.json")
        self.assertIn("allowRemote", str(caught.exception))
        tool = hands.Tool({"id": "remote", "kind": "http", "url": "https://api.example.com/x",
                           "allowRemote": True}, "t.json")
        self.assertTrue(tool.allow_remote)

    def test_the_host_cannot_come_from_an_argument(self):
        with self.assertRaises(hands.ToolError):
            hands.Tool({"id": "aimed", "kind": "http", "url": "http://{host}/x", "allowRemote": True,
                        "args": {"host": {"type": "string"}}}, "t.json")


class OriginTest(unittest.TestCase):
    def test_missing_origin_is_allowed(self):
        self.assertTrue(hands.origin_allowed(None))

    def test_loopback_origins_are_allowed(self):
        for origin in ("http://127.0.0.1:8799", "http://localhost:1234", "http://[::1]:80"):
            with self.subTest(origin=origin):
                self.assertTrue(hands.origin_allowed(origin))

    def test_a_remote_page_is_refused(self):
        for origin in ("https://evil.example", "http://192.168.1.9:8799", "http://127.0.0.1.evil.com"):
            with self.subTest(origin=origin):
                self.assertFalse(hands.origin_allowed(origin))

    def test_file_origin_needs_the_flag(self):
        self.assertFalse(hands.origin_allowed("null"))
        self.assertTrue(hands.origin_allowed("null", allow_file_origin=True))

    def test_another_loopback_port_is_another_site(self):
        self.assertTrue(hands.origin_allowed("http://127.0.0.1:8799", port=8799))
        self.assertTrue(hands.origin_allowed("http://localhost:8799", port=8799))
        for origin in ("http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1"):
            with self.subTest(origin=origin):
                self.assertFalse(hands.origin_allowed(origin, port=8799))

    def test_host_must_name_this_bridge(self):
        self.assertTrue(hands.host_allowed("127.0.0.1:8799", 8799))
        self.assertTrue(hands.host_allowed("localhost:8799", 8799))
        self.assertTrue(hands.host_allowed(None, 8799))
        for host in ("evil.example:8799", "127.0.0.1:3000", "127.0.0.1.evil.com:8799", "evil.example"):
            with self.subTest(host=host):
                self.assertFalse(hands.host_allowed(host, 8799))


class RateLimiterTest(unittest.TestCase):
    def test_allows_a_burst_then_makes_you_wait(self):
        limiter = hands.RateLimiter(tokens=3, window=60)
        self.assertEqual([limiter.take() for _ in range(3)], [0.0, 0.0, 0.0])
        self.assertGreater(limiter.take(), 0)


class AuditTest(unittest.TestCase):
    def test_appends_and_tails(self):
        with tempfile.TemporaryDirectory() as tmp:
            audit = hands.Audit(Path(tmp) / "log.jsonl")
            audit.write({"event": "invoke", "tool": "a"})
            audit.write({"event": "invoke", "tool": "b"})
            entries = audit.tail(10)
            self.assertEqual([e["tool"] for e in entries], ["a", "b"])
            self.assertIn("ts", entries[0])

    def test_an_unwritable_log_does_not_raise(self):
        audit = hands.Audit(Path("/definitely/not/writable/log.jsonl"))
        audit.write({"event": "invoke"})  # must not raise


class HttpSurfaceTest(unittest.TestCase):
    """Boots the real server and talks to it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        # The app folder is a subdirectory on purpose: the escape tests assert that
        # nothing was written *outside* it, and if it were the temp folder itself
        # that check would be about the shared system temp dir -- where any stray
        # file from another run would fail a test that has nothing to do with it.
        cls.root = Path(cls.tmp.name) / "app"
        (cls.root / "tools").mkdir(parents=True)
        (cls.root / "index.html").write_text("<h1>app</h1>", encoding="utf-8")
        (cls.root / "tools" / "t.json").write_text(json.dumps({
            "tools": [
                manifest(id="echo", argv=["/bin/echo", "{text}"], matches=["echo"]),
                {"id": "escape", "kind": "file-read", "roots": [str(cls.root)],
                 "args": {"path": {"type": "string", "required": True}}},
            ]
        }), encoding="utf-8")
        cls.bridge = hands.Bridge(cls.root)
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), hands.make_handler(cls.bridge, False))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.tmp.cleanup()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def get(self, path, origin=None):
        request = urllib.request.Request(self.url(path))
        if origin:
            request.add_header("Origin", origin)
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())

    def post(self, path, payload, origin=None):
        request = urllib.request.Request(
            self.url(path), data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        if origin:
            request.add_header("Origin", origin)
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())

    def test_health(self):
        status, body = self.get("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["tools"], 2)

    def test_tools_listing_never_leaks_the_command(self):
        _, body = self.get("/api/tools")
        ids = [t["id"] for t in body["tools"]]
        self.assertEqual(ids, ["echo", "escape"])
        blob = json.dumps(body)
        # the manifest's argv is the one thing a caller must not be able to read
        # or influence, so the listing describes the tool without publishing it
        self.assertNotIn("/bin/echo", blob)
        self.assertNotIn('"argv":', blob)

    def test_install_then_invoke_round_trip(self):
        body = json.dumps({"tools": [manifest(id="installed", argv=["/bin/echo", "{text}"])]})
        status, out = self.post("/api/install", {"filename": "dropped.json", "content": body})
        self.assertEqual(status, 200)
        self.assertEqual(out["tools"], ["installed"])
        _, listing = self.get("/api/tools")
        self.assertIn("installed", [t["id"] for t in listing["tools"]])
        _, called = self.post("/api/invoke", {"id": "installed", "args": {"text": "works"}})
        self.assertIn("works", called["result"]["output"])
        self.post("/api/uninstall", {"filename": "dropped.json", "confirm": True})

    def test_install_refuses_to_clobber_without_overwrite(self):
        body = json.dumps(manifest(id="clobber"))
        self.post("/api/install", {"filename": "clobber.json", "content": body})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/install", {"filename": "clobber.json", "content": body})
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("overwrite", json.loads(caught.exception.read())["error"])
        status, _ = self.post("/api/install", {"filename": "clobber.json", "content": body, "overwrite": True})
        self.assertEqual(status, 200)
        self.post("/api/uninstall", {"filename": "clobber.json", "confirm": True})

    def test_install_refuses_a_broken_manifest_and_writes_nothing(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/install", {"filename": "broken.json", "content": "{ nope"})
        self.assertEqual(caught.exception.code, 400)
        self.assertFalse((self.root / "tools" / "broken.json").exists())

    def test_install_cannot_write_outside_the_tools_folder(self):
        self.post("/api/install", {"filename": "../../escape.json",
                                  "content": json.dumps(manifest(id="escapee"))})
        self.assertFalse((self.root.parent / "escape.json").exists())
        self.assertTrue((self.root / "tools" / "escape.json").exists())
        self.post("/api/uninstall", {"filename": "escape.json", "confirm": True})

    def test_uninstall_needs_confirmation(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/uninstall", {"filename": "t.json"})
        self.assertEqual(caught.exception.code, 400)
        self.assertTrue((self.root / "tools" / "t.json").exists(), "it deleted without a confirmation")

    def test_per_request_dry_run_does_not_execute(self):
        status, body = self.post("/api/invoke", {"id": "echo", "args": {"text": "x"}, "dryRun": True})
        self.assertEqual(status, 200)
        self.assertTrue(body["result"]["dryRun"])
        self.assertIn("/bin/echo", body["result"]["plan"]["argv"])
        # ...and the audit says so, rather than recording an execution
        last = [e for e in self.bridge.audit.tail(50) if e.get("event") == "invoke" and e.get("ok")][-1]
        self.assertTrue(last["dryRun"], "a per-request dry run was audited as an execution")

    def test_serves_the_app(self):
        request = urllib.request.Request(self.url("/"))
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"<h1>app</h1>", response.read())

    def test_invokes_a_tool(self):
        status, body = self.post("/api/invoke", {"id": "echo", "args": {"text": "hi there"}})
        self.assertEqual(status, 200)
        self.assertEqual(body["result"]["exit"], 0)
        self.assertIn("hi there", body["result"]["output"])

    def test_refuses_an_unknown_tool(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/invoke", {"id": "nope", "args": {}})
        self.assertEqual(caught.exception.code, 404)

    def test_refuses_an_escaped_path_over_http(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/invoke", {"id": "escape", "args": {"path": "/etc/passwd"}})
        self.assertEqual(caught.exception.code, 400)
        payload = json.loads(caught.exception.read())
        self.assertIn("outside every declared root", payload["error"])

    def test_refuses_a_foreign_origin(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/health", origin="https://evil.example")
        self.assertEqual(caught.exception.code, 403)

    def test_refuses_another_localhost_port(self):
        # another dev server on this machine is another site: it may not fire hands
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/invoke", {"id": "echo", "args": {"text": "x"}},
                      origin=f"http://127.0.0.1:{self.port + 1}")
        self.assertEqual(caught.exception.code, 403)

    def test_answers_its_own_origin(self):
        status, _ = self.get("/api/health", origin=f"http://127.0.0.1:{self.port}")
        self.assertEqual(status, 200)

    def test_refuses_a_rebound_host(self):
        # DNS rebinding: a same-origin GET carries no Origin, only a foreign Host
        request = urllib.request.Request(self.url("/api/run"), headers={"Host": f"evil.example:{self.port}"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 403)

    def test_refuses_an_option_smuggled_in_as_an_argument(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.post("/api/invoke", {"id": "echo", "args": {"text": "--version"}})
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("would be read as an option", json.loads(caught.exception.read())["error"])

    def test_reload_picks_up_a_new_manifest(self):
        (self.root / "tools" / "extra.json").write_text(
            json.dumps(manifest(id="late")), encoding="utf-8")
        status, body = self.post("/api/reload", {})
        self.assertEqual(status, 200)
        self.assertEqual(body["tools"], 3)
        (self.root / "tools" / "extra.json").unlink()
        self.post("/api/reload", {})

    def test_the_audit_log_records_both_outcomes(self):
        self.post("/api/invoke", {"id": "echo", "args": {"text": "ok"}})
        try:
            self.post("/api/invoke", {"id": "echo", "args": {}})
        except urllib.error.HTTPError:
            pass
        _, body = self.get("/api/log")
        tools = [e.get("tool") for e in body["entries"]]
        self.assertIn("echo", tools)
        self.assertTrue(any(e.get("ok") is False for e in body["entries"]))

    def runs_dir(self):
        return self.root / "runs"

    def clear_runs(self):
        for path in self.runs_dir().glob("*"):
            path.unlink()

    def run_files(self):
        return sorted(path.name for path in self.runs_dir().glob("*.json"))

    @staticmethod
    def record(run_id, brief="echo one; echo two", states=("ok",), done=True):
        return {"kind": "agent-tornado-run", "version": 1, "id": run_id, "brief": brief,
                "done": done,
                "plan": [{"clause": f"step {i}", "tool": "echo", "state": state,
                          "attempts": 0, "output": ""} for i, state in enumerate(states)]}

    def test_a_saved_run_comes_back_from_the_bridge(self):
        self.clear_runs()
        record = self.record("2026-09-22T10-00-00-000Z-0001")
        status, out = self.post("/api/run", {"record": record})
        self.assertEqual(status, 200)
        _, body = self.get("/api/run")
        self.assertEqual(body["record"], record)
        # and it lands on disk as something you can read, not a blob
        written = (self.runs_dir() / (record["id"] + ".json")).read_text(encoding="utf-8")
        self.assertIn("\n  ", written, "the record was written on one unreadable line")
        self.assertEqual(json.loads(written), record)
        self.clear_runs()

    def test_an_empty_run_store_answers_with_no_record(self):
        self.clear_runs()
        status, body = self.get("/api/run")
        self.assertEqual(status, 200)
        self.assertIsNone(body["record"], "an empty store must read as no run, not as an error")

    def test_a_torn_run_file_reads_as_no_run_rather_than_a_crash(self):
        # The save is atomic, so this should not happen -- but if the machine dies
        # at the wrong moment the next boot must still come up.
        self.clear_runs()
        self.runs_dir().mkdir(exist_ok=True)
        (self.runs_dir() / "2026-09-22T10-00-00-000Z-0001.json").write_text(
            '{"kind": "agent-tornado-run", "pla', encoding="utf-8")
        status, body = self.get("/api/run")
        self.assertEqual(status, 200)
        self.assertIsNone(body["record"], "a half-written record broke the bridge instead of reading as none")
        self.clear_runs()

    def test_a_second_run_does_not_disturb_the_first(self):
        self.clear_runs()
        first = self.record("2026-09-22T10-00-00-000Z-0001", brief="the first task")
        second = self.record("2026-09-22T10-00-01-000Z-0001", brief="the second task",
                             states=("ok", "idle"), done=False)
        self.post("/api/run", {"record": first})
        self.post("/api/run", {"record": second})
        # the first run's file is still there, and still says what the first run did
        kept = json.loads((self.runs_dir() / (first["id"] + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(kept, first, "the second run overwrote the first run's record")
        self.assertEqual(len(self.run_files()), 2)
        self.clear_runs()

    def test_the_newest_run_is_the_one_offered(self):
        self.clear_runs()
        ids = [f"2026-09-22T10-00-0{i}-000Z-0001" for i in range(3)]
        for index, run_id in enumerate(ids):
            self.post("/api/run", {"record": self.record(run_id, brief=f"task {index}")})
        _, body = self.get("/api/run")
        self.assertEqual(body["record"]["id"], ids[-1], "the store did not offer the newest run")
        self.clear_runs()

    def test_a_run_that_never_settled_is_not_offered_as_the_newest(self):
        self.clear_runs()
        good = self.record("2026-09-22T10-00-00-000Z-0001", brief="the run that landed")
        self.post("/api/run", {"record": good})
        # Three ways a save can fail to settle, all newer than the good one: torn,
        # empty, and something that parses but is not one of ours.
        newer = self.runs_dir() / "2026-09-22T10-00-09-000Z-0001.json"
        for label, contents in (("torn", '{"kind": "agent-tornado-run", "brief": "half a'),
                                ("empty", ""),
                                ("not ours", '{"notes": "something else entirely"}')):
            with self.subTest(unsettled=label):
                newer.write_text(contents, encoding="utf-8")
                _, body = self.get("/api/run")
                self.assertEqual(body["record"]["id"], good["id"],
                                 f"a {label} newest record was offered as the newest run")
        newer.unlink()
        # and a save interrupted before the rename leaves no record at all
        (self.runs_dir() / "2026-09-22T10-00-10-000Z-0001.json.tmp").write_text("{", encoding="utf-8")
        _, body = self.get("/api/run")
        self.assertEqual(body["record"]["id"], good["id"])
        self.clear_runs()

    def test_a_record_with_nothing_in_it_is_still_the_newest(self):
        self.clear_runs()
        finished = self.record("2026-09-22T10-00-00-000Z-0001", brief="the run before")
        self.post("/api/run", {"record": finished})
        # What a cleared run writes. It must win, or a reload would resurrect the
        # run you just cleared -- which is why "never settled" cannot mean "empty".
        cleared = self.record("2026-09-22T10-00-01-000Z-0001", brief="", states=(), done=False)
        self.post("/api/run", {"record": cleared})
        _, body = self.get("/api/run")
        self.assertEqual(body["record"]["id"], cleared["id"])
        self.assertEqual(body["record"]["plan"], [])
        self.clear_runs()

    def test_only_the_newest_runs_are_kept(self):
        self.clear_runs()
        ids = [f"2026-09-22T10-{i:02d}-00-000Z-0001" for i in range(hands.RUN_KEEP + 3)]
        for run_id in ids:
            self.post("/api/run", {"record": self.record(run_id)})
        files = self.run_files()
        self.assertEqual(len(files), hands.RUN_KEEP, f"retention left {len(files)} records on disk")
        for dropped in ids[:3]:
            self.assertNotIn(dropped + ".json", files, "retention dropped a record it should have kept")
        self.assertIn(ids[-1] + ".json", files)
        self.clear_runs()

    def test_the_run_being_written_is_never_the_one_dropped(self):
        self.clear_runs()
        ids = [f"2026-09-22T10-{i:02d}-00-000Z-0001" for i in range(hands.RUN_KEEP + 2)]
        for run_id in ids:
            self.post("/api/run", {"record": self.record(run_id)})
        # A resumed run keeps writing to its own old id, so retention has to spare
        # the record it is writing or a long-lived run would lose its state on
        # every save -- silently, and while the app reported it saved.
        resumed = self.record(ids[0], brief="the run I resumed", states=("ok", "running"), done=False)
        self.post("/api/run", {"record": resumed})
        kept = json.loads((self.runs_dir() / (ids[0] + ".json")).read_text(encoding="utf-8"))
        self.assertEqual(kept["brief"], "the run I resumed",
                         "the run being written was pruned out from under it")
        self.assertEqual(kept["plan"][1]["state"], "running")
        self.clear_runs()

    def test_every_saved_run_is_listed_newest_first(self):
        self.clear_runs()
        older = self.record("2026-09-22T10-00-00-000Z-0001", brief="the first task")
        newer = self.record("2026-09-22T11-00-00-000Z-0001", brief="the second task", done=False)
        self.post("/api/run", {"record": older})
        self.post("/api/run", {"record": newer})
        (self.runs_dir() / "2026-09-22T12-00-00-000Z-0001.json").write_text("{ torn", encoding="utf-8")
        _, body = self.get("/api/runs")
        self.assertEqual([run["id"] for run in body["runs"]], [newer["id"], older["id"]],
                         "a torn file hid the list, or the order is not newest first")
        first = body["runs"][1]
        self.assertEqual(first["brief"], "the first task")
        self.assertEqual(first["steps"], len(older["plan"]))
        self.assertEqual(set(first), {"id", "at", "brief", "done", "steps", "settled"},
                         "the list carries whole records instead of summaries")
        self.clear_runs()

    def test_an_older_run_can_be_opened_by_id(self):
        self.clear_runs()
        older = self.record("2026-09-22T10-00-00-000Z-0001", brief="the first task")
        self.post("/api/run", {"record": older})
        self.post("/api/run", {"record": self.record("2026-09-22T11-00-00-000Z-0001", brief="later")})
        _, body = self.get("/api/run?id=" + older["id"])
        self.assertEqual(body["record"]["brief"], "the first task")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/run?id=2026-01-01T00-00-00-000Z-0001")
        self.assertEqual(caught.exception.code, 404)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/api/run?id=..%2F..%2Fescape")
        self.assertEqual(caught.exception.code, 400)
        self.clear_runs()

    def test_a_run_id_cannot_climb_out_of_the_folder(self):
        self.clear_runs()
        for bad in ("../../escape", "a/b", "", "..", "x" * 80):
            with self.subTest(bad=bad), self.assertRaises(urllib.error.HTTPError) as caught:
                self.post("/api/run", {"record": self.record(bad)})
            self.assertEqual(caught.exception.code, 400)
            self.assertFalse((self.root.parent / "escape.json").exists(), "an id wrote outside runs/")
        self.assertEqual(self.run_files(), [], "a refused id still left a file behind")
        self.clear_runs()

    def test_a_body_that_is_not_a_run_is_refused(self):
        self.clear_runs()
        record = self.record("2026-09-22T10-00-00-000Z-0001", brief="keep me", states=(), done=False)
        self.post("/api/run", {"record": record})
        for bad in ({"record": {"kind": "something-else"}}, {"record": "not an object"}, {}):
            with self.subTest(bad=bad), self.assertRaises(urllib.error.HTTPError) as caught:
                self.post("/api/run", bad)
            self.assertEqual(caught.exception.code, 400)
        _, body = self.get("/api/run")
        self.assertEqual(body["record"]["brief"], "keep me",
                         "a refused save clobbered the run that was already there")
        self.clear_runs()

    def test_a_static_path_cannot_escape_the_root(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get("/../etc/passwd")
        self.assertIn(caught.exception.code, (400, 403, 404))

    def test_check_command_passes_on_the_real_manifests(self):
        app = Path(__file__).resolve().parent
        result = subprocess.run([sys.executable, str(app / "hands.py"), "--check"],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("0 problem(s)", result.stdout)


class LifecycleTest(unittest.TestCase):
    """The launcher's verbs, driving a real bridge on a port of its own.

    This is the double-click path minus the browser: `--start` forks the server
    into its own session exactly as the launcher does, so the detachment that
    makes closing a Terminal harmless is asserted here rather than asserted in
    prose. Nothing in this class touches the default port, and every test stops
    whatever it started, even on failure.
    """

    def setUp(self):
        self.app = Path(__file__).resolve().parent
        # resolved, because the bridge resolves --root before it serves it, and
        # /var is a symlink to /private/var on macOS.
        self.root = Path(tempfile.mkdtemp(prefix="tornado-life-")).resolve()
        (self.root / "tools").mkdir()
        self.port = free_port()
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        # A bridge left behind by a failed assertion would hold a port for the
        # rest of the session, so the cleanup is unconditional.
        self.addCleanup(self.verb, "--stop")

    def verb(self, *args, timeout=45):
        return subprocess.run(
            [sys.executable, str(self.app / "hands.py"), *args,
             "--port", str(self.port), "--root", str(self.root)],
            capture_output=True, text=True, timeout=timeout, cwd=str(self.app))

    def record(self):
        return hands.read_record(hands.record_path(self.root, self.port))

    def assert_serving(self):
        served = hands.health(self.port, timeout=2)
        self.assertTrue(served, "nothing is answering on the port")
        return served

    def assert_not_serving(self):
        self.assertFalse(hands.health(self.port, timeout=2), "something is still answering")

    # ---- the verbs -------------------------------------------------------- #

    def test_status_reports_nothing_running_rather_than_guessing(self):
        result = self.verb("--status")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not running", result.stdout)

    def test_start_serves_the_app_and_records_what_it_started(self):
        result = self.verb("--start")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        served = self.assert_serving()
        self.assertEqual(served["root"], str(self.root))

        record = self.record()
        self.assertTrue(record, "no record was written, so --stop cannot find it")
        self.assertEqual(record["port"], self.port)
        self.assertEqual(record["root"], str(self.root))
        self.assertTrue(hands.alive(record["pid"]), "the recorded pid is not running")
        self.assertTrue(hands.is_this_bridge(record["pid"]), "the record points at something else")

    def test_the_bridge_is_in_its_own_session_not_the_launchers(self):
        self.assertEqual(self.verb("--start").returncode, 0)
        pid = self.record()["pid"]
        # A Terminal closing sends SIGHUP to its own session. Being in a separate
        # session is the whole reason that cannot reach the bridge.
        self.assertNotEqual(os.getsid(pid), os.getsid(0), "the bridge shares this session")
        self.assertNotEqual(os.getpgid(pid), os.getpgid(0), "the bridge shares this process group")

    def test_starting_twice_leaves_one_bridge_and_one_pid(self):
        self.assertEqual(self.verb("--start").returncode, 0)
        first = self.record()["pid"]

        again = self.verb("--start")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("already running", again.stdout)
        self.assertEqual(self.record()["pid"], first, "the second start began a second bridge")
        self.assertTrue(hands.alive(first))

    def test_status_names_the_bridge_that_is_running(self):
        self.assertEqual(self.verb("--start").returncode, 0)
        pid = self.record()["pid"]
        result = self.verb("--status")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(str(pid), result.stdout)
        self.assertIn(str(self.root), result.stdout)

    def test_stop_frees_the_port_and_clears_the_record(self):
        self.assertEqual(self.verb("--start").returncode, 0)
        pid = self.record()["pid"]

        result = self.verb("--stop")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(str(pid), result.stdout)
        self.assert_not_serving()
        self.assertFalse(hands.alive(pid), "the process outlived the stop")
        self.assertEqual(self.record(), {}, "the record was left behind")

    def test_stop_says_so_when_there_is_nothing_to_stop(self):
        result = self.verb("--stop")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not running", result.stdout)

    # ---- the awkward cases ------------------------------------------------ #

    def test_a_stale_record_is_cleared_rather_than_trusted(self):
        # A pid that has certainly existed and certainly finished.
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        hands.write_record(hands.record_path(self.root, self.port),
                           pid=dead.pid, port=self.port, root=str(self.root))

        stopped = self.verb("--stop")
        self.assertEqual(stopped.returncode, 1, stopped.stdout + stopped.stderr)
        self.assertEqual(self.record(), {}, "a record for a dead pid was left in place")

        # and a stale record must not stop a start from working
        self.assertEqual(self.verb("--start").returncode, 0)
        self.assert_serving()

    def test_a_port_held_by_someone_else_is_named_not_taken(self):
        holder = socket.socket()
        self.addCleanup(holder.close)
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        self.port = holder.getsockname()[1]

        result = self.verb("--start")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("not agent tornado", result.stderr)
        self.assertEqual(self.record(), {}, "a record was written for a bridge that never started")

    def test_it_refuses_to_kill_a_process_that_is_not_the_bridge(self):
        # The kill is guarded by identity, because pids get recycled and a name
        # turns up in more command lines than it should.
        self.assertFalse(hands.is_this_bridge(os.getpid()))
        self.assertFalse(hands.is_this_bridge(1))
        self.assertEqual(self.verb("--start").returncode, 0)
        self.assertTrue(hands.is_this_bridge(self.record()["pid"]))

    def test_identity_is_interpreter_plus_script_not_a_substring(self):
        # Every false positive the old substring check produced, in one place: an
        # editor, a grep, a module run, a shell wrapper, and a differently-placed
        # copy. None may be signalled, whatever its arguments happen to mention.
        with mock.patch.object(hands, "process_cwd", return_value=str(self.app)):
            for command in (f"python3 {hands.SELF_SCRIPT} --port 8800",
                            "python3 hands.py --port 8800",
                            "python3 ./hands.py",
                            "python3 -u hands.py"):
                self.assertTrue(hands.runs_this_script(command, 1), command)
            for command in ("python3 test_hands.py",
                            "python3 -m unittest test_hands",
                            "python3 -m unittest",
                            "vim hands.py",
                            "grep -r hands.py .",
                            "rg --files -g hands.py",
                            "bash -c python3 /abs/hands.py",
                            "python3 /other/place/hands.py",
                            "python3 -c import hands",
                            ""):
                self.assertFalse(hands.runs_this_script(command, 1), command)

    def test_a_process_that_only_mentions_hands_py_is_not_the_bridge(self):
        # A real process whose arguments contain the name, exactly the class the
        # old check mistook for the bridge.
        decoy = sleeper("hands.py")
        self.addCleanup(decoy.wait)
        self.addCleanup(decoy.kill)

        self.assertIn("hands.py", hands.command_line(decoy.pid),
                      "the decoy does not even mention the name being guarded against")
        self.assertFalse(hands.is_this_bridge(decoy.pid),
                         "a process that merely mentions hands.py was taken for the bridge")

    def test_a_different_hands_py_is_not_this_bridge(self):
        # Two files can share the name; only the one in this app folder is the
        # bridge. Resolving the relative path against the process's own cwd is
        # what tells them apart, so a stop here can never reach someone else's copy.
        elsewhere = self.root / "somewhere-else"
        elsewhere.mkdir()
        (elsewhere / "hands.py").write_text("import time\ntime.sleep(120)\n")
        impostor = subprocess.Popen([sys.executable, "hands.py"], cwd=str(elsewhere),
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
        self.addCleanup(impostor.wait)
        self.addCleanup(impostor.kill)

        self.assertIn("hands.py", hands.command_line(impostor.pid))
        self.assertFalse(hands.is_this_bridge(impostor.pid),
                         "another file called hands.py was taken for this bridge")

    def test_the_direct_script_form_is_recognised_through_its_working_directory(self):
        # `python3 hands.py ...` leaves no absolute path in the command line, so
        # the only way to tell it from an impostor is to resolve the relative
        # script against the process's own cwd -- exactly what the CLI would do.
        child = subprocess.Popen(
            [sys.executable, "hands.py", "--port", str(self.port), "--root", str(self.root)],
            cwd=str(self.app), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(child.wait)
        self.addCleanup(child.terminate)

        self.assertTrue(hands.wait_for_health(self.port, 15), "the relative-form bridge never came up")
        command = hands.command_line(child.pid)
        self.assertIn("hands.py", command)
        self.assertNotIn(str(self.app / "hands.py"), command,
                         "this form was supposed to be relative, not absolute")
        self.assertTrue(hands.is_this_bridge(child.pid), "the direct script form was not recognised")

        # It is still reachable through the same door that stopped the launcher's.
        stopped = self.verb("--stop")
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.assert_not_serving()

    def test_stopping_the_bridge_leaves_a_decoy_untouched(self):
        # The whole point of the guard, end to end: a stop must kill the bridge
        # and nothing else, even with a decoy sitting right beside it.
        self.assertEqual(self.verb("--start").returncode, 0)
        bridge_pid = self.record()["pid"]

        decoy = sleeper("hands.py")
        self.addCleanup(decoy.wait)
        self.addCleanup(decoy.kill)

        self.assertTrue(hands.is_this_bridge(bridge_pid), "the real bridge was not recognised")
        self.assertFalse(hands.is_this_bridge(decoy.pid), "the decoy was taken for the bridge")

        stopped = self.verb("--stop")
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.assertFalse(hands.alive(bridge_pid), "the real bridge survived the stop")
        self.assertIsNone(decoy.poll(), "the stop killed a process that only mentioned hands.py")

    def test_a_poisoned_record_does_not_cost_a_decoy(self):
        # The record is written by the serving process, but a stale or copied
        # .run/ can name anything. When it does, the port still decides -- and
        # the kill still has to pass identity, so the decoy named by the record lives.
        self.assertEqual(self.verb("--start").returncode, 0)
        bridge_pid = self.record()["pid"]

        decoy = sleeper("hands.py")
        self.addCleanup(decoy.wait)
        self.addCleanup(decoy.kill)
        hands.write_record(hands.record_path(self.root, self.port),
                           pid=decoy.pid, port=self.port, root=str(self.root))

        stopped = self.verb("--stop")
        self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
        self.assertFalse(hands.alive(bridge_pid), "the bridge that actually served the port was not stopped")
        self.assertIsNone(decoy.poll(), "the record's pid was signalled even though it was a decoy")

    def test_stop_refuses_to_kill_whatever_else_holds_the_port(self):
        # A live process that is not the bridge is sitting on the port, and the
        # record even names it (its arguments mention hands.py, to be sure the
        # decision is identity and not a name). The stop must name the culprit
        # and refuse, never signal whatever happens to be listening.
        holder = subprocess.Popen(
            [sys.executable, "-c",
             "import socket, time; s = socket.socket(); "
             f"s.bind(('127.0.0.1', {self.port})); s.listen(1); time.sleep(120)",
             "hands.py"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        for _ in range(50):
            if hands.listener_pid(self.port) == holder.pid:
                break
            time.sleep(0.1)
        self.assertEqual(hands.listener_pid(self.port), holder.pid, "the holder never took the port")
        hands.write_record(hands.record_path(self.root, self.port),
                           pid=holder.pid, port=self.port, root=str(self.root))

        result = self.verb("--stop")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("not agent tornado", result.stderr)
        self.assertIsNone(holder.poll(), "the stop killed a process that is not the bridge")

    def test_records_are_kept_per_port(self):
        self.assertEqual(self.verb("--start").returncode, 0)
        other = free_port()
        result = subprocess.run(
            [sys.executable, str(self.app / "hands.py"), "--status",
             "--port", str(other), "--root", str(self.root)],
            capture_output=True, text=True, timeout=30, cwd=str(self.app))
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("not running", result.stdout)

    def test_the_bridge_knows_whether_an_app_window_is_polling(self):
        bridge = hands.Bridge(self.root)
        self.assertIsNone(bridge.window_idle(), "a fresh bridge claims a window it has never seen")
        bridge.note_browser("Python-urllib/3.9")
        self.assertIsNone(bridge.window_idle(), "the launcher's own probe counted as a window")
        bridge.note_browser("Mozilla/5.0 (Macintosh) AppleWebKit/537.36 Chrome/153.0 Safari/537.36")
        idle = bridge.window_idle()
        self.assertIsNotNone(idle)
        self.assertLess(idle, 5.0)

        self.assertEqual(self.verb("--start").returncode, 0)
        served = self.assert_serving()
        self.assertIsNone(served["appWindowIdle"], "no window has polled, but the health route says otherwise")


if __name__ == "__main__":
    unittest.main()
