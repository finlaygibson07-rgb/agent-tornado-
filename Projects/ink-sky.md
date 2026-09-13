---
title: ink-sky
tags: [project, agents, ink-sky]
status: all seven stages built
source: ~/ink-sky/HANDOFF.md
---

> [!info] Mirror
> This note mirrors `~/ink-sky/HANDOFF.md`. The repo is the source of truth; this is the copy that reaches the phone.

A tool Scout that runs unattended, and a night sky to read it in. Built 2026-09-13 from the
bundle that was sitting in `VALT/files.zip` — charter (`THE_KEYS.md`, clauses I–XI), visual law
(`THE_SIGHT.md`, clauses XII–XVIII), build brief, schema, seed, and the already-verified
scoring / identity / lifecycle / advisor / figures modules.

> [!tip] Run it
> ```
> cd ~/ink-sky
> npm run field   # the field as its own window, 127.0.0.1:8721
> npm test        # 71 tests
> ```

## What exists now

- **The store** — `spec/schema.sql` applied to SQLite via `node:sqlite`, zero dependencies.
- **The repository layer** (`src/store/repo.js`) — every write to the store. It calls the
  rule-owning functions instead of restating them: `assertTransition` on the single state
  write, `maySpeak` on the single send path, `assertVoiceIntegrity` plus a required user event
  on the only path to `reviewer_verified`, `rejectionGate` on intake.
- **The field** (`src/field/`) — a standalone window drawing the real rows as a night sky:
  fixed stars for what you hold, meteors for candidates with tails as long as they have gone
  unreviewed, seams solid or dashed, the reading and its margin notes below the horizon.
  Two values in the palette, inverting wholesale for night.
- **The GitHub adapter** (`src/sources/github.mjs`) — reads the commit graph, not the README:
  commit age, how long a maintainer takes to answer, contributors over twelve months, tests,
  changelog, typed API. Stars are recorded and never scored.
- **The Scout** (`src/agents/scout.mjs`) — sweeps, checks the archive before spending a network
  call, writes provenance at fetch time, scores without adjusting, and writes one run row.
  It has no import path to anything that can speak to you, and a test asserts that.
- **The Reddit adapter** — the only source that carries voices, so the only one from which
  anything can clear the Seal of Working. Written and tested; never run live (needs credentials).
- **The Advisor** (`src/agents/advisor.mjs`) — judges seams, not tools. Reads the graph before it
  writes a word. Subtraction before any addition. Order is the advice. Names the hole once. And
  clause X: if too little of what it surfaced was kept over ninety days, it says so once and stops.
- **The cockpit** (`src/cockpit/`) — confirms the Gateway, carries an already-authorised digest
  without composing a word of it, and holds the three automations ready without installing them.
- **111 tests**, a gate per box from `spec/ACCEPTANCE.md` for every stage.

## The one change to code that came verified

`plate()` placed falling meteors at a fixed height, so a candidate unreviewed for two weeks
was drawn half off the top of the plate. Meteors now start as low as their own tail requires;
length still means time and nothing else. New containment tests; the original test file was
not touched.

> [!warning] Read `CALIBRATION.md` before trusting a score
> Three sweeps run by hand: 30 candidates, 0 surfaced. That is **not** yet evidence the bar is
> right. GitHub carries no voices, so nothing can clear the Seal of Working until Reddit lands —
> the ratio gate passes by construction.
>
> The reading turned up two things that are your call, not the Scout's:
> - **A three-week-old repo scores the same as `gitoxide`.** Eleven of thirty scored exactly 100;
>   the Seal of Structure measures recent motion, not maturity. An age signal would fix it, and
>   adding a signal key is a rubric change.
> - **moment scores 99** while its own authors tell people to stop using it. The rubric reads the
>   commit graph, not the maintainers' verdict. No weighting change fixes that one.
>
> Also worth knowing: the mechanical Scout can only fault *mediocre* tools. It derives notes from
> measured absences, so a good repo produces no note, and clause V bars anything it cannot name an
> improvement for. Naming what would make a good tool better needs a reader. A human naming one
> brings the thing back to the queue.

> [!warning] Two things only you can do
> 1. **Reddit credentials** — a script app at reddit.com/prefs/apps, then `REDDIT_CLIENT_ID` and
>    `REDDIT_CLIENT_SECRET`. Reddit 403s everything unauthenticated. Until then nothing can clear
>    the Seal of Working and every run is `NOTHING` by construction.
> 2. **A chat channel** — `openclaw channels list` reports none. Until one exists the digest is
>    written to SQLite and stands there: durable, readable in the field, delivered nowhere.

## What is next

Nothing is scheduled, on purpose. `npm run cockpit` shows the preflight and installs nothing;
`npm run cockpit install` registers the three automations (02:00 scout, 09:00 advisor, 04:00
Sunday health). The build order says not to do that until the bar is calibrated — an unattended
system on an uncalibrated bar is a machine for generating noise at scale.

Related: [[clip-factory]], [[MCP Loader]].
