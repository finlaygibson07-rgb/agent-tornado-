# Recursive Brief Decomposition — Design

Status: implemented. The module now does what this document says; the user-facing
account lives in README.md under "The brief is an outline", and the tests that hold it
to this contract are in `tornado-behavior.test.js`.

## 1. The problem

Today a brief is decomposed **flat**, and every part of the pipeline agrees on that
flatness:

- `splitBrief` (`tornado.js:187`) — one regex, three separator tiers collapsed into
  a single list, capped at 8 items.
- `build` (`tornado.js:343`) — control plus one depth-0 root per clause; the clause
  string *is* the agent's role.
- `bindHands` (`index.html:521`) — a substring word-match, applied only to roots.
- `buildPlan` (`index.html:983`) — exactly one plan step per depth-0 root, first
  bound hand only.

So the only thing in the system that ever goes deeper is the **economic** spawner
(`patchRole` / `spawnPass`), which follows fitness, not the task. A brief has no
structure the tool can see, and "all the way down" is a property of the simulation
rather than of the work.

The goal: **the brief's own structure is the recursion.** Submit a task; the crew
tears it into sub-agents along the tree you actually wrote, all the way to its
leaves, and only then spends its economics making the crew stronger than the brief
asked.

## 2. Settled decisions

1. **Depth comes from the brief's structure**, parsed deterministically. No model is
   required to find the tree.
2. **Nesting is expressed by indentation, with a trailing colon as shorthand.**
3. **Agents walk the tree; leaves are the work.** Roots are seeded at build and each
   walks its own sub-steps as it grows.
4. **Only leaves bind hands.** A node with children is coordination; the moment a
   node is a leaf it binds its clause's hands and becomes a plan step.

## 3. The grammar

`parseBrief(text) -> Node[]`, pure, in `tornado.js`. A `Node` is
`{ clause: string, children: Node[] }`.

**Siblings** are the separators the app already teaches: a newline at equal
indentation, `;`, `,`, `|`, and the conjunctions `and then | then | and | next |
plus`.

**Depth** comes from exactly two signals:

- **Indentation.** A line more indented than the previous line becomes that line's
  child. Indentation is *relative* — only the ordering of leading whitespace matters,
  not a fixed width — so tabs and spaces both work and a ragged indent still nests.
- **Trailing colon.** `ship the bridge: verbs, window, docs` makes `ship the bridge`
  the parent of the three inline steps. The colon adopts the rest of the line, and
  any lines indented beneath it. Only the **first** colon on a line is structural;
  any further colons are literal text. A line ending in a colon adopts only the lines
  indented beneath it. When a line has both a colon tail and indented lines, the tail
  children come first, then the indented ones.

  > **Amended 2026-09-28.** The first colon stays literal in two cases: a one-word
  > label followed by a single clause (`note: like this`), and a colon with no space
  > after it (a URL, a time). Everything above still nests, including a one-word label
  > followed by a list or by indented lines. The model path no longer returns a flat
  > role list: the brief is parsed by this grammar first, the model may only add
  > sub-steps beneath its leaves, and the result is written back out as an outline and
  > parsed again, so it obeys the same budgets and depth cap.

Everything else is literal text, trimmed. Blank lines are dropped. Two clauses with
identical text produce two separate nodes and two plan steps, exactly as two identical
clauses produce two roots today; the clause→agent link in §6 simply points both steps
the same way.

Worked examples:

```
ship the bridge: lifecycle verbs, app window, docs
```
→ `ship the bridge` with three children.

```
audit the parser
  check the escapes
  check deep nesting
then update the README
```
→ two roots; the first has two children; `update the README` is the second root.

```
write it, test it, ship it
```
→ three flat siblings — **identical to today's `splitBrief`.**

## 4. The tree and who owns it

- The **run** owns the parsed tree. `build()` parses once and exposes it read-only as
  `run.tree`.
- Each agent seeded or spawned from a node receives that node's `children` as its own
  `steps` queue; it takes from the front as it grows. The agent owns its remaining
  queue; the run owns the tree.
- Each node **binds its hands once**, at build, onto the node itself (`node.hands`).
  Agents read `node.hands` when they spawn rather than re-deriving them, so
  `matchHands` is called once per leaf per build and never per spawn.

This keeps the extraction boundary intact: all of it is pure and lives in
`tornado.js`; `index.html` keeps only binding and rendering.

## 5. Crew growth — demand versus invention

This is the load-bearing rule, and the place the first draft was too polite.

The economics exist to ration **invented** sub-agents — the ones the crew decides it
needs. They are the wrong gate for a step the *brief itself demanded*: a root starts
at `fit` 0.20–0.42, below `SPAWN_FIT` (0.50), and pays `SPAWN_COST` with a 2.5-epoch
cooldown per child, so a deep brief would spend tens of epochs learning before it
began to tear itself apart.

**Rule.**

- **A demanded step** (an agent still holding unwalked `steps`) spawns on a dedicated
  cheap path: **no credit cost, no `SPAWN_FIT` gate, cooldown `DEMAND_COOLDOWN`** (§7).
  It is bounded only by the node budget and `HARD_CAP`. Its role is the step's clause; its hands are
  `step.hands` if the step is a leaf, otherwise none.
- **An invented child** (queue empty) spawns exactly as today: `patchRole`, `SPAWN_FIT`,
  `SPAWN_COST`, `SPAWN_COOLDOWN`, inherited hands.
- **Priority:** when an agent could do both, the demanded step wins. The brief is torn
  down first; surplus capacity is then spent on strengthening the crew.

Consequence worth stating: a clause role is not `verify`/`cache`/`budget`, so demanded
growth does not patch a parent's traits. That is correct — a task step is work, not a
trait patch — and it means the patch engine resumes once the plan has been walked.
The README must say so.

## 6. Hands and the plan

- **Leaves bind hands at build.** Every leaf in the tree gets its hands (and therefore
  its plan step) the moment you press build, before any epoch runs. The plan is
  *armed* immediately: `propose args`, `dry run` and `execute` operate on real leaves
  with real hands while the crew is still growing to cover them.
- **Hand choice is by specificity, not load order.** Of the tools whose `matches`
  words appear in the clause, the one with the longest matching word wins; ties fall
  back to declared order. (Today it is simply whichever tool loaded first.)
- **`buildPlan` derives steps from the tree's leaves**, not from live agents. A step's
  `agent` field is filled from a **clause→agent index built once** when the plan is
  dirty; until the matching agent exists it reads as pending. Executing a step does
  not require its agent to exist — the step is the plan, the agent is the crew.
- A flat brief's plan is identical to today's, which is the back-compat guarantee for
  both crew and plan.

## 7. Budgets and caps

- **Parser:** one forward pass, stack-based on indentation, colon as a prefix marker,
  separators split once. No backtracking, no repeated regex.
- **Nesting depth** clamps to the existing `MAX_DEPTH` (24). Excess depth **promotes
  to siblings** — nothing mushy, nothing silently re-parented.
- **Budgets, named and valued.** `ROOT_BUDGET = 8` — top-level steps, unchanged from
  today's `slice(0, 8)`. `NODE_BUDGET = 64` — total nodes, roughly eight roots by eight
  children, chosen to sit well under `SOFT_CAP` (420) so demanded structure never
  dominates the steady state. Excess **width truncates at the budget and reports the
  count**, so an over-long brief tells you it was cut instead of shrinking quietly.
- **A demanded step's cooldown is `DEMAND_COOLDOWN = 0.25` epochs**, short enough that
  the tree is walked in a handful of epochs and long enough that the tear is visible
  rather than instantaneous.
- The status line reports the tear honestly: `plan N leaves · R roots · depth D`.

## 8. Back-compat and the one semantic change

- A flat multi-line brief with no indentation and no colon parses **byte-identically**
  to today's `splitBrief`, so crew and plan are unchanged for every brief the tool has
  ever accepted.
- The one intentional change: **a colon is now a structural marker, not literal text.**
  A brief containing a colon today would previously have kept it as part of a clause.
  This is the price of the shorthand and it must be noted in the README.
- `splitBrief` is removed from the module's public surface and replaced by
  `parseBrief`; the tests follow the module's vocabulary, as the extraction pass
  established.

## 9. Testing

The proof must be deterministic and observable.

- **Parser:** indentation (tabs vs spaces, ragged), colon, colon with no tail, mixed
  colon + indentation, blank lines, over-deep (promotion), over-wide (truncation +
  reported count), and a byte-for-byte back-compat case against the old flat split.
- **Growth — the two paths proven distinct:** a demanded child spawns **without**
  meeting `SPAWN_FIT` and **without** paying `SPAWN_COST`; an invented child still must
  meet both. A child spawned for a step has `role === step.clause`, carries that
  step's children, and (if internal) carries no hands; a leaf carries its hands.
- **Plan armed before epochs:** every leaf's plan step and hand exist immediately
  after `build`, with zero epochs run.
- **Specificity:** a clause matching two tools binds the more specific one.
- **Boundary guard:** `tornado.js` remains free of DOM, wall-clock and globals, and
  the `index.html`-loads-the-module contract still holds.

## 10. Non-goals

- **No auto-execution of hands.** `dry run` and `execute` remain explicit postures;
  a tool that touches the user's real files does not fire by itself. (If wanted later:
  run a leaf when its agent arrives — a separate design.)
- **No model-authored nesting.** The model-supplied `roles` path stays a flat list and
  is treated as a flat tree of leaves; nesting is the brief's job, not the model's.
- **No persistence.** The tree and the plan remain in memory, as the app already is.

## 11. Interface summary (what changes at the boundary)

`tornado.js`:

- `parseBrief(text) -> Node[]` — new; replaces `splitBrief` (removed).
- `run.build(brief, roles) -> { roots, leaves, clauses }` — adds `leaves`, keeps
  `roots` meaning "top-level steps".
- `run.tree` — read-only parsed tree.
- agents gain `steps` (remaining demanded children); node hands live on the tree.

`index.html`:

- `buildPlan` reads `tornado.tree` leaves; clause→agent index built once per dirty plan.
- `bindHands` selects by specificity.
- status line reports leaves · roots · depth.
