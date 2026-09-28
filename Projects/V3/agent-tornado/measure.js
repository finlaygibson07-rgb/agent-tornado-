'use strict';

/* Regenerates every number quoted in README.md, straight from the simulation.
 *
 *   node measure.js           full run (a few minutes on a laptop)
 *   node measure.js --quick   milestones up to 1200 epochs only
 *
 * It loads the model directly rather than through the page, because the model no
 * longer needs a page: `loadTornado()` is the same module the browser gets, and
 * `loadTornado({ transform })` runs it with one constant moved for the sweeps.
 *
 * The simulation has no randomness and no wall-clock input, so two runs of this
 * script produce identical output. If a README number disagrees with this, the
 * README is stale and this script is right.
 */

const { loadTornado } = require('./sim-harness');

/* One call to `step(dt)` is one epoch, so a run of N epochs is N calls at dt=1.
   This must not be `run.step(N)`: that would be a single epoch advancing by N. */
const advance = (run, epochs) => { for (let i = 0; i < epochs; i++) run.step(1); };

const BRIEF = 'design a checkout flow; add retry guards; tone-check the copy; cache the cart; verify pricing';
const FULL = [50, 150, 300, 600, 1200, 3000, 9000, 18000];
const QUICK = [50, 150, 300, 600, 1200];

const pad = (value, width) => String(value).padEnd(width);
const num = (value, digits = 0) => value.toFixed(digits);

function run(milestones) {
  const sim = loadTornado().create({ matchHands: () => [], onLog: () => {} });
  sim.build(BRIEF);
  const rows = [];
  let previous = 0;
  for (const epoch of milestones) {
    advance(sim, epoch - previous);
    previous = epoch;
    rows.push({ epoch, ...sim.snapshot() });
  }
  return rows;
}

function table(rows) {
  const lines = [
    '| epoch | live | depth | coaches | coached | mean fit | throughput |',
    '|---|---|---|---|---|---|---|'
  ];
  for (const r of rows) {
    lines.push(`| ${r.epoch} | ${r.live} | ${r.depth} | ${r.coaches} | ${r.coached} | ${num(r.meanFit, 2)} | ${num(r.throughput)} |`);
  }
  return lines.join('\n');
}

/* Is MAX_DEPTH a safety net, or is it the thing actually stopping the recursion?
   Run the same brief again with the cap raised far out of reach, and see where
   depth settles on its own. */
function probeDepthCap(milestones) {
  const raised = loadTornado({ transform: s => s.replace('const MAX_DEPTH = 24;', 'const MAX_DEPTH = 200;') }).create({ matchHands: () => [], onLog: () => {} });
  raised.build(BRIEF);
  const rows = [];
  let previous = 0;
  for (const epoch of milestones) {
    advance(raised, epoch - previous);
    previous = epoch;
    rows.push({ epoch, ...raised.snapshot() });
  }
  return rows;
}

console.log('# Measured from the simulation module (deterministic)\n');

const milestones = process.argv.includes('--quick') ? QUICK : FULL;
const rows = run(milestones);
console.log(table(rows));

const first = rows[1] ?? rows[0];
const last = rows[rows.length - 1];
const drift = ((last.throughput - first.throughput) / first.throughput) * 100;
console.log(`\nThroughput at epoch ${first.epoch}: ${num(first.throughput)}`);
console.log(`Throughput at epoch ${last.epoch}: ${num(last.throughput)}`);
console.log(`Change over the run: ${drift >= 0 ? '+' : ''}${num(drift, 1)}%`);
console.log(`Depth at epoch ${last.epoch}: ${last.depth} (cap 24)`);
const perEpoch = last.spawns / last.epoch;
console.log(`Lifetime: ${last.spawns.toLocaleString('en-US')} subagents spawned, ${last.culls.toLocaleString('en-US')} culled`);
console.log(`Mean lifetime: ~${(last.live / perEpoch).toFixed(0)} epochs (${last.live} live / ${perEpoch.toFixed(2)} spawns per epoch)`);

console.log('\n## Depth-cap probe (MAX_DEPTH raised to 200)\n');
for (const probe of probeDepthCap(milestones)) {
  console.log(`epoch ${pad(probe.epoch, 6)} live ${pad(probe.live, 5)} depth ${pad(probe.depth, 4)} mean fit ${num(probe.meanFit, 2)} throughput ${num(probe.throughput)}`);
}

/* Does depth itself cost throughput, or is something else flattening the curve?
   Hold everything constant and move only the cap. */
console.log('\n## Depth is the cost: cap sweep at 3000 epochs\n');
console.log('| MAX_DEPTH | depth reached | mean fit | throughput |');
console.log('|---|---|---|---|');
for (const cap of [4, 8, 16, 24, 64]) {
  const governed = loadTornado({ transform: s => s.replace('const MAX_DEPTH = 24;', `const MAX_DEPTH = ${cap};`) }).create({ matchHands: () => [], onLog: () => {} });
  governed.build(BRIEF);
  advance(governed, 3000);
  const shot = governed.snapshot();
  console.log(`| ${cap} | ${shot.depth} | ${num(shot.meanFit, 2)} | ${num(shot.throughput)} |`);
}
