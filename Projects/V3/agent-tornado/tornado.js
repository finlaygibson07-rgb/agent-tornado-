/* tornado.js -- the simulation, on its own.
 *
 * The crew model, the trait economics, coaching and the epoch loop live here and
 * nowhere else. This file knows about agents and credits; it does not know that a
 * canvas, a DOM or a browser exists, and it never reads a clock -- `step(dt)` is
 * told how much time passed, which is what makes a 12x run evolve like a headless
 * one. Nothing in here is a global: the only thing that escapes is `Tornado`.
 *
 * The interface, in full:
 *
 *   Tornado.create({ matchHands, onLog }) -> run
 *       matchHands(clause) -> [toolId]   how a clause finds its hands. The one
 *                                        thing the model cannot know, so it is
 *                                        asked rather than imported.
 *       onLog(kind, text)                milestone lines the workspace may want
 *                                        to show. Never called for anything else,
 *                                        and never required.
 *
 *     run.build(brief, roles) -> { roots, leaves, clauses, depth, truncated }
 *         Parses the brief into a tree and seeds a control agent plus one root per
 *         top-level step. Each root walks its own sub-steps as it spawns, leaves
 *         bind their hands at build, and `roles` overrides the decomposition with a
 *         flat one when a model supplied it. `truncated` counts clauses a budget cut.
 *     run.step(dt)            one epoch. Advances, spawns, culls, measures.
 *     run.report(clause, { ok, timeout, ms, attempts }) -> touched
 *                             a hand ran for that leaf. Its outcome moves the
 *                             owning agent's traits (see applyEvidence), so the
 *                             crew patches what the world showed was weak.
 *     run.clear()             back to an empty crew.
 *     run.snapshot()          { live, depth, epoch, spawns, culls, meanFit,
 *                               throughput, efficiency, coaches, coached, roots }
 *                               -- the shape measure.js and the tests quote.
 *     run.agents              the live crew, in spawn order (read it, do not
 *                             splice it: the run owns the array)
 *     run.epoch               whole-and-fractional epochs elapsed
 *     run.brief               the brief this crew was built from
 *     run.stats               spawns, culls, maxDepth, throughput, meanFit,
 *                             efficiency, coaches -- live figures, same object
 *     run.tree                the parsed brief as { clause, children } nodes, with
 *                             each leaf's bound hands; read it, do not mutate it
 *
 * Also exported, because they are the rules worth testing on their own and the
 * workspace must agree with them: `budget` (every number the economics depend on),
 * `effectiveTraits`, `ceilingOf`, `agentValue`, `patchRole`, `isWorkingCoach`,
 * `parseBrief`, and the pure helpers `TAU`, `clamp`, `lerp`, `hash`.
 *
 * What it deliberately does not do: selection, logging destinations, rendering,
 * persistence, or timing. A cull is reported by the crew simply no longer
 * containing the agent -- the workspace pulls that each frame and decides what it
 * means for whatever was selected.
 */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module && module.exports) module.exports = api;
  else root.Tornado = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  /* =======================================================================
     the budget
     Recursion is not free and not capped by depth. Every subagent must earn its
     own right to exist: credits accrue from self-improvement and from work done,
     spawning costs them, and unproductive lineages are cut leaf-first so a dead
     branch cannot hide behind a healthy parent.
     ======================================================================= */

  const TAU = Math.PI * 2;

  const SOFT_CAP = 420;        // steady state: the cull cuts back down to this
  const HARD_CAP = 560;        // spawning ceiling, kept above SOFT_CAP so slots churn
  const MAX_DEPTH = 24;        // the indirection governor; see README, "depth is the cost"
  const GRACE = 45;            // epochs a fresh subagent is judged on headroom, not output
  const SPAWN_FIT = 0.50;      // only proven agents earn the right to spawn
  const SPAWN_COST = 1;        // credits burned per subagent
  const SPAWN_COOLDOWN = 2.5;  // epochs between spawns for one agent
  const CREDIT_RATE = 4;       // credits earned per unit of self-improvement
  const ROOT_CREDITS = 3.5;
  const CHILD_CREDITS = 0.4;
  const CULTURE_RATE = 0.18;   // cohort-wide training culture spread by coaches
  const YIELD_RATE = 0.015;    // output also buys growth, so a converged crew can reinvest
  const CREDIT_CAP = 4;        // and no agent can bank enough to flood the funnel
  const COACH_TENURE = 200;    // epochs a working coach is infrastructure, not a worker
  const STALL_FIT = 0.16;      // below this a lineage is dead weight
  const STALL_AGE = 70;        // epochs of dead weight before it is cut
  const BASE_RATE = 0.055;     // base learning rate
  const DEMAND_COOLDOWN = 0.25;// epochs between steps the brief itself demanded
  const ROOT_BUDGET = 8;       // top-level steps: the ceiling the flat split always had
  const NODE_BUDGET = 64;      // total nodes: roughly eight roots by eight children
  const EVIDENCE_HIT = 0.6;    // a trait the world just disproved keeps this share
  const EVIDENCE_LIFT = 0.25;  // a trait the world just confirmed closes this much of its gap
  const SLOW_MS = 5000;        // a hand slower than this counts against speed
  const FAST_MS = 1000;        // and one faster than this counts for it

  const TRAITS = ['precision', 'speed', 'thrift'];
  const PATCH = { precision: 'verify', speed: 'cache', thrift: 'budget' };
  const PATCH_OF = { verify: 'precision', cache: 'speed', budget: 'thrift' };
  const COACH = 'coach';

  /* =======================================================================
     helpers
     Pure, deterministic, and shared: `hash` is what makes a run reproducible,
     and `slug` is what makes a lineage readable, so the workspace reads them
     from here rather than keeping a second copy that could drift.
     ======================================================================= */

  function hash(value) { const x = Math.sin(value * 12.9898) * 43758.5453; return x - Math.floor(x); }
  function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
  function lerp(a, b, amount) { return a + (b - a) * amount; }
  function slug(text) { return String(text).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 20) || 'task'; }

  function freshStats() { return { spawns: 0, culls: 0, maxDepth: 0, throughput: 0, meanFit: 0, efficiency: 0, coaches: 0 }; }

  /* =======================================================================
     the agent
     Every agent is the same shape at every depth. A root is just an agent whose
     parent is null, which is what lets spawning recurse without a special case.
     ======================================================================= */

  let nextId = 0;

  function makeAgent(role, depth, parent) {
    const seed = hash(nextId * 7.13 + depth * 3.77 + role.length);
    const traits = {};
    for (let i = 0; i < TRAITS.length; i++) traits[TRAITS[i]] = 0.28 + hash(seed + i * 5.1) * 0.62;
    const stem = parent ? parent.name : 'root';
    const agent = {
      id: nextId++, role, depth, parent: parent || null, kids: [],
      seed, phase: hash(seed) * TAU, lobe: nextId % 3,
      age: 0, fit: 0.20 + hash(seed + 2) * 0.22, gain: 0, gainRate: 0, ceiling: 0,
      traits, learnRate: BASE_RATE, power: 0, credits: depth ? CHILD_CREDITS : ROOT_CREDITS,
      cooldown: 0, spawns: 0, hands: [], bites: 0,
      // the demanded steps this agent still has to walk (null for an invented one)
      steps: null,
      // x, y, wx, wy, _p, _f and t belong to the renderer -- where this agent was
      // last drawn, and how. The model never reads them; they live on the agent so
      // the workspace does not need a parallel map keyed by id.
      x: 0, y: 0, wx: 0, wy: 0, _p: null, _f: null, t: 0,
      // keep the whole lineage: truncating per level meant a child inherited an
      // already-clipped parent name and appended to it, producing mid-word garbage
      name: stem + '.' + slug(role)
    };
    agent.ceiling = ceilingOf(agent);
    return agent;
  }

  /* A helper earns its slot by patching the trait it was built for: a verify child
     lifts its owner's effective precision, a cache lifts speed, a budget lifts
     thrift. Saturation is deliberate -- a wall of caches must not make speed
     unbounded, and the fourth of a kind is worth much less than the first. */
  function effectiveTraits(agent) {
    const count = { precision: 0, speed: 0, thrift: 0 };
    for (const kid of agent.kids) {
      const trait = PATCH_OF[kid.role];
      if (trait) count[trait]++;
    }
    const out = {};
    for (const trait of TRAITS) {
      const own = agent.traits[trait];
      out[trait] = clamp(own + (1 - own) * (count[trait] / (count[trait] + 2.5)) * 0.75, 0, 1);
    }
    return out;
  }

  function ceilingOf(agent) {
    const t = effectiveTraits(agent);
    return 0.34 + 0.52 * (0.42 * t.precision + 0.30 * t.speed + 0.28 * t.thrift);
  }

  /* reach says how much of the brief a node can actually bite on. Depth dilutes it
     only gently: a subagent is a specialisation, so what really costs it is the
     contested slot, not its lineage position. */
  function reach(agent) { return 1 / (1 + agent.depth * 0.05); }

  /* Slot value is judged on achievement *and* on remaining headroom. Without the
     headroom term a fresh subagent is always the weakest leaf and dies before it
     gets to learn; with it, the frontier keeps moving down the lineage. */
  function agentValue(agent) {
    const headroom = Math.max(0, agent.ceiling - agent.fit);
    return (agent.fit * agent.fit + 0.8 * headroom) * reach(agent);
  }

  /* A proven lineage learns how to teach: past depth 2, agents that are still
     improving start raising coaches, and coaches are what compound. */
  function patchRole(agent) {
    if (agent.depth >= 2 && agent.gainRate > 0.0011 && hash(agent.id * 9.7) > 0.42) return COACH;
    // patch the worst *effective* trait, so a lineage that already hired three
    // caches moves on to its next real weakness instead of stacking a fourth
    const effective = effectiveTraits(agent);
    const worst = TRAITS.reduce((w, t) => (effective[t] < effective[w] ? t : w), TRAITS[0]);
    return PATCH[worst];
  }

  /* A coach with a living owner is holding that owner's ceiling up. Cutting it
     mid-session would silently delete the compounding that makes recursion pay,
     so it is protected for its tenure and then judged on its own value. */
  function isWorkingCoach(agent) {
    return agent.role === COACH && agent.parent && agent.age < COACH_TENURE;
  }

  /* What running a step's hand says about the agent that owns it. The traits
     start as guesses; this is where they meet the world. A hand that failed says
     the step was not precise, one that timed out says it was not fast, and every
     retry it needed says it was not thrifty -- and because `patchRole` patches the
     weakest effective trait, a failing step makes the crew raise `verify` helpers
     under it through the ordinary economics, with no special case. Pure: the same
     outcome always moves the same traits the same distance. */
  function applyEvidence(agent, outcome) {
    const t = agent.traits;
    const lift = trait => { t[trait] = clamp(t[trait] + (1 - t[trait]) * EVIDENCE_LIFT, 0.05, 1); };
    const hit = trait => { t[trait] = clamp(t[trait] * EVIDENCE_HIT, 0.05, 1); };
    if (outcome.timeout) hit('speed');
    else if (!outcome.ok) hit('precision');
    else {
      lift('precision');
      if (outcome.ms < FAST_MS) lift('speed');
      else if (outcome.ms > SLOW_MS) hit('speed');
    }
    const retries = Math.max(0, Math.floor(outcome.attempts || 0));
    for (let i = 0; i < retries; i++) t.thrift = clamp(t.thrift * 0.85, 0.05, 1);
    agent.ceiling = ceilingOf(agent);
    agent.fit = Math.min(agent.fit, agent.ceiling);
  }

  /* =======================================================================
     decomposition -- brief to crew
     ======================================================================= */

  /* A brief carries its own structure: separators make siblings, indentation and a
     trailing colon make children. `parseBrief` is pure -- it decides the shape and
     nothing else, because a clause cannot know what tools exist until the run is
     told. When `stats` is passed it receives the number of clauses a budget cut, so
     a truncation is reported rather than hidden. */

  const SEPARATORS = /\s*[;,|]\s*|\s+(?:and then|then|and|next|plus)\b/i;
  const LEADING_CONJUNCTION = /^(?:and then|then|and|next|plus)\s+/i;
  const FLAT_SPLIT = /\n+|\s*[;,|]\s*|\s+(?:and then|then|and|next|plus)\s+/i;
  const HAS_STRUCTURE = /^[ \t]|\n[ \t]|:/;

  /* Whether a line's first colon is outline syntax or just punctuation. It is
     structure when it ends the line, when a list follows it, or when the words
     before it are a step rather than a label. What stays literal is a one-word
     label with one clause after it -- `note: like this`, `TODO: fix it` -- and any
     colon with no space after it, which is a URL or a time, never an outline. */
  function structuralColon(content, colon) {
    const head = content.slice(0, colon).trim();
    const tail = content.slice(colon + 1);
    if (!head) return false;
    if (!tail.trim()) return true;
    if (!/^\s/.test(tail)) return false;
    if (splitClauses(tail).length > 1) return true;
    return /\s/.test(head);
  }

  function splitClauses(line) {
    return line.split(SEPARATORS).map(part => part.trim()).filter(Boolean);
  }

  function nodeCount(nodes) {
    let total = nodes.length;
    for (const node of nodes) total += nodeCount(node.children);
    return total;
  }
  function leafCount(nodes) {
    let total = 0;
    for (const node of nodes) total += node.children.length ? leafCount(node.children) : 1;
    return total;
  }
  function depthOf(nodes) {
    let deepest = 0;
    for (const node of nodes) deepest = Math.max(deepest, node.children.length ? 1 + depthOf(node.children) : 0);
    return deepest;
  }

  /* A brief with no structure is decomposed exactly as it always was: the same
     regex, the same order, the same eight-item ceiling. Keeping this path literal
     is what makes the new grammar a strict superset of the old one rather than a
     rewrite that merely agrees on the examples. */
  function flatClauses(normalized, stats) {
    const flat = normalized.split(FLAT_SPLIT).map(part => part.trim()).filter(Boolean);
    if (stats) stats.truncated = Math.max(0, flat.length - ROOT_BUDGET);
    return flat.slice(0, ROOT_BUDGET).map(clause => ({ clause, children: [] }));
  }

  function treeClauses(normalized, stats) {
    const lines = [];
    for (const raw of normalized.split('\n')) {
      const indent = /^[ \t]*/.exec(raw)[0].length;
      const content = raw.slice(indent).replace(/\s+$/, '').replace(LEADING_CONJUNCTION, '').trim();
      if (content) lines.push({ indent, content });
    }

    const roots = [];
    const stack = [{ indent: -1, node: { children: roots } }];
    for (const line of lines) {
      while (stack.length > 1 && line.indent <= stack[stack.length - 1].indent) stack.pop();
      const parent = stack[stack.length - 1].node;
      let made = null;
      const colon = line.content.indexOf(':');
      if (colon > 0 && structuralColon(line.content, colon)) {
        const head = line.content.slice(0, colon).trim();
        const tail = line.content.slice(colon + 1).trim();
        if (head) {
          const node = { clause: head, children: [] };
          if (tail) for (const clause of splitClauses(tail)) node.children.push({ clause, children: [] });
          made = [node];
        }
      }
      if (!made) made = splitClauses(line.content).map(clause => ({ clause, children: [] }));
      if (!made.length) continue;
      for (const node of made) parent.children.push(node);
      // Lines indented further nest under the last clause this line produced.
      stack.push({ indent: line.indent, node: made[made.length - 1] });
    }

    // Nesting clamps to MAX_DEPTH: anything deeper is promoted to a sibling at the
    // cap, so no clause is quietly re-parented and none is lost.
    const flatten = (nodes, out) => {
      for (const node of nodes) { out.push({ clause: node.clause, children: [] }); flatten(node.children, out); }
    };
    const capDepth = (nodes, depth) => {
      const out = [];
      for (const node of nodes) {
        out.push({ clause: node.clause, children: depth < MAX_DEPTH ? capDepth(node.children, depth + 1) : [] });
        if (depth >= MAX_DEPTH) flatten(node.children, out);
      }
      return out;
    };

    let kept = capDepth(roots, 0);
    const total = nodeCount(kept);
    if (total > NODE_BUDGET) {
      let count = 0;
      const prune = (nodes) => {
        const out = [];
        for (const node of nodes) {
          if (count >= NODE_BUDGET) return out;
          count++;
          out.push({ clause: node.clause, children: prune(node.children) });
        }
        return out;
      };
      kept = prune(kept);
      if (stats) stats.truncated = total - nodeCount(kept);
    }
    return kept;
  }

  function parseBrief(text, stats) {
    const normalized = String(text === undefined || text === null ? '' : text).replace(/\r\n?/g, '\n');
    return HAS_STRUCTURE.test(normalized) ? treeClauses(normalized, stats) : flatClauses(normalized, stats);
  }

  /* =======================================================================
     a run
     One crew on one brief. Everything mutable lives in here, so two runs cannot
     see each other and a fresh run starts from the same zero every time.
     ======================================================================= */

  function create(options) {
    const settings = options || {};
    const matchHands = typeof settings.matchHands === 'function' ? settings.matchHands : () => [];
    const onLog = typeof settings.onLog === 'function' ? settings.onLog : () => {};

    const run = { agents: [], epoch: 0, brief: '', stats: freshStats(), tree: [] };

    /* Only leaves are ever cut, so the tree stays coherent and a dead branch
       collapses from its tips inward instead of taking a healthy parent with it. */
    function removeLeaf(index) {
      const agent = run.agents[index];
      if (!agent || agent.kids.length) return;
      if (agent.parent) { const at = agent.parent.kids.indexOf(agent); if (at >= 0) agent.parent.kids.splice(at, 1); }
      run.agents.splice(index, 1);
      run.stats.culls++;
    }

    function spawnPass(dt) {
      const live = run.agents;
      if (!live.length || live.length >= HARD_CAP) return;
      // Once the funnel is full a new node has to be worth more than the cheapest
      // incumbent, because that incumbent is the one it will cost. Slots are
      // contested, never grandfathered.
      const contested = live.length >= SOFT_CAP;
      let floor = -Infinity;
      if (contested) {
        floor = Infinity;
        for (const agent of live) {
          if (agent.kids.length || agent.depth === 0) continue;
          const value = agentValue(agent);
          if (value < floor) floor = value;
        }
        if (!Number.isFinite(floor)) floor = -Infinity;
      }
      const count = live.length;

      for (let i = 0; i < count; i++) {
        if (live.length >= HARD_CAP) return;
        const agent = live[i];
        agent.cooldown -= dt;
        if (agent.cooldown > 0) continue;
        // Demand beats economics. A step the brief itself demanded is not rationed
        // the way an invented helper is -- the brief already paid for it -- so it
        // spawns without credits or fitness, bounded only by HARD_CAP, the node
        // budget and MAX_DEPTH. Whatever the agent invents after its queue is
        // empty still has to earn its slot the hard way.
        const step = agent.depth < MAX_DEPTH && agent.steps && agent.steps.length ? agent.steps.shift() : null;
        if (step) {
          const child = makeAgent(step.clause, agent.depth + 1, agent);
          child.steps = step.children;
          child.hands = child.steps.length ? [] : (step.hands || []).slice();
          // a step whose hand already ran is born knowing how that went
          for (const outcome of step.evidence || []) applyEvidence(child, outcome);
          child.fit = Math.max(0.05, agent.fit * 0.55);
          child.ceiling = ceilingOf(child);
          child.credits = CHILD_CREDITS;
          agent.cooldown = DEMAND_COOLDOWN;
          agent.spawns++;
          agent.kids.push(child);
          live.push(child);
          run.stats.spawns++;
          if (child.depth > run.stats.maxDepth) run.stats.maxDepth = child.depth;
          if (run.stats.spawns % 250 === 0) {
            onLog('spawn', `${run.stats.spawns.toLocaleString()} subagents raised · deepest ${run.stats.maxDepth}`);
          }
          continue;
        }
        if (agent.credits < SPAWN_COST || agent.fit < SPAWN_FIT || agent.depth >= MAX_DEPTH) continue;
        if (contested && agentValue(agent) <= floor) continue;
        const child = makeAgent(patchRole(agent), agent.depth + 1, agent);
        child.fit = Math.max(0.05, agent.fit * 0.55);
        child.ceiling = ceilingOf(child);
        child.credits = CHILD_CREDITS;
        child.hands = agent.hands.slice();          // a lineage inherits the hands it was given
        agent.credits -= SPAWN_COST;
        agent.cooldown = SPAWN_COOLDOWN;
        agent.spawns++;
        agent.kids.push(child);
        live.push(child);
        run.stats.spawns++;
        if (child.depth > run.stats.maxDepth) run.stats.maxDepth = child.depth;
        if (run.stats.spawns % 250 === 0) {
          onLog('spawn', `${run.stats.spawns.toLocaleString()} subagents raised · deepest ${run.stats.maxDepth}`);
        }
      }
    }

    function cullPass() {
      const live = run.agents;
      // 1. stalled leaves: dead weight is cut and the cut bubbles up the lineage
      for (let i = live.length - 1; i >= 0; i--) {
        const agent = live[i];
        if (agent.depth === 0 || agent.kids.length || isWorkingCoach(agent)) continue;
        if (agent.age > STALL_AGE && agent.fit < STALL_FIT) removeLeaf(i);
      }
      // 2. over capacity: the least valuable leaves lose their slot and the cull then
      //    makes room for the next generation, which is what keeps the frontier
      //    advancing instead of freezing at the cap. Roots are the brief; they stay.
      const excess = live.length - SOFT_CAP;
      if (excess <= 0) return;
      const candidates = [];
      for (const agent of live) {
        if (agent.kids.length || agent.depth === 0 || agent.age <= GRACE) continue;
        if (isWorkingCoach(agent)) continue; // you do not fire the trainer mid-session
        candidates.push(agent);
      }
      if (!candidates.length) return;
      candidates.sort((a, b) => agentValue(a) - agentValue(b));
      const doomed = new Set(candidates.slice(0, excess));
      for (let i = live.length - 1; i >= 0; i--) if (doomed.has(live[i])) removeLeaf(i);
    }

    /* throughput counts work actually done, not headroom: the projection in
       agentValue is for deciding who keeps a slot, never for claiming output. */
    function measure() {
      let weighted = 0, fit = 0, coaches = 0;
      for (const agent of run.agents) {
        weighted += agent.fit * agent.fit * reach(agent);
        fit += agent.fit;
        if (agent.role === COACH) coaches++;
      }
      run.stats.throughput = weighted * 10;
      run.stats.meanFit = run.agents.length ? fit / run.agents.length : 0;
      run.stats.efficiency = run.agents.length ? weighted * 10 / run.agents.length : 0;
      run.stats.coaches = coaches;
    }

    function step(dt) {
      const live = run.agents;
      run.epoch += dt;

      // Coaching is recursive by construction: a coach's power *is* its own learning
      // rate, so a coach that has itself been coached lifts more than a fresh one.
      let coachRate = 0, coaches = 0;
      for (const agent of live) {
        let power = 0;
        for (const kid of agent.kids) power += kid.role === COACH ? kid.learnRate : kid.traits.precision * 0.10;
        agent.power = Math.min(0.75, power);
        if (agent.role === COACH) { coachRate += agent.learnRate; coaches++; }
      }
      // ...and every coach also feeds a cohort-wide culture, so the gain spreads
      // past whoever paid for it.
      const culture = coaches ? (coachRate / coaches) * CULTURE_RATE : 0;

      for (const agent of live) {
        agent.age += dt;
        agent.learnRate = BASE_RATE * (1 + agent.power * 0.9) * (1 + culture);
        const ceiling = Math.min(0.995, ceilingOf(agent) + agent.power * 0.20);
        agent.ceiling = ceiling;
        // gainRate is per epoch, never per frame: thresholds must not drift with
        // frame rate or a 12x run would evolve differently from a headless one.
        agent.gainRate = (ceiling - agent.fit) * agent.learnRate;
        agent.gain = agent.gainRate * dt;
        agent.fit = clamp(agent.fit + agent.gain, 0, ceiling);
        // self-improvement pays for itself, and so does output: a fresh agent earns
        // fast off its headroom, a converged one keeps a smaller dividend from work
        // actually done. Either way a stalled, unproductive lineage earns nothing and
        // therefore stops growing on its own.
        let earned = agent.fit * agent.fit * YIELD_RATE;
        if (agent.gainRate > 0.00035) earned += agent.gainRate * CREDIT_RATE;
        agent.credits = Math.min(CREDIT_CAP, agent.credits + earned * dt);
        // traits sharpen toward whatever the agent is actually turning out to be good at
        const drift = agent.gainRate * dt * 0.5;
        for (const trait of TRAITS) agent.traits[trait] = clamp(agent.traits[trait] + drift * (agent.traits[trait] - 0.5), 0.05, 1);
      }

      spawnPass(dt);
      cullPass();
      measure();
    }

    function build(text, roles) {
      // A model-supplied role list is a flat decomposition by definition; nesting is
      // the brief's job, not the model's.
      const stats = {};
      const parsed = roles && roles.length
        ? roles.slice(0, ROOT_BUDGET).map(role => ({
            clause: typeof role === 'string' ? role : String(role.role || role.name || 'agent'),
            children: []
          }))
        : parseBrief(text, stats);
      const tree = parsed.length ? parsed : [{ clause: String(text || '').trim() || 'new task', children: [] }];

      // Hands bind once, at build, and only on leaves: a node with children is
      // coordination, and the step that does work is the leaf. The run owns the
      // tree; the agents it seeds below hold pointers into it, never copies.
      (function bind(nodes) {
        for (const node of nodes) {
          node.hands = node.children.length ? [] : matchHands(node.clause).slice(0, 3);
          bind(node.children);
        }
      })(tree);

      nextId = 0;
      const agents = [makeAgent('control', 0, null)];
      for (const node of tree) {
        const agent = makeAgent(node.clause, 0, null);
        agent.steps = node.children;     // the agent walks its own subtree, one step per spawn
        agent.hands = node.hands;
        agents.push(agent);
      }
      const seeded = ROOT_CREDITS + Math.min(3, tree.length * 0.35);
      for (const agent of agents) agent.credits = seeded;
      agents[0].hands = [];

      run.agents = agents;
      run.stats = freshStats();
      run.brief = String(text || '').trim() || 'new task';
      run.epoch = 0;
      run.tree = tree;
      measure();
      return {
        roots: agents.length - 1,
        leaves: leafCount(tree),
        clauses: nodeCount(tree),
        depth: depthOf(tree),
        truncated: stats.truncated || 0
      };
    }

    /* A hand ran for `clause`. The outcome is kept on the leaf it belongs to, so a
       step that has not spawned yet is born knowing it, and it is applied now to
       every live agent doing that step. Returns how many agents it touched. */
    function report(clause, outcome) {
      const facts = {
        ok: !!(outcome && outcome.ok),
        timeout: !!(outcome && outcome.timeout),
        ms: Number(outcome && outcome.ms) || 0,
        attempts: Number(outcome && outcome.attempts) || 0
      };
      (function mark(nodes) {
        for (const node of nodes) {
          if (!node.children.length && node.clause === clause) (node.evidence || (node.evidence = [])).push(facts);
          mark(node.children);
        }
      })(run.tree);
      let touched = 0;
      for (const agent of run.agents) {
        if (agent.role !== clause || !agent.hands.length) continue;
        applyEvidence(agent, facts);
        touched++;
      }
      return touched;
    }

    function clear() {
      run.agents = [];
      run.epoch = 0;
      run.brief = '';
      run.stats = freshStats();
      run.tree = [];
    }

    function snapshot() {
      return {
        live: run.agents.length,
        depth: run.stats.maxDepth,
        epoch: Math.round(run.epoch),
        spawns: run.stats.spawns,
        culls: run.stats.culls,
        meanFit: run.stats.meanFit,
        throughput: run.stats.throughput,
        efficiency: run.stats.efficiency,
        coaches: run.agents.filter(a => a.role === COACH).length,
        coached: run.agents.filter(a => a.power > 0.01).length,
        roots: run.agents.filter(a => a.depth === 0).length
      };
    }

    return {
      build, step, clear, snapshot, report,
      get agents() { return run.agents; },
      get epoch() { return run.epoch; },
      get brief() { return run.brief; },
      get stats() { return run.stats; },
      get tree() { return run.tree; }
    };
  }

  return {
    // pure helpers the workspace has to agree with (`slug` stays private: it is an
    // implementation detail of how a role becomes a lineage name)
    TAU, clamp, lerp, hash,
    // every number the economics depend on
    budget: {
      SOFT_CAP, HARD_CAP, MAX_DEPTH, GRACE, SPAWN_FIT, SPAWN_COST, SPAWN_COOLDOWN,
      CREDIT_RATE, ROOT_CREDITS, CHILD_CREDITS, CULTURE_RATE, YIELD_RATE, CREDIT_CAP,
      COACH_TENURE, STALL_FIT, STALL_AGE, BASE_RATE, TRAITS, PATCH, PATCH_OF, COACH,
      DEMAND_COOLDOWN, ROOT_BUDGET, NODE_BUDGET, EVIDENCE_HIT, EVIDENCE_LIFT, SLOW_MS, FAST_MS
    },
    // the model's rules, worth testing without a crew
    effectiveTraits, ceilingOf, agentValue, patchRole, isWorkingCoach, parseBrief, applyEvidence,
    // and a crew
    create
  };
});
