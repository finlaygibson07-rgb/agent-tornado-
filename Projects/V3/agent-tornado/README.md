# agent tornado — SANDBOX TEST CHANGES

A standalone desktop tool. You give it a job — a small outline, if you like — and it
splits the job into a tree of steps, each step becomes an agent, and the agents raise
subagents that patch each other's weak traits, recursively, all the way down. It has
**hands**: a local bridge that lets it actually run tools you drop into a folder.

A **clone sandbox** of `Projects/agent-vortex`. Nothing here is canonical; the
visualiser in `Projects/agent-vortex` is untouched.

> [!warning] Sandbox only
> Everything in this folder is a *test* change. When something here proves out, port
> it back to `Projects/agent-vortex` deliberately rather than merging wholesale.

---

## Run it

Double-click **`agent tornado.app`**. No Terminal, no browser chrome: it starts the
bridge if it is not already up, opens the app in a window of its own, and exits. Close
nothing, keep nothing open. Double-click it again and it brings the window you already
have to the front instead of opening a second one.

To stop it, double-click **`stop.command`**. That is the one way out: closing the app
window deliberately does *not* stop the bridge, which is what lets the bridge outlive
windows and shells.

If you would rather see what it is doing, `launch.command` is the same thing with a
Terminal attached:

```sh
./launch.command            # start if needed, open the app, exit
./launch.command status     # is it up, on which pid, serving what
./launch.command stop       # the same stop as stop.command
TORNADO_PORT=8800 ./launch.command
```

Or by hand, from this folder — no verb serves in the foreground, which is what you want
while you are reading the log:

```sh
python3 hands.py --start         # the background start, without opening a window
python3 hands.py --status        # same as ./launch.command status
python3 hands.py --stop          # same as ./stop.command
python3 hands.py --check         # validate every tool manifest and exit
python3 hands.py --port 8800     # pick a port
python3 hands.py --dry-run       # validate and plan, never execute anything
python3 hands.py --verbose       # log every request
```

The app also opens straight from disk (`open index.html`). It works completely —
splitting, scheduling, learning, rendering — but with no hands, because the bridge is
what gives it hands. The rail says so rather than failing silently.

Python 3.9+ and a browser. Nothing to install: the bridge is stdlib only, and the app is
`index.html` beside the five modules it loads — markup, wiring and five plain scripts, no
build step.

### Where its state lives

Everything the launcher needs is in `.run/` next to the app: `bridge-<port>.pid` (who is
serving, and since when) and `bridge-<port>.log` (whatever the bridge would have printed).
It is written by the process that serves, so the record and the listener cannot disagree.
Deleting `.run/` is safe — the worst case is that `--stop` has to fall back to asking the
port who is on it.

Every run's own state is in `runs/`, one JSON file per run named by its start time: the
brief, every step with its state, retry count and output, and whether the run finished.
It is plain JSON because the record *is* the run's report — the same bytes *Export this
run as JSON* writes, readable with `less` when the app is not open.

The rules, and the reasons for them:

- **A run only ever writes its own file**, so building the next task cannot cost you the
  last one. Resuming a run writes back to its own record, so a long run is not split
  across files as it goes.
- **The write is a temp file and a rename**, so a save interrupted by a dead machine can
  cost you the newest state but never leaves half a record behind.
- **The newest record wins, by id rather than by mtime**, because the id carries the
  run's own clock: a folder copied between machines (or synced by iCloud) keeps its
  order. `GET /api/run` skips any file that will not read — a torn or half-written newest
  record means you resume the run before it, not that you resume nothing — and it skips
  anything that is not one of ours.
- **Twenty runs are kept** (`RUN_KEEP` in `hands.py`), plus the one you are working on,
  which is never the file that gets dropped. This matters because a resumed run is old by
  id: without that, the run you came back to would be deleted the moment it saved.

Deleting `runs/` is safe: the worst case is that the next launch starts with an empty
plan instead of resuming one.

Before any signal is sent, the target is identified exactly: its command line must be a
Python interpreter **running this `hands.py`**, with a relative path resolved against the
target's own working directory. A name is not an identity — an editor, a grep, a second
copy of the file elsewhere, and the test runner itself all mention `hands.py` without
being the bridge, and none of them is ever signalled. Nothing but the bridge dies.

### The macOS limits, plainly

- **The chromeless window needs a Chromium-family browser.** Chrome, Chromium, Brave,
  Edge or Vivaldi in `/Applications` (or `~/Applications`). Chrome is what this machine
  has, and it is what `--app` mode uses. With none of them the app still opens — as an
  ordinary tab in your default browser, with the address bar showing. Everything else
  about the launcher is unchanged.
- **`.app` and `.command` are the macOS doors.** The bundle is what makes a double-click
  avoid the Terminal entirely, and `osascript` is what shows an error as a dialog when
  there is no Terminal to print into. Neither exists on Linux or Windows; the Python
  verbs do, and they are the whole implementation.
- **No dock icon, by design.** The bundle is `LSUIElement`, so it lives about a second
  and leaves no icon behind. The window belongs to your browser, so that is what you see
  in the Dock and the app switcher. There is therefore no “Quit” in a menu that stops
  the bridge — `stop.command` is the deliberate act instead.
- **The window is not tied to the bridge's life.** They are independent on purpose: the
  bridge serves the app for as long as you leave it running, and a window can be closed
  and reopened (`launch.command`) without restarting it. Closing the window therefore
  also cannot stop it.
- **Gatekeeper never sees this bundle.** It is built on the machine and carries no
  quarantine attribute, so there is no first-run “unidentified developer” prompt. Copy
  it to another Mac (or download it) and that prompt appears, because the copy is
  quarantined by then — right-click ▸ Open clears it once.
- **iCloud Drive is fine, but it is not a startup location.** The folder works where it
  is; there is no launch agent, so nothing starts the bridge at login. If you want that,
  a Login Item pointing at `agent tornado.app` is the macOS way, and I have not set one up.

Working on the app itself:

```sh
node --test tornado-behavior.test.js   # 98 tests, most of which run the real sim
python3 -m unittest test_hands         # 111 tests, the bridge and its lifecycle
node measure.js                        # regenerate the measured tables below (~1 min)
node measure.js --quick                # skip the long horizons (~20s)
```

---

## The window

Three panes, one command line, no scrolling page.

```
┌──────────────────────────────────────────────────────────────────────┐
│ AGENT / TORNADO   AGENTS 560 DEPTH 12 EPOCH 543 FIT 0.66   [runbar]  │
├────────────┬────────────────────────────────────┬────────────────────┤
│ telemetry  │                                    │ task · crew ·      │
│ rail       │            the funnel              │ hands · log        │
│            │                                    │                    │
│ 1993       │      (dithered 1-bit grain)        │  decomposition     │
│ THROUGHPUT │                                    │  plan              │
│            │                                    │  recent            │
├────────────┴────────────────────────────────────┴────────────────────┤
│ › describe a job — it becomes a crew of mini agents          [build] │
└──────────────────────────────────────────────────────────────────────┘
```

- **Telemetry rail** — one loud number (throughput, the only coloured element in the
  app), then a quiet justified table: agents, depth, epoch, mean fit, spawns, culled,
  coaches, efficiency, fps. Below it, the crew summary and the bridge status.
- **Funnel** — drag to pan, wheel to zoom, click an agent to select it, `0` to reset.
- **Panel** — four tabs. *Task* shows the decomposition and the plan, with one typed
  argument field per declared argument. *Crew* is a sortable, filterable list of every
  live agent. *Hands* is where you install and see tools. *Log* is the event stream.
- **Composer** — the outline at the bottom. It grows with what you write; **Enter
  builds**, **Shift+Enter** adds a line so you can nest a step.

Drag the border between the funnel and the panel to resize it. `RAIL` and `PANEL` on
the bar hide either side, so you can run full-width on the funnel alone.

### Everything is on the keyboard

| key | |
|---|---|
| `⌘K` / `Ctrl K` | command palette — every action and every installed hand |
| `⌘B` / `⌘J` | toggle the rail / the panel |
| `⌘1`…`⌘4` | task · crew · hands · log |
| `]` / `[` | next / previous tab |
| `/` | focus the composer |
| `Enter` | build the crew |
| `Space` | pause / resume |
| `←` / `→` | run speed: hold, 1×, 4×, 12× |
| `j` / `k` | walk the crew list |
| `f` | follow the selected agent |
| `0` | reset the camera |
| `r` | rescan the hands folder |
| `Esc` | close a layer, clear the selection |
| `?` | the key map |

`Esc` unwinds one layer at a time — palette, then key map, then the selection. Bare
keys are ignored while a text field has focus, so `j` in the crew filter types rather
than jumps; `⌘`-combinations still work from inside a field.

Whatever you set — speed, tab, which panes are open, panel width, the model — is
remembered. The *simulation* is never persisted, deliberately: two runs of the same
brief have to agree.

---

## Hands

The tornado schedules and learns whether or not anything is installed. The bridge is
the part that touches the world, and it is deliberately narrow.

```sh
./launch.command        # start it
```

`launch.command` picks a Python, checks the port is free, starts the bridge and opens
the app. Leave the Terminal window open while you work; `ctrl-c` stops it.

### Adding a tool: drop it in

Open the **Hands** tab and drop a `.json` manifest onto the drop zone (or *choose a
file*). You can also just drop it anywhere on the window. If a manifest with that name
already exists, you get a confirm with a *replace it* / *keep the old one* choice — a
drop never silently overwrites a tool.

Manifests live in `tools/`. The folder ships with seven:

| id | kind | what |
|---|---|---|
| `git-status` | shell | branch + short status, for finding out what is dirty |
| `run-tests` | shell · destructive | run a node test file and return its output |
| `list-dir` | shell | list a directory, newest last |
| `read-file` | file-read | read a UTF-8 file, refuses anything over 64 KB |
| `search-text` | shell | case-insensitive search under a directory |
| `write-note` | file-write · destructive | write a markdown note into the output folder |
| `ollama-status` | http | ask the local Ollama which models are installed |

### Writing one

A manifest is `{ "tools": [ … ] }`. One tool:

```json
{
  "id": "search-text",
  "name": "Search text",
  "kind": "shell",
  "description": "Case-insensitive search for a pattern under a directory.",
  "matches": ["search", "grep", "find", "verify", "audit", "retry"],
  "argv": ["/usr/bin/grep", "-rinI", "--", "{pattern}", "{path}"],
  "roots": ["$HOME"],
  "timeout": 20,
  "args": {
    "pattern": { "type": "string", "required": true, "description": "Text to look for." },
    "path":    { "type": "path",   "required": true, "description": "Directory to search." }
  }
}
```

- **`kind`** — `shell`, `file-read`, `file-write` or `http`.
- **`argv`** — for `shell`, the command as an array. `{name}` placeholders are
  substituted from the request's named arguments and passed as argv; there is **no
  shell**. `argv` comes from the manifest and never from the request.
- **`matches`** — the words that bind a clause to this hand. This is how "verify
  pricing" finds `read-file` and `run-tests`. Keep them lowercase and concrete.
- **`roots`** — the only directories a file or shell tool may touch. Checked after
  symlink resolution. `$HOME` and other environment variables are expanded.
- **`"type": "path"`** — an argument that names a file or folder. It is resolved and
  held to `roots` before anything runs, for a shell hand as much as a file one, so
  `git -C {repo}` cannot be pointed outside them. A manifest with a `path` argument and
  no `roots` is refused at load.
- **Leading dashes** — a value substituted into `argv` may not start with `-`, or
  `node --test {file}` would take `--eval=…` as an option. A literal `"--"` earlier in
  `argv` ends option parsing, and after it a dash is allowed (a grep pattern like `-x`).
- **`allowRemote`** — an `http` hand is loopback-only unless its manifest sets
  `"allowRemote": true`, and the host can never come from an argument.
- **`confirm`** — set `true` for anything that changes the world. Every call then has
  to carry an explicit yes, which the app surfaces as an approval prompt showing the
  exact arguments.

A `description` is not decoration — it is what you read in the palette and in the
plan, and it is what the model is given when it proposes arguments. See
`tools/README.md` for the full field list.

### Running a plan

A plan is **one step per leaf** of the brief, and it is armed the moment you build:
every step has its hand before a single epoch runs, so you can propose, dry-run and
execute while the crew is still growing to cover it. Each step shows its arguments as
typed fields with the manifest's own descriptions as placeholders.

- **propose args** — asks the local model to fill the blanks, given the tool schemas.
  A value the model chose is marked `· model` on its step, and that step **asks before it
  runs**, even for a harmless hand. Typing over the value makes it yours and clears the
  mark. The mark survives a reload.
- **dry run** — sends the plan to the bridge and gets back the exact argv that *would*
  run. Nothing executes. This is the safe way to find out what a hand will do.
- **execute** — actually runs it. Destructive hands stop and ask first, and you can
  answer *run it*, *skip*, *run all remaining* or *stop*. Only an answer you gave is
  sent to the bridge as `confirm`; a hand nobody approved is sent without it, so the
  bridge's own check is a real second gate rather than a formality.
- **the crew learns from it** — each executed step reports its outcome to the
  simulation (`run.report`). A failure lowers the step agent's `precision`, a timeout
  its `speed`, each retry its `thrift`; a success raises them. Because the crew patches
  its weakest trait, a step whose hand keeps failing grows `verify` helpers under it. A
  shell that exits non-zero counts as a failure and leaves the step owed. Dry runs teach
  nothing.

Results land in **Recent calls** in the Hands tab, and every step's output is kept
under its step in the plan.

### A run survives the window

The plan used to live only in the page, which meant a reload lost the task and one
momentary failure ended a step for good. Now:

- **Every transition is written to the bridge** — armed, running, settled, skipped,
  retried — so a window closed, killed or reloaded mid-run comes back where it actually
  was. Saved in order, one behind the other, because the bridge answers on threads and
  two saves in flight could land out of order. Each run saves to **its own file** and
  never to another run's, so finishing a task does not destroy the record of the last one;
  the newest twenty are kept, and the run you are on is never the one dropped.
- **A reload resumes.** The brief goes back into the composer, the crew is rebuilt from
  it, every settled step comes back settled with its output, and the status line says
  which step you are on:  `resumed at step 2 · 1 of 3 still owed`. A step that was in
  flight when the page died comes back **idle** — nothing is running now, and pretending
  otherwise would stop that step from ever being tried again. Executing then runs only
  what was left, not the steps that already succeeded, and writes back to the same record
  rather than starting a second one. With several runs on disk it resumes the newest, and
  a newest record that will not read is stepped over rather than fatal.
- **A failure that might pass is retried twice** (`RETRY_LIMIT`). A *refusal* is not: if
  the bridge answered `4xx` — a missing argument, a destructive hand with no yes — the
  step fails at once, because sending it again would only repeat the refusal. The count
  of retries shows on the step (`retried 2×`).
- **A save that fails is not a run that fails.** With no bridge the plan still runs; you
  are told once that this run will not survive a reload.
- **Every saved run is listed** under *Saved runs* in the Task pane, newest first, with
  how many steps settled. *open* switches to it in place of the current one, which is
  already on disk, so nothing is lost. The list comes from `GET /api/runs`, and a single
  run from `GET /api/run?id=…`.
- **A typed argument is saved half a second after you stop typing**, so an argument
  that has never been part of a run still survives a reload.

The record keeps the first 2000 characters of each step's output. The pane keeps all of
it; the record keeps enough to tell you what happened, because a 64-leaf plan of full
outputs would not fit in one request to the bridge.

### How the bridge stays narrow

- Binds to `127.0.0.1` and **rejects browser requests that did not come from this app**
  (Origin check). Loopback keeps other machines out; it does not keep other web pages
  out, because browsers do not apply same-origin policy to a simple POST. Only the
  Origin header does that. The origin must be **this bridge's own port**: another dev
  server on `localhost` is another site.
- **The `Host` header must name this bridge.** A same-origin GET carries no Origin, so
  without this a DNS-rebinding page could read the run record and the tool list.
- Can only run tools that exist as manifests on disk. There is no endpoint that takes
  a command.
- `argv` comes from the manifest, not the request, and no shell is involved.
- File tools cannot leave the `roots` their own manifest declares, checked after
  symlink resolution, and neither can a shell argument typed `path`.
- No argument can become an option: a value starting with `-` is refused unless the
  manifest put a literal `--` before it.
- Destructive tools must declare `confirm: true` and every call must carry a yes, which
  the app only sends when you gave one.
- An `http` hand stays on loopback unless its manifest says `allowRemote`.
- Everything is append-only logged to `tools/.audit.jsonl`, including refusals.
- A token bucket caps invocations per window, so a runaway loop cannot hammer the
  machine while you are asleep.

---

## The brief is an outline

A brief is decomposed deterministically — no model is needed to find its shape.
Siblings are the separators the tool has always split on (a newline at the same indent,
`;`, `,`, `|`, or `and then / then / and / next / plus`). Two things make a step a
*child*:

- **Indentation** — a line indented under the line above it becomes its sub-step. Only
  the ordering matters, so tabs and ragged spaces both work.
- **A trailing colon** — `ship the bridge: verbs, window, docs` makes `ship the bridge`
  the parent of the three inline steps. Only the first colon on a line is structural.
  It stays **literal** in two cases: a one-word label with a single clause after it
  (`note: like this`, `TODO: fix the cull`), and a colon with no space after it (a URL,
  a time). A one-word label still nests a list (`ship: verbs, window`) or the lines
  indented beneath it.

```
repair the tornado
  audit the parser: check the escapes, check deep nesting
  tune the economics
```

becomes a root with two children, the first of which has two of its own. A brief with no
indentation and no colon is decomposed **exactly** as it always was.

**Two prices, stated plainly.** A colon after a step is structure, not literal text. And the old
promise *"recursion is earned"* is now *"the brief is walked; the frontier is earned"*:
a step the brief itself demanded spawns without paying credits or proving fitness,
bounded only by the node budget and `HARD_CAP`, because the brief already paid for it —
while every subagent the crew *invents* still has to earn its slot the hard way. The
status line tells you which: `plan 4 leaves · 1 roots · depth 2`. A wide brief is cut at
`NODE_BUDGET` (64) and a flat one at `ROOT_BUDGET` (8), and a cut is always reported.

---

## What the simulation does

The original was a renderer: a brief became a fixed set of dots, and the dots only
moved. This is a simulation underneath the same dither surface.

**Recursive learning.** An agent's ceiling comes from three traits (`precision`,
`speed`, `thrift`) plus two things its helpers and coaches do for it. Coaches raise the
ceiling outright and multiply the owner's learning rate, and a coach's power *is its
own learning rate*, so a coach that has itself been coached lifts more than a fresh one
— the recursion is in the mechanism, not a loop counter. Past depth 2, agents that are
still improving start raising coaches of their own, and every coach feeds a cohort-wide
training culture, so the gain spreads past whoever paid for it.

**Helpers that actually patch.** A subagent is built for its owner's worst *effective*
trait (`precision → verify`, `speed → cache`, `thrift → budget`) and raises that trait
while it lives, with deliberate saturation — the fourth cache of the same kind is worth
far less than the first, so a wall of one helper cannot run away. Because the parent
re-reads its effective traits each time it spawns, a lineage that has patched one
weakness moves on to its next.

**Self-improvement that pays for itself.** Throughput is `Σ fitness² × reach`. Credits
accrue from remaining headroom *and* from work actually done; spawning costs them, so a
stalled lineage earns nothing and stops growing on its own.

**Subagents all the way down.** An agent first walks the steps the brief demanded, then
invents its own: any agent past `SPAWN_FIT` with credits can spawn, and a subagent is the
same `makeAgent` call at every level, so it can spawn too with no special case. Depth is
bounded by the node budget early and by `MAX_DEPTH` late.

**Ruthless efficiency.** Past `SOFT_CAP` (420) a lineage may only grow if its value beats
the *cheapest incumbent leaf*, and the cull cuts back from a `HARD_CAP` of 560, so slots
churn instead of freezing at the cap. Value is judged on achievement *and* remaining
headroom, with a 45-epoch grace window, so a fresh subagent is not fired before it has
had a chance to learn. Only leaves are ever cut, so dead branches collapse tips-inward
instead of taking a healthy parent with them. A coach with a living owner is protected
for its tenure, because deleting the trainer mid-session silently deletes the
compounding.

---

## Measured

Generated by `node measure.js` against the exact `tornado.js` that ships. The simulation
has no randomness and no wall-clock input, so re-running reproduces these numbers
byte-for-byte. If a number here disagrees with that script, this file is stale.

| epoch | live | depth | coaches | coached | mean fit | throughput |
|---|---|---|---|---|---|---|
| 50 | 65 | 3 | 2 | 34 | 0.53 | 178 |
| 150 | 560 | 9 | 253 | 365 | 0.65 | 2006 |
| 300 | 548 | 9 | 242 | 306 | 0.67 | 2068 |
| 600 | 554 | 12 | 207 | 327 | 0.65 | 1888 |
| 1200 | 552 | 16 | 178 | 338 | 0.65 | 1875 |
| 3000 | 555 | 24 | 197 | 333 | 0.66 | 1703 |
| 9000 | 556 | 24 | 201 | 339 | 0.66 | 1603 |
| 18000 | 552 | 24 | 188 | 327 | 0.65 | 1555 |

At 18,000 epochs the crew had spawned 77,943 subagents and culled 77,397, still holding
552 live at mean fitness 0.65 — a mean lifetime of ~127 epochs.

### The honest headline: depth is a cost, not a capability

Throughput peaks early (~2,070 around epoch 300) and then declines ~22% as the tree
deepens. Mean fitness stays flat at ~0.65 the whole way, which is the tell: extra depth
adds **no** capability, only indirection. Isolating the variable by moving only the cap:

| MAX_DEPTH | depth reached | mean fit | throughput |
|---|---|---|---|
| 4 | 4 | 0.66 | 2204 |
| 8 | 8 | 0.65 | 1967 |
| 16 | 16 | 0.66 | 1838 |
| 24 | 24 | 0.66 | 1703 |
| 64 | 29 | 0.66 | 1708 |

So the shipped `MAX_DEPTH` of 24 is a deliberate choice, **not** the optimum: a cap of 4
buys ~29% more throughput. It is set at 24 because "subagents all the way down" was the
requirement, and the cap is the only thing standing between that requirement and an
efficiency bleed. It is a governor, not a safety net — at the shipped value it *is*
reached (epoch ~3000), and with it raised to 200 depth walks out to 50 by epoch 18,000.

**This result is only as good as one assumption.** Everything above follows from
`reach()`, which charges each level of indirection a small discount. If you believe a
subagent's work is as directly attributable as its owner's, set that decay to zero and
the drift largely disappears. The measurement is real; the conclusion is conditional on
that modelling choice, and that choice is one line (`function reach`) near the top of the
script.

---

## Design direction

**Swiss instrument panel on 1-bit phosphor.** One dominant near-black, one bone ink, one
accent spent on exactly one element. Two type families with assigned jobs: Helvetica Neue
for voice (title and labels, 9px tracked uppercase), monospace for all data and numerals
(tabular, so figures don't jitter as they tick). Every padding, margin and gap rides a
4px base unit. Zero border-radius anywhere.

Hierarchy is deliberately short. The amber throughput figure is the only chromatic thing
in the frame, so the squint test resolves to one loud number, then the funnel, then a
quiet grey rail. Interactive state is carried by ink and hairlines rather than by colour,
which is what leaves the single accent available.

The canvas draws its own ambient wind, scaled to how much crew there is: with no agents
it is near-black so the composer is unmistakably the loudest thing, and the vortex builds
as the crew does. The panes are opaque and separated by hairlines rather than shadows, so
the grain can never reach the telemetry.

The slop pass cut a drop shadow fighting the grain, native form chrome (the checkbox and
select are drawn), a HUD of ten visually identical rows, and a brief clipped mid-word in
a 132px chip. The short-lived `--hot` token was folded into a single `--accent` used once.
Several tests fail if any of that erodes back.

---

## Files

| file | what |
|---|---|
| `tornado.js` | the simulation: agents, traits, spawn/cull economics, coaching, the epoch loop. No DOM, no clock, no globals — it exports `Tornado`. |
| `stage.js` | the canvas: the camera and the funnel renderer. Reads the run and the layout state; draws. |
| `bridge.js` | the hands: the tool registry and the client that talks to the bridge, including loading, listing and saving runs. The only file that fetches it, and it talks to whichever bridge served the page. |
| `model.js` | the local model: the one Ollama client. Refines a brief by adding sub-steps under its leaves (never flattening what you typed), and proposes arguments. The only file that talks to Ollama. |
| `plan.js` | the plan: the brief's leaves, proposing their arguments, running them, resuming and recording them. Owns `plan` and the queue of saves behind it. |
| `panels.js` | the four panes and the transcript: task, crew, hands, log, and the tab switch. |
| `index.html` | markup, the shell and the wiring: state, the crew's seam to the model, the hud, the keyboard, the palette, boot. No build step, no dependencies. |
| `hands.py` | the bridge: serves the app, runs tools from `tools/`, keeps the audit log, and holds the saved run. |
| `tools/` | where hands live. Drop a `.json` here (or onto the app). |
| `agent tornado.app` | double-click: start if needed, open the app chromeless, exit. No Terminal. |
| `launch.command` | the same start with a Terminal attached, plus `stop` / `status`. |
| `stop.command` | double-click to stop the bridge. The one way out. |
| `.run/` | runtime state: the pid record and the bridge's log. Safe to delete. |
| `runs/` | one record per run: every step's state and output, and the file you export. The newest twenty are kept. Safe to delete. |
| `sim-harness.js` | the headless loaders: `loadTornado()` runs the module with no DOM; `loadSim()` builds a real DOM from the shipped markup for the page tests. |
| `tornado-behavior.test.js` | 98 tests: the brief's grammar, the module split, emergent behaviour, durable runs, per-run records and resume, navigation, the keyboard, the aura audit, and regression guards. |
| `test_hands.py` | 111 tests for the bridge, including its refusals, the run store and the launcher's lifecycle. |
| `measure.js` | regenerates every number above, plus the cap sweep, straight from the module. |
| `README.md` | this manual. |

### One simulation, three ways in

`tornado.js` is the simulation and nothing else. It never reads a clock — `step(dt)` is
told how much time passed — and it never touches a DOM, so the same module drives the
browser, the suite and the measurements, and a run is reproducible across all three.

The boundary is a single call. `index.html` does `Tornado.create({ matchHands, onLog })`
and gets back a run; `matchHands` is the one thing the model cannot know (how a clause
finds its tools), so it is asked, and `onLog` is the only thing it reports. Everything
else it needs is inside itself.

Who owns what: **the run owns the crew, its epoch and its stats** — the workspace keeps
no copy, which is why `state` there holds layout and selection only, and why Ctrl-R does
not restore a crew. **The plan owns `plan` and the record of it**, and that record is
built in one function (`runRecord`) which is both what is saved and what you export, so a
resumed run and an exported one cannot describe themselves differently. **The bridge
client owns `tools` and `bridge`** and is the only file that fetches the bridge, the
saved run included; **the stage owns the drawing**;
**the panes own the markup**. The shell (`index.html`) owns the layout, the selection and
the wiring between them.

The workspace is split the same way the simulation is, and loaded the same way: five
`<script src>` tags in a pinned order, all sharing one script scope, each served by the
bridge like any other file. That is why a test can assert a rule against the whole
workspace by name (`readSource().source`) while `readSim()` reaches only the model — and
why a guard test pins the load order, so a concern cannot quietly slide back into the
page. Each module was peeled only where its interface was already clean; what remains in
`index.html` is the shell, because that is what a shell is.

Tests reach the module directly (`require('./tornado.js')`); `measure.js` uses
`loadTornado()`, which is the same module with an optional `transform` so the depth-cap
sweep can move one constant.

---

## Verified, and what is not

Verified by running it, not by reading it:

- **209/209 tests pass** — 98 JavaScript, 111 Python, the Python suite under all three
  invocation styles (`-m unittest test_hands`, `-m unittest`, and `python3 test_hands.py`).
- The launcher path was driven rather than described: `launch.command` started the
  bridge and opened the app in a chromeless Chrome window; the shell that launched it
  was then sent **SIGHUP to its whole session** — what closing a Terminal does — and the
  bridge was still serving afterwards (new shell, `200`, same pid). A second
  `launch.command` returned in **0.14s** with “already running”, the same pid and one
  process on the port. `stop.command` freed the port and removed the record. The
  detachment is a test, not just this paragraph: the lifecycle tests assert the bridge's
  session and process group differ from the launcher's.
- The bridge was served for real and probed with `curl`: `/api/health` reports 7 tools,
  `/` returns `index.html` byte-for-byte, and `/api/invoke` from a foreign `Origin` is
  refused with **403**.
- The whole hands pipeline was driven in a real browser: a brief was decomposed, clauses
  were bound to hands by their wording, one argument was typed in, and **dry run**
  returned the exact argv the bridge would use — `/usr/bin/git -C <path> status --short
  --branch` — with nothing executed, logged in *Recent calls*.
- The browser holds **120fps at 560 agents** with no console or network errors.
- The layout was measured at 1512, 1280, 1152 and 1024 px: the topbar never overflows,
  every control stays reachable, and the panel re-clamps instead of starving the canvas.
- Both region toggles were measured live in the browser in all four combinations at
  1440, 1280, 1152 and 1024 px, the state restored from storage included: the canvas
  always takes the flexible track and stays above its own 360px floor, and a hidden
  region only ever empties its own track. That is now a test as well — the toggle test
  that used to be the whole story could only see a class flip, and a class flips just
  as happily while the layout is broken.
- **A run was saved, killed and resumed in the real browser**, not just headlessly: a
  nested brief was built in the composer, dry-run executed, every transition observed
  landing as `POST /api/run → 200`, the page reloaded, and the plan came back with the
  same three states, the brief back in the composer and the status line reading
  `a finished run was reloaded — 3 steps, all settled`. A step was then left `running`
  by hand, the page reloaded again, and it came back `resumed at step 2 · 1 of 3 still
  owed` with that step `idle` and the transcript saying `1 interrupted mid-step`. The
  record was also round-tripped through a real `Blob` and object URL in the browser.
- The live layout was re-measured after this change: at 1440 px the grid is
  `232px 816px 392px`, hiding the rail gives `0px 1048px 392px`, hiding the panel gives
  `232px 1208px 0px` — the canvas keeps the flexible track, exactly as before.
- The Ollama path works end-to-end against live `qwen2.5:14b` and `llama3.1:latest`
  (2026-09-28). With the typed tornado brief, `llama3.1` added four sub-steps under
  *audit the parser indentation* and kept the typed tree (1 root, depth 2); `qwen2.5:14b`
  judged every leaf a single action and added nothing, so the build fell back to the
  typed brief. An earlier design that asked the model for the whole outline was
  rejected after `qwen2.5:14b` promoted the typed children to roots.
- The error surface was triggered for real: the bundle was started against a port held
  by something else, and it put a native dialog on screen naming the culprit —
  *“port 65153 is held by Python, pid 45224, and that is not agent tornado.”*

Not verified, stated plainly:

- **Whether Chrome focuses the existing app window or opens a second one was measured
  indirectly, not watched.** There is no way to count another app's windows from a
  script without macOS Automation permission, which this deliberately never asks for.
  What was measured is the renderer-process count across relaunches: before the window
  check existed each `launch.command` added one (26 → 27 → 28 → 29), and after it,
  three relaunches added none. The behaviour is right; the observation is indirect.
- **The no-Chromium fallback was not exercised.** This machine has Chrome, so the
  plain-tab path has never run. It is three lines and it is reached only when no
  Chromium-family browser is installed.
- **The SIGKILL fallback was not exercised.** A bridge that ignores SIGTERM for eight
  seconds has never happened here, so the escalating kill is untested in practice.
- **Nothing starts it at login.** There is no launch agent; the README says how you
  would do it yourself.

- **No destructive hand was ever executed.** Dry runs only. `run-tests` and `write-note`
  are marked destructive and route through the approval prompt; that prompt is tested at
  the unit level, but the confirm-then-run path has not been walked on a live machine.
- **The per-run record was driven in the real browser and against the real bridge**: a
  nested brief was built and dry-run, then a second brief was built, and `runs/` was
  found to hold two files — the first run's record still complete (`done: true`, all
  steps `ok`) while the second was written. A page reloaded against the same folder
  resumed the second, and a cleared run stayed cleared. On the bridge, the newest/torn/
  retention behaviour was exercised over HTTP rather than only read: 23 runs posted left
  exactly `RUN_KEEP` on disk, a torn newest file fell back to the previous run, and a
  resumed old run's file survived its own save.
- The 18,000-epoch figures are headless. The longest run watched on screen was ~700
  epochs at 12×; nothing suggests the renderer cares, but I have not sat through 18,000
  epochs on screen.
- The layout was measured in this Chromium build only. Safari and Firefox were not tested.
- Ollama's 30-second abort path was never exercised — the local model answered well
  inside the timeout, so the "timed out · built locally" branch is untested.
- Dragging a real `.json` file onto the drop zone was exercised through the code path
  (a stubbed `DataTransfer`), not with a real OS drag.
- The fitness economy is still mostly simulated arithmetic. Executed hands now feed their
  outcomes back into the owning agent's traits, so a failing step really does grow
  verification under it, but the helpers it grows are simulated: a `verify` helper does
  not run a check of its own.

## Known rough edges

- A brief whose wording does not hit any hand's `matches` words binds nothing, and every
  step reads "no hand matched this clause". That is honest, not a bug — but it means a
  new tool is only useful once you have chosen words a brief will plausibly contain.
- The saved-runs list opens a run but does not delete one. Retention (twenty, newest
  first) is still the only way a run leaves `runs/`.
- `MAX_DEPTH` is a governor with a real efficiency cost (see above). It is not obviously
  set where you would want it.

## Provenance

| | |
|---|---|
| cloned from | `Projects/agent-vortex/index.html` @ `2ea593c` |
| cloned on | 2026-09-22 |
| upstream branch | `feat/agent-vortex-rgb-grain` |
| source doc | `Projects/agent-vortex.md` |

> [!note] Upstream moved while this was being built
> Two commits landed on the same branch in parallel (`4e5a2f1` "Restore recursive agent
> learning", `e4a537a` "Add the original undithered V2 agent vortex snapshot"), adding a
> `learnAndBranch` / `MAX_AGENTS` implementation and a `Projects/V2 mods/` folder. Those
> were not made by this session and this sandbox does not include them. A port-back is
> therefore a diff against upstream's current `agent-vortex/index.html`, not a copy of
> `index.html` from here.

Related: [[agent-vortex]], [[agent-room]].
