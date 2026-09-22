const assert = require('node:assert/strict');
const fs = require('node:fs');
const test = require('node:test');

const source = fs.readFileSync(require('node:path').join(__dirname, 'index.html'), 'utf8');

test('keeps the surface minimal and monochrome', () => {
  assert.match(source, /<canvas id="stage"/);
  assert.match(source, /--bg:#050506/);
  assert.doesNotMatch(source, /OLLAMA|localStorage|id="inbox|genome|cohort-list|id="inspect/);
  assert.doesNotMatch(source, /hsl\(|Avenir Next|--storm/);
});

test('builds agents from the prompt and connects them', () => {
  assert.match(source, /function splitBrief\(/);
  assert.match(source, /function build\(/);
  assert.match(source, /state\.agents = parts\.map/);
  assert.match(source, /state\.agents\[i\]\.parent = state\.agents/);
  assert.match(source, /function addEdge\(/);
});

test('uses one asymmetric multi-vortex positioner for nodes and streamlines', () => {
  assert.match(source, /function flowPoint\(t, phase, lobe = 0\)/);
  assert.match(source, /function fieldPoint\(/);
  assert.match(source, /lobePhase = phase \+ lobe \* TAU \/ 3/);
  assert.match(source, /Math\.sin\(state\.time \* \.16 \+ t \* 2\.7 \+ lobePhase\)/);
  assert.match(source, /for \(let i = 0; i < 34; i\+\+\)/);
});

test('renders through one shared low-resolution dither buffer', () => {
  assert.match(source, /const BAYER =/);
  assert.match(source, /new Uint8ClampedArray\(grain\.width \* grain\.height\)/);
  assert.match(source, /function paint\(/);
  assert.match(source, /ctx\.filter = 'blur\(7px\)'/);
  assert.match(source, /ctx\.globalCompositeOperation = 'screen'/);
  assert.match(source, /ctx\.imageSmoothingEnabled = false/);
  assert.match(source, /state\.field\.fill\(0\)/);
});

test('uses pointer velocity to deflect the field and local RGB split', () => {
  assert.match(source, /function pointerMove\(/);
  assert.match(source, /state\.windX = clamp/);
  assert.match(source, /state\.windY = clamp/);
  assert.match(source, /windX \* \(10 \+ t \* 28\)/);
  assert.match(source, /rgba\(255,0,0/);
  assert.match(source, /rgba\(0,0,255/);
  assert.doesNotMatch(source, /addEventListener\(['"]scroll['"]|addEventListener\(['"]wheel['"]/);
});

test('keeps empty builds inert and reset clears visible state', () => {
  assert.match(source, /if \(!ui\.prompt\.value\.trim\(\)\) \{ ui\.status\.textContent = 'enter a job before building'; return; \}/);
  assert.match(source, /ui\.prompt\.value = ''/);
  assert.match(source, /state\.paused = false; state\.speed = 0/);
  assert.match(source, /state\.agents = \[\]/);
});

test('keeps the only controls focused and responsive', () => {
  assert.match(source, /option value="0" selected>hold/);
  assert.match(source, /id="pause"/);
  assert.match(source, /id="reset"/);
  assert.match(source, /@media \(max-width:700px\)/);
  assert.match(source, /#controls \{ left:14px; right:14px/);
});
