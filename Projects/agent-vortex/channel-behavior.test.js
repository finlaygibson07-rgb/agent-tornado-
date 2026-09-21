const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync(require('node:path').join(__dirname, 'index.html'), 'utf8');

test('starts the simulator held instead of running at 4x', () => {
  assert.match(source, /<option value="0" selected>hold<\/option>/);
  assert.match(source, /let simSpeed\s*=\s*0/);
});

test('uses pointer velocity to deflect storm motes', () => {
  assert.match(source, /const channelState\s*=\s*\{/);
  assert.match(source, /channelState\.wind\.[xy]/);
  assert.match(source, /channelState\.wind\.x = clamp/);
  assert.match(source, /windX = 0, windY = 0/);
  assert.match(source, /windX \* \(0\.35 \+ t\)/);
});

test('does not let scroll drive tornado motion or global visual treatment', () => {
  assert.doesNotMatch(source, /applyScrollPressure|addEventListener\(['"]scroll['"]|addEventListener\(['"]wheel['"]/);
  assert.doesNotMatch(source, /channelState\.(?:pressure|charge)/);
  assert.match(source, /splitAmount\(a\)/);
});

test('keeps the active surface to monochrome grain and RGB split', () => {
  assert.match(source, /#environment[\s\S]*radial-gradient/);
  assert.doesNotMatch(source, /hsl\(/);
  assert.doesNotMatch(source, /240, 230, 196|217, 198, 122|232, 216, 159/);
  assert.doesNotMatch(source, /ctx\.strokeStyle|strikeCtx\.strokeStyle|ctx\.stroke\(\)/);
  assert.match(source, /rgba\(255, 0, 0/);
  assert.match(source, /rgba\(0, 0, 255/);
});

test('renders the live timestamped event strip inside SIGNALS', () => {
  assert.match(source, /id="signal-strip"/);
  assert.match(source, /logEvent[\s\S]*signal-strip/);
  assert.match(source, /signal-strip[\s\S]*childElementCount > 12/);
  assert.match(source, /\^\(WARN\|ALERT\|DISCHARGE\)/);
  assert.doesNotMatch(source, /split state is stamped in the live inbox strip/);
});

test('lets helpers recurse within a bounded depth and guarded population', () => {
  assert.match(source, /const MAX_DEPTH = 6/);
  assert.match(source, /a\.depth >= MAX_DEPTH/);
  assert.match(source, /function creationAllowed/);
  assert.match(source, /id="bypass-cap"/);
  assert.match(source, /creationAllowed\(true\)/);
});

test('renders parent-child trails for subagents', () => {
  assert.match(source, /for \(let d = 1; d <= MAX_DEPTH; d\+\+\)/);
  assert.match(source, /function organicOrbit/);
  assert.match(source, /a\.parent && a\.parent\._live[\s\S]*drawGrainTrail\(a\.parent, a, geo\)/);
});

test('ignores a second build while the first one is active', () => {
  assert.match(source, /let building = false/);
  assert.match(source, /if \(building\)[\s\S]*build already in progress/);
  assert.match(source, /if \(!creationAllowed\(true\)\) return/);
  assert.match(source, /building = true/);
  assert.match(source, /building = false/);
  assert.match(source, /let buildGeneration = 0/);
  assert.match(source, /buildGeneration\+\+/);
});
