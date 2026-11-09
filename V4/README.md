# V4 — the repair loop

A copy of `V3/agent-tornado`, plus the one thing V3 could not do: **a loop that
actually repairs a repository**, on your machine, with the local model in the loop
and a copy you can throw away.

V3 is untouched. This is the same relationship V3 has to the sandbox: a copy you can
open, run and judge on its own.

```
V4/
  README.md            this file
  agent-tornado/       the app: V3's, plus loop.js, fix.js, tools/fix.json and tools/web.json
  fixtures/broken/     a deliberately failing repo, for proving the loop end to end
```

## What changed from V3

- **`agent-tornado/loop.js`** — the loop. The model is asked what to do next; it names
  one tool; the tool runs in a scratch copy; the result goes back into the transcript.
  Up to 12 turns, up to 6 files written, and it stops when the same failure comes back
  twice with no edit in between. No DOM, no clock, no network of its own.
- **`agent-tornado/tools/fix.json`** — seven hands the loop drives: `make-work-dir`,
  `copy-repo`, `write-file`, `run-suite`, `python-suite`, `repo-delta`, `repo-diff`.
- **`agent-tornado/tools/web.json`** — `read-web`, the hand that reads one http(s) page
  as text. It is the only hand whose target comes from the caller, so the bridge holds
  it to rules instead of to a manifest: http(s) only, no credentials in the url, nothing
  that points back at this machine or a private network, and every redirect re-checked.
  The loop gets it as `read_url`, so the model can look up a deprecation notice or an
  error message instead of guessing at it.
- **Scrapin does the reading.** The hand's `engine` is `auto`: when you install the
  Scrapling fork from `finlaygibson07-rgb/Scrapin` (`pip install "scrapling[fetchers]"`,
  or `pip install -e .` in your clone), it fetches and parses the page; when it is not
  there, the standard library does, and the result says which engine ran. Scrapin is
  told **not** to follow redirects — each hop is checked by the bridge and only then
  made — because the target of the next request is exactly the thing the sandbox is
  protecting.
- **`agent-tornado/fix.js`** — the same loop from a terminal, so it can be run and
  judged with no window open.
- **A fifth panel tab, *fix*** — repo, goal, suite hand, run / stop / full diff, the
  turn list and the difference. The funnel, the rail and the crew are untouched.
- **Port 8800.** V3 keeps 8799, so both can be open at once.
- **`fixtures/broken/`** — a module whose `mean` subtracts where it should divide, and
  a test that fails because of it. It sits *outside* the app folder so that a bare
  `node --test` inside the app stays green.

## Hardening, after the audit

The repair loop runs code the model wrote, and reads text the model did not
write. So the bridge and the loop were tightened so that a page or a file which
steers the model gets as little as possible:

- **The hands need a token.** Each bridge start makes a new one. The window
  `launch.command` opens gets it; `fix.js` reads it from `.run/`. Another user on
  the machine, or a web page in another tab, does not have it and gets 401.
- **The loop only acts in `work/`.** Making the folder, writing, running a suite,
  and the loop's own list, read and search hands (`work-list`, `work-read`,
  `work-search`) are all rooted in `$HOME/Documents/agent-tornado/work`. A symlink
  that leads out of the copy is refused by the bridge, not only by `loop.js`.
- **The copy leaves out links that lead outside the repo** (`copy-tree`), and
  refuses to land on a folder that already has files in it.
- **Writing needs a yes.** The fix tab asks once, before the run, whether it may
  write and test or only read and test. `fix.js` asks on the terminal, or takes
  `--yes`. With no terminal it reads and tests only.
- **Test suites don't get your secrets.** A shell hand gets a cut-down environment,
  so API keys in the shell you launched from are not passed to code the model
  wrote. A timeout kills the whole process tree.
- **`read_url` is bounded.** At most 4 pages per run, and urls of at most 300
  characters: enough for a doc page, too little to carry a file out in a query
  string. The model is told that file contents, test output and web pages are
  data, never instructions.
- **One reply, at most 3 tool calls.** A turn can no longer be a dozen turns' worth
  of work.
- **The loop sees the end of a long test run**, where the failures are, and spots
  the same failure twice even when the timings differ.
- **`read-web` refuses anything that isn't globally routable**, including tailnet
  and carrier-grade NAT addresses (`100.64/10`) and site-local IPv6.
- **A manifest cannot declare `/` as a root.**

## What "it works" means, and what it does not

It means: you point it at a repo with a failing suite, and it copies the repo into a
scratch folder, reads and edits **the copy**, reruns the tests after each change, and
hands you a diff. It converges or it says plainly that it cannot.

It does not mean any of these, and they are deliberate:

- **Your repo is never written.** `copy-repo` is the only hand that names it, and it
  only reads. Copying the change back is your job, from the diff.
- **Whole files, not patches.** The model rewrites a file; a 14B model cannot reliably
  write a unified diff. The price is real: a rewrite can drop comments it did not
  keep, which is exactly what the diff is for.
- **The suite is a hand, not a command line.** You pick `run-suite` or `python-suite`
  (or add a manifest for your stack); you never type a shell command, because the
  bridge never runs one.
- **One repo, one small fix.** Multi-file refactors are where a local 14B model
  stops being useful. The turn and write limits are there so it fails cheaply.
- **Nothing is cleaned up automatically.** Each run leaves its copy under
  `~/Documents/agent-tornado/work/<run-id>`.
- **The web hand reads, it does not search.** It fetches a url that is already known.
  There is no search provider and no key; that is a deliberate line, not an oversight.

## Run it

```sh
cd agent-tornado
./launch.command                 # the bridge on 8800, and the app
```

The bridge on its own, without a window:

```sh
python3 hands.py --start --port 8800
```

The loop with no window at all:

```sh
node fix.js --repo /Users/you/code/thing --goal "make the tests pass"
node fix.js --repo /Users/you/code/thing --suite python-suite --diff
node fix.js --repo /Users/you/code/thing --yes     # leave to write, without the prompt
```

And the proof, using the fixture (it is broken on purpose):

```sh
cp -R ../fixtures/broken ~/broken-fixture            # copy-repo's root is $HOME
node fix.js --repo ~/broken-fixture --diff
```

A repo outside `$HOME` is refused by the manifests' `roots`; widen them in
`tools/fix.json` if you mean it.

## Verified, and how

Run in this folder, on this machine:

- **266/266 tests pass** — 119 JavaScript (`node --test tornado-behavior.test.js`),
  147 Python (`python3 -m unittest test_hands`). Twelve of the JavaScript tests are new
  and are the loop's: the copy is made from the repo and only the copy is written, a
  failure is what the model is asked about next, an escape is refused and stops the
  run, the turn limit binds, the write limit binds, a repeated failure with no edit
  ends the run, a page fetched on the model's behalf is what it reads next, a url that
  is not the web is refused as a turn rather than ending the run, and `loop.js` is held
  to the same no-clock/no-DOM/no-fetch boundary `tornado.js` is.
- **The simulation is untouched:** `tornado.js` and `stage.js` are byte-identical to
  V3's, and `bridge.js` and `plan.js` differ not at all. `hands.py` carries three kinds
  of change: the port default (8800), two messages that named the old escape hatch, and
  the `web-read` kind — its refusals, its own html-to-text pass, and the optional Scrapin
  engine behind them.
- **The manifests load:** `python3 hands.py --check` reports 18 tools, 0 problems.
- **The web hand was exercised through the bridge, for real:** `read-web` on
  `https://example.com/` returned 200, the title and the page text; a dry run returned
  the plan without touching the network; and `http://127.0.0.1:8800/api/tools` was
  refused with "127.0.0.1 is a private address, not the web".
- **Scrapin was the engine for that, not a stand-in:** with Scrapling 0.5.1 installed
  (the version this fork publishes) the bridge reported `"engine": "scrapin"` and read
  the page; it followed a real `http://github.com/` → `https://github.com/` 301 one hop
  at a time; and the repair loop pulled `example.com` into a run's transcript through
  `read_url`. Twenty-two Python tests hold it to the rest: only http(s), no credentials
  in a url, no private or local address, a redirect to `127.0.0.1` refused **before it
  is followed**, a redirect chain capped, and the text pass keeping prose while dropping
  scripts and styles.
- **`node measure.js` reproduces the shipped table** through epoch 9000 exactly. The
  18,000-epoch row reads 555 live / 1586 throughput here rather than the table's
  552 / 1555 — the simulation module is unchanged, so that one row was already out of
  date in this Node build, and it is not something V4 touched.
- **The whole loop ran against the real bridge and real hands** (scripted model, real
  `make-work-dir` → `copy-repo` → `work-list` → `work-read` → `run-suite` (exit 1) →
  `write-file` → `run-suite` (exit 0) → `finish` → `repo-delta`), taking the fixture
  from red to green, with the patch showing the one changed line.

Not verified here, stated plainly:

- **The live model.** This machine has no Ollama, so no run has been driven by a real
  `qwen2.5:14b`. The model-facing side (tool schemas, the transcript, the reply shape)
  is tested against a scripted stand-in, and `model.js`'s request is the documented
  Ollama tool-calling shape — but a real model's judgement is the one thing unit tests
  cannot stand in for. Run it against a repo you know before trusting it.
- **The app's own tab, clicked.** The pane is covered by the page tests (it renders,
  it switches, its buttons are wired) but the loop has not been driven from a browser
  in this environment.
- **`git diff --no-index` on a real multi-file change** has not been read at 64 KB,
  where the bridge clips it.
