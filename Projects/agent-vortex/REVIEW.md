# agent-vortex review — v1 vs v2

Reviewed 2026-09-22. Both versions read in full; v1 tests pass (8/8).

| | commit | branch | size |
|---|---|---|---|
| **v1** | `6bcb028` Add bounded recursive agent growth and organic hierarchy (#3) | `main` | 2,580 lines |
| **v2** | `76b8871` Simplify agent vortex into focused dithered flow renderer (Codebuff) | `pr/agent-vortex-dither` | 275 lines |

## Verdict

v1 has the ideas; v2 has the renderer. Neither is the keeper. The target is
**v1's simulation driving v2's rendering**. Do not merge `pr/agent-vortex-dither` as-is.

---

## v1 (`main`)

### Good
- **The layout encodes data.** In fitness order the funnel *is* the ranking — raw agents
  ride the wide mouth, refined ones sink to the tip. Spin rises as the brief nears
  completion (`drive = spin * (1 + taskHeat * 1.9)`).
- **Cross-run genome.** `strains`, `playbook`, and a `doctrine` that only sharpens
  (`absorb()` / `sharpen()`). Run N+1 starts where run N finished.
- **Weakness-targeted delegation.** `delegate()` builds a helper for the owner's *worst*
  trait; past `coachAt` it builds `meta` coaches that raise `learnRate` — a
  learning-to-learn loop.
- **Honest debriefs.** Every line in `composeReport()` is gated on a real counter.
- **Comments explain why**, not what.
- **Guard rails:** `SOFT_CAP` / `POP_CAP`, `MAX_DEPTH = 6`, the `building` lock,
  try/catch around every `localStorage` access.

### Bad
1. **Three stacked CSS theme layers** ("CHANNEL", "AGENT VAULT", "DREAM / DITHER"), each
   overriding the last with `!important`. Dead rules everywhere; the sky gradient in
   `#environment` is fully painted over. ~150 lines removable.
2. **The core is simulated.** Fitness, wins and work done are dice rolls. Only the
   Ollama brief rewrite is real output.
3. **Starts on `hold`**, and a test locks it there. First impression is a still vortex.
   Default to 4×.
4. **Per-grain `fillRect` rendering.** 50–300 rects per agent per frame, several with
   `shadowBlur`. Hundreds of agents means tens of thousands of draw calls per frame.
5. **Tests regex the source.** They match strings like `MAX_DEPTH = 6`; a rename breaks
   them and a logic bug passes. No behavioural test of `step()`.
6. **Loose ends:** `logEvent(text, hue)` ignores the hue; broken indentation in
   `updateHud`; `const REPORT_SECTIONS` sits on the same line as a closing `}`; the
   `feTurbulence` grain reseeds every 120 ms even while paused.
7. **Repo hygiene:** README is "mad storm"; repo name has a trailing dash; no screenshot.

---

## v2 (`pr/agent-vortex-dither`)

### Good
- **Rendering is fixed.** Every grain accumulates into one low-res `Uint8ClampedArray`,
  then one 4×4 Bayer dither pass → one `putImageData` + two `drawImage`. Solves v1 #4.
- **CSS is one small theme.** Solves v1 #1.
- **34 background streamlines** trace the funnel, so it never looks empty. The
  three-lobe asymmetric `flowPoint()` is more organic than v1's single funnel.
- **Readable** — the whole thing fits in your head.

### Bad — the simulation was deleted
- No fitness dynamics, breeding, culling, helpers, coaches, ranking, genome, debrief inbox,
  inspector, persistence or Ollama.
- **The tests lock the deletion in:** `assert.doesNotMatch(source, /OLLAMA|localStorage|id="inbox|genome|cohort-list|id="inspect/)`.
  Any attempt to restore v1 features fails CI.
- **`epoch` is a float timer.** `state.epoch += dt * state.speed`, displayed unrounded
  (`12.3481…`). Nothing reads it.
- **The speed select (hold/1×/4×) only drives that counter.**
- **`fit` is computed and never used.**
- **Agent count is frozen at build time:** one per clause, max 8, wired into a
  binary-heap tree (`parent = agents[(i - 1) / 2]`). A brief with no commas or "and"
  gives one agent.
- **Opens empty.** v1 seeded a demo brief.
- **RGB split is one pixel per agent** — effectively invisible.
- Minor: `createImageData` is allocated every frame; a full-screen `blur(7px)` filter runs
  every frame.

---

## Plan: merge the two

1. Keep v1's engine intact: `step()`, `spawn`, `delegate`, `buildCoach`, `absorb`,
   `sharpen`, `composeReport`, persistence, inbox, inspector.
2. Replace v1's render section (`drawGrainTrail`, the per-node grain loops, the SVG
   `#film-grain`) with v2's field buffer: `addGrain` / `addEdge` / `addStreamline` /
   `paint`.
3. Position funnel agents with v2's `flowPoint(t, phase, lobe)`, using v1's `a.t`
   (fitness rank) as `t`. Keep v1's `organicOrbit` for helpers.
4. Scale grain `amount` by fitness and red/blue split by `disagreement`, so the dither
   still carries data.
5. Take v2's CSS as the base and re-add only the panels v1 needs.
6. Default sim speed to 4×. Round `epoch`.
7. Replace the regex tests with a behavioural harness: load the script into a fake DOM,
   run N `step()`s, and assert population bounds, depth ≤ `MAX_DEPTH`, and that the genome
   sharpens across runs.

## Other

- `feat/agent-vortex-rgb-grain` has a whole Obsidian vault committed into it
  (`.obsidian/`, `Daily Notes/`, `Imported/`, `Knowledge/`, clip-factory and ink-sky
  notes). That doesn't belong in this repo.
- The sandbox build at `VALT/asher star/Projects/SANDBOX TEST CHANGES/agent-tornado/`
  (index.html, `sim-harness.js`, `measure.js`, `tornado-behavior.test.js`) hasn't been
  reviewed yet; it's next.
