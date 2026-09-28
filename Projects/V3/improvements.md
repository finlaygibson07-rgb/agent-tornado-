---
title: agent-tornado improvements
tags: [type/project, status/draft, project, ai-agents, tornado, sandbox, backlog]
status: P1s and most P2s built 2026-09-28; the rest open
created: 2026-09-28
updated: 2026-09-28
aliases: [agent tornado backlog]
source: Projects/SANDBOX TEST CHANGES/agent-tornado/
---

# agent-tornado improvements

Improvements for [[agent-tornado]], from a read of the sandbox on 2026-09-28. Each item
names the file it lives in. **Verified** means the problem was confirmed in the code, not
just inferred from the docs.

> [!info] Baseline when this was written
> 166/166 tests green (75 JS + 91 Python). `node measure.js` matches the vault note
> byte for byte. The bridge is up on `:8799` with 7 tools. The brief
> `repair the tornado` builds 1 root and 4 leaves, each with a hand bound.

Priority: **P1** fix before trusting it with real work · **P2** next pass · **P3** nice to have.

> [!tip] Progress, 2026-09-28
> 15 of 24 done, including every P1. Tests went from 166 to **209, all passing** (98 JS,
> 111 Python). `measure.js` output is byte-identical to before. Verified live: the
> bridge's refusals via curl, and propose → approve → execute in the app against
> `qwen2.5:14b`. Two bugs were found and fixed along the way: the page hard-coded port
> 8799, so a bridge on another port was unreachable, and a per-request dry run was
> audited as a real execution. This version is saved as `Projects/V3/agent-tornado/`.

---

## 1. Security — the hands

- [x] **P1 · Shell arguments ignore `roots`.** *Verified.* `plan()` in `hands.py` checks only
  `cwd` against the declared roots. It never checks the `{placeholders}` inside `argv`. So
  `git-status` accepts any `repo` path, and `run-tests` passes `{file}` straight to
  `node --test`. A `file` of `--eval=…` turns into arbitrary code.
  **Fix:** add a `path` arg type that goes through `resolve_within_roots()`, and reject any
  substituted argv value that starts with `-`.
  > **2026-09-28:** Done: new `path` arg type held to roots; argv values starting with `-` refused unless after a literal `--`. Four shipped args retyped.
- [x] **P1 · The server-side confirmation is a formality.** *Verified.* `plan.js:241` sends
  `confirm: !dryRun` on every real invoke, so the bridge's "destructive tools need an
  explicit confirmation" check always passes. The only real guard is the prompt in the page
  (`plan.js:267`), and *approve all* skips it.
  **Fix:** send `confirm: true` only from inside `confirmStep()`. Better still, have the
  bridge issue a one-time token per approval.
  > **2026-09-28:** Done: `confirm` is sent only when you approved (`plan.js`), so the bridge check is real.
- [x] **P1 · Model-proposed arguments can reach the shell.** *Verified.* *Propose args* writes
  Ollama output straight into `step.args` (`plan.js:157–202`), and non-confirm tools then
  run with those values. With the two fixes above this is contained. Until then, show
  proposed values as a diff that needs accepting.
  > **2026-09-28:** Done: model-chosen values are marked `· model`, and that step asks before running even for a harmless hand. Typing over one clears it; the mark survives a reload.
- [x] **P2 · Origin check allows any loopback port.** *Verified.* `origin_allowed()` compares
  hostnames only, so any other dev server on `localhost:*` can drive the bridge.
  `0.0.0.0` is also in `LOOPBACK_HOSTS`. **Fix:** pin to the exact origin, port included,
  that the bridge serves.
  > **2026-09-28:** Done: the origin must match the bridge's own port.
- [x] **P2 · No `Host` header check.** GETs with no `Origin` are allowed. A DNS-rebinding page
  could therefore read `/api/run` and `/api/tools`, though it cannot POST.
  **Fix:** reject any `Host` that isn't `127.0.0.1:<port>` or `localhost:<port>`.
  > **2026-09-28:** Done: `Host` must be this bridge on loopback (403 otherwise, verified live with curl).
- [x] **P3 · `http` hands can reach any URL** a manifest names. Consider a loopback-only
  default, with an explicit `"allowRemote": true` required per manifest.
  > **2026-09-28:** Done: `http` hands are loopback-only unless `"allowRemote": true`; the host can never be a placeholder.

## 2. The model path (Ollama)

- [x] **P1 · The model path is flat.** Already listed under *Known rough edges* in the note.
  `ollamaSpec()` (`index.html:572`) asks for a flat `{"agents":[…]}` and ignores the
  outline. **Fix:** ask for the same `{clause, children}` tree that `parseBrief` produces,
  then validate it against `ROOT_BUDGET`, `NODE_BUDGET` and `MAX_DEPTH`.
  > **2026-09-28:** Done, differently than planned: asking the model for a whole outline was tried and a live `qwen2.5:14b` promoted typed children to roots. Now the brief is parsed first and the model may only add sub-steps under leaves, so typed structure survives by construction.
- [x] **P2 · Two copies of the Ollama client.** *Verified.* `index.html:576` and
  `plan.js:171` each hard-code `http://127.0.0.1:11434/api/chat` with their own timeout
  and parsing. This breaks the note's own rule that one file owns each concern. Move both
  into `bridge.js`, or a small `model.js`, with one timeout and one JSON-repair path.
  > **2026-09-28:** Done: `model.js` is the only Ollama client (a test enforces it).
- [x] **P2 · No schema enforcement on replies.** `format: 'json'` only guarantees valid JSON,
  not the right shape. Pass a JSON schema (Ollama supports `format: {schema}`), and reuse
  the lenient-extraction plus validate-and-repair pattern from `tornado-lab/Validation.cs`.
  > **2026-09-28:** Done: replies are schema-constrained, with a plain-JSON retry for an Ollama that refuses schemas, and shapes are still validated.
- [ ] **P3 · Different models for different jobs.** Use a cheap model to decompose and a
  stronger one to propose arguments, the same maker/checker split tornado-lab's
  `--checker-model` uses.
  > **2026-09-28:** Not done.

## 3. Simulation and economics (`tornado.js`)

- [x] **P1 · Fitness isn't tied to real work.** Traits (`precision`, `speed`, `thrift`) and
  throughput are synthetic. A hand that succeeds or fails never feeds back into the crew.
  **Fix:** let tool outcomes adjust the bound leaf's traits. For example, a non-zero exit
  or a timeout cuts `precision`, and a slow call cuts `speed`. The simulation would then
  measure something real.
  > **2026-09-28:** Done: `run.report()` in `tornado.js`; a failing step now grows `verify` helpers (5 vs 0 in the test run). Non-zero shell exits now count as failures and leave the step owed.
- [ ] **P2 · Offer a depth preset.** `measure.js` shows depth 4 → 2204 throughput, versus
  1703 at the shipped `MAX_DEPTH = 24`. Keep 24 as the "all the way down" governor, and add
  a *lean* mode with a cap of 4–8 for when throughput matters more than showing the
  recursion.
  > **2026-09-28:** Not done: needs a place in the top bar; left for you to decide.
- [ ] **P3 · Throughput falls about 22% after epoch 300.** Worth testing whether culling by
  depth-weighted value (penalising indirection directly) recovers it without lowering the
  cap.
  > **2026-09-28:** Not done.

## 4. Persistence (`runs/`)

- [x] **P2 · No list of runs in the app.** Already known. Add a *Runs* tab that reads from a
  new `GET /api/runs` (id, brief, leaves, status) and offers open, export and delete.
  > **2026-09-28:** Done: *Saved runs* list in the Task pane, `GET /api/runs`, `GET /api/run?id=`, *open* switches runs.
- [x] **P3 · Arguments are lost on reload.** Already known. Save on `input` with a debounce
  of about 500 ms, instead of only at build, run and transition points.
  > **2026-09-28:** Done: typed arguments save 500 ms after you stop typing.
- [ ] **P3 · `runs/` lives in iCloud.** Two machines resuming the same run can race.
  "Newest by id" handles ordering, but not two writers on one file. Consider a
  per-machine suffix on the id.
  > **2026-09-28:** Not done.

## 5. Parser and UX

- [x] **P2 · A colon in prose nests.** Already known. Only treat a colon as structural when
  it ends the line or is followed by a list (`a: x, y, z`). Keep `note: like this` literal.
  > **2026-09-28:** Done, narrower than proposed: a colon is literal only for a one-word label plus one clause (`note: like this`) or with no space after it (URLs, times). Everything the spec documents still nests.
- [ ] **P2 · Unbound leaves.** When `matches` finds no hand, say so on the step card and offer
  the closest tools, instead of leaving the step silently unarmed.
  > **2026-09-28:** Correction: the step card already says "no tool matched this clause". Suggesting the closest tools is not done.
- [ ] **P3 · It opens empty.** The first frame shows an empty crew. Pre-fill the
  composer with the example brief so the tool shows what it does on open.
  > **2026-09-28:** Won't do: the composer is refilled by resume, so a prefilled example would fight it.

## 6. Code structure

- [ ] **P2 · `index.html` is still 1,303 lines** with 47 functions, even after the five-script
  split. Build and model code (`ollamaSpec`, `runBuild`) belongs in `plan.js`, or in a
  `model.js` (see §2). Extend the load-order guard test to match.
  > **2026-09-28:** Partly done: the Ollama client moved to `model.js`; the rest of `index.html` is unchanged.
- [ ] **P3 · `hands.py` is 1,418 lines** covering the tool runtime, the HTTP server, the
  run store and the launcher. Splitting it into `tools.py`, `server.py` and `launcher.py`
  would still need nothing installed.
  > **2026-09-28:** Not done.

## 7. Testing

- [x] **P1 · Add regression tests for §1.** Cover argv values outside `roots`, argv values
  starting with `-`, a destructive invoke without a UI-issued confirm, a foreign-port
  loopback origin, and a bad `Host`. None of these are covered today; the existing 91
  Python tests pass with all of them open.
  > **2026-09-28:** Done: 20 new Python tests, 23 new JS tests; the key ones fail on the old code.
- [x] **P2 · Contract test for the model path.** Use a stub Ollama that returns malformed,
  flat and oversized replies, and check that the build falls back cleanly.
  > **2026-09-28:** Done: stub-Ollama tests cover empty, malformed, one-step and schema-refusal replies.

## 8. Portability

- [ ] **P3 · macOS only.** The `.app`, `osascript` and the chromeless window are Mac-specific.
  A `--app` flag that opens `chrome --app=URL` or `msedge --app=URL` where available would
  cover Linux and Windows with no packaging.
  > **2026-09-28:** Not done.

---

## Suggested order

1. §1 P1 items plus their §7 tests, in one pass. That makes it safe to point the hands at
   real repos.
2. §2 tree-shaped model path plus one model client.
3. §3 real fitness feedback. This is the change that turns the simulation into a tool.
4. The *Runs* tab, then the rest as needed.

Related: [[agent-tornado]], [[agent-vortex]], [[agent-vortex-review]].
